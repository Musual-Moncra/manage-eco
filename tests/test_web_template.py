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

    def test_initial_data_hydration_in_html(self):
        # Valid PIN should hydrate initialData in HTML for instant 0ms first render
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertIn('<script id="initialData" type="application/json">', content)
        self.assertIn('"allowed_tab_keys"', content)

        # Missing or invalid PIN should not hydrate state
        no_pin_url = f"http://127.0.0.1:{self.port}/"
        with urllib.request.urlopen(no_pin_url) as resp:
            content_no_pin = resp.read().decode("utf-8")
        self.assertNotIn('<script id="initialData"', content_no_pin)

    def test_web_template_contains_mutation_controls(self):
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertIn("fab-add", content)
        self.assertIn("modal-sheet", content)
        self.assertIn("submitAction", content)
