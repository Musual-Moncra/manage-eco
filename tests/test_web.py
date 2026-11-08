import unittest
import urllib.request
import urllib.error
import json
import time
from datetime import date
from manage_eco.db import Store
from manage_eco.web import start_share_server

class WebServerTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.server = start_share_server(self.store, self.today, port=0, pin="1234")
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()

    def test_pin_protection_missing_pin(self):
        url = f"http://127.0.0.1:{self.port}/api/data"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 401)

    def test_pin_protection_wrong_pin(self):
        url = f"http://127.0.0.1:{self.port}/api/data?pin=wrong"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 401)

    def test_pin_lockout_after_5_failures(self):
        # 5 consecutive failures should trigger temporary lockout
        for _ in range(5):
            url = f"http://127.0.0.1:{self.port}/api/data?pin=wrong"
            try:
                urllib.request.urlopen(url)
            except urllib.error.HTTPError:
                pass
        # 6th request with correct PIN should now be rejected due to lockout
        correct_url = f"http://127.0.0.1:{self.port}/api/data?pin=1234"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(correct_url)
        self.assertEqual(ctx.exception.code, 401)

    def test_valid_pin_returns_json(self):
        url = f"http://127.0.0.1:{self.port}/api/data?pin=1234"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(resp.status, 200)
        self.assertIn("tabs", data)
        self.assertEqual(data["today"], "2026-11-08")

    def test_update_config_and_whitelist(self):
        self.server.update_config(allowed_tabs={"goals"}, active_tab="goals", sync_mode="follow")
        url = f"http://127.0.0.1:{self.port}/api/data?pin=1234"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(data["allowed_tab_keys"], ["goals"])
        self.assertIn("goals", data["tabs"])
        self.assertNotIn("overview", data["tabs"])
        self.assertEqual(data["sync_mode"], "follow")

    def test_sse_stream_connect_and_receive(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/api/stream?pin=1234")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Content-Type"), "text/event-stream")
        # Read the initial comment or event
        chunk = resp.fp.readline().decode()
        self.assertTrue(chunk.startswith(":") or chunk.startswith("event:"))
        conn.close()

    def test_action_endpoint_verifies_pin(self):
        url = f"http://127.0.0.1:{self.port}/api/action?pin=wrong"
        payload = json.dumps({"action": "expense", "params": {"amount": "50k"}}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 401)

    def test_action_endpoint_forbidden_without_permission(self):
        # Server default allowed_edits is {"expense"}. "cashflow" is not permitted.
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        payload = json.dumps({"action": "plan_done", "params": {"id": 1}}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 403)

    def test_action_endpoint_executes_expense_when_permitted(self):
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        payload = json.dumps({"action": "expense", "params": {"amount": "50k", "category": "food", "note": "cafe"}}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(resp.status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["command"], "expense")

    def test_action_endpoint_triggers_on_mutation_callback(self):
        mutated = []
        self.server.on_mutation = lambda: mutated.append(True)
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        payload = json.dumps({"action": "expense", "params": {"amount": "20k", "category": "other"}}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req):
            pass
        self.assertEqual(len(mutated), 1)
