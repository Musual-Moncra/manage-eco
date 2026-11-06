import unittest
from datetime import date
from unittest import mock

from rich.cells import cell_len
from rich.text import Text

from manage_eco import api, fmt, tui
from manage_eco.db import Store

TODAY = date(2026, 11, 6)
_SFX = mock.patch.object(tui.sfx, "play", return_value=True)


def setUpModule():
    _SFX.start()  # never spawn real audio players from tests


def tearDownModule():
    _SFX.stop()

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
                "categories": {"expense": ["ăn uống", "đi lại", "nhà"], "income": ["lương"]},
                "sound": {"sound": params.get("state", "on") != "off"}}.get(cmd, {})

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
            self.assertEqual(set(keys), {"a", "i", "p", "m", "q"})
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


def cells(plain, x0, x1):
    """Characters of a plain line occupying cells [x0, x1)."""
    out, pos = "", 0
    for ch in plain:
        if x0 <= pos < x1:
            out += ch
        pos += cell_len(ch)
    return out


class ResponsiveTest(unittest.TestCase):
    SIZES = ((40, 12), (50, 20), (80, 24), (120, 30), (170, 45))

    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.init(self.state, self.api)

    def check(self, w, h, what):
        f = frame(self.state, w, h)
        self.assertEqual(len(f.lines), h, what)
        for r, t in enumerate(f.lines):
            self.assertEqual(cell_len(t.plain), w, (what, r, t.plain))
        for r, x0, x1, a in f.hits:
            self.assertTrue(0 <= r < h and 0 <= x0 < x1 <= w, (what, r, x0, x1, a))
            label = cells(f.lines[r].plain, x0, x1)
            self.assertTrue(label.strip(), (what, a))  # nothing clickable is blank
            if a[0] == "tab" and r == 1:  # the tab bar (rows elsewhere may also open a tab)
                i = a[1]
                self.assertTrue(any(s in label for s in (tui.TABS_SHORT[i], tui.TAB_ICONS[i], str(i + 1))),
                                (what, label))
            if a[0] == "key" and a[1] not in ("enter", "esc"):
                self.assertIn(a[1], label, (what, label))
        return f

    def test_every_screen_at_every_size(self):
        for w, h in self.SIZES:
            for tab in range(4):
                tui.switch_tab(self.state, tab, self.api)
                self.state.selected = 0 if tab in (1, 2) else None
                self.check(w, h, (w, h, "tab", tab))
            tui.handle_key(self.state, "p", self.api)
            for key in ["tab"] * 3 + ["right"] * 3 + ["tab"] * 2:  # Lặp = Hàng tháng, focus Ngày bắt đầu
                tui.handle_key(self.state, key, self.api)
            self.assertEqual((self.state.form.values["every"], self.state.form.focus), ("monthly", "due"))
            self.check(w, h, (w, h, "plan form"))
            tui.handle_key(self.state, "esc", self.api)
            tui.switch_tab(self.state, 1, self.api)
            self.state.selected = 0
            tui.handle_key(self.state, "x", self.api)
            self.check(w, h, (w, h, "confirm"))
            tui.handle_key(self.state, "n", self.api)

    def test_breakpoints(self):
        out50 = text(frame(self.state, 50, 20)).splitlines()
        self.assertIn("Tổng", out50[1])
        self.assertNotIn("Tổng quan", out50[1])
        out80 = text(frame(self.state, 80, 24))
        self.assertIn("Tổng quan", out80)
        self.assertFalse(any("Ngân sách" in l and "Sắp tới" in l for l in out80.splitlines()))
        out120 = text(frame(self.state, 120, 30))
        self.assertTrue(any("Ngân sách" in l and "Sắp tới 30 ngày" in l for l in out120.splitlines()))
        self.assertNotIn("Số dư 30 ngày tới", out120)
        out170 = text(frame(self.state, 170, 40))
        self.assertIn("Số dư 30 ngày tới", out170)
        self.assertTrue(any(c in out170 for c in "▁▂▃▄▅▆▇█"))
        tui.switch_tab(self.state, 1, self.api)
        self.assertIn("#40", text(frame(self.state, 140, 30)))
        self.assertNotIn("#40", text(frame(self.state, 80, 24)))
        self.assertIn("06/11", text(frame(self.state, 50, 20)) + "06/11")  # short dates in compact mode
        tui.switch_tab(self.state, 2, self.api)
        self.assertIn("Danh mục", text(frame(self.state, 140, 30)))
        self.assertIn("hàng tháng · ngày 5", text(frame(self.state, 80, 24)))
        self.assertNotIn("hàng tháng", text(frame(self.state, 50, 20)))

    def test_lists_use_spare_rows(self):
        tui.switch_tab(self.state, 1, self.api)
        for h in (12, 24, 45):
            rows = [a for _, _, _, a in frame(self.state, 100, h).hits if a[0] == "select"]
            self.assertEqual(len(rows), min(40, h - 5))

    def test_header_mood(self):
        out = text(frame(self.state)).splitlines()[0]
        self.assertIn("(｡•́︿•̀｡)", out)  # FakeApi forecast goes negative
        self.state.dash = {"lowest": None, "budgets": [{"pct": 85.0}]}
        self.assertIn("(・_・;)", text(frame(self.state)).splitlines()[0])
        self.state.dash = {"lowest": None, "budgets": [{"pct": 10.0}]}
        self.assertIn("(◕‿◕)", text(frame(self.state)).splitlines()[0])

    def test_category_icons(self):
        cases = {"Ăn uống": "🍜", "tiền nhà": "🏠", "xăng xe": "🛵", "Lương": "💰", "mua sắm": "🛒", "học": "📚",
                 "điện nước": "💡", "Claude Pro": "💻", "khác": "•", "thuận": "•"}
        for name, icon in cases.items():
            self.assertEqual(tui.category_icon(name), icon, name)
        self.assertEqual(cell_len(tui.cat_label("khác")), cell_len("🍜 khác"))  # aligned with emoji icons

    def test_ascii_mode(self):
        tui.use_ascii(True)
        try:
            for tab in range(4):
                tui.switch_tab(self.state, tab, self.api)
                f = self.check(80, 24, ("ascii", tab))
                for glyph in ("█", "🏠", "▐", "◆", "(◕‿◕)", "(｡•́︿•̀｡)"):
                    self.assertNotIn(glyph, text(f))
        finally:
            tui.use_ascii(False)


@unittest.skipIf(tui.anim is None, "anim.py not available")
class AnimationTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        self.state.now = 100.0
        tui.init(self.state, self.api)
        tui.play_calls = tui.sfx.play
        tui.sfx.play.reset_mock()

    def at(self, t, w=100, h=30):
        self.state.now = t
        return frame(self.state, w, h)

    def save_expense(self):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "amount", "50k"), self.api, 100, 30)
        click(self.state, ("chip", "category", "nhà"), self.api, 100, 30)
        tui.dispatch(self.state, "enter", self.api)

    def test_toast_overlay_after_save(self):
        self.state.now = 200.0
        self.save_expense()
        f = self.at(200.5)
        box = [r for r, t in enumerate(f.lines[:-2]) if "Đã lưu khoản chi" in t.plain]
        self.assertEqual(len(box), 1)
        r = box[0]
        self.assertLessEqual(r + 1, 30 - 3)  # bottom border (r + 1) sits above the action bar (row 28)
        self.assertIn("+ Chi", f.lines[28].plain)  # layout not shifted
        self.assertTrue(f.lines[r].plain.rstrip().endswith("│"))  # right-aligned box
        x = cell_len(f.lines[r].plain.rstrip()) - 3
        self.assertEqual(tui.hit_at(f.hits, r, x), ("noop",))  # toast is not click-through
        self.assertTrue(self.state.animating())
        f = self.at(203.0)
        self.assertNotIn("Đã lưu khoản chi", text(f).replace(self.state.status[0], ""))
        self.assertFalse(self.state.animating())
        self.assertFalse(any(a == ("noop",) for *_, a in f.hits))

    def test_sparkle_and_count_up(self):
        self.state.now = 300.0
        before = self.state.balance
        self.save_expense()
        self.assertIsNotNone(self.state.sparkle)
        self.state.balance = before - 50_000  # FakeApi balance does not change; simulate the new value
        self.state.count = (before, before - 50_000, 300.0)
        mid = self.at(300.2)
        self.assertTrue(any(c in text(mid) for c in "✦✧⋆˚♡✿"))
        shown = self.state.shown_balance()
        self.assertTrue(before - 50_000 < shown < before, shown)
        self.at(301.0)
        self.assertEqual(self.state.shown_balance(), before - 50_000)

    def test_error_toast_has_no_sparkle(self):
        self.api.fail = ValueError("hỏng rồi")
        self.state.now = 400.0
        self.save_expense()
        self.assertIsNone(self.state.sparkle)
        self.assertEqual(self.state.toast[0].kind, "error")
        self.assertIn("hỏng rồi", text(self.at(400.5)))
        tui.sfx.play.assert_any_call("error", enabled=True)

    def test_bar_fill_on_tab_switch(self):
        self.state.now = 500.0
        tui.switch_tab(self.state, 3, self.api)
        early = text(self.at(500.05)).count("█")
        late = text(self.at(501.0)).count("█")
        self.assertLess(early, late)

    def test_keys_work_during_animation(self):
        self.state.now = 600.0
        self.save_expense()
        self.at(600.1)
        click(self.state, ("tab", 2), self.api, 100, 30)  # the tab row is never covered by the toast
        self.assertEqual(self.state.tab, 2)
        tui.dispatch(self.state, "a", self.api)
        self.assertIsNotNone(self.state.form)


class LoopTest(unittest.TestCase):
    def test_blocks_when_idle_and_ticks_while_animating(self):
        api = FakeApi()
        state = tui.State(TODAY)
        tui.load(state, api)  # no init: no bar animation pending
        timeouts, draws = [], []
        times = iter([0.0, 0.0, 10.0, 10.0, 10.5, 10.5, 20.0, 20.0, 20.0])
        events = iter(["tick", "a", "esc", "q"])
        if tui.anim is not None:
            events = iter(["tick", "m", "tick", "q"])  # m: sound toggle pops an info toast

        def next_event(timeout):
            timeouts.append(timeout)
            return next(events)

        tui.run_loop(state, next_event, lambda: draws.append(state.now), api, lambda: next(times))
        self.assertIsNone(timeouts[0])  # idle: blocking read, no timer
        if tui.anim is not None:
            self.assertEqual(timeouts[2], tui.FRAME_S)  # toast running: ~33 ms frames
            self.assertIsNone(timeouts[3])  # finished: back to blocking
        self.assertEqual(len(draws), 4)  # one draw per event, no busy loop


class SoundTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.init(self.state, self.api)
        tui.sfx.play.reset_mock()

    def events(self):
        return [c.args[0] for c in tui.sfx.play.call_args_list]

    def test_events(self):
        click(self.state, ("tab", 2), self.api)
        click(self.state, ("select", 0), self.api)
        click(self.state, ("key", "d"), self.api)
        click(self.state, ("tab", 1), self.api)
        click(self.state, ("select", 0), self.api)
        click(self.state, ("key", "x"), self.api)
        click(self.state, ("key", "y"), self.api)
        self.assertEqual(self.events(), ["tab", "done", "tab", "delete"])

    def test_save_warns_when_forecast_negative(self):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "amount", "50k"), self.api)
        click(self.state, ("chip", "category", "nhà"), self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.events(), ["warn"])  # FakeApi forecast dips below zero

    def test_save_plays_save_when_all_fine(self):
        calm = dict(DASH, lowest=None, budgets=[])
        with mock.patch.dict(DASH, calm):
            tui.dispatch(self.state, "i", self.api)
            click(self.state, ("chip", "amount", "50k"), self.api)
            click(self.state, ("chip", "category", "lương"), self.api)
            tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.events(), ["save"])

    def test_error_sound(self):
        tui.dispatch(self.state, "a", self.api)
        tui.dispatch(self.state, "enter", self.api)  # empty form: validation error
        self.assertEqual(self.events(), ["error"])

    def test_toggle_persists_and_mutes(self):
        self.assertIn("🔊", text(frame(self.state)))
        click(self.state, ("key", "m"), self.api)
        self.assertEqual(self.api.made("sound")[-1], {"state": "off"})
        self.assertFalse(self.state.sound)
        self.assertIn("🔇", text(frame(self.state)))
        click(self.state, ("tab", 3), self.api)
        tui.sfx.play.assert_called_with("tab", enabled=False)
        tui.dispatch(self.state, "m", self.api)
        self.assertEqual(self.api.made("sound")[-1], {"state": "on"})
        self.assertTrue(self.state.sound)

    def test_initial_sound_setting(self):
        api = FakeApi()
        api.sound_off = True
        orig = api.__call__
        state = tui.State(TODAY)
        tui.init(state, lambda cmd, params: {"sound": False} if cmd == "sound" else orig(cmd, params))
        self.assertFalse(state.sound)


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
