"""Integration tests for Accounts and Wallets tab in TUI."""
import unittest
from datetime import date
from unittest import mock

from manage_eco import tui


TODAY = date(2026, 11, 7)


class AccountsFakeApi:
    def __init__(self):
        self.calls = []
        self.accounts = [
            {"id": 1, "name": "Tiền mặt", "initial_balance": 1_000_000, "balance": 1_000_000, "is_default": True, "pct": 20.0},
            {"id": 2, "name": "Techcombank", "initial_balance": 4_000_000, "balance": 4_000_000, "is_default": False, "pct": 80.0},
        ]
        self.transfers = [
            {"id": 1, "date": "2026-11-07", "amount": 500_000, "from_account_id": 2, "from_account": "Techcombank",
             "to_account_id": 1, "to_account": "Tiền mặt", "note": "Rút ATM"}
        ]
        self.plans = [
            {"id": 1, "name": "Tiền nhà", "amount": 2_000_000, "kind": "expense",
             "due_date": "2026-11-07", "category": "nhà", "recurrence": "once", "status": "pending"}
        ]

    def __call__(self, cmd, params):
        self.calls.append((cmd, params))
        if cmd == "dash":
            return {"balance": 5_000_000, "accounts": self.accounts, "month": {}, "overdue": [], "budgets": [], "upcoming": []}
        if cmd == "account list":
            return {"accounts": self.accounts, "total_balance": 5_000_000}
        if cmd == "account transfers":
            return {"transfers": self.transfers}
        if cmd == "account add":
            new_acc = {"id": 3, "name": params["name"], "initial_balance": params.get("initial_balance", 0),
                       "balance": params.get("initial_balance", 0), "is_default": params.get("default", False), "pct": 0.0}
            self.accounts.append(new_acc)
            return {"account": new_acc}
        if cmd == "account transfer":
            return {"transfer": {"id": 2, "date": params["date"], "amount": params["amount"],
                                 "from_account": str(params["from"]), "to_account": str(params["to"]), "note": params.get("note", "")},
                    "from_balance": 3_000_000, "to_balance": 2_000_000}
        if cmd == "account set-default":
            for a in self.accounts:
                a["is_default"] = (a["id"] == params["id"])
            acc = next(a for a in self.accounts if a["id"] == params["id"])
            return {"account": acc}
        if cmd == "categories":
            return {"expense": ["food", "rent"], "income": ["salary"]}
        if cmd == "list":
            return {"transactions": [], "balance": 5_000_000}
        if cmd == "plan list":
            return {"plans": self.plans}
        if cmd == "plan done":
            p = next((x for x in self.plans if x["id"] == params["id"]), None)
            if p:
                p["status"] = "done"
            return {"transaction": {"id": 10, "amount": p["amount"] if p else 0, "kind": p["kind"] if p else "expense",
                                     "category": p["category"] if p else "", "account_id": 1},
                    "plan": p or {"name": "Test", "status": "done"}}
        if cmd == "budget status":
            return {"budgets": []}
        if cmd == "goal list":
            return {"goals": [], "total_saved": 0}
        if cmd == "history":
            return {"today": TODAY.isoformat(), "series": [], "forecast": []}
        return {}


class AccountsTuiTest(unittest.TestCase):
    def setUp(self):
        self.api = AccountsFakeApi()
        self.state = tui.State(TODAY)
        tui.load(self.state, self.api)

    def test_tab_1_is_accounts(self):
        # Click on Tab 1 (Tài khoản)
        tui.switch_tab(self.state, 1, self.api)
        self.assertEqual(self.state.tab, 1)
        self.assertEqual(tui.TABS[1], "Tài khoản")
        items = self.state.items()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "Tiền mặt")

        # Frame output contains account names
        lines = tui.accounts_lines(self.state, 100, 24)
        out = "\n".join(ln.text.plain for ln in lines)
        self.assertIn("Tiền mặt", out)
        self.assertIn("Techcombank", out)
        self.assertIn("Tổng tài sản", out)

    def test_open_add_account_form(self):
        tui.switch_tab(self.state, 1, self.api)
        # Press 'a' on Tab 1
        tui.open_account_add(self.state, self.api)
        self.assertIsNotNone(self.state.form)
        self.assertEqual(self.state.form.name, "account_add")

        # Fill and submit
        self.state.form.values["name"] = "ZaloPay"
        self.state.form.values["initial_balance"] = "500k"
        tui.submit(self.state, self.api)
        self.assertIsNone(self.state.form)
        add_calls = [c for c in self.api.calls if c[0] == "account add"]
        self.assertEqual(len(add_calls), 1)
        self.assertEqual(add_calls[0][1]["name"], "ZaloPay")

    def test_open_transfer_form(self):
        tui.switch_tab(self.state, 1, self.api)
        tui.open_account_transfer(self.state, self.api)
        self.assertIsNotNone(self.state.form)
        self.assertEqual(self.state.form.name, "account_transfer")

        self.state.form.values["from"] = "Techcombank"
        self.state.form.values["to"] = "Tiền mặt"
        self.state.form.values["amount"] = "200k"
        tui.submit(self.state, self.api)
        self.assertIsNone(self.state.form)
        tr_calls = [c for c in self.api.calls if c[0] == "account transfer"]
        self.assertEqual(len(tr_calls), 1)

    def test_transaction_form_has_account_field(self):
        # On Giao dịch tab (tab 2), open expense form
        tui.switch_tab(self.state, 2, self.api)
        form = tui.open_form(self.state, "expense", self.api)
        self.assertIn("account", [f.key for f in form.visible()])
        # Prefilled with default account "Tiền mặt"
        self.assertEqual(form.values.get("account"), "Tiền mặt")

    def test_account_initial_balance_zero_allowed(self):
        tui.switch_tab(self.state, 1, self.api)
        tui.open_account_add(self.state, self.api)
        self.state.form.values["name"] = "Ví Mới"
        self.state.form.values["initial_balance"] = "0"
        tui.submit(self.state, self.api)
        self.assertEqual(self.state.form, None)
        add_calls = [c for c in self.api.calls if c[0] == "account add"]
        self.assertEqual(add_calls[-1][1]["initial_balance"], 0)

    def test_plan_done_form_and_balance_check(self):
        # Switch to Tab 3 (Dòng tiền)
        tui.switch_tab(self.state, 3, self.api)
        self.state.selected = 0
        item = self.state.items()[0]
        self.assertEqual(item["name"], "Tiền nhà")

        # Press 'd' -> opens plan_done form
        tui.handle_key(self.state, "d", self.api)
        self.assertIsNotNone(self.state.form)
        self.assertEqual(self.state.form.name, "plan_done")
        self.assertIn("Tiền nhà", self.state.form.title)
        self.assertEqual(self.state.form.values.get("account"), "Tiền mặt")

        # Check account chips have balances
        chips = self.state.form.chips(self.state.form.field())
        chip_dict = dict(chips)
        self.assertIn("Tiền mặt (1tr)", chip_dict.get("Tiền mặt", ""))
        self.assertIn("Techcombank (4tr)", chip_dict.get("Techcombank", ""))

        # Try to submit with "Tiền mặt" (1tr < 2tr expense) -> validation error, form stays open
        tui.submit(self.state, self.api)
        self.assertIsNotNone(self.state.form)
        self.assertIn("Số dư không đủ", self.state.form.errors.get("account", ""))

        # Change to "Techcombank" (4tr >= 2tr) -> submit succeeds, form closes
        self.state.form.values["account"] = "Techcombank"
        tui.submit(self.state, self.api)
        self.assertIsNone(self.state.form)
        done_calls = [c for c in self.api.calls if c[0] == "plan done"]
        self.assertEqual(len(done_calls), 1)
        self.assertEqual(done_calls[0][1]["account"], "Techcombank")
        self.assertEqual(done_calls[0][1]["id"], 1)


if __name__ == "__main__":
    unittest.main()
