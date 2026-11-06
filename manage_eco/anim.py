"""Pure, deterministic terminal UI animations and ASCII-mode helpers (no I/O or time calls)."""
import math
import os
import random
import sys
from typing import Dict, List, Optional, Tuple

from rich.cells import cell_len
from rich.text import Text

EMOJI_KAOMOJI = {
    "success": "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "error": "(╥﹏╥)",
    "info": "(•‿•)",
}
SYMBOL_KAOMOJI = {
    "success": r"\(^o^)/",
    "error": "(T_T)",
    "info": "(^_^)",
}
ASCII_KAOMOJI = {
    "success": ":)",
    "error": ":(",
    "info": ":)",
}
UNICODE_KAOMOJI = EMOJI_KAOMOJI

EMOJI_SPARKLES = ("✦", "✧", "⋆", "˚", "♡", "✿")
SYMBOL_SPARKLES = ("·", "*", "+", "°", "♥", "★")
ASCII_SPARKLES = ("*", "+", ".")
UNICODE_SPARKLES = EMOJI_SPARKLES

PASTEL_STYLES = {
    "success": ("bold #9ece6a", "#9ece6a", "dim #9ece6a"),
    "error": ("bold #f7768e", "#f7768e", "dim #f7768e"),
    "info": ("bold #bb9af7", "#7dcfff", "dim #7dcfff"),
}
SPARKLE_COLORS = ("#bb9af7", "#7dcfff", "#9ece6a", "#f7768e", "#e0af68")

ICON_COLORS = {
    "check": "#9ece6a",   # mint
    "coin": "#e0af68",    # gold
    "pencil": "#bb9af7",  # lavender
    "trash": "#ff9e64",   # coral
    "cross": "#f7768e",   # red
}

ICON_BITMAPS: Dict[str, List[str]] = {
    "check": [
        "                ",
        "                ",
        "             ## ",
        "            ### ",
        "           ###  ",
        "          ###   ",
        "         ###    ",
        "  ##    ###     ",
        " ###   ###      ",
        "  ### ###       ",
        "   #####        ",
        "    ###         ",
        "     #          ",
        "                ",
        "                ",
        "                ",
    ],
    "coin": [
        "                ",
        "     ######     ",
        "   ##########   ",
        "  ###  ##  ###  ",
        " ### ###### ### ",
        " ##  ##  ##  ## ",
        " ##  #####   ## ",
        " ##   #####  ## ",
        " ##  ##  ##  ## ",
        " ### ###### ### ",
        "  ###  ##  ###  ",
        "   ##########   ",
        "     ######     ",
        "                ",
        "                ",
        "                ",
    ],
    "pencil": [
        "                ",
        "           ###  ",
        "          ##### ",
        "         ###### ",
        "        ######  ",
        "       ######   ",
        "      ######    ",
        "     ######     ",
        "    ######      ",
        "   ######       ",
        "  ######        ",
        "  #####         ",
        "  ####          ",
        "  ##            ",
        "                ",
        "                ",
    ],
    "trash": [
        "                ",
        "     ######     ",
        "  ############  ",
        "  ############  ",
        "                ",
        "   ##########   ",
        "   ##  ##  ##   ",
        "   ##  ##  ##   ",
        "   ##  ##  ##   ",
        "   ##  ##  ##   ",
        "   ##  ##  ##   ",
        "   ##  ##  ##   ",
        "   ##########   ",
        "    ########    ",
        "                ",
        "                ",
    ],
    "cross": [
        "                ",
        "                ",
        "  ###      ###  ",
        "  ####    ####  ",
        "   ####  ####   ",
        "    ########    ",
        "     ######     ",
        "      ####      ",
        "      ####      ",
        "     ######     ",
        "    ########    ",
        "   ####  ####   ",
        "  ####    ####  ",
        "  ###      ###  ",
        "                ",
        "                ",
    ],
}

ICON_BITMAPS_8: Dict[str, List[str]] = {
    "check": [
        "        ",
        "      ##",
        "     ## ",
        " #  ##  ",
        " ####   ",
        "  ##    ",
        "        ",
        "        ",
    ],
    "coin": [
        "  ####  ",
        " ##  ## ",
        "## ## ##",
        "## ## ##",
        "## ## ##",
        " ##  ## ",
        "  ####  ",
        "        ",
    ],
    "pencil": [
        "     ## ",
        "    ### ",
        "   ###  ",
        "  ###   ",
        " ###    ",
        " ##     ",
        " #      ",
        "        ",
    ],
    "trash": [
        "  ####  ",
        " ###### ",
        " ##  ## ",
        " ##  ## ",
        " ##  ## ",
        " ###### ",
        "        ",
        "        ",
    ],
    "cross": [
        "        ",
        " ##  ## ",
        "  ####  ",
        "   ##   ",
        "  ####  ",
        " ##  ## ",
        "        ",
        "        ",
    ],
}


def _build_stroke(icon: str, rows: List[str]) -> List[Tuple[int, int]]:
    lit = [
        (r, c)
        for r, line in enumerate(rows)
        for c, ch in enumerate(line)
        if ch != " "
    ]
    mid = len(rows) / 2.0
    if icon == "check":
        # Short stroke down-right first, then long stroke up-right
        knee = int(round(mid * 0.7))
        short = sorted([p for p in lit if p[1] <= knee], key=lambda p: (p[1], p[0]))
        long_ = sorted([p for p in lit if p[1] > knee], key=lambda p: (p[1], -p[0]))
        return short + long_
    if icon == "coin":
        # Outer ring clockwise, then inner symbol top-to-bottom
        center = (len(rows) - 1) / 2.0
        r_thresh = (len(rows) * 0.28) ** 2
        outer = [p for p in lit if (p[0] - center) ** 2 + (p[1] - center) ** 2 >= r_thresh]
        inner = [p for p in lit if (p[0] - center) ** 2 + (p[1] - center) ** 2 < r_thresh]
        outer.sort(key=lambda p: math.atan2(p[0] - center, p[1] - center))
        inner.sort(key=lambda p: (p[0], p[1]))
        return outer + inner
    if icon == "pencil":
        # From top-right eraser down-left to pencil tip
        return sorted(lit, key=lambda p: (p[0] - p[1], p[0], -p[1]))
    if icon == "cross":
        # First diagonal (\) top-left to bottom-right, then second diagonal (/) top-right to bottom-left
        n = len(rows) - 1
        diag1 = [p for p in lit if abs(p[0] - p[1]) <= abs(p[0] - (n - p[1]))]
        diag2 = [p for p in lit if abs(p[0] - p[1]) > abs(p[0] - (n - p[1]))]
        diag1.sort(key=lambda p: (p[0] + p[1], p[0]))
        diag2.sort(key=lambda p: (p[0] - p[1], p[0]))
        return diag1 + diag2
    # Default (trash): top-to-bottom, left-to-right
    return sorted(lit, key=lambda p: (p[0], p[1]))


ICON_STROKES: Dict[str, List[Tuple[int, int]]] = {
    name: _build_stroke(name, bmp) for name, bmp in ICON_BITMAPS.items()
}
ICON_STROKES_8: Dict[str, List[Tuple[int, int]]] = {
    name: _build_stroke(name, bmp) for name, bmp in ICON_BITMAPS_8.items()
}


def ascii_mode() -> bool:
    """Return True if ECO_ASCII=1, TERM is linux/dumb, or stdout encoding is not UTF-8."""
    env_ascii = os.environ.get("ECO_ASCII", "").strip().lower()
    if env_ascii in ("1", "true", "yes"):
        return True
    if os.environ.get("TERM", "").strip().lower() in ("linux", "dumb"):
        return True
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding:
        norm_enc = encoding.lower().replace("-", "").replace("_", "")
        if norm_enc != "utf8":
            return True
    return False


def _resolve_glyphs(glyphs: str) -> str:
    if ascii_mode() or glyphs == "ascii":
        return "ascii"
    if glyphs == "emoji":
        return "emoji"
    return "symbol"


def _has_disallowed_symbol_cp(s: str) -> bool:
    return any(ord(ch) >= 0x1F000 or (0xFF61 <= ord(ch) <= 0xFF9F) for ch in s)


def ease_out_cubic(x: float) -> float:
    """Cubic ease-out curve on clamped x in [0, 1]."""
    clamped = max(0.0, min(1.0, float(x)))
    return 1.0 - ((1.0 - clamped) ** 3)


def ease_out_back(x: float) -> float:
    """Back ease-out curve with slight overshoot on clamped x in [0, 1]."""
    clamped = max(0.0, min(1.0, float(x)))
    if clamped <= 0.0:
        return 0.0
    if clamped >= 1.0:
        return 1.0
    c1 = 1.70158
    c3 = c1 + 1.0
    xm1 = clamped - 1.0
    return 1.0 + c3 * (xm1 ** 3) + c1 * (xm1 ** 2)


def count_up(start: int, end: int, t: float, duration: float = 0.6) -> int:
    """Interpolate an integer from start to end over duration using ease_out_cubic."""
    if duration <= 0.0 or t >= duration:
        return int(end)
    if t <= 0.0:
        return int(start)
    k = ease_out_cubic(t / duration)
    return int(round(start + (end - start) * k))


def bar_fill(pct: float, t: float, duration: float = 0.5) -> float:
    """Animate a progress bar percentage from 0.0 to pct over duration."""
    target = float(pct)
    if duration <= 0.0 or t >= duration:
        return target
    if t <= 0.0:
        return 0.0
    return target * ease_out_cubic(t / duration)


class Toast:
    """Animated pastel popup box with kaomoji and pop-in / hold / fade phases."""

    POP_IN = 0.25
    HOLD = 1.60
    FADE = 0.35

    def __init__(
        self,
        message: str,
        kind: str = "success",
        icon: Optional[str] = None,
        duration: float = 2.2,
        *,
        glyphs: str = "symbol",
    ) -> None:
        self.message = message
        self.kind = kind if kind in PASTEL_STYLES else "info"
        self.icon = icon
        self.duration = float(duration)
        self.glyphs = glyphs

    def done(self, t: float) -> bool:
        """Return True when the toast animation has completed."""
        return float(t) >= self.duration

    def _kaomoji(self, mode: object = None) -> str:
        if isinstance(mode, bool):
            resolved = "ascii" if mode else _resolve_glyphs(self.glyphs)
        elif isinstance(mode, str):
            resolved = mode
        else:
            resolved = _resolve_glyphs(self.glyphs)
        if self.icon is not None:
            if resolved == "ascii":
                try:
                    self.icon.encode("ascii")
                    return self.icon
                except UnicodeEncodeError:
                    return ASCII_KAOMOJI.get(self.kind, ":)")
            if resolved == "symbol" and _has_disallowed_symbol_cp(self.icon):
                return SYMBOL_KAOMOJI.get(self.kind, "(^_^)")
            return self.icon
        if resolved == "ascii":
            table = ASCII_KAOMOJI
        elif resolved == "emoji":
            table = EMOJI_KAOMOJI
        else:
            table = SYMBOL_KAOMOJI
        return table.get(self.kind, table["info"])

    def frame(self, t: float, width: int = 80) -> Optional[Text]:
        """Render the toast at elapsed time t (seconds) within width columns, or None when finished."""
        elapsed = float(t)
        if elapsed < 0.0 or self.done(elapsed) or width < 4:
            return None

        mode = _resolve_glyphs(self.glyphs)
        kaomoji = self._kaomoji(mode)
        body_str = f"{kaomoji}  {self.message}" if kaomoji else self.message

        text_style, border_style, dim_style = PASTEL_STYLES[self.kind]
        fade_start = max(0.0, self.duration - self.FADE)
        if elapsed >= fade_start:
            active_text_style = dim_style
            active_border_style = dim_style
        else:
            active_text_style = text_style
            active_border_style = border_style

        if elapsed < self.POP_IN and self.POP_IN > 0:
            pop = ease_out_back(elapsed / self.POP_IN)
            extra_pad = max(0, int(round((pop - 0.8) * 2)))
        else:
            extra_pad = 0

        pad_str = " " * extra_pad
        inner_raw = f"{pad_str}{body_str}{pad_str}"

        inner_text = Text(inner_raw, style=active_text_style, no_wrap=True, overflow="ellipsis")
        max_inner_w = max(1, width - 4)
        inner_text.truncate(max_inner_w, overflow="ellipsis")
        inner_w = inner_text.cell_len
        box_w = min(width, inner_w + 4)
        pad_right = " " * max(0, (box_w - 4) - inner_w)

        if mode == "ascii":
            tl, tr, bl, br, hz, vt = "+", "+", "+", "+", "-", "|"
        else:
            tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"

        horiz = hz * max(0, box_w - 2)
        top = Text(f"{tl}{horiz}{tr}", style=active_border_style, no_wrap=True)
        mid = Text(no_wrap=True)
        mid.append(f"{vt} ", style=active_border_style)
        mid.append_text(inner_text)
        mid.append(pad_right)
        mid.append(f" {vt}", style=active_border_style)
        bot = Text(f"{bl}{horiz}{br}", style=active_border_style, no_wrap=True)

        return Text("\n").join([top, mid, bot])

    def lines(self, t: float, width: int = 80) -> List[Text]:
        """Return the toast frame split into individual lines."""
        rendered = self.frame(t, width)
        if rendered is None:
            return []
        return list(rendered.split("\n"))


class Sparkle:
    """Deterministic confetti burst drifting up and outward from the center."""

    def __init__(
        self,
        width: int,
        height: int,
        seed: int = 0,
        count: int = 14,
        duration: float = 0.9,
        *,
        glyphs: str = "symbol",
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        self.count = int(count)
        self.duration = float(duration)
        self.glyphs = glyphs

        rng = random.Random(self.seed)
        self._particles: List[Tuple[float, float, float, float, int, int]] = []
        max_rx = max(3.0, min(18.0, self.width * 0.35))
        max_ry = max(2.0, min(8.0, self.height * 0.35))
        for i in range(self.count):
            angle = (2.0 * math.pi * i / max(1, self.count)) + rng.uniform(-0.25, 0.25)
            speed = rng.uniform(0.45, 1.0)
            dx = math.cos(angle) * max_rx * speed
            dy = (math.sin(angle) * max_ry * speed) - rng.uniform(1.0, 3.0)
            start_x = rng.uniform(-1.5, 1.5)
            start_y = rng.uniform(-0.5, 0.5)
            glyph_idx = rng.randrange(64)
            color_idx = i % len(SPARKLE_COLORS)
            self._particles.append((start_x, start_y, dx, dy, glyph_idx, color_idx))

    def done(self, t: float) -> bool:
        """Return True when the sparkle burst has finished."""
        return float(t) >= self.duration

    def cells(self, t: float) -> List[Tuple[int, int, str, str]]:
        """Return list of (row, col, char, style) at elapsed time t (seconds)."""
        elapsed = float(t)
        if (
            elapsed < 0.0
            or self.done(elapsed)
            or self.width <= 0
            or self.height <= 0
            or self.duration <= 0.0
        ):
            return []

        mode = _resolve_glyphs(self.glyphs)
        if mode == "ascii":
            charset = ASCII_SPARKLES
        elif mode == "emoji":
            charset = EMOJI_SPARKLES
        else:
            charset = SYMBOL_SPARKLES
        progress = ease_out_cubic(elapsed / self.duration)
        fading = (elapsed / self.duration) >= 0.65

        cx = self.width / 2.0
        cy = self.height / 2.0
        out: List[Tuple[int, int, str, str]] = []
        seen = set()

        for sx, sy, dx, dy, g_idx, c_idx in self._particles:
            col = int(round(cx + sx + dx * progress))
            row = int(round(cy + sy + dy * progress))
            if 0 <= row < self.height and 0 <= col < self.width and (row, col) not in seen:
                seen.add((row, col))
                ch = charset[g_idx % len(charset)]
                base_color = SPARKLE_COLORS[c_idx]
                style = f"dim {base_color}" if fading else f"bold {base_color}"
                out.append((row, col, ch, style))

        return out


class PixelPopup:
    """Centered pixel-art popup with stroke draw-in, ring pulse, and dither dissolve."""

    BITMAPS = ICON_BITMAPS
    STROKES = ICON_STROKES
    BITMAPS_8 = ICON_BITMAPS_8
    STROKES_8 = ICON_STROKES_8
    COLORS = ICON_COLORS

    T_GROW = 0.18
    T_DRAW = 0.65
    T_HOLD = 1.20
    DURATION = 1.60

    def __init__(
        self,
        icon: str,
        title: str,
        subtitle: str = "",
        color: Optional[str] = None,
        *,
        glyphs: str = "symbol",
        seed: int = 0,
    ) -> None:
        self.icon = icon if icon in ICON_BITMAPS else "check"
        self.title = title
        self.subtitle = subtitle
        self.color = color or ICON_COLORS.get(self.icon, "#9ece6a")
        self.glyphs = glyphs
        self.seed = int(seed)
        self.duration = self.DURATION

        rng = random.Random(self.seed)
        self._dissolve_thresholds = [rng.uniform(0.0, 0.68) for _ in range(128)]

    def done(self, t: float) -> bool:
        """Return True when the popup animation has finished."""
        return float(t) >= self.duration

    @staticmethod
    def is_compact(width: int, height: int) -> bool:
        return width < 44 or height < 16

    def size(self, width: int, height: int) -> Tuple[int, int]:
        """Return (box_width, box_height) for the given terminal dimensions, or (0, 0) if too small."""
        if width < 16 or height < 8:
            return (0, 0)
        compact = self.is_compact(width, height)
        text_w = max(cell_len(self.title), cell_len(self.subtitle))
        if compact:
            min_w = 16
            max_w = min(width, max(min_w, min(32, text_w + 4)))
            target_h = 8 if (self.subtitle and height >= 9) else 7
            if height < target_h or width < min_w:
                return (0, 0)
            return (max_w, target_h)

        min_w = 26
        max_w = min(width - 2, max(min_w, min(42, text_w + 6)))
        target_h = 14 if self.subtitle else 13
        if height < target_h or max_w < min_w:
            return (0, 0)
        return (max_w, target_h)

    def _render_icon_rows(
        self,
        t: float,
        compact: bool,
        mode: str,
    ) -> List[Text]:
        bmp = ICON_BITMAPS_8[self.icon] if compact else ICON_BITMAPS[self.icon]
        stroke = ICON_STROKES_8[self.icon] if compact else ICON_STROKES[self.icon]
        px_size = 8 if compact else 16
        cell_rows = px_size // 2

        pen_head: Optional[Tuple[int, int]] = None
        if t < self.T_GROW:
            lit_set = set()
        elif t < self.T_DRAW:
            p = ease_out_cubic((t - self.T_GROW) / (self.T_DRAW - self.T_GROW))
            n_lit = max(1, int(round(p * len(stroke))))
            lit_set = set(stroke[:n_lit])
            pen_head = stroke[min(len(stroke) - 1, n_lit - 1)]
        else:
            lit_set = set(stroke)

        # Ring pulse during hold phase (0.65 - 1.20s)
        ring_cells: Dict[Tuple[int, int], str] = {}
        if self.T_DRAW <= t < self.T_HOLD:
            rp = (t - self.T_DRAW) / (self.T_HOLD - self.T_DRAW)
            ring_chars = (".", "o", "O") if mode == "ascii" else ("·", "∘", "○")
            ring_ch = ring_chars[min(2, int(rp * 3))]
            cr = (cell_rows - 1) / 2.0
            cc = (px_size - 1) / 2.0
            rx = (px_size / 2.0) * (0.75 + 0.22 * rp)
            ry = (cell_rows / 2.0) * (0.75 + 0.22 * rp)
            for deg in range(0, 360, 45):
                rad = math.radians(deg)
                rr = int(round(cr + math.sin(rad) * ry))
                rc = int(round(cc + math.cos(rad) * rx))
                if 0 <= rr < cell_rows and 0 <= rc < px_size:
                    ring_cells[(rr, rc)] = ring_ch

        dissolving = t >= self.T_HOLD
        dissolve_p = (t - self.T_HOLD) / (self.duration - self.T_HOLD) if dissolving else 0.0
        dither_chars = ("#", "+", ".") if mode == "ascii" else ("▓", "▒", "░")

        out_rows: List[Text] = []
        for r_cell in range(cell_rows):
            r_top = r_cell * 2
            r_bot = r_top + 1
            ln = Text(no_wrap=True)
            for c_col in range(px_size):
                top_on = (r_top, c_col) in lit_set
                bot_on = (r_bot, c_col) in lit_set
                is_head = pen_head in ((r_top, c_col), (r_bot, c_col))

                if not top_on and not bot_on:
                    if (r_cell, c_col) in ring_cells:
                        ln.append(ring_cells[(r_cell, c_col)], f"dim {self.color}")
                    else:
                        ln.append(" ")
                    continue

                if dissolving:
                    idx = (r_cell * px_size + c_col) % len(self._dissolve_thresholds)
                    thresh = self._dissolve_thresholds[idx]
                    stage = (dissolve_p - thresh) / 0.32
                    if stage >= 1.0:
                        ln.append(" ")
                        continue
                    if stage >= 0.0:
                        d_idx = min(2, int(stage * 3))
                        d_style = f"dim {self.color}" if d_idx >= 1 else self.color
                        ln.append(dither_chars[d_idx], d_style)
                        continue

                if mode == "ascii":
                    ch = "#" if (top_on and bot_on) else ("^" if top_on else "_")
                else:
                    if top_on and bot_on:
                        ch = "█"
                    elif top_on:
                        ch = "▀"
                    else:
                        ch = "▄"
                style = "bold #ffffff" if is_head else f"bold {self.color}"
                ln.append(ch, style)
            out_rows.append(ln)
        return out_rows

    def _center_line(self, content: Text, inner_w: int) -> Text:
        clipped = content.copy()
        clipped.truncate(inner_w, overflow="ellipsis")
        w = clipped.cell_len
        pad_left = max(0, (inner_w - w) // 2)
        pad_right = max(0, inner_w - w - pad_left)
        res = Text(no_wrap=True)
        if pad_left:
            res.append(" " * pad_left)
        res.append_text(clipped)
        if pad_right:
            res.append(" " * pad_right)
        return res

    def frame(
        self,
        t: float,
        width: int,
        height: int,
    ) -> Optional[Tuple[int, int, List[Text]]]:
        """Return (top_row, left_col, lines) centered on screen, or None when done or too small."""
        elapsed = float(t)
        if elapsed < 0.0 or self.done(elapsed):
            return None

        target_w, target_h = self.size(width, height)
        if target_w == 0 or target_h == 0:
            return None

        mode = _resolve_glyphs(self.glyphs)
        compact = self.is_compact(width, height)

        if elapsed < self.T_GROW and self.T_GROW > 0:
            scale = max(0.35, min(1.0, ease_out_back(elapsed / self.T_GROW)))
            cur_w = max(8, min(width, int(round(target_w * scale))))
            cur_h = max(3, min(height, int(round(target_h * scale))))
        else:
            cur_w, cur_h = target_w, target_h

        inner_w = max(1, cur_w - 2)
        inner_h = max(1, cur_h - 2)

        border_style = f"dim {self.color}" if elapsed >= self.T_HOLD else f"bold {self.color}"
        if mode == "ascii":
            tl, tr, bl, br, hz, vt = "+", "+", "+", "+", "-", "|"
        else:
            tl, tr, bl, br, hz, vt = "╭", "╮", "╰", "╯", "─", "│"

        content_rows: List[Text] = []
        if elapsed >= self.T_GROW or inner_h >= (5 if compact else 10):
            icon_rows = self._render_icon_rows(elapsed, compact, mode)
            if not compact and inner_h >= len(icon_rows) + 3:
                content_rows.append(Text(" " * inner_w, no_wrap=True))
            for ir in icon_rows:
                content_rows.append(self._center_line(ir, inner_w))
            if not compact and inner_h >= len(content_rows) + 3:
                content_rows.append(Text(" " * inner_w, no_wrap=True))

            title_style = f"dim {self.color}" if elapsed >= self.T_HOLD else f"bold {self.color}"
            content_rows.append(
                self._center_line(Text(self.title, style=title_style, no_wrap=True), inner_w)
            )
            if self.subtitle and len(content_rows) < inner_h:
                sub_style = "dim grey70" if elapsed >= self.T_HOLD else "grey85"
                content_rows.append(
                    self._center_line(Text(self.subtitle, style=sub_style, no_wrap=True), inner_w)
                )

        # Pad or trim content_rows to match inner_h vertically centered
        if len(content_rows) > inner_h:
            content_rows = content_rows[:inner_h]
        else:
            extra = inner_h - len(content_rows)
            pad_top = extra // 2
            pad_bot = extra - pad_top
            blank = Text(" " * inner_w, no_wrap=True)
            content_rows = (
                [blank.copy() for _ in range(pad_top)]
                + content_rows
                + [blank.copy() for _ in range(pad_bot)]
            )

        horiz = hz * inner_w
        lines: List[Text] = [Text(f"{tl}{horiz}{tr}", style=border_style, no_wrap=True)]
        for r_text in content_rows:
            ln = Text(no_wrap=True)
            ln.append(vt, style=border_style)
            ln.append_text(r_text)
            ln.append(vt, style=border_style)
            lines.append(ln)
        lines.append(Text(f"{bl}{horiz}{br}", style=border_style, no_wrap=True))

        top = max(0, (height - cur_h) // 2)
        left = max(0, (width - cur_w) // 2)
        if self.icon == "cross" and self.T_GROW <= elapsed < 0.50:
            shake = 1 if int((elapsed - self.T_GROW) * 32) % 2 == 0 else -1
            left = max(0, min(width - cur_w, left + shake))

        return (top, left, lines)
