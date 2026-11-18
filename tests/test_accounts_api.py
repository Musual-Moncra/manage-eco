"""Unit tests for Account and Transfer API commands in manage_eco/api.py."""
import unittest
from datetime import date

from manage_eco import api
from manage_eco.db import Store


class AccountsApiTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 7)

    def tearDown(self):
        self.store.close()

    def test_account_add_and_list(self):
        res1 = api.execute("account add", {"name": "Tiền mặt", "initial_balance": "1tr"}, self.store, self.today)
        self.assertEqual(res1["account"]["name"], "Tiền mặt")
        self.assertEqual(res1["account"]["initial_balance"], 1_000_000)
        self.assertEqual(res1["account"]["balance"], 1_000_000)
        self.assertTrue(res1["account"]["is_default"])

        res2 = api.execute("account add", {"name": "ZaloPay", "initial_balance": "500k"}, self.store, self.today)
        self.assertEqual(res2["account"]["name"], "ZaloPay")
        self.assertEqual(res2["account"]["balance"], 500_000)
        self.assertFalse(res2["account"]["is_default"])

        lst = api.execute("account list", {}, self.store, self.today)
        self.assertEqual(len(lst["accounts"]), 2)
        self.assertEqual(lst["total_balance"], 1_500_000)

    def test_account_edit_and_set_default(self):
        api.execute("account add", {"name": "Tiền mặt", "initial_balance": "1tr"}, self.store, self.today)
        res2 = api.execute("account add", {"name": "Bank", "initial_balance": "2tr"}, self.store, self.today)
        bank_id = res2["account"]["id"]

        edit_res = api.execute("account edit", {"id": bank_id, "name": "Techcombank", "initial_balance": "3tr"}, self.store, self.today)
        self.assertEqual(edit_res["account"]["name"], "Techcombank")
        self.assertEqual(edit_res["account"]["balance"], 3_000_000)

        api.execute("account set-default", {"id": bank_id}, self.store, self.today)
        lst = api.execute("account list", {}, self.store, self.today)
        bank_acc = next(a for a in lst["accounts"] if a["id"] == bank_id)
        self.assertTrue(bank_acc["is_default"])

    def test_account_add_default_balance_zero(self):
        # Adding account with no balance or empty balance defaults to 0
        res = api.execute("account add", {"name": "Heo đất"}, self.store, self.today)
        self.assertEqual(res["account"]["initial_balance"], 0)
        self.assertEqual(res["account"]["balance"], 0)

    def test_account_adjust_current_balance(self):
        # Create account with 500k
        res = api.execute("account add", {"name": "Ví phụ", "initial_balance": "500k"}, self.store, self.today)
        aid = res["account"]["id"]

        # Make an expense of 200k -> balance drops to 300k
        api.execute("expense", {"amount": "200k", "account": aid}, self.store, self.today)
        self.assertEqual(self.store.account_balance(aid), 300_000)

        # Directly adjust balance to 1tr
        res_edit = api.execute("account edit", {"id": aid, "balance": "1tr"}, self.store, self.today)
        self.assertEqual(res_edit["account"]["balance"], 1_000_000)
        self.assertEqual(self.store.account_balance(aid), 1_000_000)

        # Adjust balance via set-balance command to 0
        res_set = api.execute("account set-balance", {"id": aid, "balance": "0"}, self.store, self.today)
        self.assertEqual(res_set["account"]["balance"], 0)
        self.assertEqual(self.store.account_balance(aid), 0)

        # Add income of 10tr -> balance becomes 10tr
        api.execute("income", {"amount": "10tr", "account": aid}, self.store, self.today)
        self.assertEqual(self.store.account_balance(aid), 10_000_000)

        # Adjust balance downwards to 2tr (diff = -8tr, initial_balance becomes negative)
        res_down = api.execute("account edit", {"id": aid, "balance": "2tr"}, self.store, self.today)
        self.assertEqual(res_down["account"]["balance"], 2_000_000)
        self.assertEqual(self.store.account_balance(aid), 2_000_000)

    def test_account_rm(self):
        res = api.execute("account add", {"name": "Tiền mặt", "initial_balance": "0"}, self.store, self.today)
        res2 = api.execute("account add", {"name": "Tạm", "initial_balance": "0"}, self.store, self.today)
        temp_id = res2["account"]["id"]

        del_res = api.execute("account rm", {"id": temp_id}, self.store, self.today)
        self.assertEqual(del_res["deleted"], temp_id)
        lst = api.execute("account list", {}, self.store, self.today)
        self.assertEqual(len(lst["accounts"]), 1)

    def test_account_transfer_flow(self):
        api.execute("account add", {"name": "Techcombank", "initial_balance": "10tr"}, self.store, self.today)
        api.execute("account add", {"name": "ZaloPay", "initial_balance": "500k"}, self.store, self.today)

        # Transfer by account names
        tr = api.execute(
            "account transfer",
            {"from": "Techcombank", "to": "ZaloPay", "amount": "2tr", "note": "nạp ví"},
            self.store,
            self.today,
        )
        self.assertEqual(tr["transfer"]["amount"], 2_000_000)
        self.assertEqual(tr["from_balance"], 8_000_000)
        self.assertEqual(tr["to_balance"], 2_500_000)

        trs = api.execute("account transfers", {}, self.store, self.today)
        self.assertEqual(len(trs["transfers"]), 1)
        self.assertEqual(trs["transfers"][0]["from_account"], "Techcombank")
        self.assertEqual(trs["transfers"][0]["to_account"], "ZaloPay")

    def test_account_transfer_with_category_counts_in_budget(self):
        api.execute("account add", {"name": "ZaloPay", "initial_balance": "5tr"}, self.store, self.today)
        api.execute("account add", {"name": "MB Bank", "initial_balance": "0"}, self.store, self.today)
        api.execute("budget set", {"category": "bạn gái", "amount": "2tr"}, self.store, self.today)

        # Transfer with category
        api.execute(
            "account transfer",
            {"from": "ZaloPay", "to": "MB Bank", "amount": "500k", "category": "bạn gái", "note": "sinh hoạt chung"},
            self.store,
            self.today,
        )

        # Check budget status: spent must include the 500k transfer!
        b_status = api.execute("budget status", {}, self.store, self.today)
        bg = next(b for b in b_status["budgets"] if b["category"] == "bạn gái")
        self.assertEqual(bg["spent"], 500_000)
        self.assertEqual(bg["remaining"], 1_500_000)
        self.assertEqual(bg["pct"], 25.0)

    def test_account_edit_transfer_updates_category_and_budget(self):
        api.execute("account add", {"name": "ZaloPay", "initial_balance": "5tr"}, self.store, self.today)
        api.execute("account add", {"name": "MB Bank", "initial_balance": "0"}, self.store, self.today)
        api.execute("budget set", {"category": "bạn gái", "amount": "2tr"}, self.store, self.today)

        # Transfer without category first (like in the past)
        tr = api.execute(
            "account transfer",
            {"from": "ZaloPay", "to": "MB Bank", "amount": "500k", "note": "chuyển cũ"},
            self.store,
            self.today,
        )
        tid = tr["transfer"]["id"]

        # Initially budget spent is 0
        b_status = api.execute("budget status", {}, self.store, self.today)
        bg = next(b for b in b_status["budgets"] if b["category"] == "bạn gái")
        self.assertEqual(bg["spent"], 0)

        # Now retroactively update transfer with category
        api.execute("account edit-transfer", {"id": tid, "category": "bạn gái"}, self.store, self.today)

        # Budget now includes the past transfer
        b_status = api.execute("budget status", {}, self.store, self.today)
        bg = next(b for b in b_status["budgets"] if b["category"] == "bạn gái")
        self.assertEqual(bg["spent"], 500_000)

    def test_account_transfer_to_self_fails(self):
        api.execute("account add", {"name": "Tiền mặt", "initial_balance": "1tr"}, self.store, self.today)
        with self.assertRaises(ValueError):
            api.execute("account transfer", {"from": "Tiền mặt", "to": "Tiền mặt", "amount": "100k"}, self.store, self.today)

    def test_income_and_expense_with_account(self):
        api.execute("account add", {"name": "Tiền mặt", "initial_balance": "1tr"}, self.store, self.today)
        api.execute("account add", {"name": "Techcombank", "initial_balance": "5tr"}, self.store, self.today)

        # Expense specifying account
        exp = api.execute("expense", {"amount": "200k", "category": "food", "account": "Tiền mặt"}, self.store, self.today)
        self.assertIsNotNone(exp["transaction"].get("account_id"))
        self.assertEqual(self.store.account_balance(self.store.get_account_by_name("Tiền mặt").id), 800_000)

        # Income defaulting to default account (Tiền mặt is default)
        inc = api.execute("income", {"amount": "500k", "category": "bonus"}, self.store, self.today)
        self.assertEqual(self.store.account_balance(self.store.get_account_by_name("Tiền mặt").id), 1_300_000)

    def test_plan_done_with_account_and_validation(self):
        # Set up accounts
        api.execute("account add", {"name": "ZaloPay", "initial_balance": "500k"}, self.store, self.today)
        api.execute("account add", {"name": "Techcombank", "initial_balance": "5tr"}, self.store, self.today)

        # Plan 1: Expense 1tr (ZaloPay only has 500k, Techcombank has 5tr)
        p1 = api.execute("plan add", {"name": "Mua đồ", "amount": "1tr", "category": "shopping", "due": "2026-11-07"}, self.store, self.today)
        pid1 = p1["plan"]["id"]

        # Completing expense from ZaloPay must fail due to insufficient balance
        with self.assertRaises(ValueError) as ctx:
            api.execute("plan done", {"id": pid1, "account": "ZaloPay"}, self.store, self.today)
        self.assertIn("không đủ", str(ctx.exception))

        # Completing expense from Techcombank must succeed
        res = api.execute("plan done", {"id": pid1, "account": "Techcombank"}, self.store, self.today)
        self.assertEqual(res["plan"]["status"], "done")
        self.assertEqual(self.store.account_balance(self.store.get_account_by_name("Techcombank").id), 4_000_000)

        # Plan 2: Income 2tr into ZaloPay must succeed
        p2 = api.execute("plan add", {"name": "Lương tuần", "amount": "2tr", "category": "income", "income": True, "due": "2026-11-07"}, self.store, self.today)
        pid2 = p2["plan"]["id"]
        res2 = api.execute("plan done", {"id": pid2, "account": "ZaloPay"}, self.store, self.today)
        self.assertEqual(res2["plan"]["status"], "done")
        self.assertEqual(self.store.account_balance(self.store.get_account_by_name("ZaloPay").id), 2_500_000)

    def test_dash_includes_accounts(self):
        api.execute("account add", {"name": "Tiền mặt", "initial_balance": "1tr"}, self.store, self.today)
        d = api.execute("dash", {}, self.store, self.today)
        self.assertIn("accounts", d)
        self.assertEqual(len(d["accounts"]), 1)
        self.assertEqual(d["accounts"][0]["name"], "Tiền mặt")


if __name__ == "__main__":
    unittest.main()
