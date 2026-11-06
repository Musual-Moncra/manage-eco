import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from rich.cells import cell_len

from manage_eco.chart import (
    DOWN_COLOR,
    FORECAST_DOWN_COLOR,
    FORECAST_UP_COLOR,
    UP_COLOR,
    candle_chart,
    line_chart,
    ohlc,
    short_money,
)


def _sample_history():
    start = date(2026, 10, 15)
    series = []
    bal = 5_000_000
    for i in range(20):
        d = start + timedelta(days=i)
        inc = 25_000_000 if i == 5 else 0
        exp = 1_300_000 if i == 5 else (3_000_000 if i in (2, 12, 15) else 200_000)
        bal += inc - exp
        series.append({"date": d.isoformat(), "balance": bal, "income": inc, "expense": exp})

    forecast = []
    fbal = bal
    for j in range(1, 10):
        d = start + timedelta(days=19 + j)
        fbal += 2_000_000 if j == 3 else (-4_000_000 if j == 6 else 0)
        forecast.append({"date": d.isoformat(), "balance": fbal})
    return series, forecast


class ChartTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"ECO_ASCII": "0", "TERM": "xterm-256color"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_sizes_at_40_80_160(self):
        series, forecast = _sample_history()
        for w in (40, 80, 100, 160):
            for h in (8, 16, 24):
                lc = line_chart(series, forecast, w, h, cursor=5)
                self.assertEqual(len(lc.lines), h, (w, h))
                for ln in lc.lines:
                    self.assertEqual(cell_len(ln.plain), w, (w, h, ln.plain))

                cc = candle_chart(series, w, h, bucket="week", cursor=1)
                self.assertEqual(len(cc.lines), h, (w, h))
                for ln in cc.lines:
                    self.assertEqual(cell_len(ln.plain), w, (w, h, ln.plain))

    def test_up_and_down_colors_and_forecast_dim(self):
        series = [
            {"date": "2026-11-01", "balance": 1_000_000, "income": 1_000_000, "expense": 0},
            {"date": "2026-11-02", "balance": 5_000_000, "income": 4_000_000, "expense": 0},
            {"date": "2026-11-03", "balance": 2_000_000, "income": 0, "expense": 3_000_000},
        ]
        forecast = [
            {"date": "2026-11-04", "balance": 4_000_000},
            {"date": "2026-11-05", "balance": 1_000_000},
        ]
        ch = line_chart(series, forecast, 80, 16)
        styles = {span.style for ln in ch.lines for span in ln.spans}
        self.assertIn(UP_COLOR, styles)
        self.assertIn(DOWN_COLOR, styles)
        self.assertIn(FORECAST_UP_COLOR, styles)
        self.assertIn(FORECAST_DOWN_COLOR, styles)
        full_text = "\n".join(ln.plain for ln in ch.lines)
        self.assertIn("Hôm nay", full_text)

    def test_zero_line_without_negative_dot_grid(self):
        series = [
            {"date": "2026-11-01", "balance": 2_000_000, "income": 2_000_000, "expense": 0},
            {"date": "2026-11-02", "balance": -2_000_000, "income": 0, "expense": 4_000_000},
        ]
        ch = line_chart(series, [], 80, 16)
        body = "\n".join(ln.plain for ln in ch.lines[1:-1])
        self.assertIn("┈", body)
        self.assertNotIn("·", body)

    def test_ohlc_math_and_wide_candles(self):
        series = [
            {"date": "2026-11-02", "balance": 10_000_000, "income": 10_000_000, "expense": 0},
            {"date": "2026-11-03", "balance": 15_000_000, "income": 5_000_000, "expense": 0},
            {"date": "2026-11-04", "balance": 8_000_000, "income": 0, "expense": 7_000_000},
            {"date": "2026-11-09", "balance": 6_000_000, "income": 0, "expense": 2_000_000},
            {"date": "2026-11-10", "balance": 12_000_000, "income": 6_000_000, "expense": 0},
        ]
        weekly = ohlc(series, bucket="week")
        self.assertEqual(len(weekly), 2)
        self.assertEqual(weekly[0]["open"], 0)
        self.assertEqual(weekly[0]["high"], 15_000_000)
        self.assertEqual(weekly[0]["low"], 0)
        self.assertEqual(weekly[0]["close"], 8_000_000)
        self.assertEqual(weekly[1]["open"], 8_000_000)
        self.assertEqual(weekly[1]["high"], 12_000_000)
        self.assertEqual(weekly[1]["low"], 6_000_000)
        self.assertEqual(weekly[1]["close"], 12_000_000)

        daily = ohlc(series, bucket="day")
        self.assertEqual(len(daily), 5)
        monthly = ohlc(series, bucket="month")
        self.assertEqual(len(monthly), 1)
        self.assertEqual(monthly[0]["close"], 12_000_000)

        cc = candle_chart(series, 80, 14, bucket="week")
        body_text = "\n".join(ln.plain for ln in cc.lines[1:-1])
        # Wide candle bodies (more than 1 col wide)
        self.assertIn("███", body_text)
        self.assertEqual(cc.index_at(0), 0)
        self.assertEqual(cc.index_at(cc.plot_box[2] - 1), 1)

    def test_index_at_mapping(self):
        series, forecast = _sample_history()
        total = len(series) + len(forecast)
        ch = line_chart(series, forecast, 80, 16)
        x0, _, x1, _ = ch.plot_box
        self.assertIsNone(ch.index_at(x0 - 1))
        self.assertIsNone(ch.index_at(x1))
        self.assertEqual(ch.index_at(x0), 0)
        self.assertEqual(ch.index_at(x1 - 1), total - 1)
        mid_idx = ch.index_at((x0 + x1) // 2)
        self.assertIsNotNone(mid_idx)
        self.assertGreater(mid_idx, 0)
        self.assertLess(mid_idx, total - 1)

    def test_cursor_tooltip(self):
        series = [
            {"date": "2026-11-05", "balance": 0, "income": 0, "expense": 0},
            {"date": "2026-11-06", "balance": 23_715_000, "income": 25_000_000, "expense": 1_300_000},
            {"date": "2026-11-07", "balance": 23_000_000, "income": 0, "expense": 715_000},
        ]
        ch = line_chart(series, [], 100, 18, cursor=1)
        rendered = "\n".join(ln.plain for ln in ch.lines)
        self.assertIn("Thứ 6, 06/11", rendered)
        self.assertIn("23.715.000 ₫", rendered)
        self.assertIn("+25tr / -1,3tr", rendered)

    def test_empty_series(self):
        for w, h in ((40, 10), (80, 16)):
            lc = line_chart([], [], w, h)
            self.assertEqual(len(lc.lines), h)
            self.assertTrue(all(cell_len(ln.plain) == w for ln in lc.lines))
            self.assertIsNone(lc.index_at(5))

            cc = candle_chart([], w, h)
            self.assertEqual(len(cc.lines), h)
            self.assertTrue(all(cell_len(ln.plain) == w for ln in cc.lines))
            self.assertIsNone(cc.index_at(5))

    def test_header_pct_shown_only_when_meaningful(self):
        self.assertEqual(short_money(23_715_000), "23,7tr")
        self.assertEqual(short_money(25_000_000, signed=True), "+25tr")
        self.assertEqual(short_money(-1_300_000, signed=True), "-1,3tr")

        # First value == 0 -> omit percentage
        s_zero = [
            {"date": "2026-11-01", "balance": 0, "income": 0, "expense": 0},
            {"date": "2026-11-02", "balance": 23_700_000, "income": 23_700_000, "expense": 0},
        ]
        hdr_zero = line_chart(s_zero, [], 80, 12).lines[0].plain
        self.assertIn("▲ +23,7tr", hdr_zero)
        self.assertNotIn("%", hdr_zero)

        # Sign flip -> omit percentage
        s_flip = [
            {"date": "2026-11-01", "balance": 5_000_000, "income": 5_000_000, "expense": 0},
            {"date": "2026-11-02", "balance": -18_600_000, "income": 0, "expense": 23_600_000},
        ]
        hdr_flip = line_chart(s_flip, [], 80, 12).lines[0].plain
        self.assertIn("▼ -23,6tr", hdr_flip)
        self.assertNotIn("%", hdr_flip)

        # Same sign and |first| >= 1% of range -> show percentage
        s_normal = [
            {"date": "2026-11-01", "balance": 10_000_000, "income": 10_000_000, "expense": 0},
            {"date": "2026-11-02", "balance": 15_000_000, "income": 5_000_000, "expense": 0},
        ]
        hdr_normal = line_chart(s_normal, [], 80, 12).lines[0].plain
        self.assertIn("▲ +5tr (+50.0%)", hdr_normal)


if __name__ == "__main__":
    unittest.main()
