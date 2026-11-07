import unittest
from datetime import date
from manage_eco import tui
from manage_eco.db import Store

class TuiShareTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.state = tui.State(self.today)
        self.state.store = self.store

    def tearDown(self):
        if hasattr(self.state, "share_server") and self.state.share_server:
            self.state.share_server.stop()
        if hasattr(self.state, "share_tunnel") and self.state.share_tunnel:
            self.state.share_tunnel.stop()

    def test_tab_8_exists(self):
        self.assertIn("Chia sẻ", tui.TABS)
        self.assertEqual(len(tui.TABS), 8)

    def test_render_tab_8(self):
        self.state.tab = 7  # 0-indexed for 8th tab
        f = tui.build_frame(self.state, 80, 24)
        plain = "\n".join(l.plain for l in f.lines)
        self.assertIn("Chia sẻ", plain)
        self.assertIn("Tổng quan", plain)

    def test_toggle_sharing(self):
        self.assertFalse(self.state.share_active)
        self.state.toggle_share()
        self.assertTrue(self.state.share_active)
        self.assertIsNotNone(self.state.share_server)
        self.state.toggle_share()
        self.assertFalse(self.state.share_active)

    def test_toggle_tab_permission(self):
        self.assertIn("overview", self.state.share_allowed_tabs)
        self.state.toggle_share_tab("overview")
        self.assertNotIn("overview", self.state.share_allowed_tabs)
        self.state.toggle_share_tab("overview")
        self.assertIn("overview", self.state.share_allowed_tabs)

    def test_set_sync_mode(self):
        self.assertEqual(self.state.share_sync_mode, "free")
        self.state.set_share_sync_mode("follow")
        self.assertEqual(self.state.share_sync_mode, "follow")
