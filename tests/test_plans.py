import unittest
from datetime import date

from manage_eco.db import Store
from manage_eco.models import (
    CANCELLED,
    DONE,
    EXPENSE,
    INCOME,
    MONTHLY,
    ONCE,
    PENDING,
    WEEKLY,
    Budget,
    Plan,
    Transaction,
)
from manage_eco.plans import budget_status, cancel_plan, complete_plan, overdue, savings_goal


def make_plan(**kwargs):
    defaults = dict(
        name="rent",
        amount=5_000_000,
        kind=EXPENSE,
        due_date=date(2026, 1, 31),
        category="housing",
        recurrence=ONCE,
    )
    defaults.update(kwargs)
    return Plan(**defaults)


class CompletePlanTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_once_records_transaction_and_marks_done(self):
        plan = make_plan(name="laptop", amount=20_000_000, category="tech")
        pid = self.store.add_plan(plan)

        txn = complete_plan(self.store, pid, date(2026, 1, 15))

        self.assertIsInstance(txn, Transaction)
        self.assertEqual(txn.date, date(2026, 1, 15))
        self.assertEqual(txn.amount, 20_000_000)
        self.assertEqual(txn.kind, EXPENSE)
        self.assertEqual(txn.category, "tech")
        self.assertEqual(txn.note, "plan:laptop")
        self.assertIsNotNone(txn.id)

        stored = self.store.get_plan(pid)
        self.assertEqual(stored.status, DONE)
        self.assertEqual(self.store.list_plans(PENDING), [])

    def test_weekly_advances_seven_days_and_stays_pending(self):
        plan = make_plan(due_date=date(2026, 3, 1), recurrence=WEEKLY)
        pid = self.store.add_plan(plan)

        complete_plan(self.store, pid, date(2026, 3, 1))

        stored = self.store.get_plan(pid)
        self.assertEqual(stored.due_date, date(2026, 3, 8))
        self.assertEqual(stored.status, PENDING)

    def test_monthly_clamps_to_month_end(self):
        plan = make_plan(due_date=date(2026, 1, 31), recurrence=MONTHLY)
        pid = self.store.add_plan(plan)

        complete_plan(self.store, pid, date(2026, 1, 31))

        stored = self.store.get_plan(pid)
        self.assertEqual(stored.due_date, date(2026, 2, 28))
        self.assertEqual(stored.status, PENDING)

    def test_monthly_wraps_year(self):
        plan = make_plan(due_date=date(2026, 12, 15), recurrence=MONTHLY)
        pid = self.store.add_plan(plan)

        complete_plan(self.store, pid, date(2026, 12, 15))

        self.assertEqual(self.store.get_plan(pid).due_date, date(2027, 1, 15))

    def test_income_plan_keeps_kind(self):
        plan = make_plan(name="salary", amount=10_000_000, kind=INCOME, category="job")
        pid = self.store.add_plan(plan)

        txn = complete_plan(self.store, pid, date(2026, 1, 5))

        self.assertEqual(txn.kind, INCOME)
        self.assertEqual(txn.signed, 10_000_000)

    def test_missing_plan_raises(self):
        with self.assertRaises(ValueError):
            complete_plan(self.store, 999, date(2026, 1, 1))

    def test_non_pending_plan_raises(self):
        pid = self.store.add_plan(make_plan())
        complete_plan(self.store, pid, date(2026, 1, 31))

        with self.assertRaises(ValueError):
            complete_plan(self.store, pid, date(2026, 2, 1))


class CancelPlanTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_cancel_marks_cancelled(self):
        pid = self.store.add_plan(make_plan())

        cancel_plan(self.store, pid)

        self.assertEqual(self.store.get_plan(pid).status, CANCELLED)
        self.assertEqual(self.store.list_plans(PENDING), [])

    def test_cancel_missing_raises(self):
        with self.assertRaises(ValueError):
            cancel_plan(self.store, 42)


class OverdueTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_only_pending_before_today(self):
        past = self.store.add_plan(make_plan(name="past", due_date=date(2026, 1, 1)))
        self.store.add_plan(make_plan(name="today", due_date=date(2026, 1, 10)))
        self.store.add_plan(make_plan(name="future", due_date=date(2026, 1, 20)))
        done = self.store.add_plan(make_plan(name="done", due_date=date(2026, 1, 2)))
        self.store.update_plan(Plan("done", 1, EXPENSE, date(2026, 1, 2), "x", ONCE, DONE, done))

        result = overdue(self.store, date(2026, 1, 10))

        self.assertEqual([p.name for p in result], ["past"])

    def test_empty_when_none(self):
        self.assertEqual(overdue(self.store, date(2026, 1, 10)), [])


class BudgetStatusTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.store.set_budget(Budget("food", 2_000_000))
        self.store.set_budget(Budget("transport", 1_000_000))

    def test_spent_remaining_and_pct(self):
        self.store.add_transaction(Transaction(date(2026, 1, 3), 500_000, EXPENSE, "food"))
        self.store.add_transaction(Transaction(date(2026, 1, 4), 700_000, EXPENSE, "food"))
        self.store.add_transaction(Transaction(date(2026, 1, 5), 250_000, EXPENSE, "transport"))

        rows = {r["category"]: r for r in budget_status(self.store, 2026, 1)}

        self.assertEqual(rows["food"]["limit"], 2_000_000)
        self.assertEqual(rows["food"]["spent"], 1_200_000)
        self.assertEqual(rows["food"]["remaining"], 800_000)
        self.assertAlmostEqual(rows["food"]["pct"], 60.0)
        self.assertEqual(rows["transport"]["spent"], 250_000)
        self.assertAlmostEqual(rows["transport"]["pct"], 25.0)

    def test_ignores_income_other_months_and_other_categories(self):
        self.store.add_transaction(Transaction(date(2026, 1, 3), 500_000, INCOME, "food"))
        self.store.add_transaction(Transaction(date(2026, 2, 3), 500_000, EXPENSE, "food"))
        self.store.add_transaction(Transaction(date(2026, 1, 3), 500_000, EXPENSE, "other"))

        rows = {r["category"]: r for r in budget_status(self.store, 2026, 1)}

        self.assertEqual(rows["food"]["spent"], 0)
        self.assertAlmostEqual(rows["food"]["pct"], 0.0)

    def test_over_budget_pct_exceeds_100(self):
        self.store.add_transaction(Transaction(date(2026, 1, 3), 2_500_000, EXPENSE, "food"))

        row = budget_status(self.store, 2026, 1)[0]

        self.assertEqual(row["remaining"], -500_000)
        self.assertAlmostEqual(row["pct"], 125.0)

    def test_month_bounds_include_last_day(self):
        self.store.add_transaction(Transaction(date(2026, 1, 31), 100_000, EXPENSE, "food"))

        self.assertEqual(budget_status(self.store, 2026, 1)[0]["spent"], 100_000)


class SavingsGoalTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)

    def test_needed_and_per_month(self):
        self.store.add_transaction(Transaction(date(2026, 1, 1), 2_000_000, INCOME, "job"))

        result = savings_goal(self.store, 10_000_000, date(2026, 4, 1), date(2026, 1, 1))

        self.assertEqual(result["needed"], 8_000_000)
        self.assertEqual(result["months_left"], 3)
        self.assertEqual(result["per_month"], 2_666_667)

    def test_zero_needed_when_target_reached(self):
        self.store.add_transaction(Transaction(date(2026, 1, 1), 5_000_000, INCOME, "job"))

        result = savings_goal(self.store, 3_000_000, date(2026, 6, 1), date(2026, 1, 1))

        self.assertEqual(result["needed"], 0)
        self.assertEqual(result["per_month"], 0)

    def test_months_left_at_least_one(self):
        result = savings_goal(self.store, 1_000_000, date(2026, 1, 1), date(2026, 1, 15))

        self.assertEqual(result["months_left"], 1)
        self.assertEqual(result["per_month"], 1_000_000)

    def test_counts_months_across_years(self):
        result = savings_goal(self.store, 12_000_000, date(2027, 1, 1), date(2026, 10, 1))

        self.assertEqual(result["months_left"], 3)
        self.assertEqual(result["per_month"], 4_000_000)

    def test_balance_as_of_today_excludes_future(self):
        self.store.add_transaction(Transaction(date(2026, 1, 1), 1_000_000, INCOME, "job"))
        self.store.add_transaction(Transaction(date(2026, 2, 1), 1_000_000, INCOME, "job"))

        result = savings_goal(self.store, 5_000_000, date(2026, 6, 1), date(2026, 1, 15))

        self.assertEqual(result["needed"], 4_000_000)


if __name__ == "__main__":
    unittest.main()
