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
