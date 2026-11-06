"""Full-screen dashboard (`eco ui`): rich Layout + Live, raw-mode keys via termios.

Everything that turns api dicts into renderables is a pure function so it can be
tested by rendering to a Console(file=StringIO) without a TTY.
"""
import os
import select
import signal
import sys
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich import box
from rich.align import Align
from rich.console import Group, RenderableType
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from manage_eco.fmt import money, parse_date, parse_money, progress_bar

# --- theme ---
ACCENT = "#7dcfff"
MUTED = "grey58"
INCOME_C = "#9ece6a"
EXPENSE_C = "#f7768e"
WARN_C = "#e0af68"
BORDER = "#3b4261"
SELECT_BG = "on #283457"

TABS = [("1", "Tổng quan"), ("2", "Giao dịch"), ("3", "Dự định"), ("4", "Ngân sách"), ("5", "Dự báo 90 ngày")]
RECURRENCE_VI = {"once": "một lần", "weekly": "hàng tuần", "monthly": "hàng tháng"}
STATUS_VI = {"pending": "chờ", "done": "xong", "cancelled": "huỷ"}

# Prompt forms: (param key, Vietnamese label, default)
FORMS = {
    "expense": ("Thêm khoản chi", [("amount", "Số tiền", ""), ("category", "Danh mục", ""),
                                   ("note", "Ghi chú", ""), ("date", "Ngày", "hom nay")]),
    "income": ("Thêm khoản thu", [("amount", "Số tiền", ""), ("category", "Danh mục", ""),
                                  ("note", "Ghi chú", ""), ("date", "Ngày", "hom nay")]),
    "plan add": ("Thêm dự định", [("name", "Tên", ""), ("amount", "Số tiền", ""), ("category", "Danh mục", ""),
                                  ("due", "Ngày đến hạn", "+30"), ("every", "Lặp (once/weekly/monthly)", "once"),
                                  ("kind", "Loại (chi/thu)", "chi")]),
}

ApiCall = Callable[[str, Dict[str, Any]], Dict[str, Any]]


def _panel(body: RenderableType, title: str, **kw) -> Panel:
    return Panel(body, title="[bold %s]%s[/]" % (ACCENT, title), title_align="left",
                 box=box.ROUNDED, border_style=BORDER, padding=(0, 1), **kw)


def _amount(amount: int, kind: str = "") -> Text:
    """Coloured signed money: negative/expense red, positive/income green."""
    signed = -amount if kind == "expense" else amount
    return Text(money(signed, signed=True), style=EXPENSE_C if signed < 0 else INCOME_C)


def _vi_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return "%s/%s/%s" % (d, m, y)


def _empty(msg: str) -> Text:
    return Text(msg, style="italic " + MUTED)


# --- pure builders (dicts → renderables) ---
def header(today: date, balance: Optional[int]) -> Table:
    t = Table.grid(expand=True)
    t.add_column(ratio=1)
    t.add_column(justify="right")
    bal = Text("—", style=MUTED) if balance is None else \
        Text(money(balance), style="bold " + (EXPENSE_C if balance < 0 else INCOME_C))
    t.add_row(Text.assemble(("◆ Manage Eco", "bold " + ACCENT), ("  ·  quản lý chi tiêu", MUTED)),
              Text.assemble(("Số dư ", MUTED), bal, ("   %s" % today.strftime("%d/%m/%Y"), MUTED)))
    return t


def tab_bar(active: int) -> Text:
    out = Text()
    for i, (key, label) in enumerate(TABS):
        style = "bold black on " + ACCENT if i == active else MUTED
        out.append(" %s %s " % (key, label), style=style)
        out.append(" ")
    return out


def stat_cards(month: Dict[str, Any]) -> Table:
    grid = Table.grid(expand=True, padding=(0, 1))
    for _ in range(3):
        grid.add_column(ratio=1)
    cards = []
    for label, value, color in (("Thu tháng " + month.get("month", ""), month.get("income", 0), INCOME_C),
                                ("Chi tháng " + month.get("month", ""), month.get("expense", 0), EXPENSE_C),
                                ("Còn lại", month.get("net", 0), INCOME_C if month.get("net", 0) >= 0 else EXPENSE_C)):
        cards.append(Panel(Align.center(Text(money(value), style="bold " + color)),
                           title=Text(label, style=MUTED), box=box.ROUNDED, border_style=BORDER))
    grid.add_row(*cards)
    return grid


def budgets_table(budgets: List[Dict[str, Any]], width: int = 16, compact: bool = False) -> RenderableType:
    """Budget rows with progress bars; compact drops the "Còn" column for narrow panels."""
    if not budgets:
        return _empty("Chưa đặt ngân sách nào. Dùng: eco budget set DANH_MỤC SỐ_TIỀN")
    t = Table(box=None, expand=True, show_header=True, header_style=MUTED, pad_edge=False)
    t.add_column("Danh mục", style="bold", ratio=1, min_width=8, overflow="ellipsis", no_wrap=True)
    t.add_column("Tiến độ", no_wrap=True)
    t.add_column("Đã chi / Hạn mức", justify="right", no_wrap=True, overflow="ellipsis")
    if not compact:
        t.add_column("Còn", justify="right", no_wrap=True)
    for b in budgets:
        pct = float(b.get("pct", 0))
        rem = b.get("remaining", 0)
        cells = [b["category"],
                 Text.from_markup("%s %3d%%" % (progress_bar(pct, width), round(pct))),
                 "%s / %s" % (money(b.get("spent", 0)), money(b.get("limit", 0)))]
        if not compact:
            cells.append(Text(money(rem), style=EXPENSE_C if rem < 0 else ""))
        t.add_row(*cells)
    return t


def forecast_table(rows: List[Dict[str, Any]], limit: Optional[int] = None) -> RenderableType:
    if not rows:
        return _empty("Không có dự định nào sắp tới.")
    t = Table(box=None, expand=True, header_style=MUTED, pad_edge=False)
    t.add_column("Ngày", no_wrap=True)
    t.add_column("Dự định", ratio=1, min_width=8, overflow="ellipsis", no_wrap=True)
    t.add_column("Số tiền", justify="right", no_wrap=True)
    t.add_column("Số dư sau", justify="right", no_wrap=True)
    for r in rows[:limit]:
        t.add_row(_vi_date(r["date"]), r["name"], _amount(r["amount"]),
                  Text(money(r["balance"]), style="bold " + EXPENSE_C if r["balance"] < 0 else ""))
    if limit is not None and len(rows) > limit:
        t.add_row("", Text("… và %d mục khác" % (len(rows) - limit), style=MUTED), "", "")
    return t


def low_warning(lowest: Optional[Dict[str, Any]]) -> Optional[Text]:
    if not lowest or lowest.get("balance", 0) >= 0:
        return None
    return Text("⚠  Sẽ âm tiền ngày %s: số dư thấp nhất %s" % (_vi_date(lowest["date"]), money(lowest["balance"])),
                style="bold " + EXPENSE_C)


def overview(dash: Dict[str, Any], width: int = 120) -> RenderableType:
    """Side-by-side budget/upcoming panels from 120 columns, stacked below that so amounts never wrap."""
    parts = [stat_cards(dash.get("month", {}))]
    warn = low_warning(dash.get("lowest"))
    if warn:
        parts.append(Panel(warn, box=box.ROUNDED, border_style=EXPENSE_C))
    overdue = dash.get("overdue") or []
    if overdue:
        parts.append(Text("⏰ Quá hạn: " + ", ".join(
            "%s (%s)" % (p["name"], _vi_date(p["due_date"])) for p in overdue), style=WARN_C))
    budgets = _panel(budgets_table(dash.get("budgets") or [], width=10, compact=True), "Ngân sách tháng")
    upcoming = _panel(forecast_table(dash.get("upcoming") or [], limit=10 if width >= 120 else 5), "Sắp tới 30 ngày")
    if width >= 120:
        body = Table.grid(expand=True, padding=(0, 1))
        body.add_column(ratio=1)
        body.add_column(ratio=1)
        body.add_row(budgets, upcoming)
        parts.append(body)
    else:
        parts.extend([budgets, upcoming])
    return Group(*parts)


def transactions_view(data: Dict[str, Any], selected: int) -> RenderableType:
    txs = data.get("transactions") or []
    if not txs:
        return _panel(_empty("Chưa có giao dịch. Nhấn a để thêm chi, i để thêm thu."), "Giao dịch")
    t = Table(box=box.SIMPLE_HEAD, expand=True, header_style="bold " + ACCENT, border_style=BORDER)
    t.add_column("#", style=MUTED, justify="right")
    t.add_column("Ngày")
    t.add_column("Danh mục")
    t.add_column("Ghi chú", ratio=1)
    t.add_column("Số tiền", justify="right")
    for i, tx in enumerate(txs):
        t.add_row(str(tx["id"]), _vi_date(tx["date"]), tx["category"], tx.get("note", ""),
                  _amount(tx["amount"], tx["kind"]), style=SELECT_BG if i == selected else None)
    return _panel(t, "Giao dịch (%d)" % len(txs))


def plans_view(data: Dict[str, Any], selected: int) -> RenderableType:
    plans = data.get("plans") or []
    if not plans:
        return _panel(_empty("Chưa có dự định. Nhấn p để thêm."), "Dự định")
    t = Table(box=box.SIMPLE_HEAD, expand=True, header_style="bold " + ACCENT, border_style=BORDER)
    t.add_column("#", style=MUTED, justify="right")
    t.add_column("Đến hạn")
    t.add_column("Tên", ratio=1)
    t.add_column("Danh mục")
    t.add_column("Lặp")
    t.add_column("Trạng thái")
    t.add_column("Số tiền", justify="right")
    for i, p in enumerate(plans):
        t.add_row(str(p["id"]), _vi_date(p["due_date"]), p["name"], p["category"],
                  RECURRENCE_VI.get(p.get("recurrence", ""), p.get("recurrence", "")),
                  STATUS_VI.get(p.get("status", ""), p.get("status", "")),
                  _amount(p["amount"], p["kind"]), style=SELECT_BG if i == selected else None)
    return _panel(t, "Dự định (%d) · d = đánh dấu đã thực hiện" % len(plans))


def budgets_view(data: Dict[str, Any]) -> RenderableType:
    return _panel(budgets_table(data.get("budgets") or [], width=24), "Ngân sách tháng %s" % data.get("month", ""))


def forecast_view(data: Dict[str, Any]) -> RenderableType:
    parts = []  # type: List[RenderableType]
    warn = low_warning(data.get("lowest"))
    if warn:
        parts.append(warn)
    parts.append(forecast_table(data.get("rows") or []))
    return _panel(Group(*parts), "Dự báo %s ngày · số dư hiện tại %s" % (data.get("days", 90),
                                                                       money(data.get("balance", 0))))


def footer(state: "State") -> Text:
    if state.form:
        title, fields = FORMS[state.form]
        key, label, _ = fields[state.field]
        return Text.assemble((" %s " % title, "bold black on " + ACCENT), "  ",
                             ("%s (%d/%d): " % (label, state.field + 1, len(fields)), "bold"),
                             state.buffer, ("▏", ACCENT), ("   Enter tiếp · Esc huỷ", MUTED))
    if state.error:
        return Text(" ✗ " + state.error, style="bold " + EXPENSE_C)
    if state.message:
        return Text(" ✓ " + state.message, style="bold " + INCOME_C)
    return Text.from_markup(" [b]1-5[/] tab  [b]j/k[/] chọn  [b]a[/] thêm chi  [b]i[/] thêm thu  "
                            "[b]p[/] thêm dự định  [b]d[/] xong dự định  [b]q[/] thoát", style=MUTED)


# --- state & key handling ---
TAB_CMDS = [("dash", {}), ("list", {}), ("plan list", {}), ("budget status", {}), ("forecast", {"days": 90})]


class State:
    def __init__(self, today: date):
        self.today = today
        self.tab = 0
        self.selected = 0
        self.data = {}  # type: Dict[int, Dict[str, Any]]
        self.balance = None  # type: Optional[int]
        self.form = None  # type: Optional[str]
        self.field = 0
        self.buffer = ""
        self.values = {}  # type: Dict[str, str]
        self.message = ""
        self.error = ""
        self.running = True

    def rows(self) -> List[Dict[str, Any]]:
        d = self.data.get(self.tab, {})
        return d.get("transactions") or d.get("plans") or []


def load(state: State, api: ApiCall) -> None:
    """Fetch data for the current tab (cached until a mutation clears it)."""
    if state.tab in state.data:
        return
    cmd, params = TAB_CMDS[state.tab]
    try:
        data = api(cmd, dict(params))
    except Exception as e:  # api missing or failing: show it, keep running
        state.error = "Lỗi tải dữ liệu: %s" % e
        data = {}
    state.data[state.tab] = data
    if "balance" in data:
        state.balance = data["balance"]
    n = len(state.rows())
    state.selected = min(state.selected, max(0, n - 1))


def build_screen(state: State, width: int = 120) -> Layout:
    body = {0: lambda d: overview(d, width) if d else _empty("Không có dữ liệu."),
            1: lambda d: transactions_view(d, state.selected),
            2: lambda d: plans_view(d, state.selected),
            3: budgets_view,
            4: forecast_view}[state.tab](state.data.get(state.tab, {}))
    root = Layout()
    root.split_column(Layout(name="header", size=4), Layout(name="body", ratio=1), Layout(name="footer", size=3))
    root["header"].update(Panel(Group(header(state.today, state.balance), tab_bar(state.tab)),
                                box=box.ROUNDED, border_style=BORDER, padding=(0, 1)))
    root["body"].update(body)
    root["footer"].update(Panel(footer(state), box=box.ROUNDED, border_style=BORDER, padding=(0, 0)))
    return root


def _form_params(form: str, values: Dict[str, str], today: date) -> Tuple[str, Dict[str, Any]]:
    """Validate prompt input into an api call; raises ValueError with a Vietnamese message."""
    try:
        amount = parse_money(values["amount"])
    except ValueError:
        raise ValueError("Số tiền không hợp lệ: %r" % values["amount"])
    if not values.get("category", "").strip():
        raise ValueError("Danh mục không được để trống")
    if form in ("expense", "income"):
        try:
            d = parse_date(values.get("date") or "hom nay", today)
        except ValueError:
            raise ValueError("Ngày không hợp lệ: %r" % values.get("date"))
        return form, {"amount": amount, "category": values["category"].strip(),
                      "note": values.get("note", "").strip(), "date": d.isoformat()}
    if not values.get("name", "").strip():
        raise ValueError("Tên dự định không được để trống")
    try:
        due = parse_date(values.get("due") or "+30", today)
    except ValueError:
        raise ValueError("Ngày đến hạn không hợp lệ: %r" % values.get("due"))
    every = (values.get("every") or "once").strip().lower()
    if every not in RECURRENCE_VI:
        raise ValueError("Lặp phải là once, weekly hoặc monthly")
    kind = (values.get("kind") or "chi").strip().lower()
    if kind not in ("chi", "thu"):
        raise ValueError("Loại phải là chi hoặc thu")
    return "plan add", {"name": values["name"].strip(), "amount": amount, "category": values["category"].strip(),
                        "due": due.isoformat(), "every": every, "income": kind == "thu"}


def _mutate(state: State, api: ApiCall, cmd: str, params: Dict[str, Any], ok: str) -> None:
    try:
        api(cmd, params)
    except (LookupError, ValueError) as e:
        state.error = str(e)
        return
    except Exception as e:
        state.error = "Lỗi: %s" % e
        return
    state.message = ok
    state.data.clear()
    try:  # header balance must reflect the change whichever tab is open
        state.data[0] = api("dash", {})
        state.balance = state.data[0].get("balance", state.balance)
    except Exception:
        pass


def handle_key(state: State, key: str, api: ApiCall) -> None:
    """Apply one keypress to state (may call api). Keys: single chars, 'up', 'down', 'enter', 'esc', 'backspace'."""
    if state.form:
        _, fields = FORMS[state.form]
        if key == "esc":
            state.form = None
            state.message = "Đã huỷ"
        elif key == "backspace":
            state.buffer = state.buffer[:-1]
        elif key == "enter":
            fkey, _, default = fields[state.field]
            state.values[fkey] = state.buffer.strip() or default
            state.field += 1
            state.buffer = ""
            if state.field >= len(fields):
                form, state.form = state.form, None
                try:
                    cmd, params = _form_params(form, state.values, state.today)
                except ValueError as e:
                    state.error = str(e)
                else:
                    label = params.get("name") or params["category"]
                    _mutate(state, api, cmd, params, "Đã thêm %s: %s" % (label, money(params["amount"])))
        elif len(key) == 1 and key.isprintable():
            state.buffer += key
        load(state, api)
        return

    state.message = state.error = ""
    if key in ("q", "esc"):
        state.running = False
        return
    if key in "12345" and len(key) == 1:
        if state.tab != int(key) - 1:
            state.tab, state.selected = int(key) - 1, 0
    elif key in ("j", "down"):
        state.selected = min(state.selected + 1, max(0, len(state.rows()) - 1))
    elif key in ("k", "up"):
        state.selected = max(0, state.selected - 1)
    elif key in ("a", "i", "p"):
        state.form = {"a": "expense", "i": "income", "p": "plan add"}[key]
        state.field, state.buffer, state.values = 0, "", {}
    elif key == "d":
        rows = state.rows() if state.tab == 2 else []
        if not rows:
            state.error = "Chọn một dự định ở tab 3 trước khi nhấn d"
        else:
            p = rows[state.selected]
            if p.get("status", "pending") != "pending":
                state.error = "Dự định này đã %s" % STATUS_VI.get(p["status"], p["status"])
            else:
                _mutate(state, api, "plan done", {"id": p["id"], "date": state.today.isoformat()},
                        "Đã thực hiện: %s" % p["name"])
    load(state, api)


# --- terminal I/O ---
def _read_key(fd: int, wake_r: int) -> Optional[str]:
    """Block until a key (or a resize wake-up, which returns None)."""
    r, _, _ = select.select([fd, wake_r], [], [])
    if wake_r in r:
        os.read(wake_r, 64)
        return None
    b = os.read(fd, 1)
    if b == b"\x1b":
        if select.select([fd], [], [], 0.03)[0]:
            seq = os.read(fd, 8)
            return {b"[A": "up", b"[B": "down", b"OA": "up", b"OB": "down"}.get(seq[:2], "")
        return "esc"
    if b in (b"\r", b"\n"):
        return "enter"
    if b in (b"\x7f", b"\x08"):
        return "backspace"
    if b == b"\x03":
        raise KeyboardInterrupt
    if b and b[0] >= 0xC0:  # UTF-8 lead byte (Vietnamese input)
        need = 1 if b[0] < 0xE0 else 2 if b[0] < 0xF0 else 3
        b += os.read(fd, need)
    return b.decode("utf-8", "replace")


def _default_api(store, today: date) -> ApiCall:
    def call(cmd: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from manage_eco import api
        return api.execute(cmd, params, store, today)
    return call


def run_tui(store, today: date, api: Optional[ApiCall] = None) -> None:
    import termios
    import tty
    from rich.console import Console
    from rich.live import Live

    call = api or _default_api(store, today)
    state = State(today)
    load(state, call)
    if state.tab not in state.data or "balance" not in state.data[state.tab]:
        state.balance = store.balance(today)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    wake_r, wake_w = os.pipe()
    old_winch = signal.signal(signal.SIGWINCH, lambda *_: os.write(wake_w, b"x"))
    console = Console()
    try:
        tty.setcbreak(fd)
        with Live(build_screen(state, console.width), console=console, screen=True, auto_refresh=False) as live:
            while state.running:
                key = _read_key(fd, wake_r)
                if key:
                    handle_key(state, key, call)
                live.update(build_screen(state, console.width), refresh=True)
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(wake_r)
        os.close(wake_w)
