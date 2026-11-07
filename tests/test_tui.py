import os
import re
import unittest
from datetime import date
from unittest import mock

from rich.cells import cell_len
from rich.text import Text

from manage_eco import api, fmt, tui
from manage_eco.db import Store

TODAY = date(2026, 11, 6)
_SFX = mock.patch.object(tui.sfx, "play", return_value=True)
REAL_PIXEL = getattr(tui.anim, "PixelPopup", None)
# Most tests check what is under the overlays: they run with the corner toast (as before v6).
# PixelPopupTest / RealPixelPopupTest switch the centered popup back on.
_NO_PIXEL = mock.patch.object(tui.anim, "PixelPopup", None, create=True) if tui.anim else None
# Interaction VFX (v7) draw over text too: off by default, on in VfxTest.
VFX_NAMES = ("Ripple", "Press", "Glow", "slide")
REAL_VFX = {n: getattr(tui.anim, n, None) for n in VFX_NAMES}
_NO_VFX = [mock.patch.object(tui.anim, n, None, create=True) for n in VFX_NAMES] if tui.anim else []


def setUpModule():
    _SFX.start()  # never spawn real audio players from tests
    if _NO_PIXEL:
        _NO_PIXEL.start()
    for patcher in _NO_VFX:
        patcher.start()


def tearDownModule():
    _SFX.stop()
    if _NO_PIXEL:
        _NO_PIXEL.stop()
    for patcher in _NO_VFX:
        patcher.stop()

DASH = {"balance": 23_715_000,
        "month": {"month": "2026-11", "income": 15_000_000, "expense": 85_000, "net": 14_915_000,
                  "by_category": [{"category": "ăn uống", "amount": 60_000}, {"category": "xăng xe", "amount": 25_000}]},
        "overdue": [{"name": "Điện", "due_date": "2026-11-01"}],
        "budgets": [{"category": "ăn uống", "limit": 3_000_000, "spent": 85_000, "remaining": 2_915_000, "pct": 2.8},
                    {"category": "giải trí", "limit": 100, "spent": 120, "remaining": -20, "pct": 120.0}],
        "upcoming": [{"date": "2026-11-10", "name": "thuê nhà", "amount": -13_000_000, "balance": -500_000}],
        "lowest": {"date": "2026-11-10", "balance": -500_000},
        "accounts": [{"id": 1, "name": "Tiền mặt", "initial_balance": 1_000_000, "balance": 1_000_000, "is_default": True},
                     {"id": 2, "name": "Techcombank", "initial_balance": 5_000_000, "balance": 5_000_000, "is_default": False}]}
ACCOUNTS = [{"id": 1, "name": "Tiền mặt", "initial_balance": 1_000_000, "balance": 1_000_000, "is_default": True},
            {"id": 2, "name": "Techcombank", "initial_balance": 5_000_000, "balance": 5_000_000, "is_default": False}]
TXS = [{"id": i, "date": "2026-10-%02d" % (i % 28 + 1), "amount": 1000 * i, "kind": "expense", "category": "ăn",
        "note": "n%d" % i, "signed": -1000 * i} for i in range(1, 41)]
PLANS = [{"id": 7, "name": "laptop", "amount": 100, "kind": "expense", "due_date": "2026-12-01",
          "category": "do", "recurrence": "once", "status": "pending"},
         {"id": 8, "name": "lương", "amount": 50, "kind": "income", "due_date": "2026-12-05",
          "category": "luong", "recurrence": "monthly", "status": "pending", "day": 5}]
DONE_PLAN = {"id": 9, "name": "học phí", "amount": 2_000_000, "kind": "expense", "due_date": "2026-09-01",
             "category": "học", "recurrence": "once", "status": "done", "day": None}


def history(days, ahead):
    from datetime import timedelta
    days = days or 120
    series = [{"date": (TODAY - timedelta(days=days - 1 - i)).isoformat(), "balance": 20_000_000 + (i % 9 - 4) * 400_000,
               "income": 0, "expense": 0} for i in range(days)]
    forecast = [{"date": (TODAY + timedelta(days=i + 1)).isoformat(), "balance": 23_715_000 - 500_000 * (i // 10)}
                for i in range(ahead)]
    return {"today": TODAY.isoformat(), "series": series, "forecast": forecast}


class FakeApi:
    def __init__(self):
        self.calls = []
        self.fail = None

    def __call__(self, cmd, params):
        self.calls.append((cmd, params))
        if self.fail and cmd not in ("dash", "list", "plan list", "budget status", "categories"):
            raise self.fail
        if cmd == "history":
            return history(params.get("days", 90), params.get("ahead", 90))
        if cmd == "goal":
            return {"target": params["target"], "by": params["by"], "needed": 26_285_000, "months_left": 2,
                    "per_month": 13_142_500}
        if cmd == "goal list":
            goals = getattr(self, "goals", [
                {"id": 1, "name": "Laptop", "target": 30_000_000, "saved": 15_000_000,
                 "by": "2027-12-31", "remaining": 15_000_000, "pct": 50.0, "per_month": 1_071_429,
                 "days_left": 420, "on_track": True},
                {"id": 2, "name": "Du lịch", "target": 10_000_000, "saved": 2_000_000,
                 "by": "2027-06-30", "remaining": 8_000_000, "pct": 20.0, "per_month": 1_000_000,
                 "days_left": 236, "on_track": True},
            ])
            tot = sum(g.get("saved", 0) for g in goals)
            return {"goals": goals, "total_saved": tot, "balance": 23_715_000, "free_balance": 23_715_000 - tot}
        if cmd == "goal save":
            return {"goal": {"id": params["id"], "name": "Laptop", "saved": 20_000_000, "target": 30_000_000,
                             "by": "2027-12-31"}, "saved_added": params["amount"], "total_saved": 20_000_000,
                    "free_balance": 3_715_000}
        if cmd == "goal take":
            return {"goal": {"id": params["id"], "name": "Laptop", "saved": 10_000_000, "target": 30_000_000,
                             "by": "2027-12-31"}, "taken": params["amount"], "total_saved": 10_000_000,
                    "free_balance": 13_715_000}
        if cmd == "goal add":
            return {"goal": {"id": 3, "name": params.get("name", "Mục tiêu"), "target": params["target"],
                             "by": params["by"], "saved": 0}}
        if cmd == "goal edit":
            return {"goal": {"id": params["id"], "name": params.get("name", "Mục tiêu"), "target": params["target"],
                             "by": params["by"], "saved": 15_000_000}}
        if cmd == "goal rm":
            return {"deleted": params["id"], "goals": []}
        if cmd == "account list":
            return {"accounts": ACCOUNTS, "total_balance": 6_000_000}
        if cmd == "account transfers":
            return {"transfers": []}
        plans = PLANS + [DONE_PLAN] if params.get("all") else PLANS
        return {"dash": DASH, "list": {"transactions": TXS, "balance": 1}, "plan list": {"plans": plans},
                "budget status": {"month": "2026-11", "budgets": DASH["budgets"]},
                "categories": {"expense": ["ăn uống", "đi lại", "nhà"], "income": ["lương"], "accounts": ACCOUNTS},
                "sound": {"sound": params.get("state", "on") != "off"},
                "icons": {"icons": params.get("mode") or "symbol"}}.get(cmd, {})

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
            out = text(frame(self.state, 120))
            self.assertNotIn("Dự định", out)
            self.assertIn("Dòng tiền", out)
        tui.dispatch(self.state, "p", self.api)
        self.assertIn("Thêm dòng tiền", text(frame(self.state)))

    def test_layout_rows(self):
        out = text(frame(self.state, 120, 24)).splitlines()
        self.assertIn("Manage Eco", out[0])
        self.assertIn("Số dư 23.715.000 ₫", out[0])
        for name in tui.TABS:
            self.assertIn(name, out[1])
        self.assertIn("+ Chi", out[22])
        self.assertIn("Thoát", out[22])

        out80 = text(frame(self.state, 80, 24)).splitlines()
        self.assertIn("Tổng quan", out80[1])
        self.assertIn("Giao", out80[1])
        self.assertIn("Hũ", out80[1])

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
            self.assertEqual([t[2] for t in tabs], list(range(len(tui.TABS))))
            self.assertTrue(all(a[1] <= b[0] for a, b in zip(tabs, tabs[1:])), "tabs overlap")
            bar = {a[1] for r, x0, x1, a in f.hits if a[0] == "key" and r == 22}
            self.assertEqual(bar, {"a", "i", "p", "s", "q"})  # Tổng quan action bar
            self.assertIn(("key", "g"), [a for r, x0, x1, a in f.hits if 2 <= r < 22])  # Mục tiêu card
            self.assertTrue(all(x1 <= w for r, x0, x1, a in f.hits))

    def test_hit_map_list_rows(self):
        tui.switch_tab(self.state, 2, self.api)
        for w in (80, 140):
            f = frame(self.state, w)
            rows = {a[1]: r for r, x0, x1, a in f.hits if a[0] == "select"}
            self.assertEqual(rows[0], 4)  # header, tabs, month nav, column titles, first item
            self.assertEqual(len(rows), 24 - 4 - 2)
            self.assertEqual(tui.hit_at(f.hits, 6, w - 1), ("select", 2))
            self.assertIn("40.000 ₫", f.lines[4].plain)  # newest first

    def test_scroll_keeps_selection_visible(self):
        tui.switch_tab(self.state, 2, self.api)
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
        click(self.state, ("tab", 3), self.api)
        self.assertEqual(self.state.tab, 3)
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
                                                     "note": "xe buýt", "date": "2026-11-06", "account": "Tiền mặt"}])
        self.assertTrue(self.state.status[1])

    def test_inline_errors_keep_form_open(self):
        tui.dispatch(self.state, "i", self.api)
        for ch in "abc":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        out = text(frame(self.state))
        self.assertIn("Số tiền không hợp lệ", out)
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
        click(self.state, ("tab", 2), self.api)
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


class KeyReaderTest(unittest.TestCase):
    """The real reader over pipes (catches name clashes with the select module, timeouts, resize)."""

    def test_events_tick_and_resize(self):
        rd, wr = os.pipe()
        wake_r, wake_w = os.pipe()
        self.addCleanup(lambda: [os.close(fd) for fd in (rd, wr, wake_r, wake_w)])
        reader = tui.KeyReader(rd, wake_r)
        os.write(wr, "a\x1b[<0;3;4Mă".encode())
        self.assertEqual(reader.next(None), "a")
        self.assertEqual(reader.next(None), ("mouse", 0, 3, 4))
        self.assertEqual(reader.next(None), "ă")
        self.assertEqual(reader.next(0.01), "tick")  # nothing pending: the animation timer expires
        os.write(wake_w, b"x")
        self.assertEqual(reader.next(None), "resize")


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
                marks = [m for m in (tui.TABS_SHORT[i], tui.G["tabs"][i], str(i + 1)) if m]
                self.assertTrue(any(m in label for m in marks), (what, label))
            if a[0] == "key" and a[1] not in ("enter", "esc"):
                self.assertIn(a[1], label, (what, label))
        return f

    def test_every_screen_at_every_size(self):
        for w, h in self.SIZES:
            for tab in range(5):
                tui.switch_tab(self.state, tab, self.api)
                self.state.selected = 0 if tab in (1, 2, 3, 4, 5) else None
                self.check(w, h, (w, h, "tab", tab))
            tui.handle_key(self.state, "p", self.api)
            for key in ["tab"] * 3 + ["right"] * 3 + ["tab"] * 2:  # Lặp = Hàng tháng, focus Ngày bắt đầu
                tui.handle_key(self.state, key, self.api)
            self.assertEqual((self.state.form.values["every"], self.state.form.focus), ("monthly", "due"))
            self.check(w, h, (w, h, "plan form"))
            tui.handle_key(self.state, "esc", self.api)
            tui.switch_tab(self.state, 2, self.api)
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
        tui.switch_tab(self.state, 2, self.api)
        self.assertIn("#40", text(frame(self.state, 140, 30)))
        self.assertNotIn("#40", text(frame(self.state, 80, 24)))
        self.assertIn("06/11", text(frame(self.state, 50, 20)) + "06/11")  # short dates in compact mode
        tui.switch_tab(self.state, 3, self.api)
        self.assertIn("Danh mục", text(frame(self.state, 140, 30)))
        self.assertIn("hàng tháng · ngày 5", text(frame(self.state, 80, 24)))
        self.assertNotIn("hàng tháng", text(frame(self.state, 50, 20)))

    def test_lists_use_spare_rows(self):
        tui.switch_tab(self.state, 2, self.api)
        for h in (12, 24, 45):
            rows = [a for _, _, _, a in frame(self.state, 100, h).hits if a[0] == "select"]
            self.assertEqual(len(rows), min(40, h - 6))

    def test_header_mood(self):
        self.addCleanup(tui.set_icons, "symbol")
        for mode, faces in (("emoji", ("(｡•́︿•̀｡)", "(・_・;)", "(◕‿◕)")), ("symbol", ("(T_T)", "(o_o;)", "(^_^)"))):
            tui.set_icons(mode)
            self.state.dash = DASH  # FakeApi forecast goes negative
            self.assertIn(faces[0], text(frame(self.state)).splitlines()[0])
            self.state.dash = {"lowest": None, "budgets": [{"pct": 85.0}]}
            self.assertIn(faces[1], text(frame(self.state)).splitlines()[0])
            self.state.dash = {"lowest": None, "budgets": [{"pct": 10.0}]}
            self.assertIn(faces[2], text(frame(self.state)).splitlines()[0])

    def test_category_icons(self):
        cases = {"Ăn uống": "🍜", "tiền nhà": "🏠", "xăng xe": "🛵", "Lương": "💰", "mua sắm": "🛒", "học": "📚",
                 "điện nước": "💡", "Claude Pro": "💻", "khác": "•", "thuận": "•"}
        symbols = {"Ăn uống": "♨", "tiền nhà": "⌂", "Lương": "★", "Claude Pro": "⚙", "khác": "•"}
        for name, icon in cases.items():
            self.assertEqual(tui.category_icon(name, "emoji"), icon, name)
        for name, icon in symbols.items():
            self.assertEqual(tui.category_icon(name, "symbol"), icon, name)
        self.addCleanup(tui.set_icons, "symbol")
        tui.set_icons("emoji")
        self.assertEqual(cell_len(tui.cat_label("khác")), cell_len("🍜 khác"))  # aligned with emoji icons
        tui.set_icons("symbol")
        self.assertEqual(tui.cat_label("ăn uống"), "♨ ăn uống")

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


class NarrowMoneyTest(unittest.TestCase):
    """At narrow widths a line may shorten its amounts, but never crop one."""
    LONG = "Tiền thuê nhà chung cư cao cấp tháng mười một"

    def setUp(self):
        self.api = FakeApi()
        self.dash = dict(DASH, lowest={"date": "2027-01-11", "balance": -30_285_000},
                         overdue=[{"name": self.LONG, "due_date": "2026-11-01"}])
        self.patch = mock.patch.dict(DASH, self.dash)
        self.patch.start()
        self.state = tui.State(TODAY)
        self.state.now = 1000.0
        tui.init(self.state, self.api)

    def tearDown(self):
        self.patch.stop()

    def assert_no_cut_money(self, f, what):
        for line in f.lines:
            plain = line.plain
            for m in re.finditer(r"[+-]?\d{1,3}(?:\.\d{3})+", plain):
                self.assertTrue(plain[m.end():].startswith(" ₫"), (what, plain))

    def screens(self, w, h):
        for tab in range(4):
            tui.switch_tab(self.state, tab, self.api)
            yield "tab%d" % tab, frame(self.state, w, h)
        tui.switch_tab(self.state, 1, self.api)
        self.state.selected = 0
        tui.handle_key(self.state, "x", self.api)
        yield "confirm", frame(self.state, w, h)
        tui.handle_key(self.state, "n", self.api)
        tui.handle_key(self.state, "p", self.api)
        for ch in self.LONG:
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "tab", self.api)
        for ch in "5tr":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "tab", self.api)
        for ch in "nhà":
            tui.dispatch(self.state, ch, self.api)
        tui.dispatch(self.state, "enter", self.api)
        self.state.now += 0.5  # toast fully popped in
        yield "after save (status + toast)", frame(self.state, w, h)

    def test_no_line_drops_its_money_at_50_and_60(self):
        for w in (50, 60):
            self.state.status = ("", True)
            for what, f in self.screens(w, 24):
                self.assert_no_cut_money(f, (w, what))
                for line in f.lines:
                    self.assertEqual(cell_len(line.plain), w)

    def test_short_warning_and_status_keep_amount(self):
        for w in (50, 60):
            tui.switch_tab(self.state, 0, self.api)
            out = text(frame(self.state, w, 24))
            self.assertIn("Âm tiền 11/01: -30,3tr", out)
        f = dict(self.screens(50, 24))["after save (status + toast)"]
        status = f.lines[-1].plain.rstrip()
        self.assertTrue(status.endswith("-5tr"), status)
        if tui.anim is not None:
            toast = next(l.plain for l in f.lines[:-2] if "Đã lưu" in l.plain)
            self.assertIn("-5tr", toast)

    def test_wide_keeps_full_warning(self):
        self.assertIn("Sẽ âm tiền ngày 11/01/2027 (thấp nhất -30.285.000 ₫)", text(frame(self.state, 100, 30)))


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
        self.addCleanup(tui.set_icons, "symbol")
        tui.set_icons("emoji")  # anim's own sparkle glyphs
        self.state.now = 300.0
        before = self.state.balance
        self.save_expense()
        self.assertIsNotNone(self.state.sparkle)
        self.state.balance = before - 50_000  # FakeApi balance does not change; simulate the new value
        self.state.count = (before, before - 50_000, 300.0)
        mid = self.at(300.2)
        sparks = set(tui.anim.UNICODE_SPARKLES) - set("+*.")  # anim's own glyphs (they evolve)
        self.assertTrue(sparks & set(text(mid)), sparks)
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
        tui.switch_tab(self.state, 4, self.api)
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


class EditTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.init(self.state, self.api)

    def retype(self, field, value):
        click(self.state, ("focus", field), self.api)
        for _ in range(len(self.state.form.values[field])):
            tui.dispatch(self.state, "backspace", self.api)
        for ch in value:
            tui.dispatch(self.state, ch, self.api)

    def test_button_only_with_a_selection(self):
        click(self.state, ("tab", 2), self.api)
        self.assertNotIn(("key", "e"), [a for *_, a in frame(self.state).hits])
        tui.dispatch(self.state, "e", self.api)
        self.assertIsNone(self.state.form)
        click(self.state, ("select", 0), self.api)
        self.assertIn("✎ Sửa", text(frame(self.state)))
        click(self.state, ("tab", 0), self.api)
        self.assertNotIn(("key", "e"), [a for *_, a in frame(self.state).hits])

    def test_prefill_and_save_transaction_by_clicks(self):
        click(self.state, ("tab", 2), self.api)
        click(self.state, ("select", 0), self.api)  # newest first: #40
        click(self.state, ("key", "e"), self.api)
        form = self.state.form
        self.assertEqual(form.values, {"amount": "40.000", "category": "ăn", "account": "", "note": "n40", "date": "13/10/2026",
                                       "kind": "expense"})
        self.assertIn("Sửa giao dịch #40", text(frame(self.state)))
        click(self.state, ("chip", "kind", "income"), self.api)
        self.retype("amount", "45k")
        click(self.state, ("key", "enter"), self.api)
        self.assertIsNone(self.state.form)
        self.assertEqual(self.api.made("edit"), [{"id": 40, "amount": 45_000, "category": "ăn", "note": "n40",
                                                  "date": "2026-10-13", "kind": "income"}])
        self.assertIn("Đã sửa giao dịch #40", self.state.status[0])
        self.assertIn("+45.000 ₫", self.state.status[0])
        tui.sfx.play.assert_called_with("warn", enabled=True)  # save sound (FakeApi forecast is negative)

    def test_edit_by_keys_keeps_values(self):
        for key in ("3", "j", "j", "e"):
            tui.dispatch(self.state, key, self.api)
        self.assertEqual(self.state.form.title, "Sửa giao dịch #39")
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("edit"), [{"id": 39, "amount": 39_000, "category": "ăn", "note": "n39",
                                                  "date": "2026-10-12", "kind": "expense"}])

    def test_note_can_be_cleared(self):
        for key in ("3", "j", "e"):
            tui.dispatch(self.state, key, self.api)
        self.retype("note", "")
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("edit")[0]["note"], "")

    def test_double_click_opens_edit(self):
        click(self.state, ("tab", 2), self.api)
        self.state.now = 10.0
        click(self.state, ("select", 2), self.api)
        self.state.now = 11.0  # too slow: just a second selection
        click(self.state, ("select", 2), self.api)
        self.assertIsNone(self.state.form)
        self.state.now = 11.2
        click(self.state, ("select", 2), self.api)
        self.assertEqual(self.state.form.edit_id, 38)

    def test_plan_edit_prefill_and_new_day(self):
        click(self.state, ("tab", 3), self.api)
        click(self.state, ("select", 1), self.api)
        click(self.state, ("key", "e"), self.api)
        form = self.state.form
        self.assertEqual(form.values, {"name": "lương", "amount": "50", "category": "luong", "every": "monthly",
                                       "day": "5", "due": "05/12/2026", "kind": "income"})
        self.assertIn("Sửa dòng tiền #8", text(frame(self.state, 100, 40)))
        click(self.state, ("chip", "day", "10"), self.api, 100, 40)
        self.assertEqual(form.values["due"], "")  # api moves the due date to the new day
        tui.dispatch(self.state, "enter", self.api)
        self.assertEqual(self.api.made("plan edit"), [{"id": 8, "name": "lương", "amount": 50, "category": "luong",
                                                       "day": 10, "every": "monthly", "kind": "income"}])
        self.assertIn("Đã sửa dòng tiền", self.state.status[0])

    def test_plan_edit_to_once_drops_day(self):
        for key in ("4", "j", "j", "e"):
            tui.dispatch(self.state, key, self.api)
        click(self.state, ("chip", "every", "once"), self.api, 100, 40)
        tui.dispatch(self.state, "enter", self.api)
        params = self.api.made("plan edit")[0]
        self.assertNotIn("day", params)
        self.assertEqual((params["every"], params["due"]), ("once", "2026-12-05"))

    def test_edit_api_error_keeps_form(self):
        self.api.fail = LookupError("không tìm thấy giao dịch #40")
        for key in ("3", "j", "e", "enter"):
            tui.dispatch(self.state, key, self.api)
        self.assertIsNotNone(self.state.form)
        self.assertIn("không tìm thấy giao dịch #40", text(frame(self.state)))


class IconModeTest(unittest.TestCase):
    BANNED = set("⋆✦✧✿˚♡☆") | set(getattr(tui.anim, "UNICODE_SPARKLES", ())) - set("+*.·")

    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        self.state.now = 50.0
        tui.init(self.state, self.api)
        self.addCleanup(tui.set_icons, "symbol")

    def all_frames(self, w=120, h=32):
        out = []
        for tab in range(4):
            tui.switch_tab(self.state, tab, self.api)
            self.state.selected = 0 if tab in (1, 2) else None
            out.append(text(frame(self.state, w, h)))
        tui.dispatch(self.state, "p", self.api)
        out.append(text(frame(self.state, w, h)))
        tui.dispatch(self.state, "esc", self.api)
        tui.dispatch(self.state, "s", self.api)
        out.append(text(frame(self.state, w, h)))
        tui.dispatch(self.state, "esc", self.api)
        self.state.now = 60.0
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "amount", "50k"), self.api, w, h)
        click(self.state, ("chip", "category", "nhà"), self.api, w, h)
        tui.dispatch(self.state, "enter", self.api)  # toast/popup + sparkle
        for t in (60.2, 60.5, 61.5):
            self.state.now = t
            out.append(text(frame(self.state, w, h)))
        return "\n".join(out)

    def test_symbol_mode_is_font_safe(self):
        self.assertEqual(tui.ICON_MODE, "symbol")  # the default
        out = self.all_frames()
        wide = sorted({ch for ch in out if ord(ch) >= 0x1F000 or cell_len(ch) > 1})
        self.assertEqual(wide, [])
        self.assertFalse(self.BANNED & set(out))
        self.assertFalse([ch for ch in out if 0xFF61 <= ord(ch) <= 0xFF9F])  # half-width kana
        for mark in ("⌂", "⇄", "↻", "◎", "♪ bật", "♨ ăn uống"):
            self.assertIn(mark, out)

    def test_emoji_mode(self):
        tui.set_icons("emoji")
        out = self.all_frames()
        self.assertIn("🏠", out)
        self.assertIn("🍜 ăn", out)
        self.assertIn("🔊", out)

    def test_off_mode(self):
        tui.set_icons("off")
        out = self.all_frames()
        for mark in ("⌂", "🏠", "♨", "🍜", "♪", "🔊"):
            self.assertNotIn(mark, out)
        self.assertIn("Âm: bật", out)
        self.assertFalse([ch for ch in out if ord(ch) >= 0x1F000])

    def test_I_cycles_and_persists(self):
        modes = []
        for _ in range(3):
            tui.dispatch(self.state, "I", self.api)
            modes.append(tui.ICON_MODE)
        self.assertEqual(modes, ["emoji", "off", "symbol"])
        self.assertEqual([p["mode"] for p in self.api.made("icons") if p], ["emoji", "off", "symbol"])

    def test_settings_chips(self):
        click(self.state, ("key", "s"), self.api, 80, 24)
        self.assertTrue(self.state.settings)
        click(self.state, ("set", "icons", "emoji"), self.api, 80, 24)
        self.assertEqual(tui.ICON_MODE, "emoji")
        self.assertEqual(self.api.made("icons")[-1], {"mode": "emoji"})
        self.assertIn("📈", text(frame(self.state)))
        click(self.state, ("set", "icons", "off"), self.api, 80, 24)
        self.assertEqual(tui.ICON_MODE, "off")
        click(self.state, ("key", "esc"), self.api, 80, 24)
        self.assertFalse(self.state.settings)

    def test_env_overrides_stored_mode(self):
        with mock.patch.dict(os.environ, {"ECO_ICONS": "emoji"}):
            tui.init(tui.State(TODAY), self.api)
        self.assertEqual(tui.ICON_MODE, "emoji")
        with mock.patch.dict(os.environ, {"ECO_ICONS": "bogus"}):
            tui.init(tui.State(TODAY), self.api)
        self.assertEqual(tui.ICON_MODE, "symbol")  # invalid env value: stored setting


class FakePixel:
    """Stand-in for anim.PixelPopup: a 2-line box, None when narrow (forces the toast fallback)."""
    duration = 1.6
    made = []

    def __init__(self, icon, title, subtitle="", color=None, *, glyphs="symbol", seed=0):
        self.icon, self.title, self.subtitle, self.glyphs = icon, title, subtitle, glyphs
        FakePixel.made.append(self)

    def frame(self, t, width, height):
        if t >= self.duration or width < 60:
            return None
        lines = [Text("[%s] %s" % (self.icon, self.title)), Text(self.subtitle or "-")]
        w = max(l.cell_len for l in lines)
        return (height - 2) // 2, (width - w) // 2, lines


@unittest.skipIf(tui.anim is None, "anim.py not available")
class PixelPopupTest(unittest.TestCase):
    def setUp(self):
        FakePixel.made = []
        patcher = mock.patch.object(tui.anim, "PixelPopup", FakePixel, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        self.state.now = 10.0
        tui.init(self.state, self.api)

    def save(self, w=100, h=30):
        tui.dispatch(self.state, "a", self.api)
        click(self.state, ("chip", "amount", "50k"), self.api, w, h)
        click(self.state, ("chip", "category", "nhà"), self.api, w, h)
        tui.dispatch(self.state, "enter", self.api)

    def test_popups_for_each_event(self):
        self.save()
        tui.dispatch(self.state, "4", self.api)  # keys dismiss the popup and still act
        tui.dispatch(self.state, "j", self.api)
        tui.dispatch(self.state, "d", self.api)
        tui.dispatch(self.state, "3", self.api)
        tui.dispatch(self.state, "j", self.api)
        tui.dispatch(self.state, "e", self.api)
        tui.dispatch(self.state, "enter", self.api)
        tui.dispatch(self.state, "j", self.api)
        tui.dispatch(self.state, "x", self.api)
        tui.dispatch(self.state, "y", self.api)
        tui.dispatch(self.state, "a", self.api)
        tui.dispatch(self.state, "enter", self.api)  # validation error
        got = [(p.icon, p.title) for p in FakePixel.made]
        self.assertEqual(got, [("check", "Đã lưu!"), ("coin", "Đã thanh toán!"), ("pencil", "Đã sửa!"),
                               ("trash", "Đã xoá"), ("cross", "Kiểm tra lại các ô được đánh dấu ▲")])
        self.assertEqual(FakePixel.made[0].subtitle, "nhà -50.000 ₫")
        self.assertEqual(FakePixel.made[0].glyphs, "symbol")

    def test_centered_over_body_without_toast(self):
        self.save()
        self.state.now += 0.3
        f = frame(self.state, 100, 30)
        rows = [r for r, t in enumerate(f.lines) if "[check] Đã lưu!" in t.plain]
        self.assertEqual(rows, [2 + (26 - 2) // 2])
        self.assertFalse(any("Đã lưu khoản chi" in t.plain for t in f.lines[:-2]))  # no corner toast
        self.assertTrue(self.state.animating())

    def test_falls_back_to_toast_when_it_does_not_fit(self):
        self.save(50, 24)
        self.state.now += 0.3
        out = text(frame(self.state, 50, 24))
        self.assertNotIn("[check]", out)
        self.assertTrue(any("Đã lưu khoản" in l for l in out.splitlines()[:-2]))

    def test_key_dismisses_and_still_acts(self):
        self.save()
        self.state.now += 0.2
        tui.dispatch(self.state, "2", self.api)
        self.assertIsNone(self.state.popup)
        self.assertEqual(self.state.tab, 1)
        self.assertNotIn("[check]", text(frame(self.state, 100, 30)))

    def test_click_only_dismisses(self):
        self.save()
        self.state.now += 0.2
        click(self.state, ("tab", 2), self.api, 100, 30)
        self.assertIsNone(self.state.popup)
        self.assertEqual(self.state.tab, 0)  # the click did not reach the tab underneath
        click(self.state, ("tab", 2), self.api, 100, 30)
        self.assertEqual(self.state.tab, 2)

    def test_finished_popup_hides_fallback_and_stops_animating(self):
        self.save()
        self.state.now += 1.7
        out = text(frame(self.state, 100, 30))
        self.assertNotIn("[check]", out)
        self.assertFalse(any("Đã lưu khoản" in l for l in out.splitlines()[:-2]))
        self.assertFalse(self.state.animating())


@unittest.skipUnless(REAL_PIXEL is not None, "anim.PixelPopup not landed")
class RealPixelPopupTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(tui.anim, "PixelPopup", REAL_PIXEL)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_long_subtitle_keeps_its_amount(self):
        api = FakeApi()
        state = tui.State(TODAY)
        state.now = 1.0
        tui.init(state, api)
        tui.dispatch(state, "p", api)
        for value in ("Tiền thuê nhà chung cư cao cấp tháng mười một", "5tr", "nhà"):
            for ch in value:
                tui.dispatch(state, ch, api)
            tui.dispatch(state, "tab", api)
        tui.dispatch(state, "enter", api)
        state.now = 2.0  # hold phase: title + subtitle visible
        out = text(frame(state, 120, 40))
        self.assertIn("Đã lưu!", out)
        self.assertTrue(any("-5tr" in l or "-5.000.000 ₫" in l for l in out.splitlines()[:-2]), out)
        for m in re.finditer(r"[+-]?\d{1,3}(?:\.\d{3})+", out):
            self.assertTrue(out[m.end():].startswith(" ₫"), out)

    def test_symbol_popup_is_font_safe(self):
        api = FakeApi()
        state = tui.State(TODAY)
        state.now = 1.0
        tui.init(state, api)
        tui.dispatch(state, "a", api)
        tui.dispatch(state, "enter", api)  # error → cross popup
        chars = set()
        for t in (1.05, 1.3, 1.8, 2.4):
            state.now = t
            chars |= set(text(frame(state, 120, 40)))
        self.assertFalse([ch for ch in chars if ord(ch) >= 0x1F000 or cell_len(ch) > 1])

    def test_real_popup_renders_and_fits(self):
        api = FakeApi()
        state = tui.State(TODAY)
        state.now = 5.0
        tui.init(state, api)
        tui.dispatch(state, "a", api)
        click(state, ("chip", "amount", "50k"), api, 120, 40)
        click(state, ("chip", "category", "nhà"), api, 120, 40)
        tui.dispatch(state, "enter", api)
        self.assertIsNotNone(state.popup)
        for t in (5.05, 5.4, 5.9, 6.4, 6.7):
            state.now = t
            for w, h in ((120, 40), (60, 20), (40, 12)):
                f = frame(state, w, h)
                self.assertEqual(len(f.lines), h)
                self.assertTrue(all(cell_len(l.plain) == w for l in f.lines))


class UiOnlyTest(unittest.TestCase):
    """v7: every CLI task reachable by clicks."""

    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.init(self.state, self.api)

    def keys_on_bar(self, w=100, h=30):
        return {a[1] for r, x0, x1, a in frame(self.state, w, h).hits if a[0] == "key" and r == h - 2}

    def test_budget_add_edit_delete_by_clicks(self):
        click(self.state, ("tab", 4), self.api)
        self.assertIn("b", self.keys_on_bar())
        click(self.state, ("key", "b"), self.api, 100, 30)
        self.assertEqual(self.state.form.name, "budget")
        click(self.state, ("chip", "category", "đi lại"), self.api, 100, 30)
        click(self.state, ("chip", "amount", "3tr"), self.api, 100, 30)
        click(self.state, ("key", "enter"), self.api, 100, 30)
        self.assertEqual(self.api.made("budget set"), [{"category": "đi lại", "amount": 3_000_000}])
        self.assertIn("Đã lưu ngân sách", self.state.status[0])
        click(self.state, ("select", 0), self.api)
        self.assertTrue({"e", "x"} <= self.keys_on_bar())
        click(self.state, ("key", "e"), self.api, 100, 30)
        self.assertEqual(self.state.form.title, "Sửa ngân sách: ăn uống")
        self.assertEqual(self.state.form.values, {"amount": "3.000.000"})
        click(self.state, ("chip", "amount", "5tr"), self.api, 100, 30)
        click(self.state, ("key", "enter"), self.api, 100, 30)
        self.assertEqual(self.api.made("budget set")[-1], {"category": "ăn uống", "amount": 5_000_000})
        click(self.state, ("select", 1), self.api)
        click(self.state, ("key", "x"), self.api, 100, 30)
        self.assertIn("Xoá ngân sách giải trí", text(frame(self.state, 100, 30)))
        click(self.state, ("key", "y"), self.api, 100, 30)
        self.assertEqual(self.api.made("budget delete"), [{"category": "giải trí"}])
        self.assertIn("Đã xoá ngân sách giải trí", self.state.status[0])

    def test_budget_month_nav(self):
        click(self.state, ("tab", 4), self.api)
        self.assertIn("Tháng 11/2026", text(frame(self.state)))
        click(self.state, ("month", "budget", -1), self.api)
        click(self.state, ("month", "budget", -1), self.api)
        self.assertEqual(self.api.made("budget status")[-1], {"month": "2026-09"})
        click(self.state, ("month", "budget", 1), self.api)
        self.assertEqual(self.api.made("budget status")[-1], {"month": "2026-10"})
        self.assertIn("Tháng 10/2026", text(frame(self.state)))
        tui.dispatch(self.state, "]", self.api)
        self.assertEqual(self.api.made("budget status")[-1], {"month": "2026-11"})

    def test_transactions_month_nav_and_all(self):
        click(self.state, ("tab", 2), self.api)
        self.assertIn("Mọi tháng", text(frame(self.state)))
        click(self.state, ("month", "tx", -1), self.api)
        self.assertEqual(self.api.made("list")[-1], {"month": "2026-11"})
        click(self.state, ("month", "tx", -1), self.api)
        self.assertEqual(self.api.made("list")[-1], {"month": "2026-10"})
        click(self.state, ("month", "tx", 0), self.api)
        self.assertEqual(self.api.made("list")[-1], {"all": True})

    def test_plan_filter_and_cancel_by_click(self):
        click(self.state, ("tab", 3), self.api)
        click(self.state, ("plans", True), self.api)
        self.assertEqual(self.api.made("plan list")[-1], {"all": True})
        out = text(frame(self.state))
        self.assertIn("học phí", out)
        self.assertIn("đã xong", out)
        click(self.state, ("select", 2), self.api)  # the done one: no Xong / Huỷ / Sửa
        self.assertFalse({"d", "c", "e"} & self.keys_on_bar())
        click(self.state, ("select", 0), self.api)
        self.assertTrue({"d", "c", "e"} <= self.keys_on_bar())
        click(self.state, ("key", "c"), self.api, 100, 30)
        self.assertIn("Huỷ dòng tiền laptop", text(frame(self.state, 100, 30)))
        click(self.state, ("key", "n"), self.api, 100, 30)
        self.assertEqual(self.api.made("plan cancel"), [])
        self.assertEqual(self.state.status[0], "Không huỷ")
        click(self.state, ("key", "c"), self.api, 100, 30)
        click(self.state, ("key", "y"), self.api, 100, 30)
        self.assertEqual(self.api.made("plan cancel"), [{"id": 7}])
        self.assertIn("Đã huỷ dòng tiền", self.state.status[0])

    def test_overview_spending_by_category(self):
        out = text(frame(self.state, 80, 30))
        self.assertIn("Chi theo danh mục", out)
        self.assertIn("71%", out)  # 60k of 85k
        self.assertIn("xăng xe", out)

    def test_goal_card_and_form(self):
        self.assertIn("Mục tiêu tiết kiệm: chưa đặt", text(frame(self.state, 100, 30)))
        click(self.state, ("key", "g"), self.api, 100, 30)
        self.assertEqual(self.state.form.name, "goal")
        click(self.state, ("chip", "amount", "50tr"), self.api, 100, 30)
        click(self.state, ("focus", "by"), self.api, 100, 30)
        click(self.state, ("chip", "by", "31/12/2026"), self.api, 100, 40)
        click(self.state, ("key", "enter"), self.api, 100, 40)
        self.assertEqual(self.api.made("goal"), [{"target": 50_000_000, "by": "2026-12-31"}])
        out = text(frame(self.state, 100, 30))
        self.assertIn("Mục tiêu 50tr trước 31/12/2026: cần 13,1tr/tháng (2 tháng)", out)
        click(self.state, ("key", "g"), self.api, 100, 30)  # edit: prefilled
        self.assertEqual(self.state.form.values, {"amount": "50.000.000", "by": "31/12/2026"})

    def test_multiple_goal_jars_rendering(self):
        self.state.goals = [
            {"id": 1, "name": "Laptop", "target": 30_000_000, "saved": 15_000_000,
             "by": "2027-12-31", "remaining": 15_000_000, "pct": 50.0, "per_month": 1_071_429,
             "days_left": 420, "on_track": True},
            {"id": 2, "name": "Du lịch", "target": 10_000_000, "saved": 2_000_000,
             "by": "2027-06-30", "remaining": 8_000_000, "pct": 20.0, "per_month": 1_000_000,
             "days_left": 236, "on_track": True},
        ]
        self.state.total_saved = 17_000_000
        out = text(frame(self.state, 100, 30))
        self.assertIn("Tiền tự do", out)
        self.assertIn("Laptop", out)
        self.assertIn("50%", out)
        self.assertIn("Du lịch", out)
        self.assertIn("20%", out)

    def test_savings_jars_tab_and_take_form(self):
        # Switch to Hũ tiết kiệm (tab 5, key '6')
        tui.switch_tab(self.state, 5, self.api)
        self.assertEqual(self.state.tab, 5)
        out = text(frame(self.state, 100, 30))
        self.assertIn("Hũ tiết kiệm", out)
        self.assertIn("Tiền tự do", out)
        self.assertIn("Laptop", out)
        self.assertIn("+ Góp", out)
        self.assertIn("- Rút", out)

        # Open '- Rút' form for Laptop (id=1)
        click(self.state, ("key", "goal_take:1"), self.api, 100, 30)
        self.assertEqual(self.state.form.name, "goal_take")
        self.assertEqual(self.state.form.edit_id, 1)

        # Enter withdrawal amount and submit
        click(self.state, ("chip", "amount", "1tr"), self.api, 100, 30)
        click(self.state, ("key", "enter"), self.api, 100, 30)
        self.assertEqual(self.api.made("goal take"), [{"id": 1, "amount": 1_000_000}])

    def test_chart_milestones_and_quick_jump(self):
        # Switch to Biểu đồ (tab 6, key '7')
        tui.switch_tab(self.state, 6, self.api)
        self.assertEqual(self.state.tab, 6)
        out = text(frame(self.state, 100, 30))
        # Milestone chips exist on chart
        self.assertIn("Hôm nay", out)
        self.assertIn("Cuối T", out)

        # Clicking a milestone jump action sets the cursor
        f = frame(self.state, 100, 30)
        jump_actions = [a for *_, a in f.hits if a[0] == "chart_jump"]
        self.assertTrue(len(jump_actions) >= 2, jump_actions)
        target_idx = jump_actions[0][1]
        click(self.state, jump_actions[0], self.api, 100, 30)
        self.assertEqual(self.state.chart["cursor"], target_idx)

        # Keyboard shortcuts: '[' / ']' for step 7 days, Home/End
        tui.dispatch(self.state, "]", self.api)
        self.assertEqual(self.state.chart["cursor"], target_idx + 7)
        tui.dispatch(self.state, "[", self.api)
        self.assertEqual(self.state.chart["cursor"], target_idx)
        tui.dispatch(self.state, "0", self.api)
        # 0 or Home jumps to today's index in series
        n_hist = len((self.state.data.get(6) or {}).get("series") or [])
        self.assertEqual(self.state.chart["cursor"], max(0, n_hist - 1))

    def test_every_size_still_exact(self):
        for w, h in ((40, 12), (50, 20), (80, 24), (170, 45)):
            for tab in range(len(tui.TABS)):
                tui.switch_tab(self.state, tab, self.api)
                f = frame(self.state, w, h)
                self.assertEqual(len(f.lines), h)
                self.assertTrue(all(cell_len(l.plain) == w for l in f.lines), (w, tab))
                self.assertTrue(all(0 <= x0 < x1 <= w for r, x0, x1, a in f.hits), (w, tab))
            tui.dispatch(self.state, "s", self.api)
            self.assertEqual(len(frame(self.state, w, h).lines), h)
            tui.dispatch(self.state, "esc", self.api)


class ChartTabTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        tui.init(self.state, self.api)
        tui.dispatch(self.state, "7", self.api)

    def test_loads_history_and_fills_rows(self):
        self.assertEqual(self.state.tab, 6)
        self.assertEqual(self.api.made("history")[-1], {"days": 90, "ahead": 30})
        for w, h in ((50, 20), (100, 30), (160, 45)):
            f = frame(self.state, w, h)
            plot = [r for r, x0, x1, a in f.hits if a == ("plot",)]
            chips = {r for r, x0, x1, a in f.hits if a[0] in ("chartset", "chart_jump")}
            self.assertEqual(len(plot) + len(chips), h - 4, (w, h))  # chips + chart use every body row
            self.assertTrue(all(cell_len(l.plain) == w for l in f.lines))

    @unittest.skipIf(tui.chart_mod is None, "chart.py not available")
    def test_range_forecast_mode_chips(self):
        click(self.state, ("chartset", "days", "30"), self.api, 100, 30)
        self.assertEqual(self.api.made("history")[-1], {"days": 30, "ahead": 30})
        click(self.state, ("chartset", "ahead", "90"), self.api, 100, 30)
        self.assertEqual(self.api.made("history")[-1], {"days": 30, "ahead": 90})
        n = len(self.api.made("history"))
        click(self.state, ("chartset", "mode", "candle"), self.api, 100, 30)
        self.assertEqual(len(self.api.made("history")), n)  # mode change needs no reload
        hits = [a for *_, a in frame(self.state, 100, 30).hits]
        self.assertIn(("chartset", "bucket", "month"), hits)
        click(self.state, ("chartset", "bucket", "month"), self.api, 100, 30)
        self.assertEqual(self.state.chart["bucket"], "month")
        self.assertEqual(len(frame(self.state, 100, 30).lines), 30)

    @unittest.skipIf(tui.chart_mod is None, "chart.py not available")
    def test_plot_click_and_arrows_move_cursor(self):
        f = frame(self.state, 100, 30)
        row = next(r for r, x0, x1, a in f.hits if a == ("plot",))
        x0, y0, x1, y1 = self.state.chart_obj.plot_box
        col = (x0 + x1) // 2
        tui.dispatch(self.state, ("mouse", 0, col + 1, row + 1), self.api)
        expected = self.state.chart_obj.index_at(col)
        self.assertIsNotNone(expected)
        self.assertEqual(self.state.chart["cursor"], expected)
        tui.dispatch(self.state, "right", self.api)
        self.assertEqual(self.state.chart["cursor"], expected + 1)
        tui.dispatch(self.state, "left", self.api)
        tui.dispatch(self.state, "left", self.api)
        self.assertEqual(self.state.chart["cursor"], expected - 1)
        frame(self.state, 100, 30)  # tooltip renders
        tui.dispatch(self.state, "esc", self.api)
        self.assertIsNone(self.state.chart["cursor"])

    def test_fallback_without_chart_module(self):
        with mock.patch.object(tui, "chart_mod", None):
            out = text(frame(self.state, 80, 24))
        self.assertIn("thấp", out)

    def test_overview_sparkline_opens_chart(self):
        tui.dispatch(self.state, "1", self.api)
        click(self.state, ("tab", 6), self.api, 170, 40)  # the tab itself
        tui.dispatch(self.state, "1", self.api)
        f = frame(self.state, 170, 40)
        spark = [r for r, x0, x1, a in f.hits if a == ("tab", 6) and r > 1]
        self.assertTrue(spark)  # the 30-day sparkline row links to Biểu đồ


@unittest.skipIf(tui.anim is None or REAL_VFX["Ripple"] is None, "anim VFX not available")
class VfxTest(unittest.TestCase):
    def setUp(self):
        for name, real in REAL_VFX.items():
            patcher = mock.patch.object(tui.anim, name, real)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.api = FakeApi()
        self.state = tui.State(TODAY)
        self.state.now = 100.0
        tui.init(self.state, self.api)
        self.state.now = 110.0  # bar fill done
        frame(self.state, 100, 30)

    def test_click_has_no_visual_press_effect(self):
        tui.sfx.play.reset_mock()
        click(self.state, ("key", "s"), self.api, 100, 30)  # opens settings
        tui.sfx.play.assert_any_call("click", enabled=True)  # the soft ping stays
        self.assertFalse(self.state.animating())  # no ripple / press flash to wait for
        self.assertFalse(hasattr(self.state, "ripples") or hasattr(self.state, "press"))
        a = frame(self.state, 100, 30).lines
        self.state.now += 0.05
        b = frame(self.state, 100, 30).lines
        self.assertEqual([(l.plain, [str(s.style) for s in l.spans]) for l in a],
                         [(l.plain, [str(s.style) for s in l.spans]) for l in b])  # nothing changes over time

    def test_loop_stays_blocking_after_click(self):
        timeouts = []
        times = iter([110.0] * 8)
        f = frame(self.state, 100, 30)
        r, x0, x1, _ = next(h for h in f.hits if h[3] == ("key", "s"))
        events = iter([("mouse", 0, x0 + 2, r + 1), "tick", "q"])

        def next_event(timeout):
            timeouts.append(timeout)
            return next(events)

        def draw():
            self.state.hits = tui.build_frame(self.state, 100, 30).hits

        tui.run_loop(self.state, next_event, draw, self.api, lambda: next(times))
        self.assertTrue(all(t is None for t in timeouts), timeouts)  # nothing animates on a click

    def test_tab_underline_slides(self):
        f = frame(self.state, 120, 30)
        spans = {a[1]: (x0, x1) for r, x0, x1, a in f.hits if r == 1 and a[0] == "tab"}
        click(self.state, ("tab", 3), self.api, 120, 30)
        self.assertEqual(self.state.slide[:2], (0, 3))

        def underline_start():
            line = frame(self.state, 120, 30).lines[1]
            idx = tui._cell_index(line)
            return next(col for col in range(120) if any(
                "underline" in str(sp.style) and sp.start <= idx[col] < sp.end for sp in line.spans))
        self.state.now = 110.05
        mid = underline_start()
        self.state.now = 112.0
        self.assertEqual(underline_start(), spans[3][0])
        self.assertTrue(spans[0][0] < mid < spans[3][0], (spans, mid))

    def test_no_glow_on_new_selection(self):
        tui.dispatch(self.state, "2", self.api)
        self.state.now = 112.0  # tab slide over
        tui.dispatch(self.state, "j", self.api)
        self.assertFalse(self.state.animating())
        self.assertFalse(hasattr(self.state, "glow"))

    def test_symbol_mode_safe_with_vfx_and_chart(self):
        chars = set()
        for tab in range(5):
            tui.switch_tab(self.state, tab, self.api)
            self.state.selected = 0 if tab in (1, 2, 3) else None
            f = frame(self.state, 120, 30)
            r, x0, x1, a = f.hits[0]
            tui.dispatch(self.state, ("mouse", 0, x0 + 1, r + 1), self.api)
            for dt in (0.05, 0.15, 0.3):
                self.state.now += dt
                chars |= set(text(frame(self.state, 120, 30)))
        self.assertFalse(sorted(ch for ch in chars if ord(ch) >= 0x1F000 or cell_len(ch) > 1))


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
        return [c.args[0] for c in tui.sfx.play.call_args_list if c.args[0] != "click"]

    def test_events(self):
        click(self.state, ("tab", 3), self.api)
        click(self.state, ("select", 0), self.api)
        click(self.state, ("key", "d"), self.api)
        click(self.state, ("tab", 2), self.api)
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
        tui.dispatch(self.state, "s", self.api)
        self.assertIn("♪ bật", text(frame(self.state)))
        click(self.state, ("set", "sound", "off"), self.api)
        self.assertEqual(self.api.made("sound")[-1], {"state": "off"})
        self.assertFalse(self.state.sound)
        self.assertIn("♪ tắt", text(frame(self.state)))
        click(self.state, ("tab", 4), self.api)
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
        click(state, ("tab", 3), call)
        self.assertIn("hàng tháng · ngày 10", text(frame(state)))
        self.assertIn("10/11/2026", text(frame(state)))
        click(state, ("select", 0), call)
        click(state, ("key", "d"), call)
        self.assertEqual(state.balance, -1_000_000)
        click(state, ("tab", 2), call)
        click(state, ("select", 0), call)
        click(state, ("key", "x"), call)
        click(state, ("key", "y"), call)
        self.assertEqual(store.balance(TODAY), 2_000_000)
        for w, h in ((80, 24), (140, 40)):
            for tab in range(len(tui.TABS)):
                tui.switch_tab(state, tab, call)
                self.assertEqual(len(frame(state, w, h).lines), h)
        store.close()


if __name__ == "__main__":
    unittest.main()
