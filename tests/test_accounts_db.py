"""Unit tests for Account, Transfer models and database store operations."""
import unittest
from datetime import date

from manage_eco.db import Store
from manage_eco.models import Account, Transfer, Transaction, INCOME, EXPENSE


class AccountsDbTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def tearDown(self):
        self.store.close()

    def test_add_account_first_becomes_default(self):
        acc_id = self.store.add_account(Account("Tiền mặt", 1_000_000))
        acc = self.store.get_account(acc_id)
        self.assertIsNotNone(acc)
        self.assertEqual(acc.name, "Tiền mặt")
        self.assertEqual(acc.initial_balance, 1_000_000)
        self.assertTrue(acc.is_default)
        self.assertEqual(self.store.get_default_account().id, acc_id)

    def test_add_second_account_default_behavior(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000))
        id2 = self.store.add_account(Account("ZaloPay", 500_000))
        acc2 = self.store.get_account(id2)
        self.assertFalse(acc2.is_default)
        self.assertEqual(self.store.get_default_account().id, id1)

        # Adding 3rd account with is_default=True shifts default
        id3 = self.store.add_account(Account("Techcombank", 5_000_000, is_default=True))
        self.assertTrue(self.store.get_account(id3).is_default)
        self.assertFalse(self.store.get_account(id1).is_default)
        self.assertEqual(self.store.get_default_account().id, id3)

    def test_get_account_by_name(self):
        self.store.add_account(Account("Vietcombank", 2_000_000))
        acc = self.store.get_account_by_name("vietcombank")
        self.assertIsNotNone(acc)
        self.assertEqual(acc.name, "Vietcombank")
        self.assertIsNone(self.store.get_account_by_name("NonExistent"))

    def test_update_account_and_set_default(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000))
        id2 = self.store.add_account(Account("ZaloPay", 500_000))

        acc1 = self.store.get_account(id1)
        acc1.name = "Ví Tiền Mặt"
        acc1.initial_balance = 1_500_000
        self.store.update_account(acc1)

        updated1 = self.store.get_account(id1)
        self.assertEqual(updated1.name, "Ví Tiền Mặt")
        self.assertEqual(updated1.initial_balance, 1_500_000)

        self.store.set_default_account(id2)
        self.assertTrue(self.store.get_account(id2).is_default)
        self.assertFalse(self.store.get_account(id1).is_default)

    def test_account_balance_with_income_expense(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000))
        id2 = self.store.add_account(Account("Techcombank", 10_000_000))

        # Add income to id2
        self.store.add_transaction(Transaction(date(2026, 11, 1), 5_000_000, INCOME, "salary", "luong", account_id=id2))
        # Add expense from id1
        self.store.add_transaction(Transaction(date(2026, 11, 2), 200_000, EXPENSE, "food", "an trua", account_id=id1))

        self.assertEqual(self.store.account_balance(id1), 800_000)
        self.assertEqual(self.store.account_balance(id2), 15_000_000)
        self.assertEqual(self.store.total_balance(), 15_800_000)

    def test_account_balance_with_transfers(self):
        id1 = self.store.add_account(Account("Techcombank", 10_000_000))
        id2 = self.store.add_account(Account("ZaloPay", 500_000))

        tr_id = self.store.add_transfer(Transfer(date(2026, 11, 7), 2_000_000, id1, id2, "nap vi"))
        self.assertGreater(tr_id, 0)

        self.assertEqual(self.store.account_balance(id1), 8_000_000)
        self.assertEqual(self.store.account_balance(id2), 2_500_000)
        self.assertEqual(self.store.total_balance(), 10_500_000)

        transfers = self.store.list_transfers()
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0].amount, 2_000_000)
        self.assertEqual(transfers[0].note, "nap vi")

    def test_transfer_self_rejected(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000))
        with self.assertRaises(ValueError):
            self.store.add_transfer(Transfer(date(2026, 11, 7), 100_000, id1, id1))

    def test_delete_account_constraints(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000))
        id2 = self.store.add_account(Account("Bank", 2_000_000))

        # Account with transactions cannot be deleted
        self.store.add_transaction(Transaction(date(2026, 11, 5), 50_000, EXPENSE, "food", account_id=id1))
        with self.assertRaises(ValueError):
            self.store.delete_account(id1)

        # Account with transfers cannot be deleted
        self.store.add_transfer(Transfer(date(2026, 11, 6), 100_000, id2, id1))
        with self.assertRaises(ValueError):
            self.store.delete_account(id2)

        # Account without transactions or transfers CAN be deleted
        id3 = self.store.add_account(Account("Vi rac", 0))
        self.assertTrue(self.store.delete_account(id3))
        self.assertIsNone(self.store.get_account(id3))

    def test_transactions_without_account_id_attribute_to_default(self):
        id1 = self.store.add_account(Account("Tiền mặt", 1_000_000, is_default=True))
        # Transaction without explicit account_id
        self.store.add_transaction(Transaction(date(2026, 11, 5), 100_000, EXPENSE, "food"))
        self.assertEqual(self.store.account_balance(id1), 900_000)


    def test_update_account_negative_initial_balance_allowed(self):
        id1 = self.store.add_account(Account("Tiền mặt", 0))
        acc = self.store.get_account(id1)
        acc.initial_balance = -5_000_000
        self.store.update_account(acc)
        updated = self.store.get_account(id1)
        self.assertEqual(updated.initial_balance, -5_000_000)

    def test_legacy_database_migration_removes_check_constraint(self):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
        CREATE TABLE accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            initial_balance INTEGER NOT NULL DEFAULT 0 CHECK (initial_balance >= 0),
            is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
        );
        INSERT INTO accounts (id, name, initial_balance, is_default) VALUES (1, 'Tiền mặt', 0, 1);
        """)
        # Create a store that wraps this connection or migrates it
        st = Store.__new__(Store)
        st.conn = conn
        st.conn.row_factory = sqlite3.Row
        acc_sql = st.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        self.assertIn("initial_balance >= 0", acc_sql["sql"])
        # Running the migration logic in __init__
        Store.__init__(st, ":memory:")
        # Check that constraint is gone
        new_sql = st.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='accounts'").fetchone()
        self.assertNotIn("initial_balance >= 0", new_sql["sql"])
        st.close()


if __name__ == "__main__":
    unittest.main()
