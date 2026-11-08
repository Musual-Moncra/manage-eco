"""Full-screen dashboard (`eco ui`): mouse + keyboard, rich Live, raw-mode termios input.

The screen is built as plain lines by pure functions that also record a hit map
(row, x0, x1, action) for every clickable thing, so a click maps exactly to an
action and everything is testable without a TTY. Layout adapts to the terminal
size on every frame; animations (anim.py) are overlays drawn on top of the
finished lines, so they never shift the layout or the hit map. When nothing is
animating the loop blocks on input: idle means zero redraws.
"""
import calendar
import os
import re
import secrets
import select
import signal
import sys
import time
import unicodedata
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Tuple, Union

from rich.cells import cell_len
from rich.text import Text

from manage_eco import fmt
from manage_eco.fmt import money, parse_date, parse_money, progress_bar
from manage_eco.share_data import ALL_SHAREABLE_TABS, TAB_KEY_BY_INDEX

try:
    from manage_eco import anim
except ImportError:  # animations are optional
    anim = None  # type: ignore
try:
    from manage_eco import sfx
except ImportError:  # sound is optional
    sfx = None  # type: ignore
try:
    from manage_eco import chart as chart_mod
except ImportError:  # the Biểu đồ tab falls back to a sparkline
    chart_mod = None  # type: ignore

# --- cute pastel theme ---
ACCENT = "#c4b5fd"  # lavender
PINK = "#f9a8d4"
MUTED = "#a8a2c4"
INCOME_C = "#86efac"  # mint
EXPENSE_C = "#fca5a5"  # coral
WARN_C = "#fdba74"  # peach
RULE_C = "#4c4570"
INK = "#1e1b2e"
PILL = "#3b3363"
SELECT_BG = "on #352d5c"
BTN = "#ede9fe on " + PILL
BTN_KEY = "bold %s on %s" % (PINK, PILL)
BTN_PRIMARY = "bold %s on %s" % (INK, ACCENT)
BTN_PRIMARY_KEY = "%s on %s" % (INK, ACCENT)
TAB_ON = "bold %s on %s" % (INK, ACCENT)
TAB_OFF = "#cfc8ef on #2a2448"
CHIP = "#e9e5ff on " + PILL
CHIP_ON = "bold %s on %s" % (INK, INCOME_C)

MOUSE_ON = "\x1b[?1000h\x1b[?1006h"
MOUSE_OFF = "\x1b[?1000l\x1b[?1006l"
FRAME_S = 0.033  # select timeout while an animation is running
SPARKLE_S = 0.9  # anim.Sparkle default duration
SLIDE_S = 0.18  # tab underline slide

# Structural glyphs (single-width BMP: box drawing, blocks, arrows) and, separately, icon sets.
UNICODE_GLYPHS = {"logo": "◆", "marker": "▸", "cursor": "▏", "rule": "─", "full": "█", "empty": "░", "ok": "✓",
                  "err": "✗", "arrow": "→", "prev": "‹", "next": "›", "cap_l": "▐", "cap_r": "▌", "done": "✓",
                  "del": "✕", "spark": "▁▂▃▄▅▆▇█"}
ASCII_GLYPHS = {"logo": "*", "marker": ">", "cursor": "|", "rule": "-", "full": "#", "empty": ".", "ok": "v",
                "err": "x", "arrow": "->", "prev": "<", "next": ">", "cap_l": "", "cap_r": "", "done": "v",
                "del": "x", "spark": "_.-:=+*#"}
_PLAIN_FACES = {"success": "\\(^o^)/", "error": "(T_T)", "info": "(^_^)"}
# icons: emoji = v5 set; symbol (default) = single-width BMP glyphs found in Menlo / SF Mono / DejaVu, no emoji;
# off = no icons. "w" = cells reserved for a category icon. "toast" = faces passed to anim (None: anim's own).
ICON_SETS = {
    "emoji": {"tabs": ["🏠", "🏦", "💸", "🔁", "🎯", "🏺", "📈", "🔗"], "settings": "⚙", "cancel": "⊘", "happy": "(◕‿◕)", "worried": "(・_・;)", "sad": "(｡•́︿•̀｡)",
              "sound_on": "🔊", "sound_off": "🔇", "warn": "⚠", "late": "⏰", "edit": "✎", "w": 2, "toast": None,
              "popup": "emoji"},
    "symbol": {"tabs": ["⌂", "⌸", "⇄", "↻", "◎", "◈", "⌁", "☍"], "settings": "⚙", "cancel": "⊘", "happy": "(^_^)", "worried": "(o_o;)", "sad": "(T_T)",
               "sound_on": "♪ bật", "sound_off": "♪ tắt", "warn": "▲", "late": "»", "edit": "✎", "w": 1,
               "toast": _PLAIN_FACES, "popup": "symbol"},
    "off": {"tabs": ["", "", "", "", "", "", "", ""], "settings": "", "cancel": "", "happy": "(^_^)", "worried": "(o_o;)", "sad": "(T_T)",
            "sound_on": "Âm: bật", "sound_off": "Âm: tắt", "warn": "!", "late": "!", "edit": "", "w": 0,
            "toast": _PLAIN_FACES, "popup": "symbol"},
}
_ASCII_ICONS = dict(ICON_SETS["off"], happy=":)", worried=":/", sad=":(", sound_on="Am: on", sound_off="Am: off",
                    toast={"success": ":)", "error": ":(", "info": ":)"}, popup="ascii")
ICON_MODES = ("symbol", "emoji", "off")
ASCII = False
ICON_MODE = "symbol"
G = dict(UNICODE_GLYPHS, **ICON_SETS["symbol"])  # current glyphs; see set_style()

TABS = ["Tổng quan", "Tài khoản", "Giao dịch", "Dòng tiền", "Ngân sách", "Hũ tiết kiệm", "Biểu đồ", "Chia sẻ"]
TABS_SHORT = ["Tổng", "Tài", "Giao", "Dòng", "Ngân", "Hũ", "Biểu", "Chia"]
CHART_RANGES = [("30", "1T"), ("90", "3T"), ("180", "6T"), ("365", "1N"), ("0", "Tất cả")]
CHART_AHEAD = [("0", "+0"), ("30", "+30"), ("90", "+90")]
CHART_MODES = [("line", "Line"), ("candle", "Nến")]
CHART_BUCKETS = [("day", "Ngày"), ("week", "Tuần"), ("month", "Tháng")]
CATEGORY_ICONS = [  # (accent-free keywords, emoji, symbol); first match wins
    (("an", "uong", "com", "pho", "cafe", "ca phe", "tra sua"), "🍜", "♨"),
    (("nha", "thue nha", "tien nha"), "🏠", "⌂"),
    (("xang", "xe", "grab", "taxi"), "🛵", "⊙"),
    (("luong", "thuong"), "💰", "★"),
    (("mua", "shopping", "sam"), "🛒", "¤"),
    (("hoc", "sach", "khoa hoc"), "📚", "§"),
    (("dien", "nuoc", "internet", "wifi"), "💡", "↯"),
    (("claude", "app", "goi", "phan mem"), "💻", "⚙"),
]
AMOUNT_CHIPS = [(v, v) for v in ("50k", "100k", "200k", "500k", "1tr")]
LIMIT_CHIPS = [(v, v) for v in ("500k", "1tr", "2tr", "3tr", "5tr")]
GOAL_CHIPS = [(v, v) for v in ("10tr", "20tr", "50tr", "100tr")]
EVERY = [("once", "1 lần"), ("daily", "Hàng ngày"), ("weekly", "Hàng tuần"), ("monthly", "Hàng tháng")]
DAY_CHIPS = [(str(d), str(d)) for d in (1, 5, 10, 15, 20, 25)] + [("31", "Cuối tháng")]
KINDS = [("expense", "Chi"), ("income", "Thu")]
EVERY_VI = {"once": "1 lần", "daily": "hàng ngày", "weekly": "hàng tuần", "monthly": "hàng tháng"}
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
DATE_FIELDS = ("date", "due", "by")
REQUIRED = ("name", "amount", "category")


def set_style(ascii_only: bool, mode: str) -> None:
    """Pick structural glyphs (Unicode or ASCII) and the icon set; ASCII terminals get no icons."""
    global G, ASCII, ICON_MODE
    ASCII, ICON_MODE = ascii_only, mode if mode in ICON_MODES else "symbol"
    G = dict(ASCII_GLYPHS, **_ASCII_ICONS) if ascii_only else dict(UNICODE_GLYPHS, **ICON_SETS[ICON_MODE])


def use_ascii(flag: bool) -> None:
    """Switch every glyph (icons, bars, kaomoji, pills) to plain ASCII."""
    set_style(flag, ICON_MODE)


def set_icons(mode: str) -> None:
    set_style(ASCII, mode)


def _ascii_default() -> bool:
    if anim is not None:
        return anim.ascii_mode()
    enc = (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "")
    return os.environ.get("ECO_ASCII") == "1" or os.environ.get("TERM") in ("linux", "dumb") or enc != "utf8"


class Field(NamedTuple):
    key: str
    label: str
    choices: Optional[List[Tuple[str, str]]] = None
    placeholder: str = ""
    show_if: Optional[Tuple[str, str]] = None  # (other field, value) that makes this field visible
    short: str = ""  # label for narrow terminals


_AMOUNT = Field("amount", "Số tiền", placeholder="vd: 50k, 1.5tr, 50k+20k, 3x150k")
_CATEGORY = Field("category", "Danh mục", placeholder="chọn bên dưới hoặc gõ")
_ACCOUNT = Field("account", "Tài khoản", placeholder="chọn ví bên dưới (mặc định: ví chính)")
_TX_FIELDS = [_AMOUNT, _CATEGORY, _ACCOUNT, Field("note", "Ghi chú", placeholder="(không bắt buộc)"),
              Field("date", "Ngày", placeholder="hôm nay")]
DEFAULT_CHOICES = [("0", "Không"), ("1", "Mặc định")]
FORMS = {
    "expense": ("Thêm khoản chi", _TX_FIELDS),
    "income": ("Thêm khoản thu", _TX_FIELDS),
    "tx": ("Sửa giao dịch", _TX_FIELDS + [Field("kind", "Loại", KINDS)]),
    "account_add": ("Thêm tài khoản", [Field("name", "Tên tài khoản", placeholder="vd: Tiền mặt, ZaloPay, MB Bank"),
                                       Field("balance", "Số dư", placeholder="0 (vd: 500k, 1tr) (không bắt buộc)"),
                                       Field("default", "Đặt mặc định", DEFAULT_CHOICES)]),
    "account_edit": ("Sửa tài khoản", [Field("name", "Tên tài khoản"),
                                        Field("balance", "Số dư", placeholder="nhập số dư thực tế"),
                                        Field("default", "Đặt mặc định", DEFAULT_CHOICES)]),
    "account_transfer": ("Chuyển tiền nội bộ", [Field("from", "Từ tài khoản", placeholder="tên tài khoản gửi"),
                                                Field("to", "Đến tài khoản", placeholder="tên tài khoản nhận"),
                                                _AMOUNT,
                                                Field("date", "Ngày", placeholder="hôm nay"),
                                                Field("note", "Ghi chú", placeholder="(không bắt buộc)")]),
    "budget": ("Thêm ngân sách", [_CATEGORY, Field("amount", "Hạn mức / tháng", placeholder="vd: 3tr, 100k x 30")]),
    "budget_edit": ("Sửa ngân sách", [Field("amount", "Hạn mức / tháng", placeholder="vd: 3tr, 100k x 30")]),
    "goal": ("Mục tiêu tiết kiệm", [Field("amount", "Số tiền mục tiêu", placeholder="vd: 50tr"),
                                    Field("by", "Đạt trước ngày", placeholder="mặc định: 6 tháng nữa")]),
    "goal_add": ("Thêm mục tiêu tiết kiệm", [Field("name", "Tên mục tiêu", placeholder="vd: Laptop, Du lịch"),
                                             Field("amount", "Số tiền mục tiêu", placeholder="vd: 50tr"),
                                             Field("by", "Đạt trước ngày", placeholder="vd: 31/12/2026")]),
    "goal_edit": ("Sửa mục tiêu", [Field("name", "Tên mục tiêu"),
                                   Field("amount", "Số tiền mục tiêu"),
                                   Field("by", "Đạt trước ngày")]),
    "goal_save": ("Góp vào mục tiêu", [Field("amount", "Số tiền góp", placeholder="vd: 500k, 1tr, 2tr")]),
    "goal_take": ("Rút khỏi mục tiêu", [Field("amount", "Số tiền rút", placeholder="vd: 200k, 500k, 1tr")]),
    "plan": ("Thêm dòng tiền", [Field("name", "Tên", placeholder="vd: lương, thuê nhà"),
                                _AMOUNT, _CATEGORY,
                                Field("every", "Lặp", EVERY),
                                Field("day", "Ngày trả hằng tháng", placeholder="chọn bên dưới (không bắt buộc)",
                                      show_if=("every", "monthly"), short="Ngày trả"),
                                Field("due", "Ngày bắt đầu", short="Bắt đầu"),
                                Field("kind", "Loại", KINDS)]),
    "plan_done": ("Hoàn thành dòng tiền", [_ACCOUNT, Field("date", "Ngày", placeholder="hôm nay")]),
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

    def pill(self, parts: List[Tuple[str, str]], action: Action, bg: str, caps: bool = True) -> "Line":
        """Rounded-looking button: half-block caps in the pill colour around the styled parts."""
        x0 = self.x
        if caps and G["cap_l"]:
            self.add(G["cap_l"], bg)
        for s, style in parts:
            self.add(s, style)
        if caps and G["cap_r"]:
            self.add(G["cap_r"], bg)
        self.spans.append((x0, self.x, action))
        return self

    def button(self, label: str, key: str, hint: str, primary: bool = False, mode: str = "full",
               caps: bool = True, short: str = "") -> "Line":
        """mode: full = label + key, short = short label + key, key = key only."""
        lab, kst = (BTN_PRIMARY, BTN_PRIMARY_KEY) if primary else (BTN, BTN_KEY)
        if mode == "key":
            parts = [(" %s " % hint, kst)]
        else:
            parts = [(" %s " % (short or label if mode == "short" else label), lab), ("%s " % hint, kst)]
        return self.pill(parts, ("key", key), ACCENT if primary else PILL, caps).add(" ")


class Frame(NamedTuple):
    lines: List[Text]
    hits: List[Hit]

    def renderable(self) -> Text:
        out = Text("\n").join(self.lines)
        out.no_wrap, out.overflow = True, "crop"
        return out


def hit_at(hits: List[Hit], row: int, col: int) -> Optional[Action]:
    """First hit containing (row, col); overlays come first, then buttons, then whole-row actions."""
    return next((a for r, x0, x1, a in hits if r == row and x0 <= col < x1), None)


def fit(variants: List[Callable[[], Line]], width: int) -> Line:
    """First variant whose line fits in width (the last one otherwise)."""
    ln = Line()
    for make in variants:
        ln = make()
        if ln.x <= width:
            break
    return ln


def hjoin(left: List[Line], right: List[Line], lw: int, gap: int, rw: int) -> List[Line]:
    """Two columns side by side; hit spans of the right column are shifted, row actions become spans."""
    out = []
    for i in range(max(len(left), len(right))):
        lft = left[i] if i < len(left) else Line()
        rgt = right[i] if i < len(right) else Line()
        ln = Line()
        lt = lft.text.copy()
        lt.truncate(lw, overflow="crop", pad=True)
        ln.text.append_text(lt)
        ln.add(" " * gap)
        rt = rgt.text.copy()
        rt.truncate(rw, overflow="crop")
        ln.text.append_text(rt)
        off = lw + gap
        ln.spans = ([(x0, min(x1, lw), a) for x0, x1, a in lft.spans if x0 < lw]
                    + [(x0 + off, min(x1, rw) + off, a) for x0, x1, a in rgt.spans if x0 < rw])
        if lft.action:
            ln.spans.append((0, lw, lft.action))
        if rgt.action:
            ln.spans.append((off, off + rw, rgt.action))
        out.append(ln)
    return out


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
        self.edit_id = None  # type: Optional[int]

    def kind(self) -> str:
        if self.name in ("budget", "budget_edit"):
            return "expense"
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
        if key == "by":
            return "+180"
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
            return {"budget": LIMIT_CHIPS, "budget_edit": LIMIT_CHIPS, "goal": GOAL_CHIPS,
                    "goal_add": GOAL_CHIPS, "goal_edit": GOAL_CHIPS,
                    "goal_save": AMOUNT_CHIPS, "goal_take": AMOUNT_CHIPS}.get(self.name, AMOUNT_CHIPS)
        if f.key == "category":
            return [(c, c) for c in list(self.cats.get(self.kind(), []))[:8]]
        if f.key in ("account", "from", "to"):
            acc_list = self.cats.get("accounts", [])
            chips = []
            for a in acc_list:
                name = a.get("name", str(a))
                bal = a.get("balance")
                label = "%s (%s)" % (name, short_money(bal)) if bal is not None else name
                chips.append((name, label))
            return chips
        if f.key == "day":
            return DAY_CHIPS
        if f.key == "by":
            return deadline_chips(self.today)
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
        self.dash = {}  # type: Dict[str, Any]  # last overview data, for the header mood
        self.balance = None  # type: Optional[int]
        self.form = None  # type: Optional[Form]
        self.confirm = None  # type: Optional[Dict[str, Any]]
        self.status = ("", True)  # (message, ok)
        self.hits = []  # type: List[Hit]
        self.running = True
        self.sound = True
        # animations: start times on the same clock as `now`
        self.now = 0.0
        self.toast = None  # type: Optional[Tuple[Any, float]]
        self.sparkle = None  # type: Optional[Tuple[int, float]]  # (seed, start): sized to what it surrounds
        self.count = None  # type: Optional[Tuple[int, int, float]]
        self.bars_t0 = None  # type: Optional[float]
        self.popup = None  # type: Optional[Tuple[Any, float]]
        self.popup_args = {}  # type: Dict[str, Any]  # to rebuild the popup with shortened text
        self.popup_fit = {}  # type: Dict[int, Any]  # inner width -> popup whose text fits
        self.last_click = None  # type: Optional[Tuple[Action, float]]
        # views: Giao dịch month (None = all), Ngân sách month (None = this month), Dòng tiền filter, chart
        self.tx_month = None  # type: Optional[str]
        self.budget_month = None  # type: Optional[str]
        self.plans_all = False
        self.chart = {"days": 90, "ahead": 30, "mode": "line", "bucket": "week", "cursor": None}  # type: Dict[str, Any]
        self.chart_obj = None  # type: Any  # last rendered chart, for index_at()
        self.goal = None  # type: Optional[Dict[str, Any]]  # last savings goal (this session)
        self.goals = []  # type: List[Dict[str, Any]]  # persistent savings jars (hũ tiết kiệm)
        self.total_saved = 0
        self.free_balance = None  # type: Optional[int]
        self.settings = False
        self.size = (80, 24)
        # interaction VFX: only the tab underline slide (click ripple/press/glow removed on request)
        self.slide = None  # type: Optional[Tuple[int, int, float]]  # (from tab, to tab, start)
        # sharing
        self.share_active = False
        self.share_server = None
        self.share_tunnel = None
        self.share_pin = f"{secrets.randbelow(9000) + 1000}"
        self.share_allowed_tabs = {"overview", "cashflow", "budgets", "goals", "chart"}
        self.share_sync_mode = "free"
        self.share_allowed_edits = {"expense"}

    def _on_remote_mutation(self) -> None:
        self.dirty = True
        try:
            play(self, "save")
        except Exception:
            pass
        wake_w = getattr(self, "_wake_w", None)
        if wake_w is not None:
            try:
                os.write(wake_w, b"m")
            except OSError:
                pass

    def toggle_share(self) -> None:
        if self.share_active:
            if self.share_tunnel:
                self.share_tunnel.stop()
                self.share_tunnel = None
            if self.share_server:
                self.share_server.stop()
                self.share_server = None
            self.share_active = False
            self.set_status("Đã tắt chia sẻ trực tiếp")
        else:
            try:
                from manage_eco.web import start_share_server
                from manage_eco.tunnel import create_tunnel
                self.share_pin = f"{secrets.randbelow(9000) + 1000}"
                store = getattr(self, "store", None)
                if store is None:
                    from manage_eco.db import Store
                    store = Store()
                    self.store = store
                cur_tab_key = TAB_KEY_BY_INDEX[self.tab] if self.tab < len(TAB_KEY_BY_INDEX) else "overview"
                self.share_server = start_share_server(
                    store,
                    self.today,
                    port=0,
                    pin=self.share_pin,
                    allowed_tabs=self.share_allowed_tabs,
                    active_tab=cur_tab_key,
                    sync_mode=self.share_sync_mode,
                    allowed_edits=self.share_allowed_edits,
                    on_mutation=self._on_remote_mutation,
                )
                self.share_tunnel = create_tunnel()
                self.share_tunnel.start(self.share_server.port)
                self.share_active = True
                self.set_status("Đã bật chia sẻ trực tiếp")
            except Exception as e:
                self.set_status(f"Lỗi bật chia sẻ: {e}", False)

    def toggle_share_tab(self, tab_key: str) -> None:
        if tab_key in self.share_allowed_tabs:
            self.share_allowed_tabs.remove(tab_key)
        else:
            self.share_allowed_tabs.add(tab_key)
        if self.share_server:
            self.share_server.update_config(allowed_tabs=self.share_allowed_tabs)

    def toggle_share_edit(self, edit_key: str) -> None:
        if edit_key in self.share_allowed_edits:
            self.share_allowed_edits.remove(edit_key)
        else:
            self.share_allowed_edits.add(edit_key)
        if self.share_server:
            self.share_server.update_config(allowed_edits=self.share_allowed_edits)

    def set_share_sync_mode(self, mode: str) -> None:
        self.share_sync_mode = mode
        if self.share_server:
            self.share_server.update_config(sync_mode=mode)

    def notify_share(self, event_type: str = "update") -> None:
        if self.share_active and self.share_server:
            try:
                self.share_server.notify_change(event_type)
            except Exception:
                pass

    def get_share_url(self) -> Optional[str]:
        if not self.share_active:
            return None
        pin = self.share_pin
        if self.share_tunnel and self.share_tunnel.url:
            return f"{self.share_tunnel.url}?pin={pin}"
        if self.share_server:
            from manage_eco.tunnel import get_local_ip
            return f"http://{get_local_ip()}:{self.share_server.port}/?pin={pin}"
        return None

    def items(self) -> List[Dict[str, Any]]:
        d = self.data.get(self.tab, {})
        key = {1: "accounts", 2: "transactions", 3: "plans", 4: "budgets", 5: "goals"}.get(self.tab)
        return (d.get(key) or []) if key else []

    def set_status(self, msg: str, ok: bool = True) -> None:
        self.status = (msg, ok)

    def animating(self) -> bool:
        """True while any animation still has frames to draw at `now`."""
        t = self.now
        return bool((self.popup and t - self.popup[1] < _duration(self.popup[0]))
                    or (self.toast and not self.popup and not self.toast[0].done(t - self.toast[1]))
                    or (self.sparkle and t - self.sparkle[1] < SPARKLE_S)
                    or (self.count and t - self.count[2] < 0.6)
                    or (self.bars_t0 is not None and t - self.bars_t0 < 0.5)
                    or (self.slide and t - self.slide[2] < SLIDE_S))

    def shown_balance(self) -> Optional[int]:
        if anim is not None and self.count and self.now - self.count[2] < 0.6:
            a, b, t0 = self.count
            return anim.count_up(a, b, self.now - t0)
        return self.balance

    def bar_pct(self, pct: float) -> float:
        if anim is not None and self.bars_t0 is not None and self.now - self.bars_t0 < 0.5:
            return anim.bar_fill(pct, self.now - self.bars_t0)
        return pct


def _dur(obj: Any, default: float) -> float:
    return float(getattr(obj, "duration", default))


def shift_month(month: str, step: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) + step
    return "%d-%02d" % (y + (m - 1) // 12, (m - 1) % 12 + 1)


def tab_request(state: State, tab: int) -> Tuple[str, Dict[str, Any]]:
    """The api call behind each tab, from the view settings (month, filter, chart range)."""
    if tab == 1:
        return "account list", {}
    if tab == 2:
        return "list", ({"month": state.tx_month} if state.tx_month else {"all": True})
    if tab == 3:
        return "plan list", {"all": state.plans_all}
    if tab == 4:
        return "budget status", ({"month": state.budget_month} if state.budget_month else {})
    if tab == 5:
        return "goal list", {}
    if tab == 6:
        return "history", {"days": state.chart["days"], "ahead": state.chart["ahead"]}
    return "dash", {}


def load(state: State, api: ApiCall) -> None:
    """Fetch data for the current tab (cached until a mutation clears it)."""
    if state.tab in state.data:
        return
    cmd, params = tab_request(state, state.tab)
    try:
        data = api(cmd, dict(params))
    except Exception as e:  # api missing or failing: show it, keep running
        state.set_status("Lỗi tải dữ liệu: %s" % e, False)
        data = {}
    if state.tab == 1:
        try:
            trs_data = api("account transfers", {})
            data["transfers"] = trs_data.get("transfers", [])
        except Exception:
            data["transfers"] = []
    if state.tab == 2:
        data = dict(data, transactions=list(reversed(data.get("transactions") or [])))  # newest first
    if state.tab in (0, 5) and data:
        if state.tab == 0:
            state.dash = data
        state.goals = data.get("goals") or []
        state.total_saved = data.get("total_saved", 0)
        state.free_balance = data.get("free_balance", state.balance)
    state.data[state.tab] = data
    if "balance" in data:
        state.balance = data["balance"]
    n = len(state.items())
    if state.selected is not None and state.selected >= n:
        state.selected = n - 1 if n else None
    if getattr(state, "share_active", False):
        state.notify_share("data_changed")


# --- feedback: sound, toast, sparkle, counters ---
def play(state: State, event: str) -> None:
    if sfx is not None:
        try:
            sfx.play(event, enabled=state.sound)
        except Exception:  # never let audio break the UI
            pass


def _duration(popup: Any) -> float:
    return float(getattr(popup, "duration", 1.6))


def toast(state: State, message: str, kind: str = "success", sparkle: bool = False) -> None:
    if anim is None:
        return
    faces = G["toast"]
    try:  # newer anim.py picks font-safe glyphs itself
        state.toast = (anim.Toast(message, kind, icon=faces[kind] if faces else None, glyphs=G["popup"]), state.now)
    except TypeError:
        state.toast = (anim.Toast(message, kind, icon=faces[kind] if faces else None), state.now)
    state.sparkle = (int(state.now * 1000) & 0xFFFF, state.now) if sparkle else None
    state.popup = None


def popup(state: State, icon: str, title: str, subtitle: str, message: str, kind: str = "success",
          sparkle: bool = True) -> None:
    """Centered pixel-art popup (anim.PixelPopup); the toast is kept as its fallback when it does not fit."""
    toast(state, message, kind, sparkle)
    pixel = getattr(anim, "PixelPopup", None) if anim is not None else None  # newer anim.py only
    if pixel is None:
        return
    args = dict(icon=icon, title=title, subtitle=subtitle, glyphs=G["popup"], seed=int(state.now * 1000) & 0xFFFF)
    try:
        state.popup = (pixel(**args), state.now)
    except Exception:  # an incompatible PixelPopup must never break saving
        state.popup = None
    state.popup_args, state.popup_fit = args, {}


def _fitted_popup(state: State, width: int, height: int) -> Any:
    """The popup, rebuilt (same seed, same timeline) with text shortened so amounts are never cut."""
    pixel, args = state.popup[0], state.popup_args
    size = getattr(pixel, "size", None)
    if not size or not args:
        return pixel
    inner = size(width, height)[0] - 2
    if cell_len(args["title"]) <= inner and cell_len(args["subtitle"]) <= inner:
        return pixel
    if inner not in state.popup_fit:
        state.popup_fit[inner] = type(pixel)(**dict(args, title=fit_money(args["title"], inner),
                                                    subtitle=fit_money(args["subtitle"], inner)))
    return state.popup_fit[inner]


def popup_active(state: State) -> bool:
    return bool(state.popup and state.now - state.popup[1] < _duration(state.popup[0]))


def fail(state: State, message: str) -> None:
    state.set_status(message, False)
    popup(state, "cross", message, "", message, "error", sparkle=False)
    play(state, "error")


def worrying(dash: Dict[str, Any]) -> bool:
    low = dash.get("lowest") or {}
    return low.get("balance", 0) < 0 or any(float(b.get("pct", 0)) >= 100 for b in dash.get("budgets") or [])


def celebrate(state: State, api: ApiCall, message: str, event: str, icon: str, title: str, subtitle: str,
              kind: str = "success", sparkle: bool = True) -> None:
    """After a successful change: reload, tick the balance, pop the pixel popup and play a sound."""
    before = state.balance
    refresh(state, api)
    if before is not None and state.balance is not None and before != state.balance:
        state.count = (before, state.balance, state.now)
    state.set_status(message)
    popup(state, icon, title, subtitle, message, kind, sparkle)
    play(state, "warn" if event == "save" and worrying(state.dash) else event)


# --- formatting helpers ---
def _vi_date(iso: str, short: bool = False) -> str:
    y, m, d = iso.split("-")
    return "%s/%s" % (d, m) if short else "%s/%s/%s" % (d, m, y)


def _dmy(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def short_money(v: int) -> str:
    """Compact amount for narrow columns: 85k, 3tr, 1,5tr, 2 tỷ."""
    a, sign = abs(v), "-" if v < 0 else ""
    for unit, size in (("tỷ", 10 ** 9), ("tr", 10 ** 6), ("k", 10 ** 3)):
        if a >= size:
            n = ("%.1f" % (a / size)).rstrip("0").rstrip(".").replace(".", ",")
            return sign + n + ("" if unit != "tỷ" else " ") + unit
    return "%s%dđ" % (sign, a)


MONEY_RE = re.compile(r"([+-]?)(\d{1,3}(?:\.\d{3})*) ₫")


def fit_money(s: str, width: int) -> str:
    """Make a line fit in `width` cells without losing its last amount: full text, then short
    amounts (-30,3tr), then an ellipsis in the text before the last amount."""
    if cell_len(s) <= width:
        return s
    s = MONEY_RE.sub(lambda m: short_money(int(m.group(1) + m.group(2).replace(".", ""))), s)
    if cell_len(s) <= width:
        return s
    last = None
    for last in re.finditer(r"[+-]?\d[\d,]*\s?(?:tỷ|tr|k|đ)", s):
        pass
    start = len(s)  # no amount: plain ellipsis at the end
    if last:
        start = last.start() - (1 if last.start() and s[last.start() - 1] == " " else 0)
    tail = s[start:]
    head = Text(s[:start])
    head.truncate(max(0, width - cell_len(tail)), overflow="ellipsis")
    return head.plain + tail


def _plain(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if not unicodedata.combining(c))


def category_icon(name: str, mode: Optional[str] = None) -> str:
    words = " %s " % " ".join(_plain(name).split())
    for keys, emoji, symbol in CATEGORY_ICONS:
        if any(" %s " % k in words for k in keys):
            return emoji if (mode or ICON_MODE) == "emoji" else symbol
    return "•"


def cat_label(name: str) -> str:
    display = name or "Khác"
    if not G["w"]:
        return display
    icon = category_icon(name or "khac")
    return "%s%s %s" % (icon, " " * (G["w"] - cell_len(icon)), display)  # icons padded to the set's width


def date_chips(today: date) -> List[Tuple[str, str]]:
    last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return [(_dmy(d), label) for d, label in ((today - timedelta(days=1), "Hôm qua"), (today, "Hôm nay"),
                                              (today + timedelta(days=1), "Mai"), (last, "Cuối tháng"),
                                              (last + timedelta(days=1), "Đầu tháng sau"))]


def _months_later(d: date, months: int) -> date:
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def deadline_chips(today: date) -> List[Tuple[str, str]]:
    """Chips for a savings deadline: month / year end and a few horizons."""
    month_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    return [(_dmy(d), label) for d, label in ((month_end, "Cuối tháng"), (date(today.year, 12, 31), "Cuối năm"),
                                              (_months_later(today, 3), "+3 tháng"),
                                              (_months_later(today, 6), "+6 tháng"),
                                              (_months_later(today, 12), "+1 năm"))]


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


def _bar(pct: float, width: int, shown: Optional[float] = None) -> Text:
    """Progress bar coloured by the real pct; `shown` is the (animated) fill level."""
    color = INCOME_C if pct < 80 else WARN_C if pct < 100 else EXPENSE_C
    fill = pct if shown is None else shown
    filled = int(round(max(0.0, min(100.0, fill)) / 100 * width))
    return Text.assemble((G["full"] * filled, color), (G["empty"] * (width - filled), RULE_C))


def _rule(width: int) -> Line:
    return Line().add(" " + G["rule"] * max(0, width - 2), RULE_C)


def _title(s: str) -> Line:
    return Line().add(" " + s, "bold " + ACCENT)


def mood(dash: Dict[str, Any]) -> str:
    low = dash.get("lowest") or {}
    if low.get("balance", 0) < 0:
        return G["sad"]
    if any(float(b.get("pct", 0)) >= 80 for b in dash.get("budgets") or []):
        return G["worried"]
    return G["happy"]


# --- screen parts (pure) ---
def header_line(state: State, width: int) -> Line:
    bal = state.shown_balance()
    amount = "—" if bal is None else money(bal)
    color = MUTED if bal is None else EXPENSE_C if bal < 0 else INCOME_C
    face = mood(state.dash)
    for left, label in ((" %s Manage Eco " % G["logo"], "Số dư "), (" %s Eco " % G["logo"], "Số dư "),
                        (" %s Eco " % G["logo"], "")):
        right_len = cell_len(label + amount + " ")
        if cell_len(left + face) + 1 + right_len <= width:
            break
    pad = max(1, width - cell_len(left + face) - right_len)
    return (Line().add(left, "bold " + ACCENT).add(face, PINK).add(" " * pad)
            .add(label, MUTED).add(amount, "bold " + color).add(" "))


def tabs_line(active: int, width: int) -> Line:
    def make(labels: List[str], icons: bool, caps: bool, gap: str = " ", compact_pad: bool = False) -> Callable[[], Line]:
        def build() -> Line:
            ln = Line().add(" " if not compact_pad else "")
            for i, name in enumerate(labels):
                icon = G["tabs"][i] + " " if icons and G["tabs"][i] else ""
                if compact_pad:
                    text = ("%s%s" % (icon, name)) if name or not icon else icon
                else:
                    text = (" %s%s " % (icon, name)) if name or not icon else " %s" % icon
                ln.pill([(text, TAB_ON if i == active else TAB_OFF)], ("tab", i),
                        ACCENT if i == active else "#2a2448", caps).add(gap)
            return ln
        return build
    n = len(TABS)
    active_full = [TABS[i] if i == active else TABS_SHORT[i] for i in range(n)]
    icon_only = [TABS_SHORT[i] if i == active or not G["tabs"][i] else "" for i in range(n)]
    digits = [str(i + 1) for i in range(n)]
    return fit([make(TABS, True, True),
                make(TABS, True, True, compact_pad=True),
                make(active_full, True, True),
                make(active_full, True, True, compact_pad=True),
                make(TABS_SHORT, True, True),
                make(TABS_SHORT, True, False),
                make(icon_only, True, True),
                make(icon_only, True, False),
                make(digits, False, False, "")], width)


def action_line(state: State, width: int) -> Line:
    prefix = short_prefix = ""
    if state.form:
        buttons = [("Lưu", "Lưu", "enter", "Enter", True), ("Huỷ", "Huỷ", "esc", "Esc", False)]
    elif state.confirm:
        c = state.confirm
        buttons = [("Có", "Có", "y", "y", True), ("Không", "Không", "n", "n", False)]
        prefix, short_prefix = "%s %s? " % (c["verb"], c["label"]), "%s %s? " % (c["verb"], c["short"])
    elif state.settings:
        buttons = [("Đóng", "Đóng", "esc", "Esc", True)]
    else:
        buttons = {1: [("+ Thêm", "+Thêm", "a", "a", False), ("⇄ Chuyển", "Chuyển", "t", "t", False)],
                   2: [("+ Chi", "+Chi", "a", "a", False), ("+ Thu", "+Thu", "i", "i", False)],
                   3: [("+ Dòng tiền", "+Dòng", "p", "p", False)],
                   4: [("+ Ngân sách", "+NS", "b", "b", False)],
                   5: [("+ Tạo hũ", "+Hũ", "goal_add", "+Hũ", False)],
                   7: [("Bật/Tắt", "Bật/Tắt", "s", "s", False), ("Sao chép", "Chép", "c", "c", False)]}.get(
            state.tab, [("+ Chi", "+Chi", "a", "a", False), ("+ Thu", "+Thu", "i", "i", False),
                        ("+ Dòng tiền", "+Dòng", "p", "p", False)])
        item = selected_item(state)
        if item is not None:
            pending = item.get("status", "pending") == "pending"
            if state.tab == 1:
                buttons.append((("%s Sửa" % G["edit"]).strip(), G["edit"] or "Sửa", "e", "e", False))
                buttons.append(("★ Mặc định", "Mặc định", "d", "d", False))
                buttons.append(("%s Xoá" % G["del"], G["del"], "x", "x", False))
            elif state.tab == 5:
                buttons.append(("+ Góp", "+G", "goal_save:%d" % item["id"], "+G", False))
                buttons.append(("- Rút", "-R", "goal_take:%d" % item["id"], "-R", False))
                buttons.append((("%s Sửa" % G["edit"]).strip(), G["edit"] or "Sửa", "e", "e", False))
                buttons.append(("%s Xoá" % G["del"], G["del"], "x", "x", False))
            elif state.tab in (2, 4) or pending:
                buttons.append((("%s Sửa" % G["edit"]).strip(), G["edit"] or "Sửa", "e", "e", False))
            if state.tab == 3 and pending:
                buttons.append(("%s Xong" % G["done"], G["done"], "d", "d", False))
                buttons.append((("%s Huỷ" % G["cancel"]).strip(), G["cancel"] or "Huỷ", "c", "c", False))
            if state.tab in (2, 4):
                buttons.append(("%s Xoá" % G["del"], G["del"], "x", "x", False))
        gear = ("%s Cài đặt" % G["settings"]).strip()
        buttons += [(gear, G["settings"] or "Cài đặt", "s", "s", False), ("Thoát", "Thoát", "q", "q", False)]

    def make(mode: str, caps: bool, pre: str) -> Callable[[], Line]:
        def build() -> Line:
            ln = Line().add(" ")
            if pre:
                ln.add(pre, "bold " + EXPENSE_C)
            for label, short, key, hint, primary in buttons:
                ln.button(label, key, hint, primary, mode, caps, short)
            return ln
        return build
    modes = [("full", True), ("full", False), ("short", True), ("short", False), ("key", False)]
    return fit([make(m, c, prefix) for m, c in modes] + [make(m, c, short_prefix) for m, c in modes]
               + [make("key", False, "")], width)


def status_line(state: State, width: int) -> Line:
    msg, ok = state.status
    if not msg:
        return Line().add(" Nhấp chuột vào nút, hoặc bấm phím ghi trên nút.", MUTED)
    return Line().add(fit_money(" %s %s" % (G["ok"] if ok else G["err"], msg), width),
                      "bold " + (INCOME_C if ok else EXPENSE_C))


def budget_section(state: State, budgets: List[Dict[str, Any]], width: int, rows: int) -> List[Line]:
    out = [_title("Ngân sách")]
    if not budgets:
        return out + [Line().add("   Chưa đặt ngân sách (eco budget set DANH_MỤC SỐ_TIỀN)", MUTED)]
    full = width >= 70
    cat_w = 26 if width >= 120 else 20 if width >= 90 else 16 if width >= 65 else 11
    money_w = 30 if full else 11
    bar_w = max(4, min(40 if width >= 100 else 30, width - 3 - cat_w - 1 - 6 - 2 - money_w))
    for b in sorted(budgets, key=lambda b: -float(b.get("pct", 0)))[:rows]:
        pct = float(b.get("pct", 0))
        spent, limit = b.get("spent", 0), b.get("limit", 0)
        ln = Line(("tab", 4)).add("   ").cell(cat_label(b["category"]), cat_w).add(" ")
        ln.text.append_text(_bar(pct, bar_w, state.bar_pct(pct)))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        amounts = ("%s / %s" % (money(spent), money(limit))) if full else \
            "%s/%s" % (short_money(spent), short_money(limit))
        ln.cell(amounts, money_w, right=True)
        out.append(ln)
    return out


def upcoming_section(rows_data: List[Dict[str, Any]], width: int, rows: int) -> List[Line]:
    out = [_title("Sắp tới 30 ngày")]
    if not rows_data:
        return out + [Line().add("   Không có dòng tiền nào trong 30 ngày tới.", MUTED)]
    with_balance = width >= 70
    name_w = max(6, width - 3 - 5 - 2 - 2 - 15 - (19 if with_balance else 0))
    for r in rows_data[:rows]:
        amt, c = _signed(r["amount"])
        ln = (Line(("tab", 3)).add("   ").cell(_vi_date(r["date"], short=True), 5, MUTED).add("  ")
              .cell(r["name"], name_w).add("  ").cell(amt, 15, c, right=True))
        if with_balance:
            ln.add(" %s " % G["arrow"], MUTED).cell(money(r["balance"]), 15,
                                                    EXPENSE_C if r["balance"] < 0 else "", right=True)
        out.append(ln)
    return out


def balance_series(d: Dict[str, Any], today: date, days: int = 30) -> List[int]:
    """End-of-day balance for today..today+days from the dash forecast rows."""
    bal = d.get("balance") or 0
    by_day = {}  # type: Dict[str, int]
    for r in d.get("upcoming") or []:
        by_day[r["date"]] = r["balance"]  # rows are chronological: the last one of a day wins
    out = []
    for i in range(days + 1):
        bal = by_day.get((today + timedelta(days=i)).isoformat(), bal)
        out.append(bal)
    return out


def sparkline_lines(d: Dict[str, Any], today: date, width: int) -> List[Line]:
    series = balance_series(d, today)
    lo, hi = min(series), max(series)
    ticks = G["spark"]
    k = max(1, min(3, (width - 34) // len(series)))
    ln = Line(("tab", 6)).add("   ")  # opens the Biểu đồ tab
    for v in series:
        level = 0 if hi == lo else int((v - lo) / (hi - lo) * (len(ticks) - 1))
        ln.add(ticks[level] * k, EXPENSE_C if v < 0 else INCOME_C)
    ln.add("   thấp %s · cao %s" % (short_money(lo), short_money(hi)), MUTED)
    return [_title("Số dư 30 ngày tới"), ln]


def category_section(m: Dict[str, Any], width: int, rows: int) -> List[Line]:
    """This month's spending by category (api summary via dash), largest first."""
    cats = m.get("by_category") or []
    out = [_title("Chi theo danh mục")]
    if not cats:
        return out + [Line().add("   Chưa có khoản chi nào tháng này.", MUTED)]
    total = sum(c["amount"] for c in cats) or 1
    full = width >= 70
    cat_w = 26 if width >= 120 else 20 if width >= 90 else 16 if width >= 65 else 14
    money_w = 18 if full else 7
    bar_w = max(4, min(36 if width >= 100 else 24, width - 3 - cat_w - 1 - 6 - 2 - money_w))
    for c in cats[:rows]:
        pct = c["amount"] * 100.0 / total
        filled = int(round(pct / 100 * bar_w))
        ln = Line(("tab", 2)).add("   ").cell(cat_label(c["category"]), cat_w).add(" ")
        ln.text.append_text(Text.assemble((G["full"] * filled, PINK), (G["empty"] * (bar_w - filled), RULE_C)))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        ln.cell(money(c["amount"]) if full else short_money(c["amount"]), money_w, right=True)
        out.append(ln)
    return out


def goal_line(state: State, width: int) -> Line:
    """Savings goal card (one line) with its edit button; the way into the goal form."""
    g = state.goal
    ln = Line().add(" ")
    if not g:
        return ln.add("Mục tiêu tiết kiệm: chưa đặt  ", MUTED).button("Đặt mục tiêu", "g", "g", short="Đặt")
    if g.get("needed", 0) <= 0:
        text = "Mục tiêu %s trước %s: đã đủ %s" % (short_money(g["target"]), _vi_date(g["by"]), G["ok"])
    else:
        text = "Mục tiêu %s trước %s: cần %s/tháng (%d tháng)" % (
            short_money(g["target"]), _vi_date(g["by"]), short_money(g.get("per_month", 0)), g.get("months_left", 0))
    ln.add(fit_money(text, max(10, width - 12)), ACCENT).add("  ")
    return ln.button(G["edit"] or "Sửa", "g", "g", short=G["edit"] or "Sửa")


def goal_lines(state: State, width: int) -> List[Line]:
    if not state.goals:
        return [goal_line(state, width)]
    lines = []
    total_saved = state.total_saved
    free_bal = (state.balance if state.balance is not None else 0) - total_saved
    full = width >= 100
    hdr = Line().add("   Tiền tự do: ", MUTED).add(money(free_bal) if full else short_money(free_bal), "bold " + INCOME_C)
    if total_saved > 0:
        hdr.add(" · Đã góp: ", MUTED).add(money(total_saved) if full else short_money(total_saved), ACCENT)
    hdr.add("   ").click("Xem hũ →", ("tab", 5), BTN).add(" ").button("+ Mục tiêu", "goal_add", "+MT", short="+")
    lines.append(hdr)

    name_w = 28 if width >= 150 else 20 if width >= 115 else 14 if width >= 80 else 10
    bar_w = 16 if width >= 150 else 10
    use_full_money = width >= 160
    for g in state.goals:
        pct = g.get("pct", 0)
        saved = g.get("saved", 0)
        target = g.get("target", 0)
        saved_str = ("%s / %s" % (money(saved), money(target))) if use_full_money else \
                    ("%s/%s" % (short_money(saved), short_money(target)))
        rem = g.get("remaining", 0)
        per_m = g.get("per_month", 0)
        days = g.get("days_left", 0)
        track = ("%s Kịp" % G["ok"]) if g.get("on_track", True) else ("%s Chậm" % G["warn"])
        track_c = INCOME_C if g.get("on_track", True) else WARN_C
        ln = Line().add("   ◎ ", ACCENT).cell(g.get("name", "Mục tiêu"), name_w).add(" ")
        ln.text.append_text(_bar(pct, bar_w))
        ln.add(" %3d%%  " % round(pct), "bold " + ACCENT).add(saved_str, MUTED)
        if width >= 150:
            ln.add(" · thiếu %s · %s/tháng · %d ngày · " % (money(rem) if width >= 170 else short_money(rem),
                                                            money(per_m) if width >= 170 else short_money(per_m),
                                                            days), MUTED)
            ln.add(track, track_c)
        elif width >= 125:
            ln.add(" · thiếu %s · %s/th · %d ngày · " % (short_money(rem), short_money(per_m), days), MUTED)
            ln.add(track, track_c)
        ln.add("  ")
        ln.button("+ Góp", "goal_save:%d" % g["id"], "+G", short="+G")
        ln.button("- Rút", "goal_take:%d" % g["id"], "-R", short="-R")
        if width >= 100:
            ln.button(G["edit"] or "✎", "goal_edit:%d" % g["id"], "e", short="✎")
            ln.button(G["del"] or "✕", "goal_rm:%d" % g["id"], "x", short="✕")
        lines.append(ln)
    return lines


def overview_lines(state: State, d: Dict[str, Any], width: int, height: int) -> List[Line]:
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
    accs = d.get("accounts") or []
    if accs:
        acc_parts = ["%s: %s" % (a["name"], short_money(a["balance"])) for a in accs[:4]]
        out.append(Line(("tab", 1)).add("   Ví / Tài khoản: ", MUTED).add("  │  ".join(acc_parts), ACCENT))
    out.append(_rule(width))

    tail = []  # type: List[Line]
    low = d.get("lowest")
    if low and low.get("balance", 0) < 0:
        if width >= 80:
            warn = " %s Sẽ âm tiền ngày %s (thấp nhất %s)" % (G["warn"], _vi_date(low["date"]), money(low["balance"]))
        else:
            warn = " %s Âm tiền %s: %s" % (G["warn"], _vi_date(low["date"], short=True), short_money(low["balance"]))
        tail.append(Line(("tab", 3)).add(fit_money(warn, width), "bold " + EXPENSE_C))
    else:
        tail.append(Line().add(" %s Số dư không bị âm trong 90 ngày tới." % G["ok"], INCOME_C))
    overdue = d.get("overdue") or []
    if overdue:
        tail.append(Line(("tab", 3)).add(fit_money(" %s Quá hạn: %s" % (G["late"], ", ".join(p["name"] for p in overdue)),
                                                   width),
                                         WARN_C))
    for gl in reversed(goal_lines(state, width)):
        tail.insert(0, gl)
    if tail:
        tail.insert(0, _rule(width))
    spark = sparkline_lines(d, state.today, width) if width >= 160 else []
    spare = height - len(out) - len(tail) - (len(spark) + 1 if spark else 0)

    budgets, upcoming = d.get("budgets") or [], d.get("upcoming") or []
    month = d.get("month") or {}
    if width >= 120:
        lw = (width - 3) // 2
        half = max(1, min(6, (spare - 3) // 2))
        left = budget_section(state, budgets, lw, half) + [_rule(lw)] + category_section(month, lw, half)
        right = upcoming_section(upcoming, width - lw - 3, max(1, min(12, spare - 2)))
        out += hjoin(left, right, lw, 3, width - lw - 3)
    elif (spare - 5) // 3 >= 1:  # room for budgets, upcoming and spending by category
        rows = min(5, (spare - 5) // 3)
        out += (budget_section(state, budgets, width, rows) + [_rule(width)] + upcoming_section(upcoming, width, rows)
                + [_rule(width)] + category_section(month, width, rows))
    else:
        rows = max(1, min(10, (spare - 3) // 2))
        out += budget_section(state, budgets, width, rows) + [_rule(width)] + upcoming_section(upcoming, width, rows)
    if spark:
        out += [_rule(width)] + spark
    return out + tail


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


def month_label(month: str) -> str:
    return "Tháng %s/%s" % (month[5:7], month[:4])


def nav_line(state: State, key: str, month: Optional[str], all_chip: bool) -> Line:
    """‹ Tháng 11/2026 › [Tất cả]: month navigation for a list tab."""
    shown = month or state.today.strftime("%Y-%m")
    ln = Line().add(" ").click(" %s " % G["prev"], ("month", key, -1), BTN)
    ln.add("  %s  " % (month_label(shown) if month or not all_chip else "Mọi tháng"), "bold")
    ln.click(" %s " % G["next"], ("month", key, 1), BTN)
    if all_chip:
        ln.add("  ").click(" Tất cả ", ("month", key, 0), CHIP_ON if month is None else CHIP)
    return ln


def transactions_lines(state: State, width: int, height: int) -> List[Line]:
    compact, wide = width < 60, width >= 120
    date_w = 5 if compact else 10
    cat_w = 26 if width >= 140 else 20 if width >= 100 else 18 if not compact else 14
    amt_w = 18 if wide else 16 if not compact else 14
    extra = 13 if wide else 0  # "#id  Thu/Chi"
    note_w = 0 if compact else max(4, width - 1 - date_w - cat_w - amt_w - 6 - extra)
    if compact:
        cat_w = max(6, width - 1 - date_w - amt_w - 4)

    def columns(ln: Line, d: str, c: str, note: str, kind: str, ident: str, amount: str,
                styles: Tuple[str, str, str]) -> Line:
        ln.add(" ").cell(d, date_w, styles[0]).add("  ").cell(c, cat_w).add("  ")
        if note_w:
            ln.cell(note, note_w, MUTED).add("  ")
        if wide:
            ln.cell(ident, 6, MUTED).cell(kind, 5, styles[2]).add("  ")
        return ln.cell(amount, amt_w, styles[1], right=True)

    head = columns(Line(), "Ngày", "Danh mục", "Ghi chú", "Loại", "#", "Số tiền", (MUTED, MUTED, MUTED))
    head.text.stylize(MUTED)

    def row(t: Dict[str, Any]) -> Line:
        amt, c = _signed(t["amount"], t["kind"])
        return columns(Line(), _vi_date(t["date"], short=compact), cat_label(t["category"]), t.get("note", ""),
                       "Thu" if t["kind"] == "income" else "Chi", "#%s" % t["id"], amt, ("", c, c))
    return [nav_line(state, "tx", state.tx_month, True)] + list_lines(
        state, state.items(), head, row, height - 1, "Chưa có giao dịch. Nhấn [+ Chi] hoặc [+ Thu] để thêm.")


def plans_lines(state: State, width: int, height: int) -> List[Line]:
    compact, wide = width < 60, width >= 120
    date_w, amt_w = (5, 14) if compact else (10, 16)
    rec_w = 0 if compact else (28 if width >= 140 else 23)
    cat_w = (26 if width >= 140 else 18) if wide else 0
    name_w = max(4, width - 1 - date_w - amt_w - 4 - (rec_w + 2 if rec_w else 0) - (cat_w + 2 if cat_w else 0))
    today = state.today.isoformat()

    def columns(ln: Line, d: str, name: str, rec: str, cat: str, amount: str, styles: Tuple[str, str]) -> Line:
        ln.add(" ").cell(d, date_w, styles[0]).add("  ").cell(name, name_w).add("  ")
        if rec_w:
            ln.cell(rec, rec_w, MUTED).add("  ")
        if cat_w:
            ln.cell(cat, cat_w).add("  ")
        return ln.cell(amount, amt_w, styles[1], right=True)

    head = columns(Line(), "Ngày tới", "Tên", "Lặp", "Danh mục", "Số tiền", (MUTED, MUTED))
    head.text.stylize(MUTED)

    def row(p: Dict[str, Any]) -> Line:
        amt, c = _signed(p["amount"], p["kind"])
        status = p.get("status", "pending")
        rec = recurrence_label(p) if status == "pending" else {"done": "đã xong", "cancelled": "đã huỷ"}.get(status, status)
        late = WARN_C if status == "pending" and p["due_date"] < today else MUTED if status != "pending" else ""
        return columns(Line(), _vi_date(p["due_date"], short=compact), p["name"], rec,
                       cat_label(p.get("category", "")), amt, (late, c if status == "pending" else MUTED))
    filt = Line().add(" ")
    for val, label in ((False, "Đang chờ"), (True, "Tất cả")):
        filt.click(" %s " % label, ("plans", val), CHIP_ON if state.plans_all == val else CHIP).add(" ")
    return [filt] + list_lines(state, state.items(), head, row, height - 1,
                               "Chưa có dòng tiền. Nhấn [+ Dòng tiền] để thêm (vd: lương, thuê nhà, mua laptop).")


def budgets_lines(state: State, d: Dict[str, Any], width: int, height: int) -> List[Line]:
    nav = nav_line(state, "budget", state.budget_month or d.get("month"), False)
    full, wide = width >= 80, width >= 100
    cat_w = 28 if width >= 140 else 22 if width >= 100 else 18 if width >= 60 else 12
    money_w = 30 if full else 11
    rem_w = 16 if wide else 0
    bar_w = max(4, min(50 if width >= 140 else 40, width - 1 - cat_w - 2 - 6 - 2 - money_w - (rem_w + 2 if rem_w else 0)))
    head = (Line().add(" ").cell("Danh mục", cat_w, MUTED).add("  ").cell("Đã dùng", bar_w + 6, MUTED).add("  ")
            .cell("Đã chi / Hạn mức", money_w, MUTED, right=True))
    if wide:
        head.add("  ").cell("Còn lại", rem_w, MUTED, right=True)

    def row(b: Dict[str, Any]) -> Line:
        pct, rem = float(b.get("pct", 0)), b.get("remaining", 0)
        spent, limit = b.get("spent", 0), b.get("limit", 0)
        ln = Line().add(" ").cell(cat_label(b["category"]), cat_w).add("  ")
        ln.text.append_text(_bar(pct, bar_w, state.bar_pct(pct)))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        ln.cell(("%s / %s" % (money(spent), money(limit))) if full else
                "%s/%s" % (short_money(spent), short_money(limit)), money_w, right=True)
        if wide:
            ln.add("  ").cell(money(rem), rem_w, EXPENSE_C if rem < 0 else "", right=True)
        return ln
    return [nav] + list_lines(state, state.items(), head, row, height - 1,
                              "Chưa đặt ngân sách. Nhấn [+ Ngân sách] để đặt hạn mức chi mỗi tháng.")


def goal_tab_lines(state: State, width: int, height: int) -> List[Line]:
    total_saved = state.total_saved
    bal = state.balance if state.balance is not None else 0
    free_bal = bal - total_saved
    full = width >= 95
    wide = width >= 135
    vwide = width >= 160

    hdr = Line().add(" ")
    if width >= 95:
        hdr.add("Số dư: ", MUTED).add(money(bal), "bold").add("  │  Đã vào hũ: ", MUTED)
        hdr.add(money(total_saved), ACCENT).add("  │  Tiền tự do: ", MUTED)
        hdr.add(money(free_bal), "bold " + INCOME_C).add("   ")
    elif width >= 75:
        hdr.add("Số dư: ", MUTED).add(short_money(bal), "bold").add("  │  Hũ: ", MUTED)
        hdr.add(short_money(total_saved), ACCENT).add("  │  Tự do: ", MUTED)
        hdr.add(short_money(free_bal), "bold " + INCOME_C).add("   ")
    else:
        hdr.add("Dư: ", MUTED).add(short_money(bal), "bold").add(" · Hũ: ", MUTED)
        hdr.add(short_money(total_saved), ACCENT).add(" · Tự do: ", MUTED)
        hdr.add(short_money(free_bal), "bold " + INCOME_C).add(" ")
    if width >= 55:
        hdr.button("+ Tạo hũ", "goal_add", "+Hũ", short="+Hũ")

    name_w = 30 if vwide else 24 if wide else 18 if full else 12
    money_w = 30 if full else 11
    status_w = 28 if vwide else 18 if wide else 0
    btn_w = 45 if wide else 27
    bar_w = max(4, min(40 if vwide else 30, width - 1 - name_w - 2 - 6 - 2 - money_w - 2 - btn_w - (status_w + 2 if status_w else 0)))

    head = Line().add(" ").cell("Hũ tiết kiệm", name_w, MUTED).add("  ").cell("Tiến độ", bar_w + 6, MUTED).add("  ")
    head.cell("Đã gom / Mục tiêu" if full else "Đã gom/Đích", money_w, MUTED, right=True)
    if status_w:
        head.add("  ").cell("Kế hoạch / Hạn" if vwide else "Hạn/Tháng", status_w, MUTED)
    head.add("  ").cell("Thao tác", btn_w, MUTED)

    def row(g: Dict[str, Any]) -> Line:
        pct = float(g.get("pct", 0))
        saved = g.get("saved", 0)
        target = g.get("target", 0)
        rem = g.get("remaining", 0)
        per_m = g.get("per_month", 0)
        on_track = g.get("on_track", True)
        done = rem <= 0

        ln = Line().add(" ").cell(g.get("name", "Hũ"), name_w).add("  ")
        ln.text.append_text(_bar(pct, bar_w, state.bar_pct(pct)))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        amounts = ("%s / %s" % (money(saved), money(target))) if full else \
                  "%s/%s" % (short_money(saved), short_money(target))
        ln.cell(amounts, money_w, right=True)
        if status_w:
            if vwide:
                status_txt = "★ Đã đạt mục tiêu" if done else ("%s/tháng · %s" % (money(per_m), "✓ Kịp" if on_track else "▲ Chậm"))
            else:
                status_txt = "★ Đạt" if done else ("%s/th %s" % (short_money(per_m), "✓" if on_track else "▲"))
            status_style = ("bold " + INCOME_C) if done else (INCOME_C if on_track else WARN_C)
            ln.add("  ").cell(status_txt, status_w, status_style)
        ln.add("  ")
        ln.button("+ Góp", "goal_save:%d" % g["id"], "+G", short="+G")
        ln.button("- Rút", "goal_take:%d" % g["id"], "-R", short="-R")
        if wide:
            ln.button(G["edit"] or "✎", "goal_edit:%d" % g["id"], "e", short="✎")
            ln.button(G["del"] or "✕", "goal_rm:%d" % g["id"], "x", short="✕")
        return ln

    return [hdr] + list_lines(state, state.items(), head, row, height - 1,
                              "Chưa có hũ tiết kiệm. Nhấn [+ Tạo hũ] để bắt đầu tích luỹ.")


def chart_chip_lines(state: State, width: int) -> List[Line]:
    """Range / forecast / mode (/ bucket) chips, wrapping group by group."""
    c = state.chart
    groups = [("Khoảng", "days", CHART_RANGES, str(c["days"])), ("Dự báo", "ahead", CHART_AHEAD, str(c["ahead"])),
              ("Kiểu", "mode", CHART_MODES, c["mode"])]
    if c["mode"] == "candle":
        groups.append(("Nến", "bucket", CHART_BUCKETS, c["bucket"]))
    lines, ln = [], Line().add(" ")  # type: List[Line], Line
    for title, key, chips, cur in groups:
        group_w = cell_len(title) + 2 + sum(cell_len(lbl) + 3 for _, lbl in chips)
        if ln.x > 1 and ln.x + group_w > width:
            lines.append(ln)
            ln = Line().add(" ")
        ln.add(title + ": ", MUTED)
        for val, label in chips:
            if ln.x + cell_len(label) + 3 > width:
                lines.append(ln)
                ln = Line().add("   ")
            ln.click(" %s " % label, ("chartset", key, val), CHIP_ON if val == cur else CHIP).add(" ")
        ln.add("  ")
    return lines + [ln]


def get_chart_milestones(state: State) -> List[Tuple[str, str, str, int, Optional[str]]]:
    """Return list of (wide_label, full_label, short_label, data_index, diff_str) for chart milestones."""
    d = state.data.get(6) or {}
    series = d.get("series") or []
    forecast = d.get("forecast") or []
    all_pts = series + forecast
    if not all_pts:
        return []

    n_hist = len(series)
    today_idx = max(0, n_hist - 1)
    today_bal = int(all_pts[today_idx]["balance"])

    milestones = []
    # 1. Hôm nay
    milestones.append(("Hôm nay: %s" % money(today_bal), "Hôm nay: %s" % short_money(today_bal), "Hôm nay", today_idx, None))

    date_to_idx = {str(pt["date"]): i for i, pt in enumerate(all_pts)}
    today = state.today

    # 2. Cuối tháng này
    last_day_this_month = calendar.monthrange(today.year, today.month)[1]
    eom_this = date(today.year, today.month, last_day_this_month).isoformat()
    if eom_this in date_to_idx:
        idx = date_to_idx[eom_this]
        bal = int(all_pts[idx]["balance"])
        diff = bal - today_bal
        diff_str = "%s%s" % ("▲+" if diff >= 0 else "▼-", short_money(abs(diff)))
        diff_full = "%s%s" % ("▲+" if diff >= 0 else "▼-", money(abs(diff)))
        milestones.append(("Cuối T%02d: %s (%s)" % (today.month, money(bal), diff_full),
                           "Cuối T%02d: %s (%s)" % (today.month, short_money(bal), diff_str),
                           "Cuối T%02d" % today.month, idx, diff_str))

    # 3. Cuối tháng sau
    next_y = today.year + (1 if today.month == 12 else 0)
    next_m = 1 if today.month == 12 else today.month + 1
    last_day_next_month = calendar.monthrange(next_y, next_m)[1]
    eom_next = date(next_y, next_m, last_day_next_month).isoformat()
    if eom_next in date_to_idx:
        idx = date_to_idx[eom_next]
        bal = int(all_pts[idx]["balance"])
        diff = bal - today_bal
        diff_str = "%s%s" % ("▲+" if diff >= 0 else "▼-", short_money(abs(diff)))
        diff_full = "%s%s" % ("▲+" if diff >= 0 else "▼-", money(abs(diff)))
        milestones.append(("Cuối T%02d: %s (%s)" % (next_m, money(bal), diff_full),
                           "Cuối T%02d: %s (%s)" % (next_m, short_money(bal), diff_str),
                           "Cuối T%02d" % next_m, idx, diff_str))

    # 4. Thấp nhất trong dự báo
    if forecast:
        fore_min_idx = min(range(n_hist, len(all_pts)), key=lambda i: int(all_pts[i]["balance"]))
        min_pt = all_pts[fore_min_idx]
        min_bal = int(min_pt["balance"])
        d_parts = str(min_pt["date"]).split("-")
        ddmm = "%s/%s" % (d_parts[2], d_parts[1]) if len(d_parts) == 3 else str(min_pt["date"])
        milestones.append(("Thấp nhất: %s (%s)" % (money(min_bal), ddmm),
                           "Thấp nhất: %s (%s)" % (short_money(min_bal), ddmm),
                           "Thấp: %s" % short_money(min_bal), fore_min_idx, None))

    return milestones


def chart_milestone_lines(state: State, width: int, max_lines: int = 1) -> List[Line]:
    milestones = get_chart_milestones(state)
    if not milestones:
        return []
    cur = state.chart.get("cursor")
    lines = []
    ln = Line().add(" ").add("Mốc: ", MUTED)
    for wide_lbl, full_lbl, short_lbl, idx, diff in milestones:
        lbl = wide_lbl if width >= 140 else full_lbl if width >= 80 else short_lbl
        w = cell_len(lbl) + 3
        if ln.x > 1 and ln.x + w > width:
            if len(lines) + 1 >= max_lines:
                break
            lines.append(ln)
            ln = Line().add("   ")
        is_active = (cur == idx)
        style = CHIP_ON if is_active else CHIP
        ln.click(" %s " % lbl, ("chart_jump", idx), style).add(" ")
    return lines + [ln]


def _chart_count(state: State) -> int:
    d = state.data.get(6) or {}
    if state.chart["mode"] == "candle" and chart_mod is not None and hasattr(chart_mod, "ohlc"):
        try:
            return len(chart_mod.ohlc(d.get("series") or [], state.chart["bucket"]))
        except Exception:
            return 0
    return len(d.get("series") or []) + len(d.get("forecast") or [])


def chart_lines(state: State, width: int, height: int) -> List[Line]:
    """Biểu đồ tab: chips, milestones, then a stock-style chart (chart.py) filling every remaining row."""
    chips = chart_chip_lines(state, width)
    room = max(0, height - len(chips) - 3)
    max_ms = 1 if room < 8 or width < 60 else 2
    ms = chart_milestone_lines(state, width, max_lines=max_ms) if room >= 1 else []
    out = chips + ms
    d = state.data.get(6) or {}
    series, forecast = d.get("series") or [], d.get("forecast") or []
    plot_h = max(3, height - len(out))
    c, cur = state.chart, state.chart["cursor"]
    chart = None
    if chart_mod is not None and series:
        try:
            if c["mode"] == "candle":
                chart = chart_mod.candle_chart(series, width, plot_h, bucket=c["bucket"], cursor=cur,
                                               glyphs=G["popup"])
            else:
                chart = chart_mod.line_chart(series, forecast, width, plot_h, cursor=cur, glyphs=G["popup"],
                                              goals=state.goals)
        except Exception as e:  # a broken chart must not break the app
            state.set_status("Lỗi biểu đồ: %s" % e, False)
    state.chart_obj = chart
    if chart is None:
        values = [r["balance"] for r in series + forecast]
        if not values:
            return out + [Line(), Line().add("   Chưa có dữ liệu để vẽ biểu đồ.", MUTED)]
        step = max(1, len(values) // max(1, width - 6))
        values = values[::step]
        lo, hi = min(values), max(values)
        ln = Line().add("   ")
        for v in values[:width - 6]:
            level = 0 if hi == lo else int((v - lo) / (hi - lo) * (len(G["spark"]) - 1))
            ln.add(G["spark"][level], EXPENSE_C if v < 0 else INCOME_C)
        return out + [Line(), ln, Line().add("   thấp %s · cao %s" % (short_money(lo), short_money(hi)), MUTED)]
    for t in chart.lines[:plot_h]:
        ln = Line(("plot",))
        ln.text = t.copy()
        ln.text.no_wrap, ln.text.overflow = True, "crop"
        out.append(ln)
    return out


def settings_lines(state: State, width: int) -> List[Line]:
    """Cài đặt: sound and icon style as clickable chips (persisted through the api)."""
    out = [Line(), _title(("%s Cài đặt" % G["settings"]).strip()), Line()]
    ln = Line().add("   ").cell("Âm thanh", 14)
    for val, label in (("on", "Bật"), ("off", "Tắt")):
        ln.click(" %s " % label, ("set", "sound", val), CHIP_ON if (val == "on") == state.sound else CHIP).add(" ")
    out.append(ln.add("  " + (G["sound_on"] if state.sound else G["sound_off"]), MUTED))
    ln = Line().add("   ").cell("Biểu tượng", 14)
    for val, label in (("symbol", "Ký hiệu"), ("emoji", "Emoji"), ("off", "Không")):
        ln.click(" %s " % label, ("set", "icons", val), CHIP_ON if ICON_MODE == val else CHIP).add(" ")
    out.append(ln)
    sample = " ".join(i for i in G["tabs"] if i) + "  " + cat_label("ăn uống")
    out += [Line().add("   ").cell("Xem trước", 14).add(sample, MUTED), Line(),
            Line().add("   Phím tắt: m bật/tắt âm · I đổi biểu tượng · Esc đóng", MUTED)]
    return out


def chip_lines(chips: List[Tuple[str, str]], key: str, width: int, on: Callable[[str], bool], indent: int,
               max_lines: int = 2) -> List[Line]:
    """Clickable (value, label) chips under a form field, wrapped onto at most `max_lines` rows."""
    lines = []  # type: List[Line]
    ln = None  # type: Optional[Line]
    for value, label in chips:
        w = cell_len(label) + 3
        if ln is None or ln.x + w > width:
            if len(lines) == max_lines:
                break
            ln = Line().add(" " * indent)
            lines.append(ln)
        ln.click(" %s " % label, ("chip", key, value), CHIP_ON if on(value) else CHIP).add(" ")
    return lines


def calendar_lines(form: Form, key: str, indent: int) -> List[Line]:
    """Mini month calendar for a date field: ‹ › change month, click a day to pick it."""
    dv = form.date_value(key)
    y, m = form.months.get(key) or ((dv or form.today).year, (dv or form.today).month)
    pad = " " * indent
    out = [Line().add(pad).click(" %s " % G["prev"], ("cal", key, -1), BTN).add("  Tháng %02d/%d  " % (m, y), "bold")
           .click(" %s " % G["next"], ("cal", key, 1), BTN),
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
            return "%s %s, %s" % (G["arrow"], WEEKDAYS[dv.weekday()], _dmy(dv)), ACCENT
        return ("%s chưa hiểu ngày này" % G["warn"], WARN_C) if value else None
    return None


def form_lines(form: Form, width: int) -> Tuple[List[Line], Tuple[int, int]]:
    """Form rows plus the (first, last) row of the focused field's block, for scrolling."""
    compact = width < 60
    indent = 14 if compact else 23
    out = [Line(), _title(form.title)]
    if form.error:
        out.append(Line().add("   %s %s" % (G["err"], form.error), EXPENSE_C))
    out.append(Line())
    focus_rows = (0, 0)
    for f in form.visible():
        start, focused = len(out), f.key == form.focus
        ln = Line(("focus", f.key)).add(" %s " % G["marker"] if focused else "   ", ACCENT)
        ln.cell(f.short if compact and f.short else f.label, indent - 3, "bold " + ACCENT if focused else "")
        value = form.values[f.key]
        below = []  # type: List[Line]
        if f.choices:
            for val, label in f.choices:
                ln.click(" %s " % label, ("chip", f.key, val), CHIP_ON if val == value else CHIP).add(" ")
            if ln.x > width:  # no room inline: show the choice, chips wrap underneath
                ln = Line(("focus", f.key)).add(" %s " % G["marker"] if focused else "   ", ACCENT)
                ln.cell(f.short or f.label, indent - 3, "bold " + ACCENT if focused else "")
                ln.add(dict(f.choices).get(value, ""), "bold")
                below = chip_lines(f.choices, f.key, width, lambda v, cur=value: v == cur, indent, max_lines=3)
        else:
            ln.add(value, "bold" if focused else "")
            if focused:
                ln.add(G["cursor"], ACCENT)
            if not value:
                ln.add(form.placeholder(f), MUTED)
            preview = _preview(form, f)
            if preview:
                ln.add("  " + preview[0], preview[1])
            below = chip_lines(form.chips(f), f.key, width, lambda v, k=f.key: form.chip_on(k, v), indent)
        out.append(ln)
        out.extend(below)
        if focused and f.key in DATE_FIELDS:
            out.extend(calendar_lines(form, f.key, indent))
        if f.key in form.errors:
            out.append(Line().add(" " * indent + "%s %s" % (G["warn"], form.errors[f.key]), EXPENSE_C))
        if focused:
            focus_rows = (start, len(out) - 1)
    out += [Line(), Line().add("   Tab/↑↓ chuyển ô · nhấp để chọn · Số tiền nhận phép tính + - x :", MUTED)]
    return out, focus_rows


def accounts_lines(state: State, width: int, height: int) -> List[Line]:
    d = state.data.get(1) or {}
    accs = d.get("accounts") or []
    tot = d.get("total_balance") or 0
    full = width >= 90
    wide = width >= 120

    hdr = Line().add(" ")
    if width >= 80:
        hdr.add("Tổng tài sản: ", MUTED).add(money(tot), "bold " + INCOME_C).add("  │  Số tài khoản: ", MUTED)
        hdr.add("%d ví/tài khoản" % len(accs), ACCENT).add("   ")
    else:
        hdr.add("Tổng: ", MUTED).add(short_money(tot), "bold " + INCOME_C).add(" · %d ví" % len(accs), ACCENT).add(" ")
    if width >= 95:
        hdr.button("+ Thêm", "a", "a", short="+")
        hdr.button("⇄ Chuyển", "t", "t", short="⇄")

    name_w = 26 if wide else 20 if full else 16
    bal_w = 18 if full else 14
    pct_w = 6
    bar_w = max(6, min(36 if wide else 24, width - 1 - name_w - 2 - bal_w - 2 - pct_w - 12))

    head = Line().add(" ").cell("Tài khoản", name_w, MUTED).add("  ")
    head.cell("Số dư", bal_w, MUTED, right=True).add("  ")
    head.cell("Tỷ lệ", bar_w + pct_w + 2, MUTED).add("  ")
    head.cell("Mặc định", 10, MUTED)

    def row(a: Dict[str, Any]) -> Line:
        pct = float(a.get("pct", 0.0))
        bal = a.get("balance", 0)
        bal_c = INCOME_C if bal > 0 else (WARN_C if bal == 0 else EXPENSE_C)
        is_def = bool(a.get("is_default", False))

        ln = Line().add(" ").cell(a.get("name", "Ví"), name_w, "bold").add("  ")
        ln.cell(money(bal) if full else short_money(bal), bal_w, "bold " + bal_c, right=True).add("  ")
        ln.text.append_text(_bar(pct, bar_w, state.bar_pct(pct)))
        ln.cell(" %2.0f%%" % pct, pct_w, right=True).add("  ")
        if is_def:
            ln.cell("[Mặc định]", 10, "bold " + ACCENT)
        else:
            ln.cell("", 10)
        return ln

    transfers = d.get("transfers") or []
    if height >= 16 and transfers:
        acc_height = max(5, min(len(accs) + 3, height - 8))
        acc_box = [hdr] + list_lines(state, accs, head, row, acc_height,
                                     "Chưa có tài khoản nào. Nhấn [+ Thêm] để tạo ví đầu tiên.")
        tr_lines = [_rule(width), Line().add("   Lịch sử chuyển tiền gần đây", MUTED)]
        tr_head = Line().add(" ").cell("Ngày", 12, MUTED).add("  ").cell("Từ → Đến", 30, MUTED).add("  ").cell("Số tiền", 16, MUTED, right=True).add("  ").cell("Ghi chú", 25, MUTED)
        tr_lines.append(tr_head)
        for tr in transfers[:max(2, height - len(acc_box) - 3)]:
            route = "%s → %s" % (tr.get("from_account", ""), tr.get("to_account", ""))
            tr_ln = Line().add(" ").cell(tr.get("date", ""), 12).add("  ").cell(route, 30, ACCENT).add("  ")
            tr_ln.cell(money(tr.get("amount", 0)), 16, "bold " + INCOME_C, right=True).add("  ")
            tr_ln.cell(tr.get("note", ""), 25, MUTED)
            tr_lines.append(tr_ln)
        return acc_box + tr_lines

    return [hdr] + list_lines(state, accs, head, row, height - 1,
                              "Chưa có tài khoản nào. Nhấn [+ Thêm] để tạo ví đầu tiên.")


def body_lines(state: State, width: int, height: int) -> List[Line]:
    if state.form:
        lines, (first, last) = form_lines(state.form, width)
        if len(lines) > height:  # scroll so the focused field (with its calendar) stays visible
            start = min(first, max(0, last - height + 1))
            lines = lines[start:start + height]
        return lines
    if state.settings:
        return settings_lines(state, width)
    d = state.data.get(state.tab, {})
    if state.tab == 0:
        return overview_lines(state, d, width, height) if d else [Line(), Line().add("   Không có dữ liệu.", MUTED)]
    if state.tab == 1:
        return accounts_lines(state, width, height)
    if state.tab == 2:
        return transactions_lines(state, width, height)
    if state.tab == 3:
        return plans_lines(state, width, height)
    if state.tab == 4:
        return budgets_lines(state, d, width, height)
    if state.tab == 5:
        return goal_tab_lines(state, width, height)
    if state.tab == 6:
        return chart_lines(state, width, height)
    return share_tab_lines(state, width, height)


def share_tab_lines(state: State, width: int, height: int) -> List[Line]:
    out: List[Line] = []
    out.append(Line())

    # 1. Title / Switch
    l_hdr = Line().add("   ")
    if state.share_active:
        l_hdr.click(" ● ĐANG CHIA SẺ ", ("toggle_share",), "bold #1e1b2e on #86efac")
        l_hdr.add("  nhấp hoặc bấm ", MUTED)
        l_hdr.add("s", "bold " + PINK)
        l_hdr.add(" để tắt", MUTED)
        if state.share_server:
            cnt = state.share_server.client_count()
            l_hdr.add(" · ", RULE_C)
            l_hdr.add(f"{cnt} thiết bị đang xem", "bold " + ACCENT)
    else:
        l_hdr.click(" ○ ĐÃ TẮT CHIA SẺ ", ("toggle_share",), "bold #ede9fe on #352d5c")
        l_hdr.add("  nhấp hoặc bấm ", MUTED)
        l_hdr.add("s", "bold " + PINK)
        l_hdr.add(" để bật chia sẻ trực tiếp", MUTED)
    out.append(l_hdr)
    out.append(Line())

    if state.share_active:
        # 2. Connection Details
        pin = state.share_pin
        from manage_eco.tunnel import get_local_ip, generate_terminal_qr
        local_ip = get_local_ip()
        port = state.share_server.port if state.share_server else 8080
        local_url = f"http://{local_ip}:{port}/?pin={pin}"
        tunnel_url = f"{state.share_tunnel.url}?pin={pin}" if (state.share_tunnel and state.share_tunnel.url) else None
        active_url = tunnel_url or local_url

        l_link = Line().add("   Đường link: ", MUTED)
        l_link.add(active_url, "bold " + INCOME_C)
        l_link.add("   ")
        l_link.click("[Sao chép c]", ("copy_share_url",), "bold #ede9fe on #352d5c")
        out.append(l_link)

        l_sub = Line().add("   Mã PIN: ", MUTED).add(pin, "bold " + PINK)
        if tunnel_url:
            provider = getattr(state.share_tunnel, "provider_name", "HTTPS")
            l_sub.add(f"   (Đã bật HTTPS {provider} cho 4G từ xa)", MUTED)
        else:
            l_sub.add(f"   (Wi-Fi nội bộ: {local_url} · Cài 'brew install cloudflared' hoặc bật Tailscale để mở 4G từ xa)", MUTED)
        out.append(l_sub)
        out.append(Line())
    else:
        out.append(Line().add("   Chia sẻ thông tin tài chính (Tổng quan, Hũ, Ngân sách...) cho bạn gái xem", MUTED))
        out.append(Line().add("   trên điện thoại qua 4G/Wi-Fi ở chế độ chỉ đọc (View-only an toàn tuyệt đối).", MUTED))
        out.append(Line())

    # 3. Tab Whitelist Permissions
    out.append(Line().add("   CÁC TAB ĐƯỢC PHÉP XEM TRÊN WEB (bấm số 1-7 hoặc nhấp chuột):", "bold " + ACCENT))
    share_items = [
        ("overview", "1.Tổng quan"),
        ("accounts", "2.Tài khoản"),
        ("transactions", "3.Giao dịch"),
        ("cashflow", "4.Dòng tiền"),
        ("budgets", "5.Ngân sách"),
        ("goals", "6.Hũ tiết kiệm"),
        ("chart", "7.Biểu đồ"),
    ]
    l_c1 = Line().add("   ")
    for key, label in share_items[:4]:
        is_on = key in state.share_allowed_tabs
        mark = "✓" if is_on else " "
        style = CHIP_ON if is_on else CHIP
        l_c1.click(f"[{mark} {label}]", ("toggle_share_tab", key), style).add(" ")
    out.append(l_c1)

    l_c2 = Line().add("   ")
    for key, label in share_items[4:]:
        is_on = key in state.share_allowed_tabs
        mark = "✓" if is_on else " "
        style = CHIP_ON if is_on else CHIP
        l_c2.click(f"[{mark} {label}]", ("toggle_share_tab", key), style).add(" ")
    out.append(l_c2)
    out.append(Line())

    # 4. Action / Edit Permissions
    out.append(Line().add("   CÁC QUYỀN ĐƯỢC PHÉP CHỈNH SỬA TRÊN WEB (nhấp chuột hoặc phím a, d, g, x):", "bold " + ACCENT))
    edit_items = [
        ("expense", "Ghi chi tiêu a"),
        ("cashflow", "Xong dòng d"),
        ("goals", "Góp hũ g"),
        ("edit_tx", "Xoá gd x"),
    ]
    l_edits = Line().add("   ")
    for key, label in edit_items:
        is_on = key in state.share_allowed_edits
        mark = "✓" if is_on else " "
        style = CHIP_ON if is_on else CHIP
        l_edits.click(f"[{mark} {label}]", ("toggle_share_edit", key), style).add(" ")
    out.append(l_edits)
    out.append(Line())

    # 5. Sync Mode
    out.append(Line().add("   CHẾ ĐỘ ĐỒNG BỘ HIỂN THỊ:", "bold " + ACCENT))
    is_free = state.share_sync_mode == "free"
    l_sync = Line().add("   ")
    l_sync.click("[Tự do duyệt web]", ("set_share_sync_mode", "free"), CHIP_ON if is_free else CHIP)
    l_sync.add("  ")
    l_sync.click("[Đi cùng tôi (Follow Me)]", ("set_share_sync_mode", "follow"), CHIP_ON if not is_free else CHIP)
    out.append(l_sync)
    out.append(Line())

    # 5. QR Code (shown when active)
    if state.share_active:
        out.append(Line().add("   QUÉT MÃ QR ĐỂ MỞ TRÊN ĐIỆN THOẠI:", "bold " + ACCENT))
        qr_lines = generate_terminal_qr(active_url)
        for ql in qr_lines:
            out.append(Line().add("   " + ql, ACCENT))
        out.append(Line())

    return out


def copy_share_url(state: State) -> None:
    url = state.get_share_url()
    if not url:
        state.set_status("Chưa bật chia sẻ", False)
        return
    copied = False
    try:
        import subprocess
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(url.encode("utf-8"))
        copied = True
    except Exception:
        pass
    if copied:
        state.set_status(f"Đã chép link: {url}")
    else:
        state.set_status(f"Link: {url}")


# --- overlays (toast + sparkle) ---
def _tail(text: Text, start: int) -> Text:
    """The part of a line from cell `start` on; a wide char cut in half becomes a space."""
    pos = 0
    for i, ch in enumerate(text.plain):
        if pos >= start:
            return Text(" " * (pos - start)) + text[i:]
        pos += cell_len(ch)
    return Text(" " * max(0, pos - start))


def put(line: Text, x: int, piece: Text) -> Text:
    """Line with `piece` drawn over it starting at cell x (same cell width as before)."""
    width = line.cell_len
    left = line.copy()
    left.truncate(x, overflow="crop", pad=True)
    out = left + piece + _tail(line, x + piece.cell_len)
    out.truncate(width, overflow="crop", pad=True)
    out.no_wrap, out.overflow = True, "crop"
    return out


_SAFE_SPARKS = "*+·"
_RISKY_SPARKS = set("✦✧⋆˚♡✿")


def _sparkles(state: State, lines: List[Text], width: int, height: int, avoid: Tuple[int, int, int, int]) -> None:
    """Confetti bursting out of the box `avoid` (top, left, bottom, right), never drawn inside it."""
    if not state.sparkle:
        return
    seed, t0 = state.sparkle
    bh, bw = avoid[2] - avoid[0], avoid[3] - avoid[1]
    try:
        sp = anim.Sparkle(bw + 20, bh + 8, seed=seed, duration=SPARKLE_S, glyphs=G["popup"])
    except TypeError:  # older anim.py: no glyph modes
        sp = anim.Sparkle(bw + 20, bh + 8, seed=seed, duration=SPARKLE_S)
    area_top, area_left = avoid[0] - 4, avoid[1] - 10
    for r, c, ch, style in sp.cells(state.now - t0):
        row, col = area_top + r, area_left + c
        inside = avoid[0] <= row < avoid[2] and avoid[1] <= col < avoid[3]
        if 2 <= row < height - 2 and 0 <= col < width and not inside:
            if ICON_MODE != "emoji" and ch in _RISKY_SPARKS:  # not in every monospace font
                ch = _SAFE_SPARKS[(r + c) % len(_SAFE_SPARKS)]
            lines[row] = put(lines[row], col, Text(ch, style=style))


def _draw_popup(state: State, lines: List[Text], width: int, height: int) -> bool:
    """Pixel popup centered over the body; False when there is none or it does not fit (toast fallback)."""
    t0 = state.popup[1]
    try:
        fr = _fitted_popup(state, width, max(0, height - 4)).frame(state.now - t0, width, max(0, height - 4))
    except Exception:
        fr = None
    if not fr:
        return False
    top, left, box = fr
    top += 2  # frame() is relative to the body area
    box = box[:max(0, height - 2 - top)]
    bw = max((b.cell_len for b in box), default=0)
    _sparkles(state, lines, width, height, (top, left, top + len(box), left + bw))
    for i, b in enumerate(box):
        if 0 <= top + i < len(lines):
            lines[top + i] = put(lines[top + i], max(0, left), b)
    return True


def apply_overlays(state: State, lines: List[Text], hits: List[Hit], width: int, height: int) -> List[Hit]:
    """Draw the pixel popup, or the toast (bottom-right, above the action bar) with its sparkles.
    The toast swallows clicks on itself; a popup is dismissed by any click (see dispatch)."""
    if state.popup:
        if not popup_active(state):
            return hits  # popup finished: its fallback toast is over too
        if _draw_popup(state, lines, width, height):
            return hits
    if not state.toast:
        return hits
    t = state.now - state.toast[1]
    box_w = max(4, min(52, width - 2))
    toast_ = state.toast[0]
    # inner width minus the kaomoji and the pop-in padding; shorten so the amount is never cut off
    kao = toast_._kaomoji(anim.ascii_mode()) if hasattr(toast_, "_kaomoji") else ""
    room = box_w - 4 - (cell_len(kao) + 2 if kao else 0) - 2
    if cell_len(toast_.message) > room:
        extra = {"glyphs": toast_.glyphs} if hasattr(toast_, "glyphs") else {}
        toast_ = anim.Toast(fit_money(toast_.message, room), toast_.kind, toast_.icon, toast_.duration, **extra)
    box = toast_.lines(t, box_w)
    top = height - 2 - len(box)
    if not box or top < 2:
        return hits
    tw = max(b.cell_len for b in box)
    x0 = max(0, width - tw - 1)
    blocked = []  # type: List[Hit]
    _sparkles(state, lines, width, height, (top, x0, top + len(box), x0 + tw))
    for i, b in enumerate(box):
        left = 1 if x0 > 0 else 0  # one blank cell around the box so no stray glyphs touch its border
        right = 1 if x0 + b.cell_len < width else 0
        lines[top + i] = put(lines[top + i], x0 - left, Text(" " * left) + b + Text(" " * right))
        blocked.append((top + i, x0, x0 + b.cell_len, ("noop",)))
    return blocked + hits


def _cell_index(text: Text) -> List[int]:
    """Character index for every cell of a line (wide characters cover two cells)."""
    out = []  # type: List[int]
    for i, ch in enumerate(text.plain):
        out += [i] * cell_len(ch)
    return out


def _stylize_cells(line: Text, x0: int, x1: int, style: str) -> None:
    idx = _cell_index(line)
    x0, x1 = max(0, x0), min(len(idx), x1)
    if x0 < x1:
        line.stylize(style, idx[x0], idx[x1 - 1] + 1)


def _anim_attr(name: str) -> Any:
    return getattr(anim, name, None) if anim is not None else None  # VFX land in anim.py over time


def apply_vfx(state: State, lines: List[Text], hits: List[Hit], width: int) -> None:
    """Restyle in place (never moves anything): the tab underline (sliding)."""
    t = state.now
    tabs = {a[1]: (x0, x1) for r, x0, x1, a in hits if r == 1 and a[0] == "tab"}
    if state.tab in tabs and len(lines) > 1:
        x0, x1 = tabs[state.tab]
        slide = _anim_attr("slide")
        if state.slide and slide and t - state.slide[2] < SLIDE_S and state.slide[0] in tabs:
            fx0, fx1 = tabs[state.slide[0]]
            x0, x1 = slide(fx0, x0, t - state.slide[2], SLIDE_S), slide(fx1, x1, t - state.slide[2], SLIDE_S)
        _stylize_cells(lines[1], x0, x1, "underline")


def build_frame(state: State, width: int, height: int) -> Frame:
    """Exactly `height` lines of at most `width` cells, plus the hit map."""
    body_h = max(0, height - 4)
    body = body_lines(state, width, body_h)[:body_h]
    body += [Line() for _ in range(body_h - len(body))]
    rows = ([header_line(state, width), tabs_line(state.tab, width)] + body
            + [action_line(state, width), status_line(state, width)])[:height]
    lines, spans, row_hits = [], [], []  # type: List[Text], List[Hit], List[Hit]
    for r, ln in enumerate(rows):
        ln.text.truncate(width, overflow="crop", pad=True)
        lines.append(ln.text)
        spans += [(r, x0, min(x1, width), a) for x0, x1, a in ln.spans if x0 < width]
        if ln.action:
            row_hits.append((r, 0, width, ln.action))
    state.size = (width, height)
    apply_vfx(state, lines, spans + row_hits, width)
    hits = apply_overlays(state, lines, spans + row_hits, width, height)
    return Frame(lines, hits)


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
    if "amount" in v:
        try:
            params["amount"] = parse_money(v["amount"])
        except ValueError:
            errors["amount"] = "Số tiền không hợp lệ (vd: 50k, 1.5tr, 50k+20k, 3x150k)"
    if "category" in v:
        if v["category"]:
            params["category"] = v["category"]
        elif form.name in ("budget", "plan"):
            errors["category"] = "Chọn hoặc gõ một danh mục"
        else:
            params["category"] = ""
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
        if form.edit_id is not None:
            params.update(id=form.edit_id, every=v["every"], kind=v["kind"])
            return "plan edit", params, errors
        params.update(every=v["every"], income=v["kind"] == "income")
        return "plan add", params, errors
    if form.name in ("budget", "budget_edit"):
        category = params.get("category") if form.name == "budget" else form.edit_id
        return "budget set", {"category": category, "amount": params.get("amount")}, errors
    if form.name == "goal":
        return "goal", {"target": params.get("amount"), "by": params.get("by")}, errors
    if form.name == "goal_add":
        return "goal add", {"name": v.get("name") or "Mục tiêu", "target": params.get("amount"), "by": params.get("by")}, errors
    if form.name == "goal_edit":
        return "goal edit", {"id": form.edit_id, "name": v.get("name") or "Mục tiêu", "target": params.get("amount"), "by": params.get("by")}, errors
    if form.name == "goal_save":
        return "goal save", {"id": form.edit_id, "amount": params.get("amount")}, errors
    if form.name == "goal_take":
        return "goal take", {"id": form.edit_id, "amount": params.get("amount")}, errors
    if "account" in v and v["account"]:
        params["account"] = v["account"]
    if form.name == "account_add":
        if not v.get("name"):
            errors["name"] = "Nhập tên tài khoản"
        init_bal = 0
        raw_bal = (v.get("balance") or v.get("initial_balance") or "").strip()
        if raw_bal:
            try:
                init_bal = parse_money(raw_bal, allow_zero=True)
            except ValueError:
                errors["initial_balance"] = "Số dư không hợp lệ (vd: 0, 1tr, 500k)"
                errors["balance"] = "Số dư không hợp lệ (vd: 0, 1tr, 500k)"
        return "account add", {"name": v.get("name", ""), "initial_balance": init_bal, "default": v.get("default") == "1"}, errors
    if form.name == "account_edit":
        if not v.get("name"):
            errors["name"] = "Nhập tên tài khoản"
        params = {"id": form.edit_id, "name": v.get("name", ""), "default": v.get("default") == "1"}
        raw_bal = (v.get("balance") or v.get("initial_balance") or "").strip()
        if raw_bal:
            try:
                bal = parse_money(raw_bal, allow_zero=True)
                if "balance" in v:
                    params["balance"] = bal
                else:
                    params["initial_balance"] = bal
            except ValueError:
                errors["balance"] = "Số dư không hợp lệ (vd: 0, 1tr, 500k)"
                errors["initial_balance"] = "Số dư không hợp lệ (vd: 0, 1tr, 500k)"
        return "account edit", params, errors
    if form.name == "account_transfer":
        if not v.get("from"):
            errors["from"] = "Nhập tài khoản nguồn"
        if not v.get("to"):
            errors["to"] = "Nhập tài khoản đích"
        d_val = params.get("date") or today.isoformat()
        return "account transfer", {"from": v.get("from"), "to": v.get("to"), "amount": params.get("amount"), "date": d_val, "note": v.get("note", "")}, errors
    if form.name == "plan_done":
        if "account" in v and not v["account"]:
            if form.cats.get("accounts"):
                errors["account"] = "Chọn tài khoản thanh toán"
        plan = getattr(form, "meta", None)
        if plan and plan.get("kind") == "expense":
            acc_name = v.get("account")
            acc_list = form.cats.get("accounts", [])
            matched_acc = next(
                (a for a in acc_list if a.get("name") == acc_name or str(a.get("id")) == acc_name),
                None
            )
            if matched_acc and matched_acc.get("balance") is not None:
                if matched_acc["balance"] < plan.get("amount", 0):
                    errors["account"] = "Số dư không đủ (%s < %s)" % (
                        short_money(matched_acc["balance"]), short_money(plan.get("amount", 0))
                    )
        d_val = params.get("date") or today.isoformat()
        return "plan done", {"id": form.edit_id, "account": v.get("account"), "date": d_val}, errors
    params["note"] = v["note"]
    if form.name == "tx":
        params.update(id=form.edit_id, kind=v["kind"])
        return "edit", params, errors
    return form.name, params, errors


# --- input handling ---
def refresh(state: State, api: ApiCall) -> None:
    """Drop cached data after a change and reload the header balance and current tab."""
    state.data.clear()
    tab, state.tab = state.tab, 0
    load(state, api)
    state.tab = tab
    load(state, api)
    if state.goal:  # the goal depends on the balance
        try:
            state.goal.update(api("goal", {"target": state.goal["target"], "by": state.goal["by"]}))
        except Exception:
            pass


def init(state: State, api: ApiCall) -> None:
    """First load: overview data, stored sound and icon settings ($ECO_ICONS wins), bars filling in."""
    load(state, api)
    try:
        state.sound = bool(api("sound", {}).get("sound", True))
    except Exception:
        pass
    mode = os.environ.get("ECO_ICONS", "")
    if mode not in ICON_MODES:
        try:
            mode = api("icons", {}).get("icons", "symbol")
        except Exception:
            mode = "symbol"
    set_icons(mode)
    state.bars_t0 = state.now


def open_form(state: State, name: str, api: ApiCall) -> Form:
    try:
        cats = api("categories", {})
    except Exception:
        cats = {}
    try:
        acc_data = api("account list", {})
        cats["accounts"] = acc_data.get("accounts", [])
    except Exception:
        pass
    form = Form(name, cats, state.today)
    if name in ("expense", "income", "plan_done") and cats.get("accounts"):
        def_acc = next((a["name"] for a in cats["accounts"] if a.get("is_default")), cats["accounts"][0]["name"])
        form.values["account"] = def_acc
    state.form = form
    return state.form


def open_plan_done(state: State, plan: Dict[str, Any], api: ApiCall) -> Form:
    form = open_form(state, "plan_done", api)
    form.edit_id = plan["id"]
    sign = "+" if plan.get("kind") == "income" else "-"
    form.title = "Hoàn thành: %s (%s%s)" % (
        plan.get("name", "Dòng tiền"), sign, money(plan.get("amount", 0))
    )
    form.values["date"] = state.today.isoformat()
    form.meta = plan
    return form


def open_account_add(state: State, api: ApiCall) -> Form:
    return open_form(state, "account_add", api)


def open_account_transfer(state: State, api: ApiCall) -> Form:
    form = open_form(state, "account_transfer", api)
    item = selected_item(state) if state.tab == 1 else None
    if item and "name" in item:
        form.values["from"] = item["name"]
    return form


def _amount_text(amount: int) -> str:
    return money(amount)[:-2]  # "50.000": parse_money reads dotted thousands


def selected_item(state: State) -> Optional[Dict[str, Any]]:
    items = state.items()
    if state.selected is None or state.selected >= len(items):
        return None
    return items[state.selected]


def open_edit(state: State, api: ApiCall) -> None:
    """Form pre-filled with the selected transaction / dòng tiền / ngân sách / tài khoản."""
    item = selected_item(state)
    if item is None:
        return
    if state.tab == 1:
        form = open_form(state, "account_edit", api)
        form.values.update(name=item["name"], balance=_amount_text(item["balance"]),
                           default="1" if item.get("is_default") else "0")
        form.title = "Sửa tài khoản: %s" % item["name"]
        form.edit_id = item["id"]
        return
    if state.tab == 5:
        open_goal_edit(state, item["id"], api)
        return
    if state.tab == 4:
        form = open_form(state, "budget_edit", api)
        form.values["amount"] = _amount_text(item["limit"])
        form.title = "Sửa ngân sách: %s" % item["category"]
        form.edit_id = item["category"]
        return
    if state.tab == 3 and item.get("status", "pending") != "pending":
        state.set_status("Dòng tiền này đã %s" % ("xong" if item["status"] == "done" else "huỷ"), False)
        return
    if state.tab == 2:
        form = open_form(state, "tx", api)
        form.values.update(amount=_amount_text(item["amount"]), category=item["category"],
                           note=item.get("note", ""), date=_dmy(date.fromisoformat(item["date"])), kind=item["kind"])
        if item.get("account_id") and "accounts" in form.cats:
            acc_name = next((a["name"] for a in form.cats["accounts"] if a["id"] == item["account_id"]), "")
            if acc_name:
                form.values["account"] = acc_name
        form.title = "Sửa giao dịch #%d" % item["id"]
    else:
        form = open_form(state, "plan", api)
        form.values.update(name=item["name"], amount=_amount_text(item["amount"]), category=item["category"],
                           every=item.get("recurrence") or "once", day=str(item.get("day") or ""),
                           due=_dmy(date.fromisoformat(item["due_date"])), kind=item["kind"])
        form.title = "Sửa dòng tiền #%d" % item["id"]
    form.edit_id = item["id"]


def open_goal(state: State, api: ApiCall) -> None:
    form = open_form(state, "goal", api)
    if state.goal:
        form.values.update(amount=_amount_text(state.goal["target"]), by=_dmy(date.fromisoformat(state.goal["by"])))


def open_goal_add(state: State, api: ApiCall) -> None:
    open_form(state, "goal_add", api)


def open_goal_save(state: State, gid: int, api: ApiCall) -> None:
    goals = state.goals or state.items()
    g = next((x for x in goals if x.get("id") == gid), None)
    form = open_form(state, "goal_save", api)
    form.edit_id = gid
    if g:
        form.title = "Góp vào hũ %s (có %s / cần %s)" % (
            g.get("name", ""), short_money(g.get("saved", 0)), short_money(g.get("target", 0)))


def open_goal_take(state: State, gid: int, api: ApiCall) -> None:
    goals = state.goals or state.items()
    g = next((x for x in goals if x.get("id") == gid), None)
    form = open_form(state, "goal_take", api)
    form.edit_id = gid
    if g:
        form.title = "Rút từ hũ %s (có %s)" % (g.get("name", ""), short_money(g.get("saved", 0)))


def open_goal_edit(state: State, gid: int, api: ApiCall) -> None:
    goals = state.goals or state.items()
    g = next((x for x in goals if x.get("id") == gid), None)
    form = open_form(state, "goal_edit", api)
    form.edit_id = gid
    if g:
        form.title = "Sửa mục tiêu: %s" % g.get("name", "")
        by_d = date.fromisoformat(g["by"]) if isinstance(g.get("by"), str) else g.get("by")
        form.values.update(name=g.get("name", ""),
                           amount=_amount_text(g.get("target", 0)),
                           by=_dmy(by_d) if by_d else "")


def confirm_goal_rm(state: State, gid: int, api: ApiCall) -> None:
    goals = state.goals or state.items()
    g = next((x for x in goals if x.get("id") == gid), None)
    name = g.get("name", "") if g else ("#%d" % gid)
    ask(state, "Xoá", "mục tiêu %s" % name, name, "goal rm", {"id": gid},
        ("Đã xoá mục tiêu %s" % name, "delete", "trash", "Đã xoá", name, "info", False))


def set_icon_mode(state: State, api: ApiCall, mode: str) -> None:
    try:
        mode = api("icons", {"mode": mode}).get("icons", mode)
    except Exception as e:
        fail(state, str(e))
        return
    set_icons(mode)
    state.set_status("Icon: %s" % mode)
    toast(state, state.status[0], "info")


def cycle_icons(state: State, api: ApiCall) -> None:
    set_icon_mode(state, api, ICON_MODES[(ICON_MODES.index(ICON_MODE) + 1) % len(ICON_MODES)])


def ask(state: State, verb: str, label: str, short: str, cmd: str, params: Dict[str, Any],
        done: Tuple[Any, ...]) -> None:
    """Confirmation in the action bar; `done` are the celebrate() arguments after the api call."""
    state.confirm = {"verb": verb, "label": label, "short": short, "cmd": cmd, "params": params, "done": done}


def submit(state: State, api: ApiCall) -> None:
    form = state.form
    cmd, params, errors = validate(form, state.today)
    form.errors = errors
    if errors:
        form.focus = next((f.key for f in form.visible() if f.key in errors), form.focus)
        fail(state, "Kiểm tra lại các ô được đánh dấu %s" % G["warn"])
        return
    try:
        result = api(cmd, params) or {}
    except Exception as e:  # LookupError / ValueError from api: keep the form open
        form.error = str(e)
        fail(state, str(e))
        return
    state.form = None
    if cmd == "budget set":
        item = "%s %s" % (params["category"], money(params["amount"]))
        edited = form.name == "budget_edit"
        verb = "Đã sửa" if edited else "Đã lưu"
        celebrate(state, api, "%s ngân sách %s %s" % (verb, G["ok"], item), "save", "pencil" if edited else "check",
                  verb + "!", item)
        return
    if cmd == "goal":
        sub = "cần %s/tháng · %d tháng" % (short_money(result.get("per_month", 0)), result.get("months_left", 0))
        state.goal = None  # set after the refresh: it is fresh already
        celebrate(state, api, "Đã đặt mục tiêu %s %s trước %s: %s" % (
            G["ok"], short_money(params["target"]), _vi_date(params["by"]), sub), "save", "check", "Đã đặt mục tiêu!", sub)
        state.goal = dict(result, target=params["target"], by=params["by"])
        return
    if cmd == "goal save":
        g = result.get("goal") or {}
        added = short_money(result.get("saved_added", 0))
        name = g.get("name", "")
        celebrate(state, api, "Đã góp %s vào %s" % (added, name), "save", "coin", "Đã góp!", "%s (+%s)" % (name, added))
        return
    if cmd == "goal take":
        g = result.get("goal") or {}
        taken = short_money(result.get("taken", 0))
        name = g.get("name", "")
        celebrate(state, api, "Đã rút %s từ %s" % (taken, name), "save", "coin", "Đã rút!", "%s (-%s)" % (name, taken))
        return
    if cmd in ("goal add", "goal edit"):
        g = result.get("goal") or {}
        name = g.get("name", "")
        verb = "Đã sửa" if cmd == "goal edit" else "Đã thêm"
        icon = "pencil" if cmd == "goal edit" else "check"
        celebrate(state, api, "%s mục tiêu %s" % (verb, name), "save", icon, verb + "!", name)
        return
    if cmd in ("account add", "account edit"):
        a = result.get("account") or {}
        name = a.get("name", "")
        verb = "Đã sửa" if cmd == "account edit" else "Đã thêm"
        bal_str = " (số dư: %s)" % money(a["balance"]) if "balance" in a else ""
        celebrate(state, api, "%s tài khoản %s%s" % (verb, name, bal_str), "save", "pencil" if cmd == "account edit" else "check",
                  verb + "!", "%s%s" % (name, bal_str))
        return
    if cmd == "account transfer":
        tr = result.get("transfer") or {}
        amt = money(tr.get("amount", 0))
        msg = "%s → %s: %s" % (tr.get("from_account", ""), tr.get("to_account", ""), amt)
        celebrate(state, api, "Đã chuyển %s" % msg, "save", "coin", "Đã chuyển!", msg)
        return
    if cmd == "plan done":
        tx = result.get("transaction") or {}
        p = result.get("plan") or {}
        income = tx.get("kind") == "income"
        amt = tx.get("amount", 0)
        item = "%s %s" % (p.get("name", "Dòng tiền"), money(amt if income else -amt, signed=True))
        title = "Đã nhận!" if income else "Đã thanh toán!"
        celebrate(state, api, "%s %s %s" % (title[:-1], G["ok"], item), "done", "coin", title, item)
        return
    income = params.get("income") or params.get("kind") == "income" or cmd == "income"
    amount = money(params["amount"] if income else -params["amount"], signed=True)
    item = "%s %s" % (params.get("name") or params["category"], amount)
    if cmd in ("edit", "plan edit"):
        what = "giao dịch #%d" % params["id"] if cmd == "edit" else "dòng tiền"
        celebrate(state, api, "Đã sửa %s %s %s" % (what, G["ok"], item), "save", "pencil", "Đã sửa!", item)
        return
    what = {"plan add": "dòng tiền", "expense": "khoản chi", "income": "khoản thu"}[cmd]
    celebrate(state, api, "Đã lưu %s %s %s" % (what, G["ok"], item), "save", "check", "Đã lưu!", item)


def toggle_sound(state: State, api: ApiCall) -> None:
    set_sound(state, api, not state.sound)


def set_sound(state: State, api: ApiCall, want: bool) -> None:
    try:
        state.sound = bool(api("sound", {"state": "on" if want else "off"}).get("sound", want))
    except Exception as e:
        fail(state, str(e))
        return
    state.set_status("Đã bật âm thanh" if state.sound else "Đã tắt âm thanh")
    toast(state, state.status[0], "info")
    play(state, "tab")


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
    state.settings = False
    if state.tab != tab:
        state.slide = (state.tab, tab, state.now)
        state.tab, state.selected, state.scroll = tab, None, 0
        play(state, "tab")
        if tab in (0, 4, 5):
            state.bars_t0 = state.now
        if state.share_active and state.share_server:
            cur_key = TAB_KEY_BY_INDEX[tab] if tab < len(TAB_KEY_BY_INDEX) else "overview"
            state.share_server.update_config(active_tab=cur_key)
    load(state, api)


def select_row(state: State, index: Optional[int]) -> None:
    """Change the selected row (no glow sweep: click effects were removed on request)."""
    state.selected = index


def change_view(state: State, api: ApiCall, tab: int) -> None:
    """A view setting of `tab` changed: reload it, keep the selection sane."""
    state.data.pop(tab, None)
    state.selected, state.scroll = None, 0
    load(state, api)


def move_month(state: State, api: ApiCall, key: str, step: int) -> None:
    this = state.today.strftime("%Y-%m")
    if key == "tx":
        state.tx_month = None if step == 0 else shift_month(state.tx_month, step) if state.tx_month else this
        change_view(state, api, 2)
    else:
        state.budget_month = shift_month(state.budget_month or this, step)
        change_view(state, api, 4)


def chart_set(state: State, api: ApiCall, key: str, value: str) -> None:
    state.chart[key] = int(value) if key in ("days", "ahead") else value
    state.chart["cursor"] = None
    if key in ("days", "ahead"):
        state.data.pop(6, None)
        load(state, api)


def move_cursor(state: State, step: int) -> None:
    n = _chart_count(state)
    if not n:
        return
    cur = state.chart["cursor"]
    state.chart["cursor"] = max(0, min(n - 1, (n - 1 if cur is None else cur + step)))


def handle_key(state: State, key: str, api: ApiCall) -> None:
    """Apply one key: single chars or 'up' 'down' 'left' 'right' 'enter' 'esc' 'tab' 'shift-tab' 'backspace'."""
    if state.form:
        _form_key(state, key, api)
        return
    if state.confirm:
        if key in ("y", "enter"):
            c, state.confirm = state.confirm, None
            try:
                api(c["cmd"], c["params"])
            except Exception as e:
                fail(state, str(e))
                return
            state.selected = None
            celebrate(state, api, *c["done"])
        elif key in ("n", "esc"):
            state.set_status("Không %s" % state.confirm["verb"].lower())
            state.confirm = None
        return
    if state.settings and key in ("esc", "s"):
        state.settings = False
        return
    items = state.items()
    if key in ("q", "ctrl-c"):
        state.running = False
    elif state.tab == 7 and key in ("s", "enter", " "):
        state.toggle_share()
    elif state.tab == 7 and key in ("1", "2", "3", "4", "5", "6", "7"):
        idx = int(key) - 1
        if idx < len(TAB_KEY_BY_INDEX):
            state.toggle_share_tab(TAB_KEY_BY_INDEX[idx])
    elif state.tab == 7 and key == "m":
        state.set_share_sync_mode("follow" if state.share_sync_mode == "free" else "free")
    elif state.tab == 7 and key == "a":
        state.toggle_share_edit("expense")
    elif state.tab == 7 and key == "d":
        state.toggle_share_edit("cashflow")
    elif state.tab == 7 and key == "g":
        state.toggle_share_edit("goals")
    elif state.tab == 7 and key == "x":
        state.toggle_share_edit("edit_tx")
    elif state.tab == 7 and key == "c":
        copy_share_url(state)
    elif key in [str(i + 1) for i in range(len(TABS))]:
        switch_tab(state, int(key) - 1, api)
    elif key == "tab":
        switch_tab(state, (state.tab + 1) % len(TABS), api)
    elif state.tab == 6 and key in ("left", "right", "h", "l"):
        move_cursor(state, -1 if key in ("left", "h") else 1)
    elif state.tab == 6 and key in ("[", "{"):
        move_cursor(state, -7)
    elif state.tab == 6 and key in ("]", "}"):
        move_cursor(state, 7)
    elif state.tab == 6 and key in ("0", "home"):
        n_hist = len((state.data.get(6) or {}).get("series") or [])
        state.chart["cursor"] = max(0, n_hist - 1)
    elif state.tab == 6 and key in ("$", "end"):
        n = _chart_count(state)
        state.chart["cursor"] = max(0, n - 1)
    elif key in ("j", "down") and items:
        select_row(state, 0 if state.selected is None else min(state.selected + 1, len(items) - 1))
    elif key in ("k", "up") and items:
        select_row(state, 0 if state.selected is None else max(0, state.selected - 1))
    elif key == "esc":
        state.selected = None
        state.chart["cursor"] = None
    elif key == "d" and state.tab == 1 and state.selected is not None:
        acc = items[state.selected]
        try:
            api("account set-default", {"id": acc["id"]})
            refresh(state, api)
            celebrate(state, api, "Đã đặt %s làm mặc định" % acc["name"], "save", "check", "Đã đặt!", acc["name"])
        except Exception as e:
            fail(state, str(e))
    elif key == "x" and state.tab == 1 and state.selected is not None:
        acc = items[state.selected]
        ask(state, "Xoá", "tài khoản %s" % acc["name"], "#%d %s" % (acc["id"], acc["name"]), "account rm",
            {"id": acc["id"]},
            ("Đã xoá tài khoản %s" % acc["name"], "delete", "trash", "Đã xoá", acc["name"], "info", False))
    elif key == "account_add" or (key == "a" and state.tab == 1):
        open_account_add(state, api)
    elif key == "account_transfer" or (key == "t" and state.tab == 1):
        open_account_transfer(state, api)
    elif key == "s":
        state.settings = True
    elif key in ("[", "]") and state.tab in (2, 4):
        move_month(state, api, "tx" if state.tab == 2 else "budget", -1 if key == "[" else 1)
    elif key == "b":
        open_form(state, "budget", api)
    elif key == "g":
        if state.tab == 5:
            open_goal_add(state, api)
        else:
            open_goal(state, api)
    elif key == "goal_add":
        open_goal_add(state, api)
    elif key.startswith("goal_save:"):
        open_goal_save(state, int(key.split(":")[1]), api)
    elif key.startswith("goal_take:"):
        open_goal_take(state, int(key.split(":")[1]), api)
    elif key.startswith("goal_edit:"):
        open_goal_edit(state, int(key.split(":")[1]), api)
    elif key.startswith("goal_rm:"):
        confirm_goal_rm(state, int(key.split(":")[1]), api)
    elif key == "e" and state.tab == 5 and state.selected is not None:
        open_goal_edit(state, items[state.selected]["id"], api)
    elif key == "x" and state.tab == 5 and state.selected is not None:
        confirm_goal_rm(state, items[state.selected]["id"], api)
    elif key == "c" and state.tab == 3 and state.selected is not None:
        p = items[state.selected]
        if p.get("status", "pending") == "pending":
            amount = short_money(p["amount"] if p["kind"] == "income" else -p["amount"])
            ask(state, "Huỷ", "dòng tiền %s %s" % (p["name"], amount), "#%d %s" % (p["id"], amount), "plan cancel",
                {"id": p["id"]}, ("Đã huỷ dòng tiền %s %s" % (G["ok"], p["name"]), "delete", "trash", "Đã huỷ",
                                  p["name"], "info", False))
    elif key == "m":
        toggle_sound(state, api)
    elif key == "I":
        cycle_icons(state, api)
    elif key == "e":
        open_edit(state, api)
    elif key in ("a", "i", "p"):
        open_form(state, {"a": "expense", "i": "income", "p": "plan"}[key], api)
    elif key == "d" and state.tab == 3 and state.selected is not None \
            and items[state.selected].get("status", "pending") == "pending":
        p = items[state.selected]
        open_plan_done(state, p, api)
    elif key == "x" and state.tab == 2 and state.selected is not None:
        t = items[state.selected]
        label = "%s %s ngày %s" % (t["category"], money(t["amount"]), _vi_date(t["date"]))
        short = "#%d %s" % (t["id"], short_money(-t["amount"] if t["kind"] == "expense" else t["amount"]))
        ask(state, "Xoá", label, short, "rm", {"id": t["id"]},
            ("Đã xoá giao dịch #%d" % t["id"], "delete", "trash", "Đã xoá", "giao dịch #%d" % t["id"], "info", False))
    elif key == "x" and state.tab == 4 and state.selected is not None:
        b = items[state.selected]
        ask(state, "Xoá", "ngân sách %s (%s)" % (b["category"], money(b["limit"])), "NS %s" % b["category"],
            "budget delete", {"category": b["category"]},
            ("Đã xoá ngân sách %s" % b["category"], "delete", "trash", "Đã xoá", "ngân sách %s" % b["category"],
             "info", False))


_CLICK_SOUND = ("key", "chip", "cal", "month", "plans", "chartset", "chart_jump", "set",
                "toggle_share", "toggle_share_tab", "toggle_share_edit", "set_share_sync_mode", "copy_share_url")


def handle_click(state: State, x: int, y: int, api: ApiCall) -> None:
    """Left click at 1-based terminal coordinates, resolved through the last frame's hit map."""
    hit = next((h for h in state.hits if h[0] == y - 1 and h[1] <= x - 1 < h[2]), None)
    if not hit:
        return
    action = hit[3]
    kind = action[0]
    if kind in _CLICK_SOUND:  # soft ping for buttons and chips (no visual press effect)
        play(state, "click")
    if kind == "tab":
        switch_tab(state, action[1], api)
    elif kind == "key":
        handle_key(state, action[1], api)
    elif kind == "select" and not state.confirm:
        last, state.last_click = state.last_click, (action, state.now)
        if state.selected == action[1] and last and last[0] == action and state.now - last[1] < 0.4:
            state.last_click = None
            open_edit(state, api)  # double click
        else:
            select_row(state, action[1])
    elif kind == "month":
        move_month(state, api, action[1], action[2])
    elif kind == "plans":
        state.plans_all = action[1]
        change_view(state, api, 3)
    elif kind == "chartset":
        chart_set(state, api, action[1], action[2])
    elif kind == "chart_jump":
        state.chart["cursor"] = action[1]
    elif kind == "plot" and state.chart_obj is not None:
        index = state.chart_obj.index_at(x - 1)
        if index is not None:
            state.chart["cursor"] = index
    elif kind == "set":
        if action[1] == "sound":
            set_sound(state, api, action[2] == "on")
        else:
            set_icon_mode(state, api, action[2])
    elif kind == "toggle_share":
        state.toggle_share()
    elif kind == "toggle_share_tab":
        state.toggle_share_tab(action[1])
    elif kind == "toggle_share_edit":
        state.toggle_share_edit(action[1])
    elif kind == "set_share_sync_mode":
        state.set_share_sync_mode(action[1])
    elif kind == "copy_share_url":
        copy_share_url(state)
    elif kind == "focus" and state.form:
        state.form.focus = action[1]
    elif kind == "chip" and state.form:
        form, key = state.form, action[1]
        form.values[key] = action[2]
        form.errors.pop(key, None)
        if key == "day" and form.edit_id is not None:
            form.values["due"] = ""  # editing: let the api move the due date to the new day
        # jump to the next required field still empty, so "click category, type amount, Enter" works
        req = ("amount",) if form.name in ("income", "expense", "tx") else REQUIRED
        form.focus = next((f.key for f in form.visible() if f.key in req and not form.values[f.key]), key)
    elif kind == "cal" and state.form:
        form, key = state.form, action[1]
        dv = form.date_value(key) or form.today
        y, m = form.months.get(key) or (dv.year, dv.month)
        m += action[2]
        form.months[key] = (y + (m - 1) // 12, (m - 1) % 12 + 1)
        form.focus = key


def dispatch(state: State, event: Event, api: ApiCall) -> None:
    if not event or event in ("tick", "resize"):
        return
    if popup_active(state):  # any input dismisses the popup; clicks only dismiss, keys still act
        state.popup = state.toast = state.sparkle = None
        if isinstance(event, tuple):
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
    """Reader of input events: blocks forever when timeout is None, returns "tick" when it expires
    and "resize" when the wake pipe fires."""

    def __init__(self, fd: int, wake_r: int):
        self.fd, self.wake_r, self.buf = fd, wake_r, b""

    def next(self, timeout: Optional[float] = None) -> Event:
        while True:
            event, n = parse_input(self.buf)
            if n:
                self.buf = self.buf[n:]
                return event
            r, _, _ = select.select([self.fd, self.wake_r], [], [], 0.05 if self.buf else timeout)
            if self.wake_r in r:
                os.read(self.wake_r, 64)
                return "resize"
            if self.fd in r:
                self.buf += os.read(self.fd, 1024)
            elif self.buf:  # an incomplete sequence timed out: lone ESC, or junk
                lone_esc, self.buf = self.buf == b"\x1b", b""
                return "esc" if lone_esc else ""
            else:
                return "tick"


def run_loop(state: State, next_event: Callable[[Optional[float]], Event], draw: Callable[[], None],
             api: ApiCall, clock: Callable[[], float]) -> None:
    """Draw, then wait: forever when idle (zero redraws), FRAME_S while an animation runs."""
    while state.running:
        if getattr(state, "dirty", False):
            state.dirty = False
            refresh(state, api)
        state.now = clock()
        draw()
        event = next_event(FRAME_S if state.animating() else None)
        state.now = clock()
        dispatch(state, event, api)


def _default_api(store, today: date) -> ApiCall:
    def call(cmd: str, params: Dict[str, Any]) -> Dict[str, Any]:
        from manage_eco import api
        return api.execute(cmd, params, store, today)
    return call


def run_tui(store, today: date, api: Optional[ApiCall] = None, clock: Callable[[], float] = time.monotonic) -> None:
    import termios
    import tty
    from rich.console import Console
    from rich.live import Live

    use_ascii(_ascii_default())
    call = api or _default_api(store, today)
    state = State(today)
    state.now = clock()
    init(state, call)

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    wake_r, wake_w = os.pipe()
    state._wake_w = wake_w
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

            def draw() -> None:
                width, height = console.size
                frame = build_frame(state, width, height)
                state.hits = frame.hits
                live.update(frame.renderable(), refresh=True)
            run_loop(state, reader.next, draw, call, clock)
    except KeyboardInterrupt:
        pass
    finally:
        state._wake_w = None
        if hasattr(state, "share_server") and state.share_server:
            state.share_server.stop()
        if hasattr(state, "share_tunnel") and state.share_tunnel:
            state.share_tunnel.stop()
        os.write(out_fd, MOUSE_OFF.encode())
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(wake_r)
        os.close(wake_w)
