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

    def test_action_unauthorized_returns_json(self):
        url = f"http://127.0.0.1:{self.port}/api/action?pin=wrong"
        payload = json.dumps({"action": "expense", "params": {"amount": "50k"}}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 401")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 401)
            body = json.loads(err.read().decode())
            self.assertFalse(body["ok"])
            self.assertIn("PIN", body["error"])

    def test_action_endpoint_malformed_and_non_dict_payloads(self):
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        # Test non-dict array payload
        req = urllib.request.Request(url, data=b"[1, 2, 3]", headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 400")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 400)
            body = json.loads(err.read().decode())
            self.assertFalse(body["ok"])

        # Test non-dict params
        bad_params = json.dumps({"action": "expense", "params": "not a dict"}).encode("utf-8")
        req = urllib.request.Request(url, data=bad_params, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 400")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 400)
            body = json.loads(err.read().decode())
            self.assertFalse(body["ok"])

    def test_action_endpoint_payload_too_large(self):
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        huge_payload = b"x" * 70000
        req = urllib.request.Request(url, data=huge_payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            self.fail("Expected HTTPError 413")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 413)

    def test_action_endpoint_executes_plan_done_goal_save_tx_delete(self):
        from manage_eco import api
        # Setup initial plan, goal, and transaction
        p = api.execute("plan add", {"name": "TestPlan", "amount": 100000, "category": "bills", "due": "2026-11-10"}, self.store, self.today)
        plan_id = p["plan"]["id"]
        g = api.execute("goal add", {"name": "TestGoal", "target": 500000, "by": "2027-12-31"}, self.store, self.today)
        goal_id = g["goal"]["id"]
        tx = api.execute("expense", {"amount": 50000, "category": "food"}, self.store, self.today)
        tx_id = tx["transaction"]["id"]

        self.server.update_config(allowed_edits={"cashflow", "goals", "edit_tx", "expense"})
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"

        # 1. plan_done
        req = urllib.request.Request(url, data=json.dumps({"action": "plan_done", "params": {"id": plan_id}}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            self.assertTrue(data["ok"])
            self.assertEqual(data["command"], "plan done")

        # 2. goal_save
        req = urllib.request.Request(url, data=json.dumps({"action": "goal_save", "params": {"id": goal_id, "amount": "150k"}}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            self.assertTrue(data["ok"])
            self.assertEqual(data["command"], "goal save")

        # 3. tx_delete
        req = urllib.request.Request(url, data=json.dumps({"action": "tx_delete", "params": {"id": tx_id}}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            self.assertTrue(data["ok"])
            self.assertEqual(data["command"], "rm")

    def test_concurrent_actions_no_cursor_collision(self):
        import threading
        self.server.update_config(allowed_edits={"expense"})
        url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
        errors = []

        def worker(idx):
            try:
                payload = json.dumps({"action": "expense", "params": {"amount": f"{10 + idx}k", "category": "test"}}).encode()
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req) as resp:
                    data = json.loads(resp.read().decode())
                    if not data.get("ok"):
                        errors.append(f"Not ok: {data}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
