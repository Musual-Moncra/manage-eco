import unittest
from datetime import date

from manage_eco.fmt import money, parse_date, parse_money, progress_bar


class FmtTest(unittest.TestCase):
    def test_money(self):
        self.assertEqual(money(1250000), "1.250.000 ₫")
        self.assertEqual(money(0), "0 ₫")
        self.assertEqual(money(1250000, signed=True), "+1.250.000 ₫")
        self.assertEqual(money(-1250000, signed=True), "-1.250.000 ₫")
        self.assertEqual(money(-500000, signed=False), "-500.000 ₫")

    def test_parse_money_valid(self):
        self.assertEqual(parse_money("1250000"), 1_250_000)
        self.assertEqual(parse_money("1.250.000"), 1_250_000)
        self.assertEqual(parse_money("1,250,000"), 1_250_000)
        self.assertEqual(parse_money("1.5tr"), 1_500_000)
        self.assertEqual(parse_money("1.5m"), 1_500_000)
        self.assertEqual(parse_money("200k"), 200_000)
        self.assertEqual(parse_money(" 2,5tr "), 2_500_000)

    def test_parse_money_invalid(self):
        for bad in ("", "   ", "0", "-100", "-5k", "0tr", "abc", "1.2", "12xyz"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_money(bad)

    def test_parse_date(self):
        today = date(2026, 11, 6)
        self.assertEqual(parse_date("2026-11-06", today), date(2026, 11, 6))
        self.assertEqual(parse_date("06/11/2026", today), date(2026, 11, 6))
        self.assertEqual(parse_date("today", today), today)
        self.assertEqual(parse_date("hom nay", today), today)
        self.assertEqual(parse_date("hôm nay", today), today)
        self.assertEqual(parse_date("+7", today), date(2026, 11, 13))
        self.assertEqual(parse_date("-2", today), date(2026, 11, 4))

    def test_parse_date_invalid(self):
        today = date(2026, 11, 6)
        for bad in ("", "not-a-date", "2026-13-40", "32/11/2026", "+abc"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_date(bad, today)

    def test_progress_bar(self):
        bar_green = progress_bar(50.0, width=20)
        self.assertIn("[green]", bar_green)
        self.assertEqual(bar_green.count("█"), 10)
        self.assertEqual(bar_green.count("░"), 10)

        bar_yellow = progress_bar(80.0, width=20)
        self.assertIn("[yellow]", bar_yellow)
        self.assertIn("[yellow]", progress_bar(99.9, width=20))

        bar_red = progress_bar(100.0, width=20)
        self.assertIn("[red]", bar_red)
        self.assertEqual(bar_red.count("█"), 20)

        bar_over = progress_bar(150.0, width=10)
        self.assertIn("[red]", bar_over)
        self.assertEqual(bar_over.count("█"), 10)
        self.assertEqual(bar_over.count("░"), 0)


if __name__ == "__main__":
    unittest.main()
