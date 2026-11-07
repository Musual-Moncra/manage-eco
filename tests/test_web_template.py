import unittest
import urllib.request
from datetime import date
from manage_eco.db import Store
from manage_eco.web import start_share_server

class WebTemplateTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.server = start_share_server(self.store, self.today, port=0, pin="5678")
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()

    def test_index_html_rendered(self):
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertEqual(resp.status, 200)
        self.assertIn("Manage Eco", content)
        self.assertIn("EventSource", content)
        self.assertIn("#1e1b2e", content)  # theme background color
        self.assertIn("tab-nav", content)
        self.assertIn("tab-content", content)
        self.assertIn("badge-live", content)

    def test_chart_tab_rendering_support(self):
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertIn("function renderChart", content)
        self.assertIn("currentSelectedTab === 'chart'", content)
