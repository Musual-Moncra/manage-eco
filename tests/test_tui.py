import unittest
from datetime import date
from io import StringIO

from rich.console import Console

from manage_eco import api, tui
from manage_eco.db import Store

TODAY = date(2026, 11, 6)


def render(renderable, width=120, height=None):
    con = Console(file=StringIO(), width=width, height=height, color_system=None, legacy_windows=False)
    con.print(renderable)
    return con.file.getvalue()


class BuildersTest(unittest.TestCase):
    def test_tab_bar_and_header(self):
        out = render(tui.tab_bar(1)) + render(tui.header(TODAY, -5000))
        for label in ("Tổng quan", "Giao dịch", "Dự định", "Ngân sách", "Dự báo"):
            self.assertIn(label, out)
        self.assertIn("-5.000 ₫", out)
        self.assertIn("06/11/2026", out)

    def test_overview_with_warning(self):
        dash = {"balance": 1000, "month": {"month": "2026-11", "income": 2000, "expense": 1000, "net": 1000},
                "overdue": [{"name": "Điện", "due_date": "2026-11-01"}],
                "budgets": [{"category": "an", "limit": 100, "spent": 120, "remaining": -20, "pct": 120.0}],
                "upcoming": [{"date": "2026-11-10", "name": "thuê nhà", "amount": -3000, "balance": -2000}],
                "lowest": {"date": "2026-11-10", "balance": -2000}}
        out = render(tui.overview(dash), width=140)
        self.assertIn("Sẽ âm tiền ngày 10/11/2026", out)
        self.assertIn("Quá hạn: Điện", out)
        self.assertIn("120%", out)
        self.assertIn("thuê nhà", out)
        self.assertIn("2.000 ₫", out)

    def test_overview_money_never_wraps(self):
        state = tui.State(TODAY)
        state.data[0] = {"balance": 1, "month": {"month": "2026-11", "income": 15_000_000, "expense": 85_000,
                                                  "net": 14_915_000},
                         "budgets": [{"category": "ăn uống", "limit": 3_000_000, "spent": 85_000,
                                      "remaining": 2_915_000, "pct": 2.8}],
                         "upcoming": [{"date": "2026-11-10", "name": "thuê nhà", "amount": -13_000_000,
                                       "balance": -500_000}]}
        for width in (100, 110, 140):
            out = render(tui.build_screen(state, width), width=width, height=30)
            self.assertIn("ăn uống", out, width)
            self.assertIn("85.000 ₫ / 3.000.000 ₫", out, width)
            self.assertIn("-13.000.000 ₫", out, width)
        render(tui.build_screen(state, 60), width=60, height=30)  # narrow terminal must not crash

    def test_no_warning_when_positive(self):
        self.assertIsNone(tui.low_warning({"date": "2026-11-10", "balance": 0}))
        self.assertIsNone(tui.low_warning(None))

    def test_empty_views(self):
        self.assertIn("Chưa có giao dịch", render(tui.transactions_view({}, 0)))
        self.assertIn("Chưa có dự định", render(tui.plans_view({}, 0)))
        self.assertIn("Chưa đặt ngân sách", render(tui.budgets_view({})))
        self.assertIn("Không có dự định", render(tui.forecast_view({})))

    def test_forecast_table_limit(self):
        rows = [{"date": "2026-11-%02d" % d, "name": "x%d" % d, "amount": -1, "balance": 5} for d in range(7, 20)]
        self.assertIn("… và 3 mục khác", render(tui.forecast_table(rows, limit=10)))


class FakeApi:
    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, cmd, params):
        self.calls.append((cmd, params))
        if self.fail:
            raise self.fail
        if cmd == "plan list":
            return {"plans": [{"id": 7, "name": "laptop", "amount": 100, "kind": "expense", "due_date": "2026-12-01",
                               "category": "do", "recurrence": "once", "status": "pending"},
                              {"id": 8, "name": "lương", "amount": 50, "kind": "income", "due_date": "2026-12-05",
                               "category": "luong", "recurrence": "monthly", "status": "pending"}]}
        return {"balance": 42}


class KeysTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.load(self.state, self.api)

    def keys(self, *ks):
        for k in ks:
            tui.handle_key(self.state, k, self.api)

    def type(self, text):
        self.keys(*list(text), "enter")

    def test_quit_and_tabs(self):
        self.assertEqual(self.state.balance, 42)
        self.keys("3")
        self.assertEqual(self.state.tab, 2)
        self.keys("j", "j", "j")
        self.assertEqual(self.state.selected, 1)
        self.keys("k", "up")
        self.assertEqual(self.state.selected, 0)
        self.keys("q")
        self.assertFalse(self.state.running)

    def test_add_expense_prompt(self):
        self.keys("a")
        self.assertIn("Số tiền", render(tui.footer(self.state)))
        self.type("50k")
        self.type("ăn")
        self.type("phở")
        self.keys("enter")  # date default: hom nay
        self.assertIsNone(self.state.form)
        self.assertEqual(self.api.calls[-2], ("expense", {"amount": 50000, "category": "ăn", "note": "phở",
                                                           "date": "2026-11-06"}))
        self.assertIn("Đã thêm", self.state.message)

    def test_add_plan_prompt(self):
        self.keys("p")
        for v in ("lương", "10tr", "luong", "+10", "monthly", "thu"):
            self.type(v)
        cmd, params = next(c for c in self.api.calls if c[0] == "plan add")
        self.assertEqual(params, {"name": "lương", "amount": 10_000_000, "category": "luong",
                                  "due": "2026-11-16", "every": "monthly", "income": True})

    def test_bad_input_shows_error_without_calling_api(self):
        self.keys("i")
        self.type("abc")
        self.type("x")
        self.keys("enter", "enter")
        self.assertIn("Số tiền không hợp lệ", self.state.error)
        self.assertFalse(any(c[0] == "income" for c in self.api.calls))

    def test_esc_and_backspace(self):
        self.keys("a", "1", "2", "backspace")
        self.assertEqual(self.state.buffer, "1")
        self.keys("esc")
        self.assertIsNone(self.state.form)
        self.assertTrue(self.state.running)

    def test_plan_done_on_selected(self):
        self.keys("3", "j", "d")
        self.assertIn(("plan done", {"id": 8, "date": "2026-11-06"}), self.api.calls)
        self.assertIn("lương", self.state.message)

    def test_d_outside_plans_tab(self):
        self.keys("d")
        self.assertIn("tab 3", self.state.error)

    def test_api_error_in_footer(self):
        self.keys("3")
        self.api.fail = LookupError("không tìm thấy dự định 7")
        self.keys("d")
        self.assertIn("không tìm thấy", render(tui.footer(self.state)))


class RealApiTest(unittest.TestCase):
    """End-to-end against api.execute with an in-memory store; every tab renders."""

    def test_all_tabs_render(self):
        store = Store(":memory:")
        call = lambda cmd, params: api.execute(cmd, params, store, TODAY)
        state = tui.State(TODAY)
        tui.load(state, call)
        tui.handle_key(state, "i", call)
        for v in ("2tr", "luong", "", ""):
            for ch in v:
                tui.handle_key(state, ch, call)
            tui.handle_key(state, "enter", call)
        tui.handle_key(state, "p", call)
        for v in ("thuê nhà", "3tr", "nha", "+4", "monthly", "chi"):
            for ch in v:
                tui.handle_key(state, ch, call)
            tui.handle_key(state, "enter", call)
        self.assertEqual(state.error, "")
        outs = []
        for tab in "12345":
            tui.handle_key(state, tab, call)
            self.assertEqual(state.error, "", tab)
            outs.append(render(tui.build_screen(state, 130), width=130, height=40))
        self.assertIn("2.000.000 ₫", outs[0])
        self.assertIn("thuê nhà", outs[2])
        self.assertIn("Sẽ âm tiền", outs[4])  # 2tr - 3tr monthly within 90 days
        tui.handle_key(state, "3", call)
        tui.handle_key(state, "d", call)
        self.assertEqual(store.balance(TODAY), -1_000_000)
        self.assertEqual(state.balance, -1_000_000)
        store.close()


if __name__ == "__main__":
    unittest.main()
