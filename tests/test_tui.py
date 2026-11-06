import unittest
from datetime import date
from unittest import mock

from rich.cells import cell_len

from manage_eco import api, fmt, tui
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
          "category": "luong", "recurrence": "monthly", "status": "pending", "day": 5}]


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

    def test_wording_dong_tien(self):
        for tab in range(4):
            tui.switch_tab(self.state, tab, self.api)
            out = text(frame(self.state))
            self.assertNotIn("Dự định", out)
            self.assertIn("Dòng tiền", out)
        tui.dispatch(self.state, "p", self.api)
        self.assertIn("Thêm dòng tiền", text(frame(self.state)))

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
        out = text(frame(self.state))
        self.assertIn("✓ Xong", out)
        self.assertIn("hàng tháng · ngày 5", out)
        click(self.state, ("key", "d"), self.api)
        self.assertEqual(self.api.made("plan done"), [{"id": 8, "date": "2026-11-06"}])
        self.assertIn("lương", self.state.status[0])

    def test_add_expense_by_clicks(self):
        click(self.state, ("key", "a"), self.api, 140, 40)
        self.assertIsNotNone(self.state.form)
        click(self.state, ("chip", "amount", "200k"), self.api, 140, 40)
        click(self.state, ("chip", "category", "đi lại"), self.api, 140, 40)
        click(self.state, ("focus", "note"), self.api, 140, 40)
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
        self.assertEqual(self.state.form.focus, "amount")
        self.assertIn("lương", out)  # income categories offered

    def fill_plan(self, name="lương", amount="10tr", category="luong"):
        tui.dispatch(self.state, "p", self.api)
        for value in (name, amount, category):
            for ch in value:
                tui.dispatch(self.state, ch, self.api)
            tui.dispatch(self.state, "tab", self.api)

    def test_plan_form_keys(self):
        self.fill_plan()
        self.assertEqual(self.state.form.focus, "every")
        for _ in range(3):
            tui.dispatch(self.state, "right", self.api)  # 1 lần → hàng ngày → hàng tuần → hàng tháng
        tui.dispatch(self.state, "tab", self.api)
        self.assertEqual(self.state.form.focus, "day")
        tui.dispatch(self.state, "tab", self.api)
        for ch in "+10":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "tab", self.api)
        tui.dispatch(self.state, "right", self.api)  # Loại: Chi → Thu
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan add"), [{"name": "lương", "amount": 10_000_000, "category": "luong",
                                                      "due": "2026-11-16", "every": "monthly", "income": True}])

    def test_daily_chip(self):
        self.fill_plan("cà phê", "30k", "ăn uống")
        click(self.state, ("chip", "every", "daily"), self.api)
        self.assertNotIn(("chip", "day", "5"), [a for *_, a in frame(self.state).hits])
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan add"), [{"name": "cà phê", "amount": 30_000, "category": "ăn uống",
                                                      "due": "2026-11-07", "every": "daily", "income": False}])

    def test_monthly_day_chip_omits_due(self):
        self.fill_plan("thuê nhà", "3tr", "nhà")
        click(self.state, ("chip", "every", "monthly"), self.api)
        out = text(frame(self.state))
        self.assertIn("Ngày trả hằng tháng", out)
        self.assertIn("Cuối tháng", out)
        click(self.state, ("chip", "day", "5"), self.api)
        self.assertIn("tự tính lần tới ngày 5", text(frame(self.state)))
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan add"), [{"name": "thuê nhà", "amount": 3_000_000, "category": "nhà",
                                                      "day": 5, "every": "monthly", "income": False}])

    def test_month_end_chip_and_day_hidden_when_not_monthly(self):
        self.fill_plan("lương", "10tr", "luong")
        click(self.state, ("chip", "every", "monthly"), self.api)
        click(self.state, ("chip", "day", "31"), self.api)
        self.assertEqual(self.state.form.values["day"], "31")
        click(self.state, ("chip", "every", "weekly"), self.api)
        self.assertNotIn("Ngày trả hằng tháng", text(frame(self.state)))
        tui.dispatch(self.state, "enter", self.api)
        params = self.api.made("plan add")[0]
        self.assertNotIn("day", params)
        self.assertEqual((params["every"], params["due"]), ("weekly", "2026-11-07"))

    def test_bad_typed_day(self):
        self.fill_plan()
        click(self.state, ("chip", "every", "monthly"), self.api)
        click(self.state, ("focus", "day"), self.api)
        for ch in "40":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan add"), [])
        self.assertEqual(self.state.form.focus, "day")
        self.assertIn("Ngày trả phải là số từ 1 đến 31", text(frame(self.state)))

    def test_amount_preview(self):
        tui.dispatch(self.state, "a", self.api)
        for ch in "50k+20k":
            tui.dispatch(self.state, ch, self.api)
        fake = lambda v: "= 70.000 ₫" if "+" in v else None
        with mock.patch.object(fmt, "money_preview", fake, create=True):
            line = next(l.plain for l in frame(self.state).lines if "Số tiền" in l.plain)
        self.assertRegex(line, r"50k\+20k▏\s+= 70\.000 ₫")
        self.assertIn("phép tính + - x :", text(frame(self.state)))

    @unittest.skipUnless(hasattr(fmt, "money_preview"), "fmt.money_preview not landed yet")
    def test_amount_preview_real(self):
        tui.dispatch(self.state, "a", self.api)
        for ch in "50k+20k":
            tui.dispatch(self.state, ch, self.api)
        self.assertIn("70.000 ₫", text(frame(self.state)))

    def test_date_chips_and_calendar(self):
        tui.dispatch(self.state, "a", self.api)
        hits = [a for *_, a in frame(self.state).hits]
        self.assertIn(("chip", "date", "05/11/2026"), hits)  # Hôm qua chip, always shown
        self.assertNotIn(("cal", "date", 1), hits)  # calendar only while the date field is focused
        click(self.state, ("focus", "date"), self.api)
        out = text(frame(self.state))
        for label in ("Hôm qua", "Hôm nay", "Mai", "Cuối tháng", "Đầu tháng sau", "Tháng 11/2026", "T2"):
            self.assertIn(label, out)
        self.assertIn("→ %s, 06/11/2026" % tui.WEEKDAYS[TODAY.weekday()], out)
        click(self.state, ("chip", "date", "20/11/2026"), self.api)
        self.assertEqual(self.state.form.values["date"], "20/11/2026")
        click(self.state, ("focus", "date"), self.api)
        click(self.state, ("cal", "date", 1), self.api)
        self.assertIn("Tháng 12/2026", text(frame(self.state)))
        click(self.state, ("chip", "date", "01/12/2026"), self.api)
        click(self.state, ("chip", "amount", "50k"), self.api)
        click(self.state, ("chip", "category", "nhà"), self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("expense")[0]["date"], "2026-12-01")

    def test_calendar_hit_map_positions(self):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("focus", "date"), self.api)
        for w, h in ((80, 24), (140, 40)):
            f = frame(self.state, w, h)
            days = {a[2]: (r, x0, x1) for r, x0, x1, a in f.hits if a[:2] == ("chip", "date") and a[2][2:] == "/11/2026"}
            self.assertEqual(len([d for d in days if d[0:2].isdigit()]), 30, w)
            r1, x1a, _ = days["02/11/2026"]  # Monday
            r2, x2a, _ = days["09/11/2026"]  # next Monday: same column, next row
            self.assertEqual((x1a, r2), (x2a, r1 + 1))
            r, x0, x1 = days["06/11/2026"]
            self.assertIn("6", f.lines[r].plain[x0:x1])

    def test_plan_form_fits_80x24_with_calendar(self):
        self.fill_plan()
        click(self.state, ("chip", "every", "monthly"), self.api)
        click(self.state, ("focus", "due"), self.api)
        f = frame(self.state, 80, 24)
        self.assertEqual(len(f.lines), 24)
        hits = [a for *_, a in f.hits]
        self.assertIn(("cal", "due", 1), hits)
        self.assertIn(("key", "enter"), hits)

    def test_category_chip_moves_focus_to_empty_amount(self):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "category", "nhà"), self.api)
        self.assertEqual(self.state.form.focus, "amount")
        for ch in "75k":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("expense")[0]["amount"], 75_000)

    def test_api_error_shown_and_form_kept(self):
        self.api.fail = ValueError("danh mục quá dài")
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "amount", "50k"), self.api)
        click(self.state, ("chip", "category", "nhà"), self.api)
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
        for value in ("thuê nhà", "3tr", "nha"):
            for ch in value:
                tui.dispatch(state, ch, call)
            tui.dispatch(state, "tab", call)
        click(state, ("chip", "every", "monthly"), call)
        click(state, ("chip", "day", "10"), call)
        tui.dispatch(state, "enter", call)
        self.assertTrue(state.status[1], state.status)
        self.assertEqual(state.balance, 2_000_000)
        self.assertIn("Sẽ âm tiền", text(frame(state)))
        click(state, ("tab", 2), call)
        self.assertIn("hàng tháng · ngày 10", text(frame(state)))
        self.assertIn("10/11/2026", text(frame(state)))
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
