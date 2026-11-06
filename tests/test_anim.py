import os
import unittest
from unittest.mock import patch

from rich.cells import cell_len

from manage_eco.anim import (
    Sparkle,
    Toast,
    ascii_mode,
    bar_fill,
    count_up,
    ease_out_back,
    ease_out_cubic,
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
        # ease_out_back overshoots 1.0 slightly in the upper-middle range
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
            self.assertFalse(t.done(0.0))
            self.assertFalse(t.done(1.0))
            self.assertTrue(t.done(t.duration))
            self.assertTrue(t.done(3.0))

            f_pop = t.frame(0.1, width=60)
            self.assertIsNotNone(f_pop)
            self.assertIn("Đã lưu dòng tiền", f_pop.plain)
            for ln in f_pop.split("\n"):
                self.assertLessEqual(ln.cell_len, 60)

            f_hold = t.frame(1.0, width=80)
            self.assertIsNotNone(f_hold)

            f_fade = t.frame(2.0, width=80)
            self.assertIsNotNone(f_fade)

            self.assertIsNone(t.frame(t.duration, width=80))
            self.assertIsNone(t.frame(2.5, width=80))

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
                toast = Toast("Test message", kind=kind)
                frame = toast.frame(0.5, width=50)
                self.assertIsNotNone(frame)
                self.assertIn(expected, frame.plain)
                # Ensure purely ASCII characters when message is ASCII
                frame.plain.encode("ascii")

            sp = Sparkle(width=60, height=20, seed=7)
            for _, _, ch, _ in sp.cells(0.4):
                self.assertIn(ch, ("*", "+"))
                ch.encode("ascii")

        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "dumb"}, clear=False):
            self.assertTrue(ascii_mode())

        with patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False):
            with patch("manage_eco.anim.sys.stdout") as mock_stdout:
                mock_stdout.encoding = "ascii"
                self.assertTrue(ascii_mode())


if __name__ == "__main__":
    unittest.main()
