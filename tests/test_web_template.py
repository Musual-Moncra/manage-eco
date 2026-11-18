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
        self.assertIn("inputAccount", content)
        self.assertIn("groupAccount", content)
        self.assertIn("escapeHtml", content)
        self.assertIn("promptGoalSave(${g.id})", content)
        self.assertIn("updateAccountSelect", content)

    def test_transactions_large_dataset_support(self):
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertIn("txSearchInput", content)
        self.assertIn("loadMoreTx", content)
        self.assertIn("loadAllTx", content)
        self.assertIn("escapeHtml(t.category", content)
        self.assertIn("escapeHtml(t.note", content)

    def test_transactions_with_many_items_e2e(self):
        from manage_eco.models import Transaction
        import json
        self.server.update_config(allowed_tabs={"transactions", "overview"})
        # Add 75 transactions
        for i in range(75):
            self.store.add_transaction(Transaction(self.today, 10000 + i, "expense", "food", f"Item #{i}"))
        
        # Verify API returns all 75 transactions
        api_url = f"http://127.0.0.1:{self.port}/api/data?pin=5678"
        with urllib.request.urlopen(api_url) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        txs = data["tabs"]["transactions"]["transactions"]
        self.assertEqual(len(txs), 75)

        # Verify HTML hydration includes all items without truncation
        html_url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(html_url) as resp:
            html = resp.read().decode("utf-8")
        self.assertIn("Item #0", html)
        self.assertIn("Item #74", html)


