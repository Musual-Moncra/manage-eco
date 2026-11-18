import unittest
from datetime import date

from manage_eco.fmt import date_preview, money, money_preview, parse_date, parse_money, progress_bar


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

    def test_parse_money_arithmetic(self):
        self.assertEqual(parse_money("50k+20k"), 70_000)
        self.assertEqual(parse_money("50k+1.5tr"), 1_550_000)
        self.assertEqual(parse_money("3x150k"), 450_000)
        self.assertEqual(parse_money("3X150k"), 450_000)
        self.assertEqual(parse_money("3×150k"), 450_000)
        self.assertEqual(parse_money("3*150k"), 450_000)
        self.assertEqual(parse_money("150kx3"), 450_000)
        self.assertEqual(parse_money("1tr:4"), 250_000)
        self.assertEqual(parse_money("1tr/4"), 250_000)
        self.assertEqual(parse_money("1tr÷4"), 250_000)
        self.assertEqual(parse_money("(2tr-500k)*2"), 3_000_000)
        self.assertEqual(parse_money("1.250.000+200k"), 1_450_000)
        self.assertEqual(parse_money("-50k + 200k"), 150_000)
        self.assertEqual(parse_money("100k / 3"), 33_333)
        self.assertEqual(parse_money("200k / 3"), 66_667)

    def test_parse_money_invalid(self):
        for bad in (
            "",
            "   ",
            "0",
            "-100",
            "-5k",
            "0tr",
            "abc",
            "1.2",
            "12xyz",
            "50k+",
            "50k-50k",
            "50k-100k",
            "1tr:0",
            "1tr/(50k-50k)",
            "(50k+20k",
            "50k+20k)",
            "()",
            "50k 20k",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_money(bad)

    def test_parse_money_allow_negative(self):
        self.assertEqual(parse_money("-100k", allow_negative=True), -100_000)
        self.assertEqual(parse_money("-2tr", allow_negative=True), -2_000_000)
        self.assertEqual(parse_money("50k - 150k", allow_negative=True), -100_000)
        self.assertEqual(parse_money("0", allow_negative=True), 0)

    def test_money_preview(self):
        self.assertEqual(money_preview("50k+20k"), "= 70.000 ₫")
        self.assertEqual(money_preview("3x150k"), "= 450.000 ₫")
        self.assertEqual(money_preview("1tr:4"), "= 250.000 ₫")
        self.assertEqual(money_preview("(2tr-500k)*2"), "= 3.000.000 ₫")
        self.assertIsNone(money_preview("50k"))
        self.assertIsNone(money_preview("1.250.000"))
        self.assertIsNone(money_preview("(50k)"))
        self.assertIsNone(money_preview("50k+"))
        self.assertIsNone(money_preview("50k-100k"))
        self.assertIsNone(money_preview("1tr:0"))
        self.assertIsNone(money_preview(""))

    def test_parse_date(self):
        today = date(2026, 11, 6)  # Friday (Thứ 6)
        self.assertEqual(parse_date("2026-11-06", today), date(2026, 11, 6))
        self.assertEqual(parse_date("06/11/2026", today), date(2026, 11, 6))
        self.assertEqual(parse_date("today", today), today)
        self.assertEqual(parse_date("hom nay", today), today)
        self.assertEqual(parse_date("hôm nay", today), today)
        self.assertEqual(parse_date("+7", today), date(2026, 11, 13))
        self.assertEqual(parse_date("-2", today), date(2026, 11, 4))

        # Easier dates (v4)
        self.assertEqual(parse_date("hôm qua", today), date(2026, 11, 5))
        self.assertEqual(parse_date("hom qua", today), date(2026, 11, 5))
        self.assertEqual(parse_date("qua", today), date(2026, 11, 5))
        self.assertEqual(parse_date("mai", today), date(2026, 11, 7))
        self.assertEqual(parse_date("ngày mai", today), date(2026, 11, 7))
        self.assertEqual(parse_date("ngay mai", today), date(2026, 11, 7))
        self.assertEqual(parse_date("mốt", today), date(2026, 11, 8))
        self.assertEqual(parse_date("mot", today), date(2026, 11, 8))
        self.assertEqual(parse_date("ngày kia", today), date(2026, 11, 8))
        self.assertEqual(parse_date("15", today), date(2026, 11, 15))
        self.assertEqual(parse_date("31", today), date(2026, 11, 30))  # clamped to Nov 30
        self.assertEqual(parse_date("15/12", today), date(2026, 12, 15))
        self.assertEqual(parse_date("15-12", today), date(2026, 12, 15))
        self.assertEqual(parse_date("6/11/26", today), date(2026, 11, 6))
        self.assertEqual(parse_date("thứ 6", today), date(2026, 11, 13))  # today excluded
        self.assertEqual(parse_date("t6", today), date(2026, 11, 13))
        self.assertEqual(parse_date("thứ 7", today), date(2026, 11, 7))
        self.assertEqual(parse_date("t2", today), date(2026, 11, 9))
        self.assertEqual(parse_date("chủ nhật", today), date(2026, 11, 8))
        self.assertEqual(parse_date("chu nhat", today), date(2026, 11, 8))
        self.assertEqual(parse_date("cn", today), date(2026, 11, 8))
        self.assertEqual(parse_date("tuần sau", today), date(2026, 11, 13))
        self.assertEqual(parse_date("tháng sau", today), date(2026, 12, 6))
        self.assertEqual(parse_date("thang sau", date(2026, 1, 31)), date(2026, 2, 28))
        self.assertEqual(parse_date("đầu tháng sau", today), date(2026, 12, 1))
        self.assertEqual(parse_date("dau thang sau", today), date(2026, 12, 1))
        self.assertEqual(parse_date("cuối tháng", today), date(2026, 11, 30))
        self.assertEqual(parse_date("cuoi thang", today), date(2026, 11, 30))

    def test_parse_date_invalid(self):
        today = date(2026, 11, 6)
        for bad in ("", "not-a-date", "2026-13-40", "32/11/2026", "+abc", "0", "32", "t8", "thứ 1"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_date(bad, today)

    def test_date_preview(self):
        today = date(2026, 11, 6)
        self.assertEqual(date_preview("+7", today), "→ Thứ 6, 13/11/2026")
        self.assertEqual(date_preview("chủ nhật", today), "→ Chủ nhật, 08/11/2026")
        self.assertEqual(date_preview("mai", today), "→ Thứ 7, 07/11/2026")
        self.assertEqual(date_preview("15/11", today), "→ Chủ nhật, 15/11/2026")
        self.assertIsNone(date_preview("2026-11-06", today))
        self.assertIsNone(date_preview("", today))
        self.assertIsNone(date_preview("invalid", today))

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
