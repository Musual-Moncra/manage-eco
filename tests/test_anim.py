import os
import unittest
from unittest.mock import patch

from rich.cells import cell_len

from manage_eco.anim import (
    ICON_BITMAPS,
    ICON_BITMAPS_8,
    ICON_STROKES,
    ICON_STROKES_8,
    SYMBOL_SPARKLES,
    Glow,
    PixelPopup,
    Press,
    Ripple,
    Sparkle,
    Toast,
    ascii_mode,
    bar_fill,
    count_up,
    ease_out_back,
    ease_out_cubic,
    slide,
)


class AnimTest(unittest.TestCase):
    def test_easing_endpoints_and_clamping(self):
        self.assertEqual(ease_out_cubic(-1.0), 0.0)
        self.assertEqual(ease_out_cubic(0.0), 0.0)
        self.assertEqual(ease_out_cubic(1.0), 1.0)
        self.assertEqual(ease_out_cubic(2.0), 1.0)
        self.assertGreater(ease_out_cubic(0.5), 0.5)

        self.assertEqual(ease_out_back(-0.5), 0.0)
        self.assertEqual(ease_out_back(0.0), 0.0)
        self.assertEqual(ease_out_back(1.0), 1.0)
        self.assertEqual(ease_out_back(1.5), 1.0)
        self.assertGreater(ease_out_back(0.7), 1.0)

    def test_count_up_and_bar_fill(self):
        self.assertEqual(count_up(100, 1000, 0.0, duration=0.6), 100)
        self.assertEqual(count_up(100, 1000, 0.6, duration=0.6), 1000)
        self.assertEqual(count_up(100, 1000, 1.0, duration=0.6), 1000)
        mid = count_up(100, 1000, 0.3, duration=0.6)
        self.assertGreater(mid, 550)
        self.assertLess(mid, 1000)

        self.assertEqual(bar_fill(80.0, 0.0, duration=0.5), 0.0)
        self.assertAlmostEqual(bar_fill(80.0, 0.5, duration=0.5), 80.0)
        self.assertAlmostEqual(bar_fill(80.0, 1.0, duration=0.5), 80.0)
        self.assertGreater(bar_fill(80.0, 0.25, duration=0.5), 40.0)

    def test_toast_lifecycle_and_width(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            t = Toast("Đã lưu dòng tiền ✓ Tiền nhà", kind="success")
            self.assertEqual(t.glyphs, "symbol")
            self.assertFalse(t.done(0.0))
            self.assertFalse(t.done(1.0))
            self.assertTrue(t.done(t.duration))
            self.assertTrue(t.done(3.0))

            f_pop = t.frame(0.1, width=60)
            self.assertIsNotNone(f_pop)
            self.assertIn("Đã lưu dòng tiền", f_pop.plain)
            self.assertIn(r"\(^o^)/", f_pop.plain)
            for ln in f_pop.split("\n"):
                self.assertLessEqual(ln.cell_len, 60)

            f_hold = t.frame(1.0, width=80)
            self.assertIsNotNone(f_hold)

            f_fade = t.frame(2.0, width=80)
            self.assertIsNotNone(f_fade)

            self.assertIsNone(t.frame(t.duration, width=80))
            self.assertIsNone(t.frame(2.5, width=80))

    def test_symbol_mode_no_high_unicode_or_halfwidth_kana(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            expected_kaomoji = {
                "success": r"\(^o^)/",
                "error": "(T_T)",
                "info": "(^_^)",
            }
            for kind, kao in expected_kaomoji.items():
                toast = Toast("Thông báo", kind=kind, glyphs="symbol")
                frame = toast.frame(0.5, width=80)
                self.assertIsNotNone(frame)
                self.assertIn(kao, frame.plain)
                for ch in frame.plain:
                    cp = ord(ch)
                    self.assertLess(cp, 0x1F000, f"Codepoint >= U+1F000 in {frame.plain!r}")
                    self.assertFalse(0xFF61 <= cp <= 0xFF9F, f"Half-width kana in {frame.plain!r}")

            for seed in range(10):
                sp = Sparkle(width=80, height=24, seed=seed, count=20, glyphs="symbol")
                for _, _, ch, _ in sp.cells(0.4):
                    self.assertIn(ch, SYMBOL_SPARKLES)
                    cp = ord(ch)
                    self.assertLess(cp, 0x1F000)
                    self.assertFalse(0xFF61 <= cp <= 0xFF9F)

    def test_emoji_and_ascii_glyph_modes(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            t_emoji = Toast("Yay", kind="success", glyphs="emoji")
            self.assertIn("(ﾉ◕ヮ◕)ﾉ*:･ﾟ✧", t_emoji.frame(0.5, width=60).plain)

            t_ascii = Toast("Yay", kind="success", glyphs="ascii")
            f_ascii = t_ascii.frame(0.5, width=60).plain
            self.assertIn(":)", f_ascii)
            f_ascii.encode("ascii")

            sp_ascii = Sparkle(width=60, height=20, seed=3, glyphs="ascii")
            for _, _, ch, _ in sp_ascii.cells(0.4):
                self.assertIn(ch, ("*", "+", "."))

    def test_sparkle_determinism_and_bounds(self):
        s1 = Sparkle(width=80, height=24, seed=42, count=14, duration=0.9)
        s2 = Sparkle(width=80, height=24, seed=42, count=14, duration=0.9)
        s3 = Sparkle(width=80, height=24, seed=99, count=14, duration=0.9)

        c1 = s1.cells(0.3)
        c2 = s2.cells(0.3)
        c3 = s3.cells(0.3)
        self.assertEqual(c1, c2)
        self.assertNotEqual(c1, c3)
        self.assertGreater(len(c1), 0)

        for t in (0.0, 0.2, 0.5, 0.85):
            for row, col, ch, style in s1.cells(t):
                self.assertGreaterEqual(row, 0)
                self.assertLess(row, 24)
                self.assertGreaterEqual(col, 0)
                self.assertLess(col, 80)
                self.assertEqual(cell_len(ch), 1)
                self.assertTrue(style)

        self.assertTrue(s1.done(0.9))
        self.assertEqual(s1.cells(0.9), [])
        self.assertEqual(s1.cells(1.5), [])

    def test_ascii_fallbacks(self):
        with patch.dict(os.environ, {"ECO_ASCII": "1"}, clear=False):
            self.assertTrue(ascii_mode())
            for kind, expected in (("success", ":)"), ("error", ":("), ("info", ":)")):
                toast = Toast("Test message", kind=kind, glyphs="emoji")
                frame = toast.frame(0.5, width=50)
                self.assertIsNotNone(frame)
                self.assertIn(expected, frame.plain)
                frame.plain.encode("ascii")

            sp = Sparkle(width=60, height=20, seed=7, glyphs="symbol")
            for _, _, ch, _ in sp.cells(0.4):
                self.assertIn(ch, ("*", "+", "."))
                ch.encode("ascii")

        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "dumb"}, clear=False):
            self.assertTrue(ascii_mode())

        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            with patch("manage_eco.anim.sys.stdout") as mock_stdout:
                mock_stdout.encoding = "ascii"
                self.assertTrue(ascii_mode())

    def test_pixel_popup_bitmaps_and_strokes(self):
        expected_icons = ("check", "coin", "pencil", "trash", "cross")
        for name in expected_icons:
            bmp = ICON_BITMAPS[name]
            self.assertEqual(len(bmp), 16, name)
            for row_s in bmp:
                self.assertEqual(len(row_s), 16, name)
            lit = {(r, c) for r, row_s in enumerate(bmp) for c, ch in enumerate(row_s) if ch != " "}
            stroke = ICON_STROKES[name]
            self.assertGreater(len(lit), 0, name)
            self.assertEqual(len(stroke), len(lit), name)
            self.assertEqual(set(stroke), lit, name)

            bmp8 = ICON_BITMAPS_8[name]
            self.assertEqual(len(bmp8), 8, name)
            for row_s in bmp8:
                self.assertEqual(len(row_s), 8, name)
            lit8 = {(r, c) for r, row_s in enumerate(bmp8) for c, ch in enumerate(row_s) if ch != " "}
            stroke8 = ICON_STROKES_8[name]
            self.assertEqual(len(stroke8), len(lit8), name)
            self.assertEqual(set(stroke8), lit8, name)

    def test_pixel_popup_timeline_and_centering(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            popup = PixelPopup("check", "Đã lưu!", "Tiền nhà -5.000.000 ₫", glyphs="symbol", seed=42)
            for t in (0.0, 0.4, 1.0, 1.5):
                res = popup.frame(t, 80, 24)
                self.assertIsNotNone(res, f"Expected frame at t={t}")
                top, left, lines = res
                box_h = len(lines)
                box_w = lines[0].cell_len
                self.assertEqual(top, (24 - box_h) // 2)
                self.assertEqual(left, (80 - box_w) // 2)
                for ln in lines:
                    self.assertEqual(ln.cell_len, box_w)
                    for ch in ln.plain:
                        cp = ord(ch)
                        self.assertLess(cp, 0x1F000)
                        self.assertFalse(0xFF61 <= cp <= 0xFF9F)

            # Growing box at t=0 is smaller than full size at t=1.0
            _, _, lines_0 = popup.frame(0.0, 80, 24)
            _, _, lines_1 = popup.frame(1.0, 80, 24)
            self.assertLess(len(lines_0), len(lines_1))
            self.assertLess(lines_0[0].cell_len, lines_1[0].cell_len)

            # Finished at t=1.7 -> None
            self.assertTrue(popup.done(1.7))
            self.assertIsNone(popup.frame(1.7, 80, 24))

            # Cross shake between 0.18 and 0.5
            cross = PixelPopup("cross", "Lỗi!", "Không hợp lệ")
            _, left_a, _ = cross.frame(0.20, 80, 24)
            _, left_b, _ = cross.frame(0.24, 80, 24)
            self.assertNotEqual(left_a, left_b)

    def test_pixel_popup_compact_and_too_small(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            popup = PixelPopup("coin", "Đã thanh toán!", "Điện nước")
            # Compact when width < 44 or height < 16
            self.assertTrue(popup.is_compact(40, 20))
            self.assertTrue(popup.is_compact(80, 12))
            res_c = popup.frame(0.8, 40, 12)
            self.assertIsNotNone(res_c)
            top, left, lines = res_c
            self.assertLessEqual(len(lines), 8)
            self.assertGreaterEqual(top, 0)
            self.assertGreaterEqual(left, 0)
            self.assertLessEqual(left + lines[0].cell_len, 40)
            self.assertLessEqual(top + len(lines), 12)

            # Too small even for compact -> None
            self.assertIsNone(popup.frame(0.8, 12, 6))
            self.assertEqual(popup.size(12, 6), (0, 0))

    def test_v7_ripple_press_slide_glow(self):
        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            rip = Ripple(10, 20, glyphs="symbol", duration=0.35)
            self.assertFalse(rip.done(0.1))
            self.assertTrue(rip.done(0.35))
            c0 = rip.cells(0.0)
            self.assertEqual(len(c0), 1)
            self.assertEqual((c0[0][0], c0[0][1]), (10, 20))
            c_mid = rip.cells(0.2)
            self.assertGreater(len(c_mid), 4)
            for _, _, ch, _ in c_mid:
                self.assertIn(ch, ("·", "∘", "○", "◌"))
            self.assertEqual(rip.cells(0.35), [])

            rip_ascii = Ripple(5, 5, glyphs="ascii", duration=0.35)
            for _, _, ch, _ in rip_ascii.cells(0.2):
                self.assertIn(ch, (".", "o", "O"))

            pr = Press(duration=0.12)
            self.assertTrue(pr.active(0.0))
            self.assertTrue(pr.active(0.06))
            self.assertFalse(pr.active(0.12))
            self.assertTrue(pr.done(0.12))

            self.assertEqual(slide(10, 30, 0.0, duration=0.18), 10)
            self.assertEqual(slide(10, 30, 0.18, duration=0.18), 30)
            self.assertGreater(slide(10, 30, 0.09, duration=0.18), 20)

            glow = Glow(width=80, duration=0.4)
            self.assertFalse(glow.done(0.2))
            self.assertTrue(glow.done(0.4))
            self.assertEqual(glow.style_at(40, 0.4), "")
            lit_cols = [c for c in range(80) if glow.style_at(c, 0.15)]
            self.assertGreater(len(lit_cols), 0)
            self.assertLess(len(lit_cols), 80)


if __name__ == "__main__":
    unittest.main()
