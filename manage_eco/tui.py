"""Full-screen dashboard (`eco ui`): mouse + keyboard, rich Live, raw-mode termios input.

The screen is built as plain lines by pure functions that also record a hit map
(row, x0, x1, action) for every clickable thing, so a click maps exactly to an
action and everything is testable without a TTY.
"""
import calendar
import os
import select
import signal
import sys
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union

from rich.cells import cell_len
from rich.text import Text

from manage_eco import fmt
from manage_eco.fmt import money, parse_date, parse_money

# --- theme ---
ACCENT = "#7dcfff"
MUTED = "grey58"
INCOME_C = "#9ece6a"
EXPENSE_C = "#f7768e"
WARN_C = "#e0af68"
RULE_C = "#3b4261"
SELECT_BG = "on #283457"
BTN = "white on #2f3549"
BTN_KEY = "bold %s on #2f3549" % ACCENT
BTN_PRIMARY = "bold black on " + ACCENT
BTN_PRIMARY_KEY = "black on " + ACCENT
TAB_ON = "bold black on " + ACCENT
TAB_OFF = "grey70 on #1f2335"
CHIP = "grey85 on #2f3549"
CHIP_ON = "bold black on " + INCOME_C

MOUSE_ON = "\x1b[?1000h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1000l\x1b[?1006l"

TABS = ["Tổng quan", "Giao dịch", "Dòng tiền", "Ngân sách"]
TAB_CMDS = [("dash", {}), ("list", {"all": True}), ("plan list", {}), ("budget status", {})]
AMOUNT_CHIPS = [(v, v) for v in ("50k", "100k", "200k", "500k", "1tr")]
EVERY = [("once", "1 lần"), ("daily", "Hàng ngày"), ("weekly", "Hàng tuần"), ("monthly", "Hàng tháng")]
DAY_CHIPS = [(str(d), str(d)) for d in (1, 5, 10, 15, 20, 25)] + [("31", "Cuối tháng")]
KINDS = [("expense", "Chi"), ("income", "Thu")]
EVERY_VI = {"once": "1 lần", "daily": "hàng ngày", "weekly": "hàng tuần", "monthly": "hàng tháng"}
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
DATE_FIELDS = ("date", "due")
REQUIRED = ("name", "amount", "category")
INDENT = 23  # column where form values and chips start


class Field(NamedTuple):
    key: str
    label: str
    choices: Optional[List[Tuple[str, str]]] = None
    placeholder: str = ""
    show_if: Optional[Tuple[str, str]] = None  # (other field, value) that makes this field visible


_AMOUNT = Field("amount", "Số tiền", placeholder="vd: 50k, 1.5tr, 50k+20k, 3x150k")
_CATEGORY = Field("category", "Danh mục", placeholder="chọn bên dưới hoặc gõ")
_TX_FIELDS = [_AMOUNT, _CATEGORY, Field("note", "Ghi chú", placeholder="(không bắt buộc)"),
              Field("date", "Ngày", placeholder="hôm nay")]
FORMS = {
    "expense": ("Thêm khoản chi", _TX_FIELDS),
    "income": ("Thêm khoản thu", _TX_FIELDS),
    "plan": ("Thêm dòng tiền", [Field("name", "Tên", placeholder="vd: lương, thuê nhà"),
                                _AMOUNT, _CATEGORY,
                                Field("every", "Lặp", EVERY),
                                Field("day", "Ngày trả hằng tháng", placeholder="chọn bên dưới (không bắt buộc)",
                                      show_if=("every", "monthly")),
                                Field("due", "Ngày bắt đầu"),
                                Field("kind", "Loại", KINDS)]),
}

ApiCall = Callable[[str, Dict[str, Any]], Dict[str, Any]]
Action = Tuple[Any, ...]
Hit = Tuple[int, int, int, Action]  # (row, x0, x1) 0-based, x1 exclusive
Event = Union[str, Tuple[str, int, int, int], None]


# --- line building with click spans ---
class Line:
    """One screen row; `action` makes the whole row clickable, `spans` mark buttons."""

    def __init__(self, action: Optional[Action] = None):
        self.text = Text(no_wrap=True, overflow="crop")
        self.spans = []  # type: List[Tuple[int, int, Action]]
        self.action = action

    @property
    def x(self) -> int:
        return self.text.cell_len

    def add(self, s: str, style: str = "") -> "Line":
        self.text.append(s, style)
        return self

    def cell(self, s: str, width: int, style: str = "", right: bool = False) -> "Line":
        """Fixed-width column, truncated with an ellipsis."""
        t = Text(s, style=style)
        t.truncate(max(0, width), overflow="ellipsis")
        pad = " " * max(0, width - t.cell_len)
        if right:
            self.add(pad)
        self.text.append_text(t)
        if not right:
            self.add(pad)
        return self

    def click(self, s: str, action: Action, style: str = "") -> "Line":
        x0 = self.x
        self.add(s, style)
        self.spans.append((x0, self.x, action))
        return self

    def button(self, label: str, key: str, hint: str, primary: bool = False) -> "Line":
        x0 = self.x
        self.add(" %s " % label, BTN_PRIMARY if primary else BTN)
        self.add(" %s " % hint, BTN_PRIMARY_KEY if primary else BTN_KEY)
        self.spans.append((x0, self.x, ("key", key)))
        return self.add(" ")


class Frame(NamedTuple):
    lines: List[Text]
    hits: List[Hit]

    def renderable(self) -> Text:
        out = Text("\n").join(self.lines)
        out.no_wrap, out.overflow = True, "crop"
        return out


def hit_at(hits: List[Hit], row: int, col: int) -> Optional[Action]:
    """First hit containing (row, col); button spans come before whole-row actions."""
    return next((a for r, x0, x1, a in hits if r == row and x0 <= col < x1), None)


# --- state ---
class Form:
    def __init__(self, name: str, cats: Dict[str, List[str]], today: date):
        self.name = name
        self.title, self.fields = FORMS[name]
        self.values = {f.key: (f.choices[0][0] if f.choices else "") for f in self.fields}  # type: Dict[str, str]
        self.focus = self.fields[0].key
        self.errors = {}  # type: Dict[str, str]
        self.error = ""
        self.cats = cats
        self.today = today
        self.months = {}  # type: Dict[str, Tuple[int, int]]  # calendar month shown per date field

    def kind(self) -> str:
        return self.values.get("kind") or self.name

    def visible(self) -> List[Field]:
        return [f for f in self.fields if not f.show_if or self.values.get(f.show_if[0]) == f.show_if[1]]

    def field(self) -> Field:
        vis = self.visible()
        return next((f for f in vis if f.key == self.focus), vis[0])

    def move(self, step: int) -> None:
        keys = [f.key for f in self.visible()]
        i = keys.index(self.focus) if self.focus in keys else 0
        self.focus = keys[(i + step) % len(keys)]

    def day(self) -> Optional[int]:
        """Chosen monthly pay day, if the field is visible and valid."""
        v = self.values.get("day", "").strip()
        if self.values.get("every") != "monthly" or not v.isdigit() or not 1 <= int(v) <= 31:
            return None
        return int(v)

    def default_date(self, key: str) -> str:
        if key == "date":
            return "hom nay"
        return "+30" if self.values.get("every") == "once" else "+1"

    def date_value(self, key: str) -> Optional[date]:
        """The date a date field currently means (its default when empty), or None."""
        v = self.values[key].strip()
        if not v and key == "due" and self.day():
            return None
        try:
            return parse_date(v or self.default_date(key), self.today)
        except ValueError:
            return None

    def placeholder(self, f: Field) -> str:
        if f.key == "due":
            day = self.day()
            if day:
                return "không bắt buộc · tự tính lần tới %s" % ("cuối tháng" if day == 31 else "ngày %d" % day)
            return "mặc định: 30 ngày nữa" if self.values.get("every") == "once" else "mặc định: ngày mai"
        return f.placeholder

    def chips(self, f: Field) -> List[Tuple[str, str]]:
        if f.key == "amount":
            return AMOUNT_CHIPS
        if f.key == "category":
            return [(c, c) for c in list(self.cats.get(self.kind(), []))[:8]]
        if f.key == "day":
            return DAY_CHIPS
        if f.key in DATE_FIELDS:
            return date_chips(self.today)
        return []

    def chip_on(self, key: str, value: str) -> bool:
        if key in DATE_FIELDS:
            dv = self.date_value(key)
            return dv is not None and parse_date(value, self.today) == dv
        return self.values.get(key, "").strip() == value


class State:
    def __init__(self, today: date):
        self.today = today
        self.tab = 0
        self.selected = None  # type: Optional[int]
        self.scroll = 0
        self.data = {}  # type: Dict[int, Dict[str, Any]]
        self.balance = None  # type: Optional[int]
        self.form = None  # type: Optional[Form]
        self.confirm = None  # type: Optional[Dict[str, Any]]
        self.status = ("", True)  # (message, ok)
        self.hits = []  # type: List[Hit]
        self.running = True

    def items(self) -> List[Dict[str, Any]]:
        if self.tab not in (1, 2):
            return []
        d = self.data.get(self.tab, {})
        return d.get("transactions") or d.get("plans") or []

    def set_status(self, msg: str, ok: bool = True) -> None:
        self.status = (msg, ok)


def load(state: State, api: ApiCall) -> None:
    """Fetch data for the current tab (cached until a mutation clears it)."""
    if state.tab in state.data:
        return
    cmd, params = TAB_CMDS[state.tab]
    try:
        data = api(cmd, dict(params))
    except Exception as e:  # api missing or failing: show it, keep running
        state.set_status("Lỗi tải dữ liệu: %s" % e, False)
        data = {}
    if state.tab == 1:
        data = dict(data, transactions=list(reversed(data.get("transactions") or [])))  # newest first
    state.data[state.tab] = data
    if "balance" in data:
        state.balance = data["balance"]
    n = len(state.items())
    if state.selected is not None and state.selected >= n:
        state.selected = n - 1 if n else None


# --- formatting helpers ---
def _vi_date(iso: str, short: bool = False) -> str:
    y, m, d = iso.split("-")
    return "%s/%s" % (d, m) if short else "%s/%s/%s" % (d, m, y)


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def date_chips(today: date) -> List[Tuple[str, str]]:
    last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return [(_dmy(d), label) for d, label in ((today - timedelta(days=1), "Hôm qua"), (today, "Hôm nay"),
                                              (today + timedelta(days=1), "Mai"), (last, "Cuối tháng"),
                                              (last + timedelta(days=1), "Đầu tháng sau"))]


def recurrence_label(p: Dict[str, Any]) -> str:
    r = p.get("recurrence", "")
    label = EVERY_VI.get(r, r)
    if r == "monthly":
        day = p.get("day") or int(p["due_date"][8:])
        label += " · " + ("cuối tháng" if day == 31 else "ngày %d" % day)
    return label


def _signed(amount: int, kind: str = "") -> Tuple[str, str]:
    v = -amount if kind == "expense" else amount
    return money(v, signed=True), EXPENSE_C if v < 0 else INCOME_C


def _bar(pct: float, width: int) -> Text:
    color = INCOME_C if pct < 80 else WARN_C if pct < 100 else EXPENSE_C
    filled = int(round(max(0.0, min(100.0, pct)) / 100 * width))
    return Text.assemble(("█" * filled, color), ("░" * (width - filled), RULE_C))


def _rule(width: int) -> Line:
    return Line().add(" " + "─" * max(0, width - 2), RULE_C)


def _title(s: str) -> Line:
    return Line().add(" " + s, "bold " + ACCENT)


# --- screen parts (pure) ---
def header_line(balance: Optional[int], width: int) -> Line:
    left = " ◆ Manage Eco"
    bal = "—" if balance is None else money(balance)
    color = MUTED if balance is None else EXPENSE_C if balance < 0 else INCOME_C
    right_len = cell_len("Số dư " + bal + " ")
    return (Line().add(left, "bold " + ACCENT).add(" " * max(1, width - cell_len(left) - right_len))
            .add("Số dư ", MUTED).add(bal, "bold " + color).add(" "))


def tabs_line(active: int) -> Line:
    ln = Line().add(" ")
    for i, name in enumerate(TABS):
        ln.click(" %d %s " % (i + 1, name), ("tab", i), TAB_ON if i == active else TAB_OFF).add(" ")
    return ln


def action_line(state: State) -> Line:
    ln = Line().add(" ")
    if state.form:
        return ln.button("Lưu", "enter", "Enter", primary=True).button("Huỷ", "esc", "Esc")
    if state.confirm:
        ln.add("Xoá %s? " % state.confirm["label"], "bold " + EXPENSE_C)
        return ln.button("Có", "y", "y", primary=True).button("Không", "n", "n")
    ln.button("+ Chi", "a", "a").button("+ Thu", "i", "i").button("+ Dòng tiền", "p", "p")
    if state.selected is not None and state.tab == 2:
        ln.button("✓ Xong", "d", "d")
    if state.selected is not None and state.tab == 1:
        ln.button("✕ Xoá", "x", "x")
    return ln.button("Thoát", "q", "q")


def status_line(state: State) -> Line:
    msg, ok = state.status
    if not msg:
        return Line().add(" Nhấp chuột vào nút, hoặc bấm phím ghi trên nút.", MUTED)
    return Line().add((" ✓ " if ok else " ✗ ") + msg, "bold " + (INCOME_C if ok else EXPENSE_C))


def overview_lines(d: Dict[str, Any], width: int) -> List[Line]:
    m = d.get("month") or {}
    inc, exp, net = m.get("income", 0), m.get("expense", 0), m.get("net", 0)
    net_c = EXPENSE_C if net < 0 else INCOME_C
    month = m.get("month", "")
    label = "Tháng %s/%s" % (month[5:], month[:4]) if len(month) == 7 else "Tháng này"
    one = (Line().add("   %s   " % label, MUTED).add("Thu ", MUTED).add(money(inc), "bold " + INCOME_C)
           .add("    Chi ", MUTED).add(money(exp), "bold " + EXPENSE_C)
           .add("    Còn lại ", MUTED).add(money(net), "bold " + net_c))
    out = [Line()]
    if one.x <= width:
        out.append(one)
    else:
        out.append(Line().add("   " + label, MUTED))
        for name, v, c in (("Thu", inc, INCOME_C), ("Chi", exp, EXPENSE_C), ("Còn lại", net, net_c)):
            out.append(Line().add("   ").cell(name, 10, MUTED).add(money(v), "bold " + c))
    out.append(_rule(width))

    out.append(_title("Ngân sách"))
    budgets = sorted(d.get("budgets") or [], key=lambda b: -float(b.get("pct", 0)))[:5]
    if not budgets:
        out.append(Line().add("   Chưa đặt ngân sách (eco budget set DANH_MỤC SỐ_TIỀN)", MUTED))
    bar_w = max(6, min(24, width - 60))
    for b in budgets:
        pct = float(b.get("pct", 0))
        ln = Line(("tab", 3)).add("   ").cell(b["category"], 14).add(" ")
        ln.text.append_text(_bar(pct, bar_w))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        ln.cell("%s / %s" % (money(b.get("spent", 0)), money(b.get("limit", 0))), 27, right=True)
        out.append(ln)
    out.append(_rule(width))

    out.append(_title("Sắp tới 30 ngày"))
    upcoming = (d.get("upcoming") or [])[:5]
    if not upcoming:
        out.append(Line().add("   Không có dòng tiền nào trong 30 ngày tới.", MUTED))
    name_w = max(8, width - 52)
    for r in upcoming:
        amt, c = _signed(r["amount"])
        out.append(Line(("tab", 2)).add("   ").cell(_vi_date(r["date"], short=True), 5, MUTED).add("  ")
                   .cell(r["name"], name_w).add("  ").cell(amt, 15, c, right=True).add("  → ", MUTED)
                   .cell(money(r["balance"]), 15, EXPENSE_C if r["balance"] < 0 else "", right=True))
    low = d.get("lowest")
    if low and low.get("balance", 0) < 0:
        out.append(Line(("tab", 2)).add(" ⚠ Sẽ âm tiền ngày %s (thấp nhất %s)" % (
            _vi_date(low["date"]), money(low["balance"])), "bold " + EXPENSE_C))
    else:
        out.append(Line().add(" ✓ Số dư không bị âm trong 90 ngày tới.", INCOME_C))
    overdue = d.get("overdue") or []
    if overdue:
        out.append(Line(("tab", 2)).add(" ⏰ Quá hạn: " + ", ".join(p["name"] for p in overdue), WARN_C))
    return out


def list_lines(state: State, items: List[Dict[str, Any]], head: Line, row: Callable[[Dict[str, Any]], Line],
               height: int, empty: str) -> List[Line]:
    """Header + one clickable row per item, scrolled so the selection stays visible."""
    if not items:
        return [Line(), Line().add("   " + empty, MUTED)]
    visible = max(1, height - 1)
    if state.selected is not None:
        state.scroll = max(min(state.scroll, state.selected), state.selected - visible + 1)
    state.scroll = max(0, min(state.scroll, len(items) - visible))
    out = [head]
    for i in range(state.scroll, min(len(items), state.scroll + visible)):
        ln = row(items[i])
        ln.action = ("select", i)
        if i == state.selected:
            ln.text.style = SELECT_BG
        out.append(ln)
    return out


def transactions_lines(state: State, width: int, height: int) -> List[Line]:
    note_w = max(4, width - 48)
    head = (Line().add(" ").cell("Ngày", 10, MUTED).add("  ").cell("Danh mục", 14, MUTED).add("  ")
            .cell("Ghi chú", note_w, MUTED).add("  ").cell("Số tiền", 16, MUTED, right=True))

    def row(t: Dict[str, Any]) -> Line:
        amt, c = _signed(t["amount"], t["kind"])
        return (Line().add(" ").cell(_vi_date(t["date"]), 10).add("  ").cell(t["category"], 14).add("  ")
                .cell(t.get("note", ""), note_w, MUTED).add("  ").cell(amt, 16, c, right=True))
    return list_lines(state, state.items(), head, row, height,
                      "Chưa có giao dịch. Nhấn [+ Chi] hoặc [+ Thu] để thêm.")


def plans_lines(state: State, width: int, height: int) -> List[Line]:
    name_w = max(4, width - 58)
    head = (Line().add(" ").cell("Ngày tới", 10, MUTED).add("  ").cell("Tên", name_w, MUTED).add("  ")
            .cell("Lặp", 23, MUTED).add("  ").cell("Số tiền", 16, MUTED, right=True))
    today = state.today.isoformat()

    def row(p: Dict[str, Any]) -> Line:
        amt, c = _signed(p["amount"], p["kind"])
        return (Line().add(" ").cell(_vi_date(p["due_date"]), 10, WARN_C if p["due_date"] < today else "").add("  ")
                .cell(p["name"], name_w).add("  ").cell(recurrence_label(p), 23, MUTED)
                .add("  ").cell(amt, 16, c, right=True))
    return list_lines(state, state.items(), head, row, height,
                      "Chưa có dòng tiền. Nhấn [+ Dòng tiền] để thêm (vd: lương, thuê nhà, mua laptop).")


def budgets_lines(d: Dict[str, Any], width: int) -> List[Line]:
    budgets = d.get("budgets") or []
    if not budgets:
        return [Line(), Line().add("   Chưa đặt ngân sách. Dùng lệnh: eco budget set DANH_MỤC SỐ_TIỀN", MUTED)]
    wide = width >= 100
    bar_w = max(6, min(30, width - (72 if wide else 56)))
    head = (Line().add(" ").cell("Danh mục", 14, MUTED).add("  ").cell("Đã dùng", bar_w + 6, MUTED).add("  ")
            .cell("Đã chi / Hạn mức", 27, MUTED, right=True))
    if wide:
        head.add("  ").cell("Còn lại", 14, MUTED, right=True)
    out = [Line(), head]
    for b in budgets:
        pct, rem = float(b.get("pct", 0)), b.get("remaining", 0)
        ln = Line().add(" ").cell(b["category"], 14).add("  ")
        ln.text.append_text(_bar(pct, bar_w))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        ln.cell("%s / %s" % (money(b.get("spent", 0)), money(b.get("limit", 0))), 27, right=True)
        if wide:
            ln.add("  ").cell(money(rem), 14, EXPENSE_C if rem < 0 else "", right=True)
        out.append(ln)
    out += [Line(), Line().add("   Đặt/sửa hạn mức: eco budget set DANH_MỤC SỐ_TIỀN", MUTED)]
    return out


def chip_lines(chips: List[Tuple[str, str]], key: str, width: int, on: Callable[[str], bool],
               max_lines: int = 2) -> List[Line]:
    """Clickable (value, label) chips under a form field, wrapped onto at most `max_lines` rows."""
    lines = []  # type: List[Line]
    ln = None  # type: Optional[Line]
    for value, label in chips:
        w = cell_len(label) + 3
        if ln is None or ln.x + w > width:
            if len(lines) == max_lines:
                break
            ln = Line().add(" " * INDENT)
            lines.append(ln)
        ln.click(" %s " % label, ("chip", key, value), CHIP_ON if on(value) else CHIP).add(" ")
    return lines


def calendar_lines(form: Form, key: str) -> List[Line]:
    """Mini month calendar for a date field: ‹ › change month, click a day to pick it."""
    dv = form.date_value(key)
    y, m = form.months.get(key) or ((dv or form.today).year, (dv or form.today).month)
    pad = " " * INDENT
    out = [Line().add(pad).click(" ‹ ", ("cal", key, -1), BTN).add("  Tháng %02d/%d  " % (m, y), "bold")
           .click(" › ", ("cal", key, 1), BTN),
           Line().add(pad + "".join("%3s" % d for d in ("T2", "T3", "T4", "T5", "T6", "T7", "CN")), MUTED)]
    for week in calendar.monthcalendar(y, m):
        ln = Line().add(pad)
        for d in week:
            if not d:
                ln.add("   ")
                continue
            day = date(y, m, d)
            style = CHIP_ON if day == dv else "bold underline " + ACCENT if day == form.today else ""
            ln.click("%3d" % d, ("chip", key, _dmy(day)), style)
        out.append(ln)
    return out


def _preview(form: Form, f: Field) -> Optional[Tuple[str, str]]:
    """Live hint after a field: amount arithmetic result, or the weekday + date a date field means."""
    value = form.values[f.key].strip()
    if f.key == "amount":
        fn = getattr(fmt, "money_preview", None)  # added by fmt owner; absent on older fmt
        p = fn(value) if fn and value else None
        return (p, "bold " + INCOME_C) if p else None
    if f.key in DATE_FIELDS:
        fn = getattr(fmt, "date_preview", None)
        if fn and value:
            try:
                p = fn(value, form.today)
            except Exception:
                p = None
            if p:
                return p, ACCENT
        dv = form.date_value(f.key)
        if dv:
            return "→ %s, %s" % (WEEKDAYS[dv.weekday()], _dmy(dv)), ACCENT
        return ("⚠ chưa hiểu ngày này", WARN_C) if value else None
    return None


def form_lines(form: Form, width: int) -> Tuple[List[Line], Tuple[int, int]]:
    """Form rows plus the (first, last) row of the focused field's block, for scrolling."""
    out = [Line(), _title(form.title)]
    if form.error:
        out.append(Line().add("   ✗ " + form.error, EXPENSE_C))
    out.append(Line())
    focus_rows = (0, 0)
    for f in form.visible():
        start, focused = len(out), f.key == form.focus
        ln = Line(("focus", f.key)).add(" ▸ " if focused else "   ", ACCENT)
        ln.cell(f.label, INDENT - 3, "bold " + ACCENT if focused else "")
        value = form.values[f.key]
        if f.choices:
            for val, label in f.choices:
                ln.click(" %s " % label, ("chip", f.key, val), CHIP_ON if val == value else CHIP).add(" ")
        else:
            ln.add(value, "bold" if focused else "")
            if focused:
                ln.add("▏", ACCENT)
            if not value:
                ln.add(form.placeholder(f), MUTED)
            preview = _preview(form, f)
            if preview:
                ln.add("  " + preview[0], preview[1])
        out.append(ln)
        out.extend(chip_lines(form.chips(f), f.key, width, lambda v, k=f.key: form.chip_on(k, v)))
        if focused and f.key in DATE_FIELDS:
            out.extend(calendar_lines(form, f.key))
        if f.key in form.errors:
            out.append(Line().add(" " * INDENT + "⚠ " + form.errors[f.key], EXPENSE_C))
        if focused:
            focus_rows = (start, len(out) - 1)
    out += [Line(), Line().add("   Tab/↑↓ chuyển ô · nhấp để chọn · Số tiền nhận phép tính + - x :", MUTED)]
    return out, focus_rows


def body_lines(state: State, width: int, height: int) -> List[Line]:
    if state.form:
        lines, (first, last) = form_lines(state.form, width)
        if len(lines) > height:  # scroll so the focused field (with its calendar) stays visible
            start = min(first, max(0, last - height + 1))
            lines = lines[start:start + height]
        return lines
    d = state.data.get(state.tab, {})
    if state.tab == 0:
        return overview_lines(d, width) if d else [Line(), Line().add("   Không có dữ liệu.", MUTED)]
    if state.tab == 1:
        return transactions_lines(state, width, height)
    if state.tab == 2:
        return plans_lines(state, width, height)
    return budgets_lines(d, width)


def build_frame(state: State, width: int, height: int) -> Frame:
    """Exactly `height` lines of at most `width` cells, plus the hit map."""
    body_h = max(0, height - 4)
    body = body_lines(state, width, body_h)[:body_h]
    body += [Line() for _ in range(body_h - len(body))]
    rows = ([header_line(state.balance, width), tabs_line(state.tab)] + body
            + [action_line(state), status_line(state)])[:height]
    lines, spans, row_hits = [], [], []  # type: List[Text], List[Hit], List[Hit]
    for r, ln in enumerate(rows):
        ln.text.truncate(width, overflow="crop", pad=True)
        lines.append(ln.text)
        spans += [(r, x0, min(x1, width), a) for x0, x1, a in ln.spans if x0 < width]
        if ln.action:
            row_hits.append((r, 0, width, ln.action))
    return Frame(lines, spans + row_hits)


# --- form validation ---
def validate(form: Form, today: date) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    """(api cmd, params, field errors); errors are Vietnamese and keyed by field."""
    v = {k: s.strip() for k, s in form.values.items()}
    visible = {f.key for f in form.visible()}
    errors, params = {}, {}  # type: Dict[str, str], Dict[str, Any]
    if "name" in v:
        if v["name"]:
            params["name"] = v["name"]
        else:
            errors["name"] = "Nhập tên dòng tiền"
    try:
        params["amount"] = parse_money(v["amount"])
    except ValueError:
        errors["amount"] = "Số tiền không hợp lệ (vd: 50k, 1.5tr, 50k+20k, 3x150k)"
    if v["category"]:
        params["category"] = v["category"]
    else:
        errors["category"] = "Chọn hoặc gõ một danh mục"
    if "day" in visible and v["day"]:
        if form.day():
            params["day"] = form.day()
        else:
            errors["day"] = "Ngày trả phải là số từ 1 đến 31"
    for key in DATE_FIELDS:
        if key not in v or (key == "due" and not v[key] and "day" in params):
            continue  # due omitted: api picks the next date on the chosen day
        try:
            params[key] = parse_date(v[key] or form.default_date(key), today).isoformat()
        except ValueError:
            errors[key] = "Ngày không hợp lệ (vd: 06/11/2026, 2026-11-06, +3)"
    if form.name == "plan":
        params.update(every=v["every"], income=v["kind"] == "income")
        return "plan add", params, errors
    params["note"] = v["note"]
    return form.name, params, errors


# --- input handling ---
def refresh(state: State, api: ApiCall) -> None:
    """Drop cached data after a change and reload the header balance and current tab."""
    state.data.clear()
    tab, state.tab = state.tab, 0
    load(state, api)
    state.tab = tab
    load(state, api)


def open_form(state: State, name: str, api: ApiCall) -> None:
    try:
        cats = api("categories", {})
    except Exception:
        cats = {}
    state.form = Form(name, cats, state.today)


def submit(state: State, api: ApiCall) -> None:
    form = state.form
    cmd, params, errors = validate(form, state.today)
    form.errors = errors
    if errors:
        form.focus = next((f.key for f in form.visible() if f.key in errors), form.focus)
        state.set_status("Kiểm tra lại các ô được đánh dấu ⚠", False)
        return
    try:
        api(cmd, params)
    except Exception as e:  # LookupError / ValueError from api: keep the form open
        form.error = str(e)
        state.set_status(str(e), False)
        return
    state.form = None
    state.set_status("Đã lưu %s: %s" % (params.get("name") or params["category"], money(params["amount"])))
    refresh(state, api)


def _form_key(state: State, key: str, api: ApiCall) -> None:
    form = state.form
    f = form.field()
    if key == "esc":
        state.form = None
        state.set_status("Đã huỷ")
    elif key == "enter":
        submit(state, api)
    elif key in ("tab", "down"):
        form.move(1)
    elif key in ("shift-tab", "up"):
        form.move(-1)
    elif f.choices:
        if key in ("left", "right", " "):
            keys = [c[0] for c in f.choices]
            step = -1 if key == "left" else 1
            form.values[f.key] = keys[(keys.index(form.values[f.key]) + step) % len(keys)]
    elif key == "backspace":
        form.values[f.key] = form.values[f.key][:-1]
    elif len(key) == 1 and key.isprintable():
        form.values[f.key] += key
        form.errors.pop(f.key, None)


def switch_tab(state: State, tab: int, api: ApiCall) -> None:
    state.form = state.confirm = None
    if state.tab != tab:
        state.tab, state.selected, state.scroll = tab, None, 0
    load(state, api)


def handle_key(state: State, key: str, api: ApiCall) -> None:
    """Apply one key: single chars or 'up' 'down' 'left' 'right' 'enter' 'esc' 'tab' 'shift-tab' 'backspace'."""
    if state.form:
        _form_key(state, key, api)
        return
    if state.confirm:
        if key in ("y", "enter"):
            tid, state.confirm = state.confirm["id"], None
            try:
                api("rm", {"id": tid})
            except Exception as e:
                state.set_status(str(e), False)
                return
            state.selected = None
            state.set_status("Đã xoá giao dịch #%d" % tid)
            refresh(state, api)
        elif key in ("n", "esc"):
            state.confirm = None
            state.set_status("Không xoá")
        return
    items = state.items()
    if key in ("q", "ctrl-c"):
        state.running = False
    elif key in ("1", "2", "3", "4"):
        switch_tab(state, int(key) - 1, api)
    elif key == "tab":
        switch_tab(state, (state.tab + 1) % len(TABS), api)
    elif key in ("j", "down") and items:
        state.selected = 0 if state.selected is None else min(state.selected + 1, len(items) - 1)
    elif key in ("k", "up") and items:
        state.selected = 0 if state.selected is None else max(0, state.selected - 1)
    elif key == "esc":
        state.selected = None
    elif key in ("a", "i", "p"):
        open_form(state, {"a": "expense", "i": "income", "p": "plan"}[key], api)
    elif key == "d" and state.tab == 2 and state.selected is not None:
        p = items[state.selected]
        try:
            api("plan done", {"id": p["id"], "date": state.today.isoformat()})
        except Exception as e:
            state.set_status(str(e), False)
            return
        state.set_status("Đã thực hiện: %s (%s)" % (p["name"], money(p["amount"])))
        refresh(state, api)
    elif key == "x" and state.tab == 1 and state.selected is not None:
        t = items[state.selected]
        state.confirm = {"id": t["id"], "label": "%s %s ngày %s" % (t["category"], money(t["amount"]),
                                                                      _vi_date(t["date"]))}


def handle_click(state: State, x: int, y: int, api: ApiCall) -> None:
    """Left click at 1-based terminal coordinates, resolved through the last frame's hit map."""
    action = hit_at(state.hits, y - 1, x - 1)
    if not action:
        return
    kind = action[0]
    if kind == "tab":
        switch_tab(state, action[1], api)
    elif kind == "key":
        handle_key(state, action[1], api)
    elif kind == "select" and not state.confirm:
        state.selected = action[1]
    elif kind == "focus" and state.form:
        state.form.focus = action[1]
    elif kind == "chip" and state.form:
        form, key = state.form, action[1]
        form.values[key] = action[2]
        form.errors.pop(key, None)
        # jump to the next required field still empty, so "click category, type amount, Enter" works
        form.focus = next((f.key for f in form.visible() if f.key in REQUIRED and not form.values[f.key]), key)
    elif kind == "cal" and state.form:
        form, key = state.form, action[1]
        dv = form.date_value(key) or form.today
        y, m = form.months.get(key) or (dv.year, dv.month)
        m += action[2]
        form.months[key] = (y + (m - 1) // 12, (m - 1) % 12 + 1)
        form.focus = key


def dispatch(state: State, event: Event, api: ApiCall) -> None:
    if not event:
        return
    if isinstance(event, tuple):
        _, b, x, y = event
        b &= ~0b11100  # drop shift/meta/ctrl bits
        if b == 0:
            handle_click(state, x, y, api)
        elif b in (64, 65) and not state.form and not state.confirm:
            handle_key(state, "up" if b == 64 else "down", api)
        return
    handle_key(state, event, api)


_ESC_KEYS = {b"A": "up", b"B": "down", b"C": "right", b"D": "left", b"Z": "shift-tab"}


def parse_input(buf: bytes) -> Tuple[Event, int]:
    """Decode one event from the start of buf → (event, bytes consumed); (None, 0) means wait for more.

    Events: key names / single characters, or ("mouse", button, x, y) for SGR presses.
    Mouse releases and unknown sequences decode to "" (consumed, ignored).
    """
    if not buf:
        return None, 0
    b0 = buf[0]
    if b0 == 0x1B:
        if len(buf) < 2:
            return None, 0
        if buf[1:2] not in (b"[", b"O"):
            return "esc", 1
        if buf[1:3] == b"[<":
            end = next((i for i in range(3, len(buf)) if buf[i] in b"Mm"), -1)
            if end < 0:
                return (None, 0) if len(buf) < 32 else ("", len(buf))
            try:
                b, x, y = (int(n) for n in buf[3:end].split(b";"))
            except ValueError:
                return "", end + 1
            return (("mouse", b, x, y) if buf[end:end + 1] == b"M" else ""), end + 1
        end = next((i for i in range(2, len(buf)) if 0x40 <= buf[i] <= 0x7E), -1)
        if end < 0:
            return None, 0
        return _ESC_KEYS.get(buf[end:end + 1], ""), end + 1
    if b0 in (0x0D, 0x0A):
        return "enter", 1
    if b0 in (0x7F, 0x08):
        return "backspace", 1
    if b0 == 0x09:
        return "tab", 1
    if b0 == 0x03:
        return "ctrl-c", 1
    n = 1 if b0 < 0xC0 else 2 if b0 < 0xE0 else 3 if b0 < 0xF0 else 4
    if len(buf) < n:
        return None, 0
    return buf[:n].decode("utf-8", "replace"), n


class KeyReader:
    """Blocking reader of input events; returns "resize" when the wake pipe fires."""

    def __init__(self, fd: int, wake_r: int):
        self.fd, self.wake_r, self.buf = fd, wake_r, b""

    def next(self) -> Event:
        while True:
            event, n = parse_input(self.buf)
            if n:
                self.buf = self.buf[n:]
                return event
            r, _, _ = select.select([self.fd, self.wake_r], [], [], 0.05 if self.buf else None)
            if self.wake_r in r:
                os.read(self.wake_r, 64)
                return "resize"
            if self.fd in r:
                self.buf += os.read(self.fd, 1024)
            elif self.buf:  # an incomplete sequence timed out: lone ESC, or junk
                lone_esc, self.buf = self.buf == b"\x1b", b""
                return "esc" if lone_esc else ""


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

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    wake_r, wake_w = os.pipe()
    old_winch = signal.signal(signal.SIGWINCH, lambda *_: os.write(wake_w, b"x"))
    console = Console()
    reader = KeyReader(fd, wake_r)
    out_fd = sys.__stdout__.fileno()  # bypass Live's stdout proxy, which would swallow escape codes
    try:
        tty.setcbreak(fd)
        with Live(Text(), console=console, screen=True, auto_refresh=False,
                  redirect_stdout=False, redirect_stderr=False) as live:
            console.file.flush()
            os.write(out_fd, MOUSE_ON.encode())
            while state.running:
                width, height = console.size
                frame = build_frame(state, width, height)
                state.hits = frame.hits
                live.update(frame.renderable(), refresh=True)
                dispatch(state, reader.next(), call)
    except KeyboardInterrupt:
        pass
    finally:
        os.write(out_fd, MOUSE_OFF.encode())
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(wake_r)
        os.close(wake_w)
