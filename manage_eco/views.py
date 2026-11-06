"""Rich renderables built from api dicts. Imported only in human (non --json) mode."""
from typing import List

from rich import box
from rich.columns import Columns
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from manage_eco.fmt import money, progress_bar

ACCENT = "#7aa2f7"
INC = "#9ece6a"
EXP = "#f7768e"
WARN = "#e0af68"
MUTED = "#737aa2"


def _table(title: str, *cols: str, right=()) -> Table:
    t = Table(title=title, title_style="bold %s" % ACCENT, box=box.ROUNDED, border_style=MUTED,
              header_style="bold")
    for c in cols:
        t.add_column(c, justify="right" if c in right else "left")
    return t


def _signed(amount: int) -> str:
    return "[%s]%s[/]" % (INC if amount >= 0 else EXP, money(amount, signed=True))


def _bal(amount: int) -> str:
    return "[bold %s]%s[/]" % (INC if amount >= 0 else EXP, money(amount))


def tx_table(txs: List[dict]) -> Table:
    t = _table("Giao dịch", "#", "Ngày", "Danh mục", "Số tiền", "Ghi chú", right=("#", "Số tiền"))
    for x in txs:
        t.add_row(str(x["id"]), x["date"], x["category"], _signed(x["signed"]), "[%s]%s[/]" % (MUTED, x["note"]))
    if not txs:
        t.add_row("", "", "[dim]chưa có giao dịch[/]", "", "")
    return t


def plan_table(items: List[dict], today: str = "", title: str = "Dự định") -> Table:
    t = _table(title, "#", "Đến hạn", "Tên", "Danh mục", "Số tiền", "Lặp", "Trạng thái", right=("#", "Số tiền"))
    rec = {"once": "1 lần", "weekly": "hàng tuần", "monthly": "hàng tháng"}
    st = {"pending": "[%s]chờ[/]" % WARN, "done": "[%s]xong[/]" % INC, "cancelled": "[dim]huỷ[/]"}
    for p in items:
        signed = p["amount"] if p["kind"] == "income" else -p["amount"]
        due = p["due_date"]
        if p["status"] == "pending" and today and due < today:
            due = "[bold %s]%s ⚠[/]" % (EXP, due)
        t.add_row(str(p["id"]), due, p["name"], p["category"], _signed(signed),
                  rec.get(p["recurrence"], p["recurrence"]), st.get(p["status"], p["status"]))
    if not items:
        t.add_row("", "", "[dim]chưa có dự định[/]", "", "", "", "")
    return t


def budget_table(rows: List[dict]) -> Table:
    t = _table("Ngân sách tháng", "Danh mục", "Đã chi", "Hạn mức", "Còn lại", "Mức dùng",
               right=("Đã chi", "Hạn mức", "Còn lại"))
    for r in rows:
        t.add_row(r["category"], money(r["spent"]), money(r["limit"]), _signed(r["remaining"]),
                  "%s %3d%%" % (progress_bar(r["pct"]), round(r["pct"])))
    if not rows:
        t.add_row("[dim]chưa đặt ngân sách — eco budget set <danh mục> <số tiền>[/]", "", "", "", "")
    return t


def forecast_table(rows: List[dict], title: str = "Dự báo dòng tiền") -> Table:
    t = _table(title, "Ngày", "Khoản", "Số tiền", "Số dư", right=("Số tiền", "Số dư"))
    for r in rows:
        t.add_row(r["date"], r["name"], _signed(r["amount"]), _bal(r["balance"]))
    if not rows:
        t.add_row("[dim]không có dự định nào trong khoảng này[/]", "", "", "")
    return t


def low_warning(lowest) -> Text:
    if lowest and lowest["balance"] < 0:
        return Text.from_markup("[bold %s]⚠  Số dư sẽ âm %s vào ngày %s — cân nhắc hoãn/giảm khoản chi.[/]"
                                % (EXP, money(lowest["balance"]), lowest["date"]))
    if lowest:
        return Text.from_markup("[%s]✓  Số dư thấp nhất dự kiến: %s (%s)[/]"
                                % (INC, money(lowest["balance"]), lowest["date"]))
    return Text("")


def _stat(label: str, value: str) -> Panel:
    return Panel(Text.from_markup(value, justify="center"), title=label, title_align="center",
                 box=box.ROUNDED, border_style=MUTED, width=26)


def stats(balance: int, month: dict) -> Columns:
    return Columns([
        _stat("Số dư", _bal(balance)),
        _stat("Thu %s" % month["month"], "[%s]%s[/]" % (INC, money(month["income"]))),
        _stat("Chi %s" % month["month"], "[%s]%s[/]" % (EXP, money(month["expense"]))),
        _stat("Ròng", _signed(month["net"])),
    ])


def summary_view(d: dict) -> Group:
    t = _table("Chi theo danh mục", "Danh mục", "Số tiền", "Tỷ trọng", right=("Số tiền",))
    for c in d["by_category"]:
        pct = 100 * c["amount"] / d["expense"] if d["expense"] else 0
        t.add_row(c["category"], money(c["amount"]),
                  "[%s]%s[/] %3d%%" % (ACCENT, "█" * max(1, round(pct / 5)), round(pct)))
    return Group(_month_stats(d), t)


def _month_stats(d: dict) -> Columns:
    return Columns([
        _stat("Thu %s" % d["month"], "[%s]%s[/]" % (INC, money(d["income"]))),
        _stat("Chi %s" % d["month"], "[%s]%s[/]" % (EXP, money(d["expense"]))),
        _stat("Ròng", _signed(d["net"])),
    ])


def dashboard(d: dict) -> Group:
    parts = [Panel(Text.from_markup("[bold %s]Manage Eco[/]  ·  %s" % (ACCENT, d["today"])), box=box.HEAVY,
                   border_style=ACCENT), stats(d["balance"], d["month"])]
    if d["overdue"]:
        parts.append(plan_table(d["overdue"], d["today"], title="⚠ Dự định quá hạn"))
    parts.append(budget_table(d["budgets"]))
    parts.append(forecast_table(d["upcoming"], title="30 ngày tới"))
    parts.append(low_warning(d["lowest"]))
    return Group(*parts)


def render(cmd: str, d: dict):
    """Renderable for an api command result."""
    if cmd in ("income", "expense"):
        x = d["transaction"]
        return Text.from_markup("✓ Đã ghi #%d  %s  %s   ·   Số dư: %s"
                                % (x["id"], x["category"], _signed(x["signed"]), _bal(d["balance"])))
    if cmd == "list":
        return Group(tx_table(d["transactions"]), Text.from_markup("Số dư: %s" % _bal(d["balance"])))
    if cmd == "rm":
        return Text.from_markup("✓ Đã xoá #%d   ·   Số dư: %s" % (d["deleted"], _bal(d["balance"])))
    if cmd == "summary":
        return summary_view(d)
    if cmd == "plan add":
        p = d["plan"]
        return Text.from_markup("✓ Đã thêm dự định #%d  %s  %s  (đến hạn %s)"
                                % (p["id"], p["name"], money(p["amount"]), p["due_date"]))
    if cmd == "plan list":
        return plan_table(d["plans"])
    if cmd == "plan done":
        return Text.from_markup("✓ Đã thực hiện \"%s\" → giao dịch #%d %s"
                                % (d["plan"]["name"], d["transaction"]["id"], _signed(d["transaction"]["signed"])))
    if cmd == "plan cancel":
        return Text.from_markup("✓ Đã huỷ dự định #%d" % d["plan"]["id"])
    if cmd == "budget set":
        return Text.from_markup("✓ Ngân sách %s: %s/tháng" % (d["budget"]["category"], money(d["budget"]["limit"])))
    if cmd == "budget status":
        return budget_table(d["budgets"])
    if cmd == "forecast":
        return Group(Text.from_markup("Số dư hôm nay: %s" % _bal(d["balance"])),
                     forecast_table(d["rows"], title="Dự báo %d ngày" % d["days"]), low_warning(d["lowest"]))
    if cmd == "goal":
        return Panel(Text.from_markup(
            "Mục tiêu [bold]%s[/] trước %s\nCòn thiếu [bold]%s[/] trong %d tháng\n→ cần để dành [bold %s]%s/tháng[/]"
            % (money(d["target"]), d["by"], money(d["needed"]), d["months_left"], INC, money(d["per_month"]))),
            title="Mục tiêu tiết kiệm", box=box.ROUNDED, border_style=ACCENT, expand=False)
    if cmd == "dash":
        return dashboard(d)
    if cmd == "categories":
        return Text.from_markup("[bold]Chi:[/] %s\n[bold]Thu:[/] %s"
                                % (", ".join(d["expense"]) or "-", ", ".join(d["income"]) or "-"))
    return Text(str(d))
