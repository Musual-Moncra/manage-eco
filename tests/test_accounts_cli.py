"""CLI and JSON contract tests for Account and Transfer commands."""
import json
import subprocess
import sys
import unittest
from datetime import date
from io import StringIO
from unittest.mock import patch

from manage_eco import cli
from manage_eco.db import Store


class AccountsCliTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 7)

    def tearDown(self):
        self.store.close()

    def run_cli(self, *args):
        buf = StringIO()
        with patch("sys.stdout", buf):
            code = cli.main(list(args), store=self.store, today=self.today)
        return code, buf.getvalue()

    def test_json_account_add_and_list(self):
        code, out = self.run_cli("--json", "account", "add", "Tiền mặt", "1.5tr", "--default")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["command"], "account add")
        self.assertEqual(data["data"]["account"]["name"], "Tiền mặt")
        self.assertEqual(data["data"]["account"]["balance"], 1_500_000)
        self.assertTrue(data["data"]["account"]["is_default"])

        # Add 2nd account
        code2, out2 = self.run_cli("--json", "account", "add", "ZaloPay", "500k")
        self.assertEqual(code2, 0)

        # List accounts
        code3, out3 = self.run_cli("--json", "account", "list")
        self.assertEqual(code3, 0)
        data3 = json.loads(out3)
        self.assertEqual(len(data3["data"]["accounts"]), 2)
        self.assertEqual(data3["data"]["total_balance"], 2_000_000)

    def test_json_account_transfer(self):
        self.run_cli("--json", "account", "add", "Techcombank", "10tr")
        self.run_cli("--json", "account", "add", "ZaloPay", "500k")

        code, out = self.run_cli("--json", "account", "transfer", "Techcombank", "ZaloPay", "2tr", "-n", "nap vi")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(data["data"]["transfer"]["amount"], 2_000_000)
        self.assertEqual(data["data"]["from_balance"], 8_000_000)
        self.assertEqual(data["data"]["to_balance"], 2_500_000)

    def test_json_account_transfer_self_fails_exit_2(self):
        self.run_cli("--json", "account", "add", "Tiền mặt", "1tr")
        code, out = self.run_cli("--json", "account", "transfer", "Tiền mặt", "Tiền mặt", "100k")
        self.assertEqual(code, 2)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["code"], "invalid")

    def test_json_expense_with_account_flag(self):
        self.run_cli("--json", "account", "add", "Tiền mặt", "1tr")
        code, out = self.run_cli("--json", "expense", "50k", "food", "-a", "Tiền mặt")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertIsNotNone(data["data"]["transaction"]["account_id"])

    def test_json_account_add_default_zero(self):
        code, out = self.run_cli("--json", "account", "add", "Ví Không")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["data"]["account"]["balance"], 0)
        self.assertEqual(data["data"]["account"]["initial_balance"], 0)

    def test_json_account_set_balance_and_edit_balance(self):
        self.run_cli("--json", "account", "add", "Tiền mặt", "500k")
        code, out = self.run_cli("--json", "account", "set-balance", "Tiền mặt", "1.2tr")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["data"]["account"]["balance"], 1_200_000)

        code2, out2 = self.run_cli("--json", "account", "edit", "Tiền mặt", "--balance", "2tr")
        self.assertEqual(code2, 0)
        data2 = json.loads(out2)
        self.assertEqual(data2["data"]["account"]["balance"], 2_000_000)

    def test_json_mode_does_not_import_rich(self):
        # Run subprocess with clean env and verify rich is not in sys.modules
        script = (
            "import sys, os\n"
            "from manage_eco import cli\n"
            "cli.main(['--json', 'account', 'list'], today=__import__('datetime').date(2026, 11, 7))\n"
            "assert 'rich' not in sys.modules, f'rich was imported: {sys.modules.get(\"rich\")}'\n"
        )
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
