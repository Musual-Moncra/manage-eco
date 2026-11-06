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
from manage_eco.fmt import money, parse_date, parse_money

try:
    from manage_eco import anim
except ImportError:  # animations are optional
    anim = None  # type: ignore
try:
    from manage_eco import sfx
except ImportError:  # sound is optional
    sfx = None  # type: ignore

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

UNICODE_GLYPHS = {"logo": "◆", "marker": "▸", "cursor": "▏", "rule": "─", "full": "█", "empty": "░", "ok": "✓",
                  "err": "✗", "warn": "⚠", "late": "⏰", "arrow": "→", "prev": "‹", "next": "›", "cap_l": "▐",
                  "cap_r": "▌", "done": "✓", "del": "✕", "spark": "▁▂▃▄▅▆▇█",
                  "happy": "(◕‿◕)", "worried": "(・_・;)", "sad": "(｡•́︿•̀｡)", "sound_on": "🔊", "sound_off": "🔇"}
ASCII_GLYPHS = {"logo": "*", "marker": ">", "cursor": "|", "rule": "-", "full": "#", "empty": ".", "ok": "v",
                "err": "x", "warn": "!", "late": "!", "arrow": "->", "prev": "<", "next": ">", "cap_l": "",
                "cap_r": "", "done": "v", "del": "x", "spark": "_.-:=+*#",
                "happy": ":)", "worried": ":/", "sad": ":(", "sound_on": "Am", "sound_off": "Tat"}
G = UNICODE_GLYPHS  # current glyph set; see use_ascii()
ICONS = True

TABS = ["Tổng quan", "Giao dịch", "Dòng tiền", "Ngân sách"]
TABS_SHORT = ["Tổng", "Giao", "Dòng", "Ngân"]
TAB_ICONS = ["🏠", "💸", "🔁", "🎯"]
CATEGORY_ICONS = [  # (accent-free keywords, icon); first match wins
    (("an", "uong", "com", "pho", "cafe", "ca phe", "tra sua"), "🍜"),
    (("nha", "thue nha", "tien nha"), "🏠"),
    (("xang", "xe", "grab", "taxi"), "🛵"),
    (("luong", "thuong"), "💰"),
    (("mua", "shopping", "sam"), "🛒"),
    (("hoc", "sach", "khoa hoc"), "📚"),
    (("dien", "nuoc", "internet", "wifi"), "💡"),
    (("claude", "app", "goi", "phan mem"), "💻"),
]
TAB_CMDS = [("dash", {}), ("list", {"all": True}), ("plan list", {}), ("budget status", {})]
AMOUNT_CHIPS = [(v, v) for v in ("50k", "100k", "200k", "500k", "1tr")]
EVERY = [("once", "1 lần"), ("daily", "Hàng ngày"), ("weekly", "Hàng tuần"), ("monthly", "Hàng tháng")]
DAY_CHIPS = [(str(d), str(d)) for d in (1, 5, 10, 15, 20, 25)] + [("31", "Cuối tháng")]
KINDS = [("expense", "Chi"), ("income", "Thu")]
EVERY_VI = {"once": "1 lần", "daily": "hàng ngày", "weekly": "hàng tuần", "monthly": "hàng tháng"}
WEEKDAYS = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật"]
DATE_FIELDS = ("date", "due")
REQUIRED = ("name", "amount", "category")


def use_ascii(flag: bool) -> None:
    """Switch every glyph (icons, bars, kaomoji, pills) to plain ASCII."""
    global G, ICONS
    G, ICONS = (ASCII_GLYPHS, False) if flag else (UNICODE_GLYPHS, True)


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
_TX_FIELDS = [_AMOUNT, _CATEGORY, Field("note", "Ghi chú", placeholder="(không bắt buộc)"),
              Field("date", "Ngày", placeholder="hôm nay")]
FORMS = {
    "expense": ("Thêm khoản chi", _TX_FIELDS),
    "income": ("Thêm khoản thu", _TX_FIELDS),
    "plan": ("Thêm dòng tiền", [Field("name", "Tên", placeholder="vd: lương, thuê nhà"),
                                _AMOUNT, _CATEGORY,
                                Field("every", "Lặp", EVERY),
                                Field("day", "Ngày trả hằng tháng", placeholder="chọn bên dưới (không bắt buộc)",
                                      show_if=("every", "monthly"), short="Ngày trả"),
                                Field("due", "Ngày bắt đầu", short="Bắt đầu"),
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
        self.sparkle = None  # type: Optional[Tuple[Any, float]]
        self.count = None  # type: Optional[Tuple[int, int, float]]
        self.bars_t0 = None  # type: Optional[float]

    def items(self) -> List[Dict[str, Any]]:
        if self.tab not in (1, 2):
            return []
        d = self.data.get(self.tab, {})
        return d.get("transactions") or d.get("plans") or []

    def set_status(self, msg: str, ok: bool = True) -> None:
        self.status = (msg, ok)

    def animating(self) -> bool:
        """True while any animation still has frames to draw at `now`."""
        t = self.now
        return bool((self.toast and not self.toast[0].done(t - self.toast[1]))
                    or (self.sparkle and not self.sparkle[0].done(t - self.sparkle[1]))
                    or (self.count and t - self.count[2] < 0.6)
                    or (self.bars_t0 is not None and t - self.bars_t0 < 0.5))

    def shown_balance(self) -> Optional[int]:
        if anim is not None and self.count and self.now - self.count[2] < 0.6:
            a, b, t0 = self.count
            return anim.count_up(a, b, self.now - t0)
        return self.balance

    def bar_pct(self, pct: float) -> float:
        if anim is not None and self.bars_t0 is not None and self.now - self.bars_t0 < 0.5:
            return anim.bar_fill(pct, self.now - self.bars_t0)
        return pct


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
    if state.tab == 0 and data:
        state.dash = data
    state.data[state.tab] = data
    if "balance" in data:
        state.balance = data["balance"]
    n = len(state.items())
    if state.selected is not None and state.selected >= n:
        state.selected = n - 1 if n else None


# --- feedback: sound, toast, sparkle, counters ---
def play(state: State, event: str) -> None:
    if sfx is not None:
        try:
            sfx.play(event, enabled=state.sound)
        except Exception:  # never let audio break the UI
            pass


def toast(state: State, message: str, kind: str = "success", sparkle: bool = False) -> None:
    if anim is None:
        return
    state.toast = (anim.Toast(message, kind), state.now)
    state.sparkle = (anim.Sparkle(44, 9, seed=int(state.now * 1000) & 0xFFFF), state.now) if sparkle else None


def fail(state: State, message: str) -> None:
    state.set_status(message, False)
    toast(state, message, "error")
    play(state, "error")


def worrying(dash: Dict[str, Any]) -> bool:
    low = dash.get("lowest") or {}
    return low.get("balance", 0) < 0 or any(float(b.get("pct", 0)) >= 100 for b in dash.get("budgets") or [])


def celebrate(state: State, api: ApiCall, message: str, event: str, kind: str = "success",
              sparkle: bool = True) -> None:
    """After a successful change: reload, tick the balance, pop a toast and play a sound."""
    before = state.balance
    refresh(state, api)
    if before is not None and state.balance is not None and before != state.balance:
        state.count = (before, state.balance, state.now)
    state.set_status(message)
    toast(state, message, kind, sparkle)
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


def category_icon(name: str) -> str:
    words = " %s " % " ".join(_plain(name).split())
    for keys, icon in CATEGORY_ICONS:
        if any(" %s " % k in words for k in keys):
            return icon
    return "•"


def cat_label(name: str) -> str:
    if not ICONS:
        return name
    icon = category_icon(name)
    return "%s%s %s" % (icon, " " if cell_len(icon) == 1 else "", name)  # icons padded to 2 cells


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
    def make(labels: List[str], icons: bool, caps: bool, gap: str = " ") -> Callable[[], Line]:
        def build() -> Line:
            ln = Line().add(" ")
            for i, name in enumerate(labels):
                icon = TAB_ICONS[i] + " " if icons and ICONS else ""
                text = (" %s%s " % (icon, name)) if name or not icon else " %s" % icon
                ln.pill([(text, TAB_ON if i == active else TAB_OFF)], ("tab", i),
                        ACCENT if i == active else "#2a2448", caps).add(gap)
            return ln
        return build
    icon_only = [TABS_SHORT[i] if i == active else "" for i in range(4)]
    digits = [str(i + 1) for i in range(4)]
    return fit([make(TABS, True, True), make(TABS, True, False), make(TABS_SHORT, True, True),
                make(TABS_SHORT, True, False), make(icon_only, True, False),
                make(digits, False, False, "")], width)


def action_line(state: State, width: int) -> Line:
    if state.form:
        buttons = [("Lưu", "Lưu", "enter", "Enter", True), ("Huỷ", "Huỷ", "esc", "Esc", False)]
        prefix = ""
    elif state.confirm:
        buttons = [("Có", "Có", "y", "y", True), ("Không", "Không", "n", "n", False)]
        prefix = "Xoá %s? " % state.confirm["label"]
    else:
        buttons = [("+ Chi", "+Chi", "a", "a", False), ("+ Thu", "+Thu", "i", "i", False),
                   ("+ Dòng tiền", "+Dòng", "p", "p", False)]
        if state.selected is not None and state.tab == 2:
            buttons.append(("%s Xong" % G["done"], G["done"], "d", "d", False))
        if state.selected is not None and state.tab == 1:
            buttons.append(("%s Xoá" % G["del"], G["del"], "x", "x", False))
        snd = G["sound_on"] if state.sound else G["sound_off"]
        buttons += [(snd, snd, "m", "m", False), ("Thoát", "Thoát", "q", "q", False)]
        prefix = ""

    short_prefix = "Xoá #%s %s? " % (state.confirm["id"], state.confirm["short"]) if state.confirm else ""

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
    cat_w = 14 if width >= 56 else 11
    money_w = 25 if full else 11
    bar_w = max(4, min(30, width - 3 - cat_w - 1 - 6 - 2 - money_w))
    for b in sorted(budgets, key=lambda b: -float(b.get("pct", 0)))[:rows]:
        pct = float(b.get("pct", 0))
        spent, limit = b.get("spent", 0), b.get("limit", 0)
        ln = Line(("tab", 3)).add("   ").cell(cat_label(b["category"]), cat_w).add(" ")
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
        ln = (Line(("tab", 2)).add("   ").cell(_vi_date(r["date"], short=True), 5, MUTED).add("  ")
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
    ln = Line(("tab", 2)).add("   ")
    for v in series:
        level = 0 if hi == lo else int((v - lo) / (hi - lo) * (len(ticks) - 1))
        ln.add(ticks[level] * k, EXPENSE_C if v < 0 else INCOME_C)
    ln.add("   thấp %s · cao %s" % (short_money(lo), short_money(hi)), MUTED)
    return [_title("Số dư 30 ngày tới"), ln]


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
    out.append(_rule(width))

    tail = []  # type: List[Line]
    low = d.get("lowest")
    if low and low.get("balance", 0) < 0:
        if width >= 80:
            warn = " %s Sẽ âm tiền ngày %s (thấp nhất %s)" % (G["warn"], _vi_date(low["date"]), money(low["balance"]))
        else:
            warn = " %s Âm tiền %s: %s" % (G["warn"], _vi_date(low["date"], short=True), short_money(low["balance"]))
        tail.append(Line(("tab", 2)).add(fit_money(warn, width), "bold " + EXPENSE_C))
    else:
        tail.append(Line().add(" %s Số dư không bị âm trong 90 ngày tới." % G["ok"], INCOME_C))
    overdue = d.get("overdue") or []
    if overdue:
        tail.append(Line(("tab", 2)).add(fit_money(" %s Quá hạn: %s" % (G["late"], ", ".join(p["name"] for p in overdue)),
                                                   width),
                                         WARN_C))
    spark = sparkline_lines(d, state.today, width) if width >= 160 else []
    spare = height - len(out) - len(tail) - (len(spark) + 1 if spark else 0)

    budgets, upcoming = d.get("budgets") or [], d.get("upcoming") or []
    if width >= 120:
        rows = max(1, min(12, spare - 2))
        lw = (width - 3) // 2
        out += hjoin(budget_section(state, budgets, lw, rows), upcoming_section(upcoming, width - lw - 3, rows),
                     lw, 3, width - lw - 3)
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


def transactions_lines(state: State, width: int, height: int) -> List[Line]:
    compact, wide = width < 60, width >= 120
    date_w, cat_w, amt_w = (5, 14, 14) if compact else (10, 18, 16)
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
    return list_lines(state, state.items(), head, row, height,
                      "Chưa có giao dịch. Nhấn [+ Chi] hoặc [+ Thu] để thêm.")


def plans_lines(state: State, width: int, height: int) -> List[Line]:
    compact, wide = width < 60, width >= 120
    date_w, amt_w = (5, 14) if compact else (10, 16)
    rec_w = 0 if compact else 23
    cat_w = 18 if wide else 0
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
        return columns(Line(), _vi_date(p["due_date"], short=compact), p["name"], recurrence_label(p),
                       cat_label(p.get("category", "")), amt, (WARN_C if p["due_date"] < today else "", c))
    return list_lines(state, state.items(), head, row, height,
                      "Chưa có dòng tiền. Nhấn [+ Dòng tiền] để thêm (vd: lương, thuê nhà, mua laptop).")


def budgets_lines(state: State, d: Dict[str, Any], width: int) -> List[Line]:
    budgets = d.get("budgets") or []
    if not budgets:
        return [Line(), Line().add("   Chưa đặt ngân sách. Dùng lệnh: eco budget set DANH_MỤC SỐ_TIỀN", MUTED)]
    full, wide = width >= 80, width >= 100
    cat_w = 18 if width >= 60 else 12
    money_w = 27 if full else 11
    bar_w = max(4, min(40, width - 1 - cat_w - 2 - 6 - 2 - money_w - (16 if wide else 0)))
    head = (Line().add(" ").cell("Danh mục", cat_w, MUTED).add("  ").cell("Đã dùng", bar_w + 6, MUTED).add("  ")
            .cell("Đã chi / Hạn mức", money_w, MUTED, right=True))
    if wide:
        head.add("  ").cell("Còn lại", 14, MUTED, right=True)
    out = [Line(), head]
    for b in budgets:
        pct, rem = float(b.get("pct", 0)), b.get("remaining", 0)
        spent, limit = b.get("spent", 0), b.get("limit", 0)
        ln = Line().add(" ").cell(cat_label(b["category"]), cat_w).add("  ")
        ln.text.append_text(_bar(pct, bar_w, state.bar_pct(pct)))
        ln.cell("%d%%" % round(pct), 6, right=True).add("  ")
        ln.cell(("%s / %s" % (money(spent), money(limit))) if full else
                "%s/%s" % (short_money(spent), short_money(limit)), money_w, right=True)
        if wide:
            ln.add("  ").cell(money(rem), 14, EXPENSE_C if rem < 0 else "", right=True)
        out.append(ln)
    out += [Line(), Line().add("   Đặt/sửa hạn mức: eco budget set DANH_MỤC SỐ_TIỀN", MUTED)]
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


def body_lines(state: State, width: int, height: int) -> List[Line]:
    if state.form:
        lines, (first, last) = form_lines(state.form, width)
        if len(lines) > height:  # scroll so the focused field (with its calendar) stays visible
            start = min(first, max(0, last - height + 1))
            lines = lines[start:start + height]
        return lines
    d = state.data.get(state.tab, {})
    if state.tab == 0:
        return overview_lines(state, d, width, height) if d else [Line(), Line().add("   Không có dữ liệu.", MUTED)]
    if state.tab == 1:
        return transactions_lines(state, width, height)
    if state.tab == 2:
        return plans_lines(state, width, height)
    return budgets_lines(state, d, width)


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


def apply_overlays(state: State, lines: List[Text], hits: List[Hit], width: int, height: int) -> List[Hit]:
    """Draw the toast (bottom-right, above the action bar) and its sparkles; the toast swallows clicks."""
    if not state.toast:
        return hits
    t = state.now - state.toast[1]
    box_w = max(4, min(52, width - 2))
    toast_ = state.toast[0]
    # inner width minus the kaomoji and the pop-in padding; shorten so the amount is never cut off
    kao = toast_._kaomoji(anim.ascii_mode()) if hasattr(toast_, "_kaomoji") else ""
    room = box_w - 4 - (cell_len(kao) + 2 if kao else 0) - 2
    if cell_len(toast_.message) > room:
        toast_ = anim.Toast(fit_money(toast_.message, room), toast_.kind, toast_.icon, toast_.duration)
    box = toast_.lines(t, box_w)
    top = height - 2 - len(box)
    if not box or top < 2:
        return hits
    tw = max(b.cell_len for b in box)
    x0 = max(0, width - tw - 1)
    blocked = []  # type: List[Hit]
    if state.sparkle:
        sp, t0 = state.sparkle
        area_top, area_left = top + len(box) // 2 - sp.height // 2, x0 + tw // 2 - sp.width // 2
        for r, c, ch, style in sp.cells(state.now - t0):
            row, col = area_top + r, area_left + c
            inside = top <= row < top + len(box) and x0 <= col < x0 + tw
            if 2 <= row < height - 2 and 0 <= col < width and not inside:
                lines[row] = put(lines[row], col, Text(ch, style=style))
    for i, b in enumerate(box):
        left = 1 if x0 > 0 else 0  # one blank cell around the box so no stray glyphs touch its border
        right = 1 if x0 + b.cell_len < width else 0
        lines[top + i] = put(lines[top + i], x0 - left, Text(" " * left) + b + Text(" " * right))
        blocked.append((top + i, x0, x0 + b.cell_len, ("noop",)))
    return blocked + hits


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


def init(state: State, api: ApiCall) -> None:
    """First load: overview data, stored sound setting, bars filling in."""
    load(state, api)
    try:
        state.sound = bool(api("sound", {}).get("sound", True))
    except Exception:
        pass
    state.bars_t0 = state.now


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
        fail(state, "Kiểm tra lại các ô được đánh dấu %s" % G["warn"])
        return
    try:
        api(cmd, params)
    except Exception as e:  # LookupError / ValueError from api: keep the form open
        form.error = str(e)
        fail(state, str(e))
        return
    state.form = None
    income = params.get("income") or cmd == "income"
    what = {"plan add": "dòng tiền", "expense": "khoản chi", "income": "khoản thu"}[cmd]
    amount = money(params["amount"] if income else -params["amount"], signed=True)
    celebrate(state, api, "Đã lưu %s %s %s %s" % (what, G["ok"], params.get("name") or params["category"], amount),
              "save")


def toggle_sound(state: State, api: ApiCall) -> None:
    want = not state.sound
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
    if state.tab != tab:
        state.tab, state.selected, state.scroll = tab, None, 0
        play(state, "tab")
        if tab in (0, 3):
            state.bars_t0 = state.now
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
                fail(state, str(e))
                return
            state.selected = None
            celebrate(state, api, "Đã xoá giao dịch #%d" % tid, "delete", "info", sparkle=False)
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
    elif key == "m":
        toggle_sound(state, api)
    elif key in ("a", "i", "p"):
        open_form(state, {"a": "expense", "i": "income", "p": "plan"}[key], api)
    elif key == "d" and state.tab == 2 and state.selected is not None:
        p = items[state.selected]
        try:
            api("plan done", {"id": p["id"], "date": state.today.isoformat()})
        except Exception as e:
            fail(state, str(e))
            return
        income = p["kind"] == "income"
        celebrate(state, api, "%s %s %s %s" % ("Đã nhận" if income else "Đã thanh toán", G["ok"], p["name"],
                                              money(p["amount"] if income else -p["amount"], signed=True)), "done")
    elif key == "x" and state.tab == 1 and state.selected is not None:
        t = items[state.selected]
        state.confirm = {"id": t["id"], "label": "%s %s ngày %s" % (t["category"], money(t["amount"]),
                                                                      _vi_date(t["date"])),
                         "short": short_money(-t["amount"] if t["kind"] == "expense" else t["amount"])}


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
    if not event or event in ("tick", "resize"):
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
        os.write(out_fd, MOUSE_OFF.encode())
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        signal.signal(signal.SIGWINCH, old_winch)
        os.close(wake_r)
        os.close(wake_w)
