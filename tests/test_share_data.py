import unittest
from datetime import date
from manage_eco.db import Store
from manage_eco.models import Account, Budget, Goal, Plan, Transaction
from manage_eco.share_data import get_shared_snapshot, ALL_SHAREABLE_TABS

class ShareDataTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.store.add_transaction(Transaction(self.today, 100000, "expense", "food", "lunch"))
        self.store.add_account(Account("Techcombank", 5000000, True))
        self.store.set_budget(Budget("food", 3000000))
        self.store.add_goal(Goal("Du lich", 10000000, date(2027, 6, 1), 2000000))
        self.store.add_plan(Plan("Tien phong", 3500000, "expense", date(2026, 11, 15), "housing", "monthly"))

    def test_filter_only_allowed_tabs(self):
        allowed = {"overview", "budgets"}
        snap = get_shared_snapshot(self.store, self.today, allowed, active_tab="overview", sync_mode="free")
        self.assertIn("overview", snap["tabs"])
        self.assertIn("budgets", snap["tabs"])
        self.assertNotIn("accounts", snap["tabs"])
        self.assertNotIn("transactions", snap["tabs"])
        self.assertNotIn("goals", snap["tabs"])
        self.assertNotIn("cashflow", snap["tabs"])
        self.assertEqual(snap["sync_mode"], "free")
        self.assertEqual(snap["allowed_tab_keys"], sorted(list(allowed)))

    def test_overview_sanitizes_unshared_subtabs(self):
        # Even if overview is allowed, unshared sub-data (accounts, cashflow, budgets, goals) must not leak
        snap = get_shared_snapshot(self.store, self.today, allowed_tabs={"overview"})
        overview = snap["tabs"]["overview"]
        self.assertNotIn("accounts", overview)
        self.assertNotIn("upcoming", overview)
        self.assertNotIn("overdue", overview)
        self.assertNotIn("budgets", overview)
        self.assertNotIn("goals", overview)

    def test_all_tabs_data(self):
        snap = get_shared_snapshot(self.store, self.today, set(ALL_SHAREABLE_TABS.keys()), active_tab="goals", sync_mode="follow")
        tabs = snap["tabs"]
        self.assertIn("overview", tabs)
        self.assertIn("accounts", tabs)
        self.assertIn("transactions", tabs)
        self.assertIn("cashflow", tabs)
        self.assertIn("budgets", tabs)
        self.assertIn("goals", tabs)
        self.assertIn("chart", tabs)
        self.assertEqual(snap["active_tab"], "goals")
        self.assertEqual(snap["sync_mode"], "follow")
        # Check specific values
        self.assertEqual(tabs["budgets"]["budgets"][0]["category"], "food")
        self.assertEqual(tabs["goals"]["goals"][0]["name"], "Du lich")
        self.assertEqual(tabs["cashflow"]["plans"][0]["name"], "Tien phong")
