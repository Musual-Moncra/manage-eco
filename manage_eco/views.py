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
        cat = x["category"] if x.get("category") else "[dim]Khác[/]"
        t.add_row(str(x["id"]), x["date"], cat, _signed(x["signed"]), "[%s]%s[/]" % (MUTED, x["note"]))
    if not txs:
        t.add_row("", "", "[dim]chưa có giao dịch[/]", "", "")
    return t


def goal_table(goals: List[dict]) -> Table:
    t = _table("Mục tiêu tiết kiệm", "#", "Tên", "Đã góp", "Mục tiêu", "Tiến độ", "Đến hạn", "Mỗi tháng",
               right=("#", "Đã góp", "Mục tiêu", "Mỗi tháng"))
    for g in goals:
        bar = progress_bar(g["pct"])
        t.add_row(str(g["id"]), g["name"], money(g["saved"]), money(g["target"]),
                  "%s %3d%%" % (bar, round(g["pct"])), g["by"], money(g.get("per_month", 0)))
    if not goals:
        t.add_row("", "[dim]chưa có mục tiêu[/]", "", "", "", "", "")
    return t


def account_table(accounts: List[dict], total_balance: int = 0) -> Table:
    t = _table("Tài khoản & Ví tiền", "#", "Tên tài khoản", "Số dư", "Tỷ lệ",
               right=("#", "Số dư", "Tỷ lệ"))
    for a in accounts:
        def_tag = " [bold %s][Mặc định][/]" % ACCENT if a.get("is_default") else ""
        bal_str = _bal(a["balance"])
        pct_str = "%3.1f%%" % a.get("pct", 0.0)
        t.add_row(str(a["id"]), a["name"] + def_tag, bal_str, pct_str)
    if not accounts:
        t.add_row("", "[dim]chưa có tài khoản[/]", "", "")
    return t


def transfer_table(transfers: List[dict]) -> Table:
    t = _table("Lịch sử chuyển tiền", "#", "Ngày", "Từ tài khoản", "Đến tài khoản", "Số tiền", "Ghi chú",
               right=("#", "Số tiền"))
    for tr in transfers:
        t.add_row(str(tr["id"]), tr["date"], tr["from_account"], tr["to_account"],
                  money(tr["amount"]), "[%s]%s[/]" % (MUTED, tr["note"]))
    if not transfers:
        t.add_row("", "", "", "[dim]chưa có giao dịch chuyển tiền[/]", "", "")
    return t


def plan_table(items: List[dict], today: str = "", title: str = "Dòng tiền") -> Table:
    t = _table(title, "#", "Đến hạn", "Tên", "Danh mục", "Số tiền", "Lặp", "Trạng thái", right=("#", "Số tiền"))
    rec = {"once": "1 lần", "daily": "hàng ngày", "weekly": "hàng tuần", "monthly": "hàng tháng"}
    st = {"pending": "[%s]chờ[/]" % WARN, "done": "[%s]xong[/]" % INC, "cancelled": "[dim]huỷ[/]"}
    for p in items:
        signed = p["amount"] if p["kind"] == "income" else -p["amount"]
        due = p["due_date"]
        if p["status"] == "pending" and today and due < today:
            due = "[bold %s]%s ⚠[/]" % (EXP, due)
        every = rec.get(p["recurrence"], p["recurrence"])
        if p.get("day"):
            every += " (ngày %d)" % p["day"]
        t.add_row(str(p["id"]), due, p["name"], p["category"], _signed(signed), every, st.get(p["status"], p["status"]))
    if not items:
        t.add_row("", "", "[dim]chưa có dòng tiền[/]", "", "", "", "")
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
        t.add_row("[dim]không có dòng tiền nào trong khoảng này[/]", "", "", "")
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
        parts.append(plan_table(d["overdue"], d["today"], title="⚠ Dòng tiền quá hạn"))
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
        return Text.from_markup("✓ Đã thêm dòng tiền #%d  %s  %s  (đến hạn %s)"
                                % (p["id"], p["name"], money(p["amount"]), p["due_date"]))
    if cmd == "plan list":
        return plan_table(d["plans"])
    if cmd == "plan done":
        return Text.from_markup("✓ Đã thực hiện \"%s\" → giao dịch #%d %s"
                                % (d["plan"]["name"], d["transaction"]["id"], _signed(d["transaction"]["signed"])))
    if cmd == "plan cancel":
        return Text.from_markup("✓ Đã huỷ dòng tiền #%d" % d["plan"]["id"])
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
    if cmd == "goal add":
        g = d["goal"]
        return Text.from_markup("✓ Đã thêm mục tiêu #%d %s: %s trước %s" % (g["id"], g["name"], money(g["target"]), g["by"]))
    if cmd == "goal list":
        return Group(goal_table(d["goals"]), Text.from_markup("Tổng đã góp: %s · Tiền tự do: %s" % (_bal(d["total_saved"]), _bal(d["free_balance"]))))
    if cmd == "goal save":
        g = d["goal"]
        return Text.from_markup("✓ Đã góp %s vào \"%s\" (đã có %s/%s, %d%%)"
                                % (money(d["saved_added"]), g["name"], money(g["saved"]), money(g["target"]), round(g["pct"])))
    if cmd == "goal take":
        g = d["goal"]
        return Text.from_markup("✓ Đã rút %s từ \"%s\" (còn %s/%s)"
                                % (money(d["taken"]), g["name"], money(g["saved"]), money(g["target"])))
    if cmd == "goal edit":
        g = d["goal"]
        return Text.from_markup("✓ Đã sửa mục tiêu #%d %s: %s trước %s" % (g["id"], g["name"], money(g["target"]), g["by"]))
    if cmd in ("goal rm", "goal delete"):
        return Text.from_markup("✓ Đã xoá mục tiêu #%d" % d["deleted"])
    if cmd == "account list":
        return Group(account_table(d["accounts"], d.get("total_balance", 0)),
                     Text.from_markup("Tổng tài sản: %s" % _bal(d.get("total_balance", 0))))
    if cmd == "account add":
        a = d["account"]
        def_tag = " [mặc định]" if a.get("is_default") else ""
        return Text.from_markup("✓ Đã thêm tài khoản #%d \"%s\"%s: số dư %s"
                                % (a["id"], a["name"], def_tag, money(a["balance"])))
    if cmd == "account edit":
        a = d["account"]
        return Text.from_markup("✓ Đã sửa tài khoản #%d \"%s\": số dư %s"
                                % (a["id"], a["name"], money(a["balance"])))
    if cmd in ("account rm", "account delete"):
        return Text.from_markup("✓ Đã xoá tài khoản #%d" % d["deleted"])
    if cmd == "account set-default":
        a = d["account"]
        return Text.from_markup("✓ Đã đặt tài khoản #%d \"%s\" làm mặc định" % (a["id"], a["name"]))
    if cmd == "account transfer":
        tr = d["transfer"]
        return Text.from_markup("✓ Đã chuyển %s từ \"%s\" sang \"%s\" (Số dư nguồn: %s, đích: %s)"
                                % (money(tr["amount"]), tr["from_account"], tr["to_account"],
                                   money(d["from_balance"]), money(d["to_balance"])))
    if cmd == "account transfers":
        return transfer_table(d["transfers"])
    if cmd == "dash":
        return dashboard(d)
    if cmd == "edit":
        x = d["transaction"]
        return Text.from_markup("✓ Đã sửa #%d  %s  %s  %s   ·   Số dư: %s"
                                % (x["id"], x["date"], x["category"], _signed(x["signed"]), _bal(d["balance"])))
    if cmd == "plan edit":
        p = d["plan"]
        return Text.from_markup("✓ Đã sửa dòng tiền #%d  %s  %s  (đến hạn %s)"
                                % (p["id"], p["name"], money(p["amount"]), p["due_date"]))
    if cmd == "icons":
        return Text("Kiểu icon: %s" % d["icons"])
    if cmd == "budget delete":
        return Text.from_markup("✓ Đã xoá ngân sách %s" % d["deleted"])
    if cmd == "history":
        s = d["series"]
        lo = min(r["balance"] for r in s) if s else 0
        hi = max(r["balance"] for r in s) if s else 0
        return Text.from_markup("%d ngày · thấp %s · cao %s · dự báo %d ngày"
                                % (len(s), money(lo), money(hi), len(d["forecast"])))
    if cmd == "sound":
        return Text.from_markup("Âm thanh: %s" % ("[%s]🔊 bật[/]" % INC if d["sound"] else "[dim]🔇 tắt[/]"))
    if cmd == "categories":
        return Text.from_markup("[bold]Chi:[/] %s\n[bold]Thu:[/] %s"
                                % (", ".join(d["expense"]) or "-", ", ".join(d["income"]) or "-"))
    return Text(str(d))
