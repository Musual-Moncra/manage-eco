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
