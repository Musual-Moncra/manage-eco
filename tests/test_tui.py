import unittest
from datetime import date

from rich.cells import cell_len

from manage_eco import api, tui
from manage_eco.db import Store

TODAY = date(2026, 11, 6)

DASH = {"balance": 23_715_000,
        "month": {"month": "2026-11", "income": 15_000_000, "expense": 85_000, "net": 14_915_000},
        "overdue": [{"name": "Điện", "due_date": "2026-11-01"}],
        "budgets": [{"category": "ăn uống", "limit": 3_000_000, "spent": 85_000, "remaining": 2_915_000, "pct": 2.8},
                    {"category": "giải trí", "limit": 100, "spent": 120, "remaining": -20, "pct": 120.0}],
        "upcoming": [{"date": "2026-11-10", "name": "thuê nhà", "amount": -13_000_000, "balance": -500_000}],
        "lowest": {"date": "2026-11-10", "balance": -500_000}}
TXS = [{"id": i, "date": "2026-11-%02d" % i, "amount": 1000 * i, "kind": "expense", "category": "ăn",
        "note": "n%d" % i, "signed": -1000 * i} for i in range(1, 41)]
PLANS = [{"id": 7, "name": "laptop", "amount": 100, "kind": "expense", "due_date": "2026-12-01",
          "category": "do", "recurrence": "once", "status": "pending"},
         {"id": 8, "name": "lương", "amount": 50, "kind": "income", "due_date": "2026-12-05",
          "category": "luong", "recurrence": "monthly", "status": "pending"}]


class FakeApi:
    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, cmd, params):
        self.calls.append((cmd, params))
        if self.fail and cmd not in ("dash", "list", "plan list", "budget status", "categories"):
            raise self.fail
        return {"dash": DASH, "list": {"transactions": TXS, "balance": 1}, "plan list": {"plans": PLANS},
                "budget status": {"month": "2026-11", "budgets": DASH["budgets"]},
                "categories": {"expense": ["ăn uống", "đi lại", "nhà"], "income": ["lương"]}}.get(cmd, {})

    def made(self, cmd):
        return [p for c, p in self.calls if c == cmd]


def frame(state, w=80, h=24):
    f = tui.build_frame(state, w, h)
    state.hits = f.hits
    return f


def text(f):
    return "\n".join(t.plain for t in f.lines)


def click(state, action, api, w=80, h=24):
    """Click the centre of the first hit with `action` in a freshly built frame."""
    f = frame(state, w, h)
    hit = next((r, x0, x1) for r, x0, x1, a in f.hits if a == action)
    tui.dispatch(state, ("mouse", 0, (hit[1] + hit[2]) // 2 + 1, hit[0] + 1), api)


class FrameTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.load(self.state, self.api)

    def test_frame_exact_size_all_tabs(self):
        for w, h in ((80, 24), (140, 40)):
            for tab in range(4):
                tui.switch_tab(self.state, tab, self.api)
                f = frame(self.state, w, h)
                self.assertEqual(len(f.lines), h)
                self.assertTrue(all(cell_len(t.plain) == w for t in f.lines), (w, tab))

    def test_layout_rows(self):
        out = text(frame(self.state)).splitlines()
        self.assertIn("Manage Eco", out[0])
        self.assertIn("Số dư 23.715.000 ₫", out[0])
        for name in tui.TABS:
            self.assertIn(name, out[1])
        self.assertIn("+ Chi", out[22])
        self.assertIn("Thoát", out[22])

    def test_overview_content(self):
        out = text(frame(self.state))
        self.assertIn("Thu 15.000.000 ₫", out)
        self.assertIn("120%", out)
        self.assertIn("thuê nhà", out)
        self.assertIn("Sẽ âm tiền ngày 10/11/2026", out)
        self.assertIn("Quá hạn: Điện", out)
        self.assertIn("85.000 ₫ / 3.000.000 ₫", out)

    def test_hit_map_tabs_and_buttons(self):
        for w in (80, 140):
            f = frame(self.state, w)
            tabs = sorted((x0, x1, a[1]) for r, x0, x1, a in f.hits if a[0] == "tab" and r == 1)
            self.assertEqual([t[2] for t in tabs], [0, 1, 2, 3])
            self.assertTrue(all(a[1] <= b[0] for a, b in zip(tabs, tabs[1:])), "tabs overlap")
            keys = {a[1]: r for r, x0, x1, a in f.hits if a[0] == "key"}
            self.assertEqual(set(keys), {"a", "i", "p", "q"})
            self.assertEqual(set(keys.values()), {22})
            self.assertTrue(all(x1 <= w for r, x0, x1, a in f.hits))

    def test_hit_map_list_rows(self):
        tui.switch_tab(self.state, 1, self.api)
        for w in (80, 140):
            f = frame(self.state, w)
            rows = {a[1]: r for r, x0, x1, a in f.hits if a[0] == "select"}
            self.assertEqual(rows[0], 3)  # header, tabs, column titles, first item
            self.assertEqual(len(rows), 24 - 4 - 1)
            self.assertEqual(tui.hit_at(f.hits, 5, w - 1), ("select", 2))
            self.assertIn("40.000 ₫", f.lines[3].plain)  # newest first

    def test_scroll_keeps_selection_visible(self):
        tui.switch_tab(self.state, 1, self.api)
        for _ in range(30):
            tui.dispatch(self.state, ("mouse", 65, 1, 5), self.api)  # wheel down
        f = frame(self.state)
        self.assertEqual(self.state.selected, 29)
        rows = {a[1]: r for r, x0, x1, a in f.hits if a[0] == "select"}
        self.assertEqual(rows[29], 21)
        self.assertIn("n11", f.lines[21].plain)


class ClickTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.load(self.state, self.api)

    def test_click_tab_and_row_and_done(self):
        click(self.state, ("tab", 2), self.api)
        self.assertEqual(self.state.tab, 2)
        self.assertNotIn(("key", "d"), [a for *_, a in frame(self.state).hits])
        click(self.state, ("select", 1), self.api)
        self.assertEqual(self.state.selected, 1)
        self.assertIn("✓ Xong", text(frame(self.state)))
        click(self.state, ("key", "d"), self.api)
        self.assertEqual(self.api.made("plan done"), [{"id": 8, "date": "2026-11-06"}])
        self.assertIn("lương", self.state.status[0])

    def test_add_expense_by_clicks(self):
        click(self.state, ("key", "a"), self.api, 140, 40)
        self.assertIsNotNone(self.state.form)
        click(self.state, ("chip", 0, "200k"), self.api, 140, 40)
        click(self.state, ("chip", 1, "đi lại"), self.api, 140, 40)
        click(self.state, ("focus", 2), self.api, 140, 40)
        for ch in "xe buýt":
            tui.dispatch(self.state, ch, self.api)
        self.assertIn("Lưu", text(frame(self.state, 140, 40)))
        click(self.state, ("key", "enter"), self.api, 140, 40)
        self.assertIsNone(self.state.form)
        self.assertEqual(self.api.made("expense"), [{"amount": 200_000, "category": "đi lại",
                                                     "note": "xe buýt", "date": "2026-11-06"}])
        self.assertTrue(self.state.status[1])

    def test_inline_errors_keep_form_open(self):
        tui.dispatch(self.state, "i", self.api)
        for ch in "abc":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        out = text(frame(self.state))
        self.assertIn("Số tiền không hợp lệ", out)
        self.assertIn("Chọn hoặc gõ một danh mục", out)
        self.assertEqual(self.api.made("income"), [])
        self.assertEqual(self.state.form.focus, 0)
        self.assertIn("lương", out)  # income categories offered

    def test_plan_form_chips_and_keys(self):
        tui.dispatch(self.state, "p", self.api)
        for value in ("lương", "10tr", "luong", "+10"):
            for ch in value:
                tui.dispatch(self.state, ch, self.api)
            tui.dispatch(self.state, "tab", self.api)
        click(self.state, ("chip", 4, "monthly"), self.api)
        tui.dispatch(self.state, "tab", self.api)
        tui.dispatch(self.state, "right", self.api)  # Loại: Chi → Thu
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan add"), [{"name": "lương", "amount": 10_000_000, "category": "luong",
                                                      "due": "2026-11-16", "every": "monthly", "income": True}])

    def test_category_chip_moves_focus_to_empty_amount(self):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", 1, "nhà"), self.api)
        self.assertEqual(self.state.form.focus, 0)
        for ch in "75k":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("expense")[0]["amount"], 75_000)

    def test_api_error_shown_and_form_kept(self):
        self.api.fail = ValueError("danh mục quá dài")
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", 0, "50k"), self.api)
        click(self.state, ("chip", 1, "nhà"), self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertIsNotNone(self.state.form)
        self.assertIn("danh mục quá dài", text(frame(self.state)))

    def test_esc_cancels_form(self):
        tui.dispatch(self.state, "a", self.api)
        tui.dispatch(self.state, "esc", self.api)
        self.assertIsNone(self.state.form)
        self.assertTrue(self.state.running)

    def test_delete_with_confirm(self):
        click(self.state, ("tab", 1), self.api)
        click(self.state, ("select", 0), self.api)
        click(self.state, ("key", "x"), self.api)
        self.assertIn("Xoá ăn", text(frame(self.state)))
        click(self.state, ("key", "n"), self.api)
        self.assertEqual(self.api.made("rm"), [])
        click(self.state, ("key", "x"), self.api)
        click(self.state, ("key", "y"), self.api)
        self.assertEqual(self.api.made("rm"), [{"id": 40}])

    def test_quit_button(self):
        click(self.state, ("key", "q"), self.api)
        self.assertFalse(self.state.running)

    def test_click_on_empty_space_is_ignored(self):
        frame(self.state)
        tui.dispatch(self.state, ("mouse", 0, 80, 24), self.api)
        self.assertEqual(self.state.tab, 0)


class ParseInputTest(unittest.TestCase):
    def test_keys(self):
        p = tui.parse_input
        self.assertEqual(p(b"a"), ("a", 1))
        self.assertEqual(p(b"\r"), ("enter", 1))
        self.assertEqual(p(b"\x7f"), ("backspace", 1))
        self.assertEqual(p(b"\t"), ("tab", 1))
        self.assertEqual(p(b"\x1b[A"), ("up", 3))
        self.assertEqual(p(b"\x1b[Bx"), ("down", 3))
        self.assertEqual(p(b"\x1b[Z"), ("shift-tab", 3))
        self.assertEqual(p(b"\x1b[3~"), ("", 4))
        self.assertEqual(p("ă".encode()), ("ă", 2))
        self.assertEqual(p("ă".encode()[:1]), (None, 0))
        self.assertEqual(p(b"\x1b"), (None, 0))
        self.assertEqual(p(b"\x1bx"), ("esc", 1))

    def test_sgr_mouse(self):
        p = tui.parse_input
        self.assertEqual(p(b"\x1b[<0;12;3M"), (("mouse", 0, 12, 3), 10))
        self.assertEqual(p(b"\x1b[<0;12;3m"), ("", 10))  # release ignored
        self.assertEqual(p(b"\x1b[<64;1;1Mq"), (("mouse", 64, 1, 1), 10))
        self.assertEqual(p(b"\x1b[<65;1"), (None, 0))  # incomplete


class RealApiTest(unittest.TestCase):
    """End-to-end against api.execute with an in-memory store."""

    def test_flow(self):
        store = Store(":memory:")
        call = lambda cmd, params: api.execute(cmd, params, store, TODAY)
        state = tui.State(TODAY)
        tui.load(state, call)
        tui.dispatch(state, "i", call)
        for ev in ["2", "t", "r", "tab", "l", "u", "o", "n", "g"]:
            tui.dispatch(state, ev, call)
        tui.dispatch(state, "enter", call)
        tui.dispatch(state, "p", call)
        for value in ("thuê nhà", "3tr", "nha", "+4"):
            for ch in value:
                tui.dispatch(state, ch, call)
            tui.dispatch(state, "tab", call)
        click(state, ("chip", 4, "monthly"), call)
        tui.dispatch(state, "enter", call)
        self.assertTrue(state.status[1], state.status)
        self.assertEqual(state.balance, 2_000_000)
        self.assertIn("Sẽ âm tiền", text(frame(state)))
        click(state, ("tab", 2), call)
        click(state, ("select", 0), call)
        click(state, ("key", "d"), call)
        self.assertEqual(state.balance, -1_000_000)
        click(state, ("tab", 1), call)
        click(state, ("select", 0), call)
        click(state, ("key", "x"), call)
        click(state, ("key", "y"), call)
        self.assertEqual(store.balance(TODAY), 2_000_000)
        for w, h in ((80, 24), (140, 40)):
            for tab in range(4):
                tui.switch_tab(state, tab, call)
                self.assertEqual(len(frame(state, w, h).lines), h)
        store.close()


if __name__ == "__main__":
    unittest.main()
