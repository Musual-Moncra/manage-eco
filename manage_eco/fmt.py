"""Formatting and parsing helpers for money, dates, and progress bars."""
import calendar
import re
import unicodedata
from datetime import date, timedelta
from typing import List, Optional, Tuple

_SUFFIX_MULTIPLIERS = {
    "triệu": 1_000_000,
    "trieu": 1_000_000,
    "nghìn": 1_000,
    "nghin": 1_000,
    "tr": 1_000_000,
    "ng": 1_000,
    "m": 1_000_000,
    "k": 1_000,
}
_SORTED_UNITS = ("triệu", "trieu", "nghìn", "nghin", "tr", "ng", "m", "k")
_CURRENCY_SUFFIXES = ("₫", "vnd", "đ")

_NUM_PART_RE = re.compile(r"\d+(?:[.,]\d+)*")
_DECIMAL_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_DOT_GROUP_RE = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_COMMA_GROUP_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DM_DASH_RE = re.compile(r"^(\d{1,2})-(\d{1,2})$")
_DM_SLASH_RE = re.compile(r"^(\d{1,2})/(\d{1,2})$")
_DMY_SHORT_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2})$")
_DMY_FULL_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
_WEEKDAY_RE = re.compile(r"^(?:thu\s*|t)([2-7])$")

_WEEKDAY_NAMES = (
    "Thứ 2",
    "Thứ 3",
    "Thứ 4",
    "Thứ 5",
    "Thứ 6",
    "Thứ 7",
    "Chủ nhật",
)

Token = Tuple[str, object, bool]


def money(amount: int, signed: bool = False) -> str:
    """Format an integer VND amount with dot thousands separators, e.g. '1.250.000 ₫'."""
    val = int(amount)
    formatted = (f"{val:+,}" if signed else f"{val:,}").replace(",", ".")
    return f"{formatted} ₫"


def _tokenize_money(s: str) -> List[Token]:
    if not isinstance(s, str):
        raise ValueError("Invalid money input")
    raw = s.strip().lower()
    if not raw:
        raise ValueError(f"Empty money value: {s!r}")

    tokens: List[Token] = []
    i = 0
    n = len(raw)

    while i < n:
        ch = raw[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "(":
            tokens.append(("LPAREN", "(", False))
            i += 1
            continue
        if ch == ")":
            tokens.append(("RPAREN", ")", False))
            i += 1
            continue
        if ch in ("+", "-"):
            tokens.append(("OP", ch, False))
            i += 1
            continue
        if ch in ("*", "x", "×"):
            tokens.append(("OP", "*", False))
            i += 1
            continue
        if ch in ("/", ":", "÷"):
            tokens.append(("OP", "/", False))
            i += 1
            continue
        if ch.isdigit():
            m = _NUM_PART_RE.match(raw, i)
            if not m:
                raise ValueError(f"Invalid number in {s!r}")
            num_str = m.group(0)
            i = m.end()
            if i < n and raw[i] in (".", ","):
                raise ValueError(f"Invalid number format in {s!r}")

            j = i
            while j < n and raw[j].isspace():
                j += 1
            unit: Optional[str] = None
            for u in _SORTED_UNITS:
                if raw.startswith(u, j):
                    after_u = j + len(u)
                    if after_u == n or not raw[after_u].isalpha() or raw[after_u] in ("x", "×", "đ"):
                        unit = u
                        i = after_u
                        break

            j = i
            while j < n and raw[j].isspace():
                j += 1
            for cur in _CURRENCY_SUFFIXES:
                if raw.startswith(cur, j):
                    after_c = j + len(cur)
                    if after_c == n or not raw[after_c].isalpha() or raw[after_c] in ("x", "×"):
                        i = after_c
                        break

            if unit is not None:
                if not _DECIMAL_RE.match(num_str):
                    raise ValueError(f"Invalid number with unit in {s!r}")
                val = float(num_str.replace(",", ".")) * _SUFFIX_MULTIPLIERS[unit]
                is_bare_decimal = False
            elif num_str.isdigit():
                val = float(int(num_str))
                is_bare_decimal = False
            elif _DOT_GROUP_RE.match(num_str):
                val = float(int(num_str.replace(".", "")))
                is_bare_decimal = False
            elif _COMMA_GROUP_RE.match(num_str):
                val = float(int(num_str.replace(",", "")))
                is_bare_decimal = False
            elif _DECIMAL_RE.match(num_str):
                val = float(num_str.replace(",", "."))
                is_bare_decimal = True
            else:
                raise ValueError(f"Invalid money format: {s!r}")

            tokens.append(("NUM", val, is_bare_decimal))
            continue

        raise ValueError(f"Unexpected token in {s!r}")

    if not tokens:
        raise ValueError(f"Empty money value: {s!r}")
    return tokens


def _eval_money_tokens(tokens: List[Token], allow_zero: bool = False, allow_negative: bool = False) -> int:
    has_op = any(tok[0] == "OP" for tok in tokens)
    if not has_op and any(tok[2] for tok in tokens if tok[0] == "NUM"):
        raise ValueError("Bare decimal without unit is not valid VND")

    pos = 0
    length = len(tokens)

    def parse_expr() -> float:
        nonlocal pos
        left = parse_term()
        while pos < length and tokens[pos][0] == "OP" and tokens[pos][1] in ("+", "-"):
            op = tokens[pos][1]
            pos += 1
            right = parse_term()
            left = left + right if op == "+" else left - right
        return left

    def parse_term() -> float:
        nonlocal pos
        left = parse_unary()
        while pos < length and tokens[pos][0] == "OP" and tokens[pos][1] in ("*", "/"):
            op = tokens[pos][1]
            pos += 1
            right = parse_unary()
            if op == "*":
                left *= right
            else:
                if right == 0:
                    raise ValueError("Division by zero")
                left /= right
        return left

    def parse_unary() -> float:
        nonlocal pos
        if pos < length and tokens[pos][0] == "OP" and tokens[pos][1] in ("+", "-"):
            op = tokens[pos][1]
            pos += 1
            val = parse_unary()
            return -val if op == "-" else val
        return parse_primary()

    def parse_primary() -> float:
        nonlocal pos
        if pos >= length:
            raise ValueError("Unexpected end of money expression")
        kind, val, _ = tokens[pos]
        if kind == "NUM":
            pos += 1
            return float(val)  # type: ignore[arg-type]
        if kind == "LPAREN":
            pos += 1
            inner = parse_expr()
            if pos >= length or tokens[pos][0] != "RPAREN":
                raise ValueError("Unclosed parenthesis in money expression")
            pos += 1
            return inner
        raise ValueError(f"Unexpected token: {val!r}")

    result_float = parse_expr()
    if pos != length:
        raise ValueError("Trailing tokens in money expression")

    result = int(round(result_float))
    if allow_negative:
        return result
    if allow_zero:
        if result < 0:
            raise ValueError(f"Amount must be >= 0 (got {result})")
    else:
        if result <= 0:
            raise ValueError(f"Amount must be > 0 (got {result})")
    return result


def parse_money(s: str, allow_zero: bool = False, allow_negative: bool = False) -> int:
    """Parse a human-friendly VND string or arithmetic expression into a positive integer amount (or >= 0 if allow_zero, or any integer if allow_negative)."""
    tokens = _tokenize_money(s)
    return _eval_money_tokens(tokens, allow_zero=allow_zero, allow_negative=allow_negative)


def money_preview(s: str) -> Optional[str]:
    """Return '= 70.000 ₫' when s contains an operator and parses, else None."""
    if not isinstance(s, str):
        return None
    try:
        tokens = _tokenize_money(s)
        if not any(tok[0] == "OP" for tok in tokens):
            return None
        amount = _eval_money_tokens(tokens)
    except ValueError:
        return None
    return f"= {money(amount)}"


def _strip_accents(s: str) -> str:
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def parse_date(s: str, today: date) -> date:
    """Parse flexible Vietnamese/ISO/relative date expressions."""
    if not isinstance(s, str):
        raise ValueError("Invalid date input")
    raw = s.strip()
    if not raw:
        raise ValueError("Empty date input")

    norm = " ".join(_strip_accents(raw.lower()).split())

    if norm in ("today", "hom nay", "nay"):
        return today
    if norm in ("hom qua", "qua"):
        return today - timedelta(days=1)
    if norm in ("mai", "ngay mai"):
        return today + timedelta(days=1)
    if norm in ("mot", "ngay kia"):
        return today + timedelta(days=2)
    if norm == "tuan sau":
        return today + timedelta(days=7)
    if norm == "thang sau":
        ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        last_day = calendar.monthrange(ny, nm)[1]
        return date(ny, nm, min(today.day, last_day))
    if norm == "dau thang sau":
        ny, nm = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
        return date(ny, nm, 1)
    if norm in ("cuoi thang", "cuoi thang nay"):
        last_day = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, last_day)

    if norm in ("chu nhat", "chua nhat", "cn"):
        days_ahead = (6 - today.weekday() - 1) % 7 + 1
        return today + timedelta(days=days_ahead)

    m_wd = _WEEKDAY_RE.match(norm)
    if m_wd:
        target_wd = int(m_wd.group(1)) - 2
        days_ahead = (target_wd - today.weekday() - 1) % 7 + 1
        return today + timedelta(days=days_ahead)

    if norm.startswith("+") or norm.startswith("-"):
        try:
            offset = int(norm)
        except ValueError as exc:
            raise ValueError(f"Invalid relative date: {s!r}") from exc
        return today + timedelta(days=offset)

    if norm.isdigit():
        day_num = int(norm)
        if not 1 <= day_num <= 31:
            raise ValueError(f"Day of month out of range (1..31): {s!r}")
        last_day = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, min(day_num, last_day))

    m_iso = _ISO_DATE_RE.match(norm)
    if m_iso:
        return date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))

    m_dm_dash = _DM_DASH_RE.match(norm)
    if m_dm_dash:
        return date(today.year, int(m_dm_dash.group(2)), int(m_dm_dash.group(1)))

    m_dm_slash = _DM_SLASH_RE.match(norm)
    if m_dm_slash:
        return date(today.year, int(m_dm_slash.group(2)), int(m_dm_slash.group(1)))

    m_dmy_short = _DMY_SHORT_RE.match(norm)
    if m_dmy_short:
        return date(2000 + int(m_dmy_short.group(3)), int(m_dmy_short.group(2)), int(m_dmy_short.group(1)))

    m_dmy_full = _DMY_FULL_RE.match(norm)
    if m_dmy_full:
        return date(int(m_dmy_full.group(3)), int(m_dmy_full.group(2)), int(m_dmy_full.group(1)))

    raise ValueError(f"Invalid date: {s!r}")


def date_preview(s: str, today: date) -> Optional[str]:
    """Return '→ Thứ 6, 13/11/2026' when s is parseable and not ISO, else None."""
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw or _ISO_DATE_RE.match(raw):
        return None
    try:
        parsed = parse_date(raw, today)
    except ValueError:
        return None
    return f"→ {_WEEKDAY_NAMES[parsed.weekday()]}, {parsed.strftime('%d/%m/%Y')}"


def progress_bar(pct: float, width: int = 20) -> str:
    """Return a rich-markup progress bar: green <80%, yellow <100%, red >=100%."""
    if pct < 80:
        color = "green"
    elif pct < 100:
        color = "yellow"
    else:
        color = "red"

    clamped = max(0.0, min(100.0, float(pct))) / 100.0
    filled = int(round(clamped * width))
    empty = max(0, width - filled)
    bar = ("█" * filled) + ("░" * empty)
    return f"[{color}]{bar}[/{color}]"
