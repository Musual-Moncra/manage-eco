"""Formatting and parsing helpers for money, dates, and progress bars."""
import re
from datetime import date, datetime, timedelta

_SUFFIX_MULTIPLIERS = {
    "tr": 1_000_000,
    "trieu": 1_000_000,
    "triệu": 1_000_000,
    "m": 1_000_000,
    "k": 1_000,
    "ng": 1_000,
    "nghin": 1_000,
    "nghìn": 1_000,
}

_UNIT_RE = re.compile(r"^([+-]?\d+(?:[.,]\d+)?)\s*([a-zA-Zàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]+)$")
_DOT_GROUP_RE = re.compile(r"^\d{1,3}(?:\.\d{3})+$")
_COMMA_GROUP_RE = re.compile(r"^\d{1,3}(?:,\d{3})+$")


def money(amount: int, signed: bool = False) -> str:
    """Format an integer VND amount with dot thousands separators, e.g. '1.250.000 ₫'."""
    val = int(amount)
    formatted = (f"{val:+,}" if signed else f"{val:,}").replace(",", ".")
    return f"{formatted} ₫"


def parse_money(s: str) -> int:
    """Parse a human-friendly VND string into a positive integer amount."""
    if not isinstance(s, str):
        raise ValueError("Invalid money input")
    raw = s.strip().lower()
    for suffix in ("₫", "vnd", "đ"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
    if not raw:
        raise ValueError(f"Empty money value: {s!r}")

    match = _UNIT_RE.match(raw)
    if match:
        num_str, unit = match.group(1), match.group(2)
        if unit not in _SUFFIX_MULTIPLIERS:
            raise ValueError(f"Unknown money unit in {s!r}")
        value = round(float(num_str.replace(",", ".")) * _SUFFIX_MULTIPLIERS[unit])
        if value <= 0:
            raise ValueError(f"Amount must be > 0: {s!r}")
        return int(value)

    if raw.isdigit():
        value = int(raw)
    elif _DOT_GROUP_RE.match(raw):
        value = int(raw.replace(".", ""))
    elif _COMMA_GROUP_RE.match(raw):
        value = int(raw.replace(",", ""))
    else:
        raise ValueError(f"Invalid money format: {s!r}")

    if value <= 0:
        raise ValueError(f"Amount must be > 0: {s!r}")
    return value


def parse_date(s: str, today: date) -> date:
    """Parse ISO YYYY-MM-DD, DD/MM/YYYY, 'today'/'hom nay', or '+N' relative days."""
    if not isinstance(s, str):
        raise ValueError("Invalid date input")
    raw = s.strip().lower()
    if not raw:
        raise ValueError("Empty date input")

    if raw in ("today", "hom nay", "hôm nay", "nay"):
        return today

    if raw.startswith("+") or raw.startswith("-"):
        try:
            offset = int(raw)
        except ValueError as exc:
            raise ValueError(f"Invalid relative date: {s!r}") from exc
        return today + timedelta(days=offset)

    if "/" in raw:
        try:
            return datetime.strptime(raw, "%d/%m/%Y").date()
        except ValueError as exc:
            raise ValueError(f"Invalid DD/MM/YYYY date: {s!r}") from exc

    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid date: {s!r}") from exc


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
