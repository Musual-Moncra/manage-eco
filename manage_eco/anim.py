"""Pure, deterministic terminal UI animations and ASCII-mode helpers (no I/O or time calls)."""
import math
import os
import random
import sys
from typing import List, Optional, Tuple

from rich.cells import cell_len
from rich.text import Text

UNICODE_KAOMOJI = {
    "success": "(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧",
    "error": "(╥﹏╥)",
    "info": "(•‿•)",
}
ASCII_KAOMOJI = {
    "success": ":)",
    "error": ":(",
    "info": ":)",
}

UNICODE_SPARKLES = ("✦", "✧", "⋆", "˚", "♡", "✿")
ASCII_SPARKLES = ("*", "+")

PASTEL_STYLES = {
    "success": ("bold #9ece6a", "#9ece6a", "dim #9ece6a"),
    "error": ("bold #f7768e", "#f7768e", "dim #f7768e"),
    "info": ("bold #bb9af7", "#7dcfff", "dim #7dcfff"),
}
SPARKLE_COLORS = ("#bb9af7", "#7dcfff", "#9ece6a", "#f7768e", "#e0af68")


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
    ) -> None:
        self.message = message
        self.kind = kind if kind in PASTEL_STYLES else "info"
        self.icon = icon
        self.duration = float(duration)

    def done(self, t: float) -> bool:
        """Return True when the toast animation has completed."""
        return float(t) >= self.duration

    def _kaomoji(self, use_ascii: bool) -> str:
        if self.icon is not None:
            if use_ascii:
                try:
                    self.icon.encode("ascii")
                    return self.icon
                except UnicodeEncodeError:
                    return ASCII_KAOMOJI.get(self.kind, ":)")
            return self.icon
        table = ASCII_KAOMOJI if use_ascii else UNICODE_KAOMOJI
        return table.get(self.kind, table["info"])

    def frame(self, t: float, width: int = 80) -> Optional[Text]:
        """Render the toast at elapsed time t (seconds) within width columns, or None when finished."""
        elapsed = float(t)
        if elapsed < 0.0 or self.done(elapsed) or width < 4:
            return None

        use_ascii = ascii_mode()
        kaomoji = self._kaomoji(use_ascii)
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

        if use_ascii:
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
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.seed = int(seed)
        self.count = int(count)
        self.duration = float(duration)

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

        use_ascii = ascii_mode()
        glyphs = ASCII_SPARKLES if use_ascii else UNICODE_SPARKLES
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
                ch = glyphs[g_idx % len(glyphs)]
                base_color = SPARKLE_COLORS[c_idx]
                style = f"dim {base_color}" if fading else f"bold {base_color}"
                out.append((row, col, ch, style))

        return out
