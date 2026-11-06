"""Stock-style Braille line chart and OHLC candlestick chart for terminal cashflow history."""
from datetime import date
from typing import Any, Dict, List, Optional, Sequence, Tuple

from rich.cells import cell_len
from rich.text import Text

from manage_eco.anim import ascii_mode
from manage_eco.fmt import money

UP_COLOR = "#86efac"
DOWN_COLOR = "#fca5a5"
FORECAST_UP_COLOR = "dim #86efac"
FORECAST_DOWN_COLOR = "dim #fca5a5"
AXIS_COLOR = "#a8a2c4"
GRID_COLOR = "#4c4570"
ZERO_LINE_COLOR = "dim #fca5a5"
CROSSHAIR_COLOR = "#c4b5fd"

_BRAILLE_BITS = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)

_WEEKDAY_NAMES = (
    "Thứ 2",
    "Thứ 3",
    "Thứ 4",
    "Thứ 5",
    "Thứ 6",
    "Thứ 7",
    "Chủ nhật",
)


def _resolve_glyphs(glyphs: str) -> str:
    if ascii_mode() or glyphs == "ascii":
        return "ascii"
    if glyphs == "emoji":
        return "emoji"
    return "symbol"


def short_money(amount: int, signed: bool = False) -> str:
    """Format compact VND for chart axes and tooltips, e.g. '23,7tr', '+25tr', '-1,3tr'."""
    val = int(amount)
    if signed:
        sign = "+" if val >= 0 else "-"
    else:
        sign = "-" if val < 0 else ""
    v = abs(val)
    if v >= 1_000_000_000:
        num = f"{v / 1_000_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{sign}{num}tỷ"
    if v >= 1_000_000:
        num = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{sign}{num}tr"
    if v >= 1_000:
        num = f"{v / 1_000:.1f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{sign}{num}k"
    return f"{sign}{v} ₫"


def _format_ddmm(iso_str: str) -> str:
    parts = iso_str.split("-")
    if len(parts) == 3:
        return f"{parts[2]}/{parts[1]}"
    return iso_str[:5]


def _format_weekday_ddmm(iso_str: str) -> str:
    try:
        d = date.fromisoformat(iso_str)
        return f"{_WEEKDAY_NAMES[d.weekday()]}, {d.strftime('%d/%m')}"
    except ValueError:
        return iso_str


def _fit_line(line: Text, width: int) -> Text:
    out = line.copy()
    out.no_wrap = True
    out.overflow = "crop"
    out.truncate(max(0, width), overflow="crop", pad=True)
    return out


def _put_text(line: Text, x: int, piece: Text, width: int) -> Text:
    if x < 0:
        x = 0
    if x >= width:
        return _fit_line(line, width)
    left = line.copy()
    left.truncate(x, overflow="crop", pad=True)
    right_start = x + piece.cell_len
    plain_len = line.cell_len
    if right_start < plain_len:
        suffix = Text(no_wrap=True)
        cur = 0
        for ch_idx, ch in enumerate(line.plain):
            w = cell_len(ch)
            if cur >= right_start:
                suffix = line[ch_idx:]
                break
            cur += w
        combined = left + piece + suffix
    else:
        combined = left + piece
    return _fit_line(combined, width)


class Chart:
    """Rendered chart lines with plot bounding box and screen-column-to-index mapping."""

    def __init__(
        self,
        lines: List[Text],
        plot_box: Tuple[int, int, int, int],
        n_points: int,
        slot_mode: bool = False,
    ) -> None:
        self.lines = lines
        self.plot_box = plot_box
        self.n_points = int(n_points)
        self._slot_mode = slot_mode

    def index_at(self, col: int) -> Optional[int]:
        """Map screen column col inside plot_box to data index 0..n_points-1, or None."""
        x0, _, x1, _ = self.plot_box
        plot_w = x1 - x0
        if self.n_points <= 0 or plot_w <= 0 or col < x0 or col >= x1:
            return None
        if self.n_points == 1 or plot_w == 1:
            return 0
        rel = col - x0
        if self._slot_mode and self.n_points <= plot_w:
            return max(0, min(self.n_points - 1, (rel * self.n_points) // plot_w))
        ratio = rel / float(plot_w - 1)
        idx = int(round(ratio * (self.n_points - 1)))
        return max(0, min(self.n_points - 1, idx))

    def col_for_index(self, idx: int) -> Optional[int]:
        """Map data index 0..n_points-1 to screen column inside plot_box."""
        x0, _, x1, _ = self.plot_box
        plot_w = x1 - x0
        if self.n_points <= 0 or plot_w <= 0 or idx < 0 or idx >= self.n_points:
            return None
        if self.n_points == 1 or plot_w == 1:
            return x0 + plot_w // 2
        if self._slot_mode and self.n_points <= plot_w:
            sx0 = (idx * plot_w) // self.n_points
            sx1 = ((idx + 1) * plot_w) // self.n_points
            return x0 + sx0 + max(1, sx1 - sx0) // 2
        return x0 + int(round(idx * (plot_w - 1) / float(self.n_points - 1)))


def ohlc(series: Sequence[Dict[str, Any]], bucket: str = "week") -> List[Dict[str, Any]]:
    """Aggregate daily history rows into OHLC buckets ('day' | 'week' | 'month') where open = previous close."""
    if not series:
        return []

    buckets: List[Tuple[Any, List[Dict[str, Any]]]] = []
    for row in series:
        d = date.fromisoformat(str(row["date"]))
        if bucket == "day":
            key: Any = d.isoformat()
        elif bucket == "month":
            key = (d.year, d.month)
        else:
            iso = d.isocalendar()
            key = (iso[0], iso[1])
        if buckets and buckets[-1][0] == key:
            buckets[-1][1].append(row)
        else:
            buckets.append((key, [row]))

    out: List[Dict[str, Any]] = []
    prev_close: Optional[int] = None

    for _, rows in buckets:
        first = rows[0]
        if prev_close is None:
            inc0 = int(first.get("income", 0) or 0)
            exp0 = int(first.get("expense", 0) or 0)
            first_bal = int(first["balance"])
            open_val = first_bal - inc0 + exp0 if (inc0 or exp0) else first_bal
        else:
            open_val = prev_close

        daily_bals = [int(r["balance"]) for r in rows]
        close_val = daily_bals[-1]
        all_vals = [open_val] + daily_bals
        high_val = max(all_vals)
        low_val = min(all_vals)
        total_inc = sum(int(r.get("income", 0) or 0) for r in rows)
        total_exp = sum(int(r.get("expense", 0) or 0) for r in rows)

        out.append({
            "date": str(first["date"]),
            "end_date": str(rows[-1]["date"]),
            "open": open_val,
            "high": high_val,
            "low": low_val,
            "close": close_val,
            "income": total_inc,
            "expense": total_exp,
        })
        prev_close = close_val

    return out


def _header_line(
    first_bal: int,
    last_bal: int,
    val_range: float,
    width: int,
    mode: str,
    extra_label: str = "",
) -> Text:
    diff = last_bal - first_bal
    up = diff >= 0
    arrow = ("^" if up else "v") if mode == "ascii" else ("▲" if up else "▼")
    color = UP_COLOR if up else DOWN_COLOR
    change_s = short_money(diff, signed=True)

    same_sign = (first_bal > 0 and last_bal > 0) or (first_bal < 0 and last_bal < 0)
    show_pct = same_sign and abs(first_bal) >= 0.01 * max(1.0, float(val_range))

    ln = Text(no_wrap=True)
    ln.append(" ")
    ln.append(money(last_bal), style=f"bold {color}")
    ln.append("  ")
    if show_pct:
        pct = (diff / float(abs(first_bal))) * 100.0
        ln.append(f"{arrow} {change_s} ({pct:+.1f}%)", style=color)
    else:
        ln.append(f"{arrow} {change_s}", style=color)
    if extra_label:
        ln.append(f"  {extra_label}", style=AXIS_COLOR)
    return _fit_line(ln, width)


def _price_ticks(min_v: float, max_v: float, plot_h: int) -> Dict[int, str]:
    if plot_h <= 0:
        return {}
    if plot_h <= 2:
        rows = sorted({0, plot_h - 1})
    elif plot_h < 7:
        rows = sorted({0, plot_h // 2, plot_h - 1})
    elif plot_h < 12:
        rows = sorted({0, plot_h // 3, (2 * plot_h) // 3, plot_h - 1})
    else:
        rows = sorted({0, plot_h // 4, plot_h // 2, (3 * plot_h) // 4, plot_h - 1})

    ticks: Dict[int, str] = {}
    span = max_v - min_v
    for r in rows:
        ratio = 0.0 if plot_h == 1 else (1.0 - r / float(plot_h - 1))
        val = int(round(min_v + span * ratio))
        ticks[r] = short_money(val)
    return ticks


def _date_axis_line(
    dates: List[str],
    plot_w: int,
    width: int,
    today_col: Optional[int] = None,
    cols: Optional[List[int]] = None,
) -> Text:
    buf = [" "] * width
    style_map = [AXIS_COLOR] * width

    n = len(dates)
    if n > 0 and plot_w >= 6:
        max_labels = min(6, max(2, plot_w // 10))
        if n <= max_labels:
            indices = list(range(n))
        else:
            indices = [int(round(k * (n - 1) / float(max_labels - 1))) for k in range(max_labels)]

        occupied = set()
        if today_col is not None and 0 <= today_col < plot_w:
            label = "Hôm nay"
            start_x = max(0, min(plot_w - len(label), today_col - len(label) // 2))
            if start_x + len(label) <= plot_w:
                for k, ch in enumerate(label):
                    buf[start_x + k] = ch
                    style_map[start_x + k] = f"bold {CROSSHAIR_COLOR}"
                for x in range(max(0, start_x - 1), min(plot_w, start_x + len(label) + 1)):
                    occupied.add(x)

        for idx in indices:
            if cols is not None and idx < len(cols):
                col = cols[idx]
            else:
                col = plot_w // 2 if n == 1 else int(round(idx * (plot_w - 1) / float(n - 1)))
            lbl = _format_ddmm(dates[idx])
            start_x = max(0, min(plot_w - len(lbl), col - len(lbl) // 2))
            if start_x < 0 or start_x + len(lbl) > plot_w:
                continue
            span_cols = set(range(start_x, start_x + len(lbl)))
            if span_cols & occupied:
                continue
            for k, ch in enumerate(lbl):
                buf[start_x + k] = ch
            occupied |= set(range(max(0, start_x - 1), min(plot_w, start_x + len(lbl) + 1)))

    ln = Text(no_wrap=True)
    for x in range(width):
        ln.append(buf[x], style=style_map[x])
    return _fit_line(ln, width)


def _overlay_tooltip(
    lines: List[Text],
    tooltip_str: str,
    cursor_col: int,
    plot_box: Tuple[int, int, int, int],
    width: int,
    mode: str,
) -> None:
    x0, y0, x1, y1 = plot_box
    plot_w = x1 - x0
    plot_h = y1 - y0
    if plot_w < 10 or plot_h < 1:
        return

    if plot_h >= 3 and plot_w >= 16:
        max_inner = max(6, plot_w - 4)
        inner = Text(tooltip_str, style="bold #ede9fe", no_wrap=True, overflow="ellipsis")
        inner.truncate(max_inner, overflow="ellipsis")
        box_w = inner.cell_len + 4
        tl, tr, bl, br, hz, vt = (
            ("+", "+", "+", "+", "-", "|")
            if mode == "ascii"
            else ("╭", "╮", "╰", "╯", "─", "│")
        )
        horiz = hz * (box_w - 2)
        top_ln = Text(f"{tl}{horiz}{tr}", style=CROSSHAIR_COLOR, no_wrap=True)
        mid_ln = Text(no_wrap=True)
        mid_ln.append(f"{vt} ", style=CROSSHAIR_COLOR)
        mid_ln.append_text(inner)
        mid_ln.append(f" {vt}", style=CROSSHAIR_COLOR)
        bot_ln = Text(f"{bl}{horiz}{br}", style=CROSSHAIR_COLOR, no_wrap=True)

        if cursor_col + 2 + box_w <= x1:
            bx = cursor_col + 2
        elif cursor_col - 1 - box_w >= x0:
            bx = cursor_col - 1 - box_w
        else:
            bx = max(x0, min(x1 - box_w, cursor_col - box_w // 2))

        for dy, b_ln in enumerate((top_ln, mid_ln, bot_ln)):
            r = y0 + dy
            if y0 <= r < y1 and 0 <= r < len(lines):
                lines[r] = _put_text(lines[r], bx, b_ln, width)
    else:
        pill = Text(f" {tooltip_str} ", style="bold #1e1b2e on #c4b5fd", no_wrap=True)
        pill.truncate(plot_w, overflow="ellipsis")
        bx = max(x0, min(x1 - pill.cell_len, cursor_col - pill.cell_len // 2))
        if 0 <= y0 < len(lines):
            lines[y0] = _put_text(lines[y0], bx, pill, width)


def line_chart(
    series: Sequence[Dict[str, Any]],
    forecast: Sequence[Dict[str, Any]] = (),
    width: int = 80,
    height: int = 20,
    *,
    cursor: Optional[int] = None,
    glyphs: str = "symbol",
) -> Chart:
    """Render a Braille stock-style up/down line chart of daily balances and forecast."""
    width = max(1, int(width))
    height = max(1, int(height))
    mode = _resolve_glyphs(glyphs)

    hist_pts = list(series or [])
    fore_pts = list(forecast or [])
    all_pts = hist_pts + fore_pts
    n_pts = len(all_pts)

    axis_w = 8 if width < 55 else 10
    plot_w = max(1, width - axis_w - 1)
    plot_h = max(1, height - 2)
    plot_box = (0, 1, plot_w, 1 + plot_h)

    if n_pts == 0:
        empty_lines = [
            _fit_line(Text(" Chưa có dữ liệu biểu đồ", style=AXIS_COLOR), width)
            if r == height // 2
            else _fit_line(Text(""), width)
            for r in range(height)
        ]
        return Chart(empty_lines, plot_box, 0)

    balances = [int(p["balance"]) for p in all_pts]
    raw_min = float(min(balances))
    raw_max = float(max(balances))
    raw_range = max(1.0, raw_max - raw_min)

    if height == 1:
        hdr = _header_line(int(all_pts[0]["balance"]), int(all_pts[-1]["balance"]), raw_range, width, mode)
        return Chart([hdr], (0, 0, plot_w, 1), n_pts)

    min_b, max_b = raw_min, raw_max
    if min_b < 0.0 < max_b:
        pass
    elif min_b == max_b:
        pad = max(1000.0, abs(min_b) * 0.1)
        min_b -= pad
        max_b += pad
    else:
        pad = (max_b - min_b) * 0.06
        min_b -= pad
        max_b += pad

    span_b = max(1.0, max_b - min_b)
    sub_w = plot_w * 2
    sub_h = plot_h * 4

    def val_to_py(v: float) -> int:
        ratio = (v - min_b) / span_b
        py = int(round((1.0 - ratio) * (sub_h - 1)))
        return max(0, min(sub_h - 1, py))

    def idx_to_px(i: int) -> int:
        if n_pts == 1:
            return sub_w // 2
        return int(round(i * (sub_w - 1) / float(n_pts - 1)))

    masks = [[0] * plot_w for _ in range(plot_h)]
    cell_styles = [[""] * plot_w for _ in range(plot_h)]

    if n_pts == 1:
        px = idx_to_px(0)
        py = val_to_py(float(balances[0]))
        masks[py // 4][px // 2] |= _BRAILLE_BITS[py % 4][px % 2]
        cell_styles[py // 4][px // 2] = UP_COLOR
    else:
        for i in range(n_pts - 1):
            x0_p, y0_p = idx_to_px(i), val_to_py(float(balances[i]))
            x1_p, y1_p = idx_to_px(i + 1), val_to_py(float(balances[i + 1]))
            rising = balances[i + 1] >= balances[i]
            is_fore = (i + 1) >= len(hist_pts)
            if is_fore:
                seg_style = FORECAST_UP_COLOR if rising else FORECAST_DOWN_COLOR
            else:
                seg_style = UP_COLOR if rising else DOWN_COLOR

            steps = max(1, abs(x1_p - x0_p), abs(y1_p - y0_p))
            for s in range(steps + 1):
                px = int(round(x0_p + (x1_p - x0_p) * s / float(steps)))
                py = int(round(y0_p + (y1_p - y0_p) * s / float(steps)))
                px = max(0, min(sub_w - 1, px))
                py = max(0, min(sub_h - 1, py))
                rc, cc = py // 4, px // 2
                masks[rc][cc] |= _BRAILLE_BITS[py % 4][px % 2]
                cell_styles[rc][cc] = seg_style

    crosses_zero = min(balances) < 0 and max(balances) >= 0
    zero_row: Optional[int] = None
    if crosses_zero:
        zero_py = val_to_py(0.0)
        zero_row = zero_py // 4

    today_col: Optional[int] = None
    if hist_pts and fore_pts and n_pts > 1:
        today_col = int(round((len(hist_pts) - 1) * (plot_w - 1) / float(n_pts - 1)))

    cursor_col: Optional[int] = None
    if cursor is not None and 0 <= cursor < n_pts:
        cursor_col = plot_w // 2 if n_pts == 1 else int(round(cursor * (plot_w - 1) / float(n_pts - 1)))

    ticks = _price_ticks(min_b, max_b, plot_h)
    zero_ch = "-" if mode == "ascii" else "┈"
    div_ch = "|" if mode == "ascii" else "┊"
    cross_ch = "|" if mode == "ascii" else "│"

    first_b = int(hist_pts[0]["balance"]) if hist_pts else balances[0]
    last_b = int(hist_pts[-1]["balance"]) if hist_pts else balances[-1]
    lines: List[Text] = [_header_line(first_b, last_b, raw_range, width, mode)]

    for r in range(plot_h):
        ln = Text(no_wrap=True)
        for c in range(plot_w):
            m = masks[r][c]
            st = cell_styles[r][c]
            if m:
                if mode == "ascii":
                    ch = "." if st.startswith("dim") else "*"
                else:
                    ch = chr(0x2800 | m)
                if c == cursor_col:
                    st = f"bold {st[4:] if st.startswith('dim ') else st} on #352d5c"
                ln.append(ch, style=st)
            elif c == cursor_col:
                ln.append(cross_ch, style=CROSSHAIR_COLOR)
            elif c == today_col:
                ln.append(div_ch, style=f"dim {AXIS_COLOR}")
            elif crosses_zero and r == zero_row:
                ln.append(zero_ch, style=ZERO_LINE_COLOR)
            else:
                ln.append(" ")

        axis_sep = "|" if mode == "ascii" else "│"
        ln.append(axis_sep, style=GRID_COLOR)
        lbl = ticks.get(r, "")
        ln.append(lbl.rjust(axis_w), style=AXIS_COLOR)
        lines.append(_fit_line(ln, width))

    if len(lines) < height:
        all_dates = [str(p["date"]) for p in all_pts]
        lines.append(_date_axis_line(all_dates, plot_w, width, today_col=today_col))

    if cursor is not None and cursor_col is not None and 0 <= cursor < n_pts:
        pt = all_pts[cursor]
        d_lbl = _format_weekday_ddmm(str(pt["date"]))
        bal_lbl = money(int(pt["balance"]))
        if cursor < len(hist_pts):
            inc = int(pt.get("income", 0) or 0)
            exp = int(pt.get("expense", 0) or 0)
            tip = f"{d_lbl} · {bal_lbl} · +{short_money(inc)} / -{short_money(exp)}"
        else:
            tip = f"{d_lbl} · {bal_lbl} · Dự báo"
        _overlay_tooltip(lines, tip, cursor_col, plot_box, width, mode)

    return Chart(lines[:height], plot_box, n_pts, slot_mode=False)


def candle_chart(
    series: Sequence[Dict[str, Any]],
    width: int = 80,
    height: int = 20,
    *,
    bucket: str = "week",
    cursor: Optional[int] = None,
    glyphs: str = "symbol",
) -> Chart:
    """Render an OHLC candlestick chart per bucket ('day' | 'week' | 'month') with centered wick and wide body."""
    width = max(1, int(width))
    height = max(1, int(height))
    mode = _resolve_glyphs(glyphs)

    candles = ohlc(series, bucket=bucket)
    n_c = len(candles)

    axis_w = 8 if width < 55 else 10
    plot_w = max(1, width - axis_w - 1)
    plot_h = max(1, height - 2)
    plot_box = (0, 1, plot_w, 1 + plot_h)

    if n_c == 0:
        empty_lines = [
            _fit_line(Text(" Chưa có dữ liệu biểu đồ nến", style=AXIS_COLOR), width)
            if r == height // 2
            else _fit_line(Text(""), width)
            for r in range(height)
        ]
        return Chart(empty_lines, plot_box, 0, slot_mode=True)

    raw_min = float(min(c["low"] for c in candles))
    raw_max = float(max(c["high"] for c in candles))
    raw_range = max(1.0, raw_max - raw_min)

    if height == 1:
        hdr = _header_line(int(candles[0]["open"]), int(candles[-1]["close"]), raw_range, width, mode)
        return Chart([hdr], (0, 0, plot_w, 1), n_c, slot_mode=True)

    min_v, max_v = raw_min, raw_max
    if min_v == max_v:
        pad = max(1000.0, abs(min_v) * 0.1)
        min_v -= pad
        max_v += pad
    else:
        pad = (max_v - min_v) * 0.06
        min_v -= pad
        max_v += pad
    span_v = max(1.0, max_v - min_v)

    def val_to_row(v: float) -> int:
        if plot_h == 1:
            return 0
        ratio = (v - min_v) / span_v
        r = int(round((1.0 - ratio) * (plot_h - 1)))
        return max(0, min(plot_h - 1, r))

    grid_ch = [[" "] * plot_w for _ in range(plot_h)]
    grid_st = [[""] * plot_w for _ in range(plot_h)]

    wick_ch = "|" if mode == "ascii" else "│"
    body_ch = "#" if mode == "ascii" else "█"

    wick_cols: List[int] = []
    slot = max(1, plot_w // max(1, n_c))

    for i, c in enumerate(candles):
        if n_c <= plot_w:
            sx0 = (i * plot_w) // n_c
            sx1 = ((i + 1) * plot_w) // n_c
            slot_w = max(1, sx1 - sx0)
            # Leave at least 1 col gap between candles when slot_w >= 2
            max_body = max(1, slot_w - 1) if slot_w >= 2 else 1
            body_w = min(max_body, max(1, (slot * 2) // 3))
            if body_w > 2 and body_w % 2 == 0:
                body_w -= 1  # odd width >= 3 centers the 1-col wick symmetrically
            bx0 = sx0 + (slot_w - body_w) // 2
            bx1 = min(plot_w, bx0 + body_w)
            w_col = bx0 + (bx1 - bx0) // 2
        else:
            w_col = int(round(i * (plot_w - 1) / float(n_c - 1)))
            w_col = max(0, min(plot_w - 1, w_col))
            bx0, bx1 = w_col, w_col + 1

        wick_cols.append(w_col)
        up = c["close"] >= c["open"]
        color = UP_COLOR if up else DOWN_COLOR

        r_high = val_to_row(float(c["high"]))
        r_low = val_to_row(float(c["low"]))
        r_open = val_to_row(float(c["open"]))
        r_close = val_to_row(float(c["close"]))

        w_top, w_bot = min(r_high, r_low), max(r_high, r_low)
        b_top, b_bot = min(r_open, r_close), max(r_open, r_close)

        for r in range(w_top, w_bot + 1):
            if 0 <= w_col < plot_w:
                grid_ch[r][w_col] = wick_ch
                grid_st[r][w_col] = color
        for r in range(b_top, b_bot + 1):
            for bc in range(bx0, bx1):
                if 0 <= bc < plot_w:
                    grid_ch[r][bc] = body_ch
                    grid_st[r][bc] = f"bold {color}"

    cursor_col: Optional[int] = None
    if cursor is not None and 0 <= cursor < n_c:
        cursor_col = wick_cols[cursor]

    ticks = _price_ticks(min_v, max_v, plot_h)
    cross_ch = "|" if mode == "ascii" else "│"

    lines: List[Text] = [
        _header_line(
            int(candles[0]["open"]),
            int(candles[-1]["close"]),
            raw_range,
            width,
            mode,
            extra_label=f"[{bucket}]",
        )
    ]

    for r in range(plot_h):
        ln = Text(no_wrap=True)
        for c in range(plot_w):
            ch = grid_ch[r][c]
            st = grid_st[r][c]
            if ch != " ":
                if c == cursor_col:
                    st = f"{st} on #352d5c"
                ln.append(ch, style=st)
            elif c == cursor_col:
                ln.append(cross_ch, style=CROSSHAIR_COLOR)
            else:
                ln.append(" ")
        axis_sep = "|" if mode == "ascii" else "│"
        ln.append(axis_sep, style=GRID_COLOR)
        lbl = ticks.get(r, "")
        ln.append(lbl.rjust(axis_w), style=AXIS_COLOR)
        lines.append(_fit_line(ln, width))

    if len(lines) < height:
        all_dates = [str(c["date"]) for c in candles]
        lines.append(_date_axis_line(all_dates, plot_w, width, cols=wick_cols))

    if cursor is not None and cursor_col is not None and 0 <= cursor < n_c:
        cd = candles[cursor]
        d_lbl = _format_weekday_ddmm(str(cd["date"]))
        close_lbl = money(int(cd["close"]))
        inc = int(cd.get("income", 0) or 0)
        exp = int(cd.get("expense", 0) or 0)
        tip = f"{d_lbl} · {close_lbl} · +{short_money(inc)} / -{short_money(exp)}"
        _overlay_tooltip(lines, tip, cursor_col, plot_box, width, mode)

    return Chart(lines[:height], plot_box, n_c, slot_mode=True)
