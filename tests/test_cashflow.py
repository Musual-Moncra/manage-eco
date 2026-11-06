import unittest
from datetime import date

from manage_eco import cashflow
from manage_eco.db import Store
from manage_eco.models import (
    CANCELLED, DAILY, EXPENSE, INCOME, MONTHLY, ONCE, WEEKLY, Plan, Transaction,
)


class CashflowTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def add(self, d, amount, kind, category):
        self.store.add_transaction(Transaction(d, amount, kind, category))

    def test_month_range(self):
        self.assertEqual(cashflow.month_range(2026, 2), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(cashflow.month_range(2024, 2), (date(2024, 2, 1), date(2024, 2, 29)))
        self.assertEqual(cashflow.month_range(2026, 12), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_summary_and_by_category(self):
        self.add(date(2026, 11, 1), 10_000_000, INCOME, "luong")
        self.add(date(2026, 11, 2), 3_000_000, EXPENSE, "nha")
        self.add(date(2026, 11, 3), 500_000, EXPENSE, "an")
        self.add(date(2026, 11, 4), 700_000, EXPENSE, "an")
        self.add(date(2026, 10, 31), 999, EXPENSE, "an")  # outside range
        start, end = cashflow.month_range(2026, 11)
        self.assertEqual(cashflow.summary(self.store, start, end),
                         {"income": 10_000_000, "expense": 4_200_000, "net": 5_800_000})
        self.assertEqual(cashflow.by_category(self.store, start, end),
                         [("nha", 3_000_000), ("an", 1_200_000)])
        self.assertEqual(cashflow.by_category(self.store, start, end, INCOME), [("luong", 10_000_000)])

    def test_summary_empty(self):
        self.assertEqual(cashflow.summary(self.store, date(2026, 1, 1), date(2026, 1, 31)),
                         {"income": 0, "expense": 0, "net": 0})

    def test_expand_once(self):
        p = Plan("laptop", 20_000_000, EXPENSE, date(2026, 12, 5), "do")
        self.assertEqual(cashflow.expand_plan(p, date(2026, 12, 1), date(2026, 12, 31)), [date(2026, 12, 5)])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 12, 6), date(2026, 12, 31)), [])

    def test_expand_weekly(self):
        p = Plan("cho", 300_000, EXPENSE, date(2026, 11, 2), "an", WEEKLY)
        self.assertEqual(cashflow.expand_plan(p, date(2026, 11, 10), date(2026, 11, 30)),
                         [date(2026, 11, 16), date(2026, 11, 23), date(2026, 11, 30)])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 10, 1), date(2026, 11, 9)),
                         [date(2026, 11, 2), date(2026, 11, 9)])

    def test_expand_daily(self):
        p = Plan("cafe", 20_000, EXPENSE, date(2026, 11, 2), "an", DAILY)
        self.assertEqual(cashflow.expand_plan(p, date(2026, 11, 1), date(2026, 11, 5)),
                         [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4), date(2026, 11, 5)])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 11, 10), date(2026, 11, 12)),
                         [date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 10, 1), date(2026, 11, 1)), [])

    def test_expand_monthly_anchor_day(self):
        p = Plan("thue nha", 5_000_000, EXPENSE, date(2026, 2, 28), "nha", MONTHLY, day=31)
        self.assertEqual(cashflow.expand_plan(p, date(2026, 2, 1), date(2026, 5, 31)),
                         [date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30),
                          date(2026, 5, 31)])
        q = Plan("bao hiem", 1_000_000, EXPENSE, date(2026, 1, 15), "bao", MONTHLY, day=31)
        self.assertEqual(cashflow.expand_plan(q, date(2026, 1, 1), date(2026, 4, 30)),
                         [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
                          date(2026, 4, 30)])

    def test_expand_monthly_clamps(self):
        p = Plan("thue nha", 5_000_000, EXPENSE, date(2026, 1, 31), "nha", MONTHLY)
        self.assertEqual(cashflow.expand_plan(p, date(2026, 1, 1), date(2026, 5, 31)),
                         [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
                          date(2026, 4, 30), date(2026, 5, 31)])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 4, 1), date(2026, 4, 29)), [])
        self.assertEqual(cashflow.expand_plan(p, date(2026, 12, 1), date(2027, 1, 31)),
                         [date(2026, 12, 31), date(2027, 1, 31)])

    def test_expand_not_pending(self):
        p = Plan("x", 1, EXPENSE, date(2026, 11, 10), "c", ONCE, CANCELLED)
        self.assertEqual(cashflow.expand_plan(p, date(2026, 11, 1), date(2026, 11, 30)), [])

    def test_forecast_and_lowest_point(self):
        today = date(2026, 11, 6)
        self.add(date(2026, 11, 1), 2_000_000, INCOME, "luong")
        self.add(date(2026, 11, 7), 9_999, EXPENSE, "future")  # after today, excluded from balance
        self.store.add_plan(Plan("thue nha", 3_000_000, EXPENSE, date(2026, 11, 10), "nha", MONTHLY))
        self.store.add_plan(Plan("luong", 4_000_000, INCOME, date(2026, 11, 25), "luong", MONTHLY))
        self.store.add_plan(Plan("hom nay", 1, EXPENSE, today, "x"))  # today excluded
        cancelled = Plan("huy", 1, EXPENSE, date(2026, 11, 8), "x", ONCE, CANCELLED)
        self.store.add_plan(cancelled)
        rows = cashflow.forecast(self.store, today, 34)  # through 2026-12-10
        self.assertEqual(rows, [
            (date(2026, 11, 10), "thue nha", -3_000_000, -1_000_000),
            (date(2026, 11, 25), "luong", 4_000_000, 3_000_000),
            (date(2026, 12, 10), "thue nha", -3_000_000, 0),
        ])
        self.assertEqual(cashflow.lowest_point(rows), (date(2026, 11, 10), -1_000_000))

    def test_lowest_point_empty(self):
        self.assertIsNone(cashflow.lowest_point([]))
        self.assertEqual(cashflow.forecast(self.store, date(2026, 11, 6), 30), [])


if __name__ == "__main__":
    unittest.main()
