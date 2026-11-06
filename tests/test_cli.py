import io
import unittest
from datetime import date

from rich.console import Console

from manage_eco.cli import main
from manage_eco.db import Store

TODAY = date(2026, 11, 6)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")

    def eco(self, *argv):
        buf = io.StringIO()
        code = main(list(argv), store=self.store, console=Console(file=buf, width=140), today=TODAY)
        return code, buf.getvalue()

    def test_full_flow(self):
        self.assertEqual(self.eco("income", "20tr", "luong")[0], 0)
        self.assertEqual(self.eco("expense", "150k", "an uong", "-n", "pho")[0], 0)
        self.assertEqual(self.store.balance(), 19_850_000)
        self.eco("budget", "set", "an uong", "3tr")
        self.eco("plan", "add", "Tien nha", "25tr", "nha", "--due", "+10", "--every", "monthly")
        code, out = self.eco("forecast", "--days", "40")
        self.assertEqual(code, 0)
        self.assertIn("Số dư sẽ âm", out)  # second rent payment pushes balance negative
        code, out = self.eco("dash")
        self.assertEqual(code, 0)
        self.assertIn("Ngân sách", out)
        for argv in (("list",), ("summary",), ("plan", "list"), ("budget", "status"),
                     ("goal", "50tr", "--by", "2027-06-01")):
            self.assertEqual(self.eco(*argv)[0], 0, argv)
        self.assertEqual(self.eco("plan", "done", "1")[0], 0)
        self.assertEqual(self.store.balance(), -5_150_000)
        self.assertEqual(self.store.list_plans()[0].due_date, date(2026, 12, 16))

    def test_errors(self):
        self.assertEqual(self.eco("expense", "abc", "x")[0], 2)
        self.assertEqual(self.eco("rm", "99")[0], 1)
        self.assertEqual(self.eco("plan", "cancel", "99")[0], 1)


if __name__ == "__main__":
    unittest.main()
