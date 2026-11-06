"""Contract tests for `eco --json` (SPEC.md section "v2").

These tests drive the real CLI in a subprocess. They are expected to fail
until manage_eco/api.py and the --json path in manage_eco/cli.py exist.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2026-11-06"

TX_KEYS = {"id", "date", "amount", "kind", "category", "note", "signed"}
PLAN_KEYS = {"id", "name", "amount", "kind", "due_date", "category", "recurrence", "status", "day"}
BUDGET_KEYS = {"category", "limit"}
BUDGET_ROW_KEYS = {"category", "limit", "spent", "remaining", "pct"}
SUMMARY_KEYS = {"month", "income", "expense", "net", "by_category"}


class JsonCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "eco.db")

    # --- helpers -------------------------------------------------------
    def run_cli(self, *args, json_mode=True, env=None):
        cmd = [sys.executable, "-m", "manage_eco"]
        if json_mode:
            cmd.append("--json")
        cmd += ["--db", self.db, "--today", TODAY]
        cmd += list(args)
        clean = os.environ.copy()
        clean.pop("ECO_DB", None)
        clean.pop("ECO_JSON", None)
        if env:
            clean.update(env)
        return subprocess.run(
            cmd, cwd=ROOT, env=clean, capture_output=True, text=True, timeout=60
        )

    def payload(self, proc):
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.fail("stdout is not exactly one JSON object: %r (stderr=%r)"
                      % (proc.stdout, proc.stderr))
        self.assertIsInstance(data, dict)
        return data

    def assert_command(self, payload, expected):
        self.assertIsInstance(payload.get("command"), str)
        normalized = payload["command"].replace("_", " ").replace("-", " ")
        self.assertEqual(normalized, expected)

    def assert_keys(self, obj, expected, exact=False):
        self.assertIsInstance(obj, dict)
        if exact:
            self.assertEqual(set(obj), set(expected))
        else:
            self.assertLessEqual(set(expected), set(obj))

    def assert_tx(self, tx):
        self.assert_keys(tx, TX_KEYS, exact=True)
        self.assertIsInstance(tx["id"], int)
        self.assertIsInstance(tx["date"], str)
        self.assertIsInstance(tx["amount"], int)
        self.assertIsInstance(tx["signed"], int)

    def assert_plan(self, plan):
        self.assert_keys(plan, PLAN_KEYS, exact=True)
        self.assertIsInstance(plan["id"], int)
        self.assertIsInstance(plan["due_date"], str)

    def assert_summary(self, summary):
        self.assert_keys(summary, SUMMARY_KEYS)
        self.assertIsInstance(summary["month"], str)
        self.assertIsInstance(summary["income"], int)
        self.assertIsInstance(summary["expense"], int)
        self.assertIsInstance(summary["net"], int)
        self.assertIsInstance(summary["by_category"], list)
        for row in summary["by_category"]:
            self.assert_keys(row, {"category", "amount"}, exact=True)

    def ok(self, *args, **kwargs):
        proc = self.run_cli(*args, **kwargs)
        self.assertEqual(proc.returncode, 0,
                         "expected exit 0, got %d; stdout=%r stderr=%r"
                         % (proc.returncode, proc.stdout, proc.stderr))
        payload = self.payload(proc)
        self.assertIs(payload.get("ok"), True)
        self.assertIn("command", payload)
        self.assertIn("data", payload)
        return payload

    def err(self, code, exit_code, *args):
        proc = self.run_cli(*args)
        self.assertEqual(proc.returncode, exit_code,
                         "expected exit %d, got %d; stdout=%r stderr=%r"
                         % (exit_code, proc.returncode, proc.stdout, proc.stderr))
        payload = self.payload(proc)
        self.assertIs(payload.get("ok"), False)
        self.assertEqual(payload.get("code"), code)
        self.assertIsInstance(payload.get("error"), str)
        self.assertTrue(payload["error"])
        return payload

    # --- income / expense ---------------------------------------------
    def test_income_and_expense(self):
        p = self.ok("income", "20000000", "salary", "-n", "luong", "-d", "2026-11-01")
        self.assert_command(p, "income")
        data = p["data"]
        self.assert_keys(data, {"transaction", "balance"})
        self.assert_tx(data["transaction"])
        tx = data["transaction"]
        self.assertEqual(tx["date"], "2026-11-01")
        self.assertEqual(tx["amount"], 20000000)
        self.assertEqual(tx["kind"], "income")
        self.assertEqual(tx["category"], "salary")
        self.assertEqual(tx["note"], "luong")
        self.assertEqual(tx["signed"], 20000000)
        self.assertEqual(data["balance"], 20000000)

        p = self.ok("expense", "1500000", "food", "-n", "pho", "-d", "2026-11-02")
        self.assert_command(p, "expense")
        tx = p["data"]["transaction"]
        self.assert_tx(tx)
        self.assertEqual(tx["kind"], "expense")
        self.assertEqual(tx["signed"], -1500000)
        self.assertEqual(p["data"]["balance"], 18500000)

    def test_amount_shorthand(self):
        p = self.ok("expense", "1.5tr", "rent")
        self.assertEqual(p["data"]["transaction"]["amount"], 1500000)

    def test_invalid_amount(self):
        self.err("invalid", 2, "expense", "abc", "food")
        self.err("invalid", 2, "income", "-5", "salary")

    # --- list / rm -----------------------------------------------------
    def test_list_filters_and_balance(self):
        self.ok("income", "1000000", "salary", "-d", "2026-11-02")
        self.ok("expense", "250000", "food", "-d", "2026-10-15")

        p = self.ok("list")
        self.assert_command(p, "list")
        self.assert_keys(p["data"], {"transactions", "balance"})
        self.assertEqual([t["date"] for t in p["data"]["transactions"]], ["2026-11-02"])
        self.assertIsInstance(p["data"]["balance"], int)

        p = self.ok("list", "--month", "2026-10")
        self.assertEqual([t["date"] for t in p["data"]["transactions"]], ["2026-10-15"])

        p = self.ok("list", "--all")
        self.assertEqual(len(p["data"]["transactions"]), 2)
        self.assertEqual(p["data"]["balance"], 750000)
        for tx in p["data"]["transactions"]:
            self.assert_tx(tx)

    def test_rm(self):
        p = self.ok("expense", "250000", "food")
        tid = p["data"]["transaction"]["id"]

        p = self.ok("rm", str(tid))
        self.assert_command(p, "rm")
        self.assert_keys(p["data"], {"deleted", "balance"})
        self.assertEqual(p["data"]["deleted"], tid)
        self.assertEqual(p["data"]["balance"], 0)

        self.err("not_found", 1, "rm", "999")

    # --- edit ----------------------------------------------------------
    def test_edit_partial_update(self):
        p = self.ok("expense", "100000", "food", "-n", "lunch", "-d", "2026-11-02")
        tid = p["data"]["transaction"]["id"]

        p = self.ok("edit", str(tid), "--amount", "150000")
        self.assert_command(p, "edit")
        self.assert_keys(p["data"], {"transaction", "balance"})
        tx = p["data"]["transaction"]
        self.assert_tx(tx)
        self.assertEqual(tx["amount"], 150000)
        self.assertEqual(tx["signed"], -150000)
        self.assertEqual(tx["category"], "food")
        self.assertEqual(tx["note"], "lunch")
        self.assertEqual(tx["date"], "2026-11-02")
        self.assertEqual(p["data"]["balance"], -150000)

        p = self.ok("edit", str(tid), "-n", "")
        self.assertEqual(p["data"]["transaction"]["note"], "")

        p = self.ok("edit", str(tid), "--kind", "income")
        tx = p["data"]["transaction"]
        self.assertEqual(tx["kind"], "income")
        self.assertEqual(tx["signed"], 150000)
        self.assertEqual(p["data"]["balance"], 150000)

        p = self.ok("edit", str(tid), "--category", "salary", "-d", "2026-11-03")
        tx = p["data"]["transaction"]
        self.assertEqual(tx["category"], "salary")
        self.assertEqual(tx["date"], "2026-11-03")
        self.assertEqual(tx["amount"], 150000)
        self.assertEqual(tx["kind"], "income")

    def test_edit_errors(self):
        self.err("not_found", 1, "edit", "999", "--amount", "1000")
        p = self.ok("expense", "1000", "food")
        tid = p["data"]["transaction"]["id"]
        self.err("invalid", 2, "edit", str(tid), "--amount", "abc")

    # --- summary -------------------------------------------------------
    def test_summary(self):
        self.ok("income", "20000000", "salary", "-d", "2026-11-01")
        self.ok("expense", "5000000", "food", "-d", "2026-11-02")
        self.ok("expense", "1000000", "food", "-d", "2026-11-03")
        self.ok("expense", "2000000", "transport", "-d", "2026-10-01")

        p = self.ok("summary")
        self.assert_command(p, "summary")
        self.assert_summary(p["data"])
        data = p["data"]
        self.assertEqual(data["month"], "2026-11")
        self.assertEqual(data["income"], 20000000)
        self.assertEqual(data["expense"], 6000000)
        self.assertEqual(data["net"], 14000000)
        self.assertEqual(data["by_category"], [{"category": "food", "amount": 6000000}])

        p = self.ok("summary", "--month", "2026-10")
        data = p["data"]
        self.assertEqual(data["month"], "2026-10")
        self.assertEqual(data["income"], 0)
        self.assertEqual(data["expense"], 2000000)
        self.assertEqual(data["net"], -2000000)
        self.assertEqual(data["by_category"], [{"category": "transport", "amount": 2000000}])

        p = self.ok("summary", "--month", "2026-12")
        self.assertEqual(p["data"]["by_category"], [])
        self.assertEqual(p["data"]["net"], 0)

    # --- plans ---------------------------------------------------------
    def test_plan_add(self):
        p = self.ok("plan", "add", "Rent", "25000000", "housing",
                    "--due", "2026-12-01", "--every", "monthly")
        self.assert_command(p, "plan add")
        self.assert_keys(p["data"], {"plan"})
        plan = p["data"]["plan"]
        self.assert_plan(plan)
        self.assertEqual(plan["name"], "Rent")
        self.assertEqual(plan["amount"], 25000000)
        self.assertEqual(plan["kind"], "expense")
        self.assertEqual(plan["due_date"], "2026-12-01")
        self.assertEqual(plan["category"], "housing")
        self.assertEqual(plan["recurrence"], "monthly")
        self.assertEqual(plan["status"], "pending")
        self.assertIsNone(plan["day"])

        p = self.ok("plan", "add", "Bonus", "5000000", "job",
                    "--due", "2026-12-15", "--income")
        plan = p["data"]["plan"]
        self.assertEqual(plan["kind"], "income")
        self.assertEqual(plan["recurrence"], "once")
        self.assertIsNone(plan["day"])

    def test_plan_add_daily(self):
        p = self.ok("plan", "add", "Coffee", "20000", "food",
                    "--due", "2026-11-10", "--every", "daily")
        self.assert_command(p, "plan add")
        plan = p["data"]["plan"]
        self.assert_plan(plan)
        self.assertEqual(plan["recurrence"], "daily")
        self.assertEqual(plan["due_date"], "2026-11-10")
        self.assertIsNone(plan["day"])

        p = self.ok("plan", "done", str(plan["id"]))
        self.assertEqual(p["data"]["plan"]["due_date"], "2026-11-11")
        self.assertEqual(p["data"]["plan"]["status"], "pending")

    def test_plan_add_monthly_day_without_due(self):
        p = self.ok("plan", "add", "Rent", "25000000", "housing",
                    "--every", "monthly", "--day", "20")
        plan = p["data"]["plan"]
        self.assert_plan(plan)
        self.assertEqual(plan["recurrence"], "monthly")
        self.assertEqual(plan["day"], 20)
        self.assertEqual(plan["due_date"], "2026-11-20")

        p = self.ok("plan", "add", "Pay", "1000000", "bills",
                    "--every", "monthly", "--day", "5")
        self.assertEqual(p["data"]["plan"]["due_date"], "2026-12-05")

    def test_plan_add_day_requires_monthly(self):
        self.err("invalid", 2, "plan", "add", "X", "1000", "cat",
                 "--every", "weekly", "--day", "5")
        self.err("invalid", 2, "plan", "add", "X", "1000", "cat",
                 "--every", "daily", "--day", "5")
        self.err("invalid", 2, "plan", "add", "X", "1000", "cat",
                 "--every", "monthly", "--day", "32")

    def test_plan_add_invalid(self):
        self.err("invalid", 2, "plan", "add", "X", "abc", "cat", "--due", "2026-12-01")
        self.err("invalid", 2, "plan", "add", "X", "1000", "cat", "--due", "not-a-date")

    def test_plan_list(self):
        p1 = self.ok("plan", "add", "A", "1000", "cat", "--due", "2026-12-01")
        p2 = self.ok("plan", "add", "B", "2000", "cat", "--due", "2026-12-02")
        p3 = self.ok("plan", "add", "C", "3000", "cat", "--due", "2026-12-03")
        self.ok("plan", "done", str(p2["data"]["plan"]["id"]))
        self.ok("plan", "cancel", str(p3["data"]["plan"]["id"]))

        p = self.ok("plan", "list")
        self.assert_command(p, "plan list")
        self.assert_keys(p["data"], {"plans"})
        self.assertEqual([x["name"] for x in p["data"]["plans"]], ["A"])
        for plan in p["data"]["plans"]:
            self.assert_plan(plan)

        p = self.ok("plan", "list", "--all")
        self.assertEqual(len(p["data"]["plans"]), 3)
        statuses = {x["name"]: x["status"] for x in p["data"]["plans"]}
        self.assertEqual(statuses, {"A": "pending", "B": "done", "C": "cancelled"})

    def test_plan_done_once(self):
        p = self.ok("plan", "add", "Laptop", "20000000", "tech", "--due", "2026-11-10")
        pid = p["data"]["plan"]["id"]

        p = self.ok("plan", "done", str(pid), "-d", "2026-11-06")
        self.assert_command(p, "plan done")
        self.assert_keys(p["data"], {"transaction", "plan"})
        tx = p["data"]["transaction"]
        self.assert_tx(tx)
        self.assertEqual(tx["date"], "2026-11-06")
        self.assertEqual(tx["amount"], 20000000)
        self.assertEqual(tx["kind"], "expense")
        self.assertEqual(tx["note"], "plan:Laptop")
        self.assertEqual(p["data"]["plan"]["status"], "done")

    def test_plan_done_monthly_clamps(self):
        p = self.ok("plan", "add", "Rent", "25000000", "housing",
                    "--due", "2027-01-31", "--every", "monthly")
        pid = p["data"]["plan"]["id"]

        p = self.ok("plan", "done", str(pid), "-d", "2027-01-31")
        plan = p["data"]["plan"]
        self.assertEqual(plan["status"], "pending")
        self.assertEqual(plan["due_date"], "2027-02-28")
        self.assertEqual(plan["day"], 31)

        p = self.ok("plan", "done", str(pid), "-d", "2027-02-28")
        self.assertEqual(p["data"]["plan"]["due_date"], "2027-03-31")

    def test_plan_cancel(self):
        p = self.ok("plan", "add", "Trip", "5000000", "travel", "--due", "2026-12-01")
        pid = p["data"]["plan"]["id"]

        p = self.ok("plan", "cancel", str(pid))
        self.assert_command(p, "plan cancel")
        self.assert_keys(p["data"], {"plan"})
        self.assertEqual(p["data"]["plan"]["status"], "cancelled")

    def test_plan_not_found(self):
        self.err("not_found", 1, "plan", "done", "999")
        self.err("not_found", 1, "plan", "cancel", "999")

    def test_plan_edit(self):
        p = self.ok("plan", "add", "Rent", "25000000", "housing",
                    "--due", "2026-12-01", "--every", "monthly", "--day", "31")
        pid = p["data"]["plan"]["id"]

        p = self.ok("plan", "edit", str(pid), "--name", "Rent 2", "--amount", "30000000")
        self.assert_command(p, "plan edit")
        self.assert_keys(p["data"], {"plan"})
        plan = p["data"]["plan"]
        self.assert_plan(plan)
        self.assertEqual(plan["name"], "Rent 2")
        self.assertEqual(plan["amount"], 30000000)
        self.assertEqual(plan["category"], "housing")
        self.assertEqual(plan["due_date"], "2026-12-01")
        self.assertEqual(plan["day"], 31)

        p = self.ok("plan", "edit", str(pid), "--day", "20")
        plan = p["data"]["plan"]
        self.assertEqual(plan["day"], 20)
        self.assertEqual(plan["due_date"], "2026-11-20")

        p = self.ok("plan", "edit", str(pid), "--every", "weekly")
        plan = p["data"]["plan"]
        self.assertEqual(plan["recurrence"], "weekly")
        self.assertIsNone(plan["day"])
        self.assertEqual(plan["due_date"], "2026-11-20")

        p = self.ok("plan", "edit", str(pid), "--every", "monthly", "--day", "15")
        plan = p["data"]["plan"]
        self.assertEqual(plan["recurrence"], "monthly")
        self.assertEqual(plan["day"], 15)
        self.assertEqual(plan["due_date"], "2026-11-15")

    def test_plan_edit_errors(self):
        p = self.ok("plan", "add", "X", "1000", "cat", "--due", "2026-12-01",
                    "--every", "monthly")
        pid = p["data"]["plan"]["id"]
        self.err("invalid", 2, "plan", "edit", str(pid), "--every", "weekly", "--day", "5")
        self.err("invalid", 2, "plan", "edit", str(pid), "--amount", "abc")
        self.err("not_found", 1, "plan", "edit", "999", "--amount", "1000")

    # --- budget --------------------------------------------------------
    def test_budget_set_and_status(self):
        p = self.ok("budget", "set", "food", "3000000")
        self.assert_command(p, "budget set")
        self.assert_keys(p["data"], {"budget"})
        self.assert_keys(p["data"]["budget"], BUDGET_KEYS, exact=True)
        self.assertEqual(p["data"]["budget"], {"category": "food", "limit": 3000000})

        self.ok("budget", "set", "food", "3500000")
        self.ok("expense", "1000000", "food", "-d", "2026-11-02")
        self.ok("expense", "500000", "food", "-d", "2026-11-03")
        self.ok("expense", "900000", "other", "-d", "2026-11-04")
        self.ok("income", "1000000", "food", "-d", "2026-11-05")

        p = self.ok("budget", "status")
        self.assert_command(p, "budget status")
        self.assert_keys(p["data"], {"month", "budgets"})
        self.assertEqual(p["data"]["month"], "2026-11")
        rows = p["data"]["budgets"]
        self.assertEqual(len(rows), 1)
        self.assert_keys(rows[0], BUDGET_ROW_KEYS)
        self.assertEqual(rows[0]["category"], "food")
        self.assertEqual(rows[0]["limit"], 3500000)
        self.assertEqual(rows[0]["spent"], 1500000)
        self.assertEqual(rows[0]["remaining"], 2000000)
        self.assertIsInstance(rows[0]["pct"], float)
        self.assertAlmostEqual(rows[0]["pct"], 1500000 / 3500000 * 100)

        p = self.ok("budget", "status", "--month", "2026-10")
        self.assertEqual(p["data"]["month"], "2026-10")
        self.assertEqual(p["data"]["budgets"][0]["spent"], 0)

    def test_budget_delete(self):
        self.ok("budget", "set", "food", "3000000")
        self.ok("budget", "set", "transport", "1000000")

        p = self.ok("budget", "delete", "food")
        self.assert_command(p, "budget delete")
        self.assert_keys(p["data"], {"deleted"}, exact=True)
        self.assertEqual(p["data"]["deleted"], "food")

        p = self.ok("budget", "status")
        self.assertEqual([r["category"] for r in p["data"]["budgets"]], ["transport"])

        self.err("not_found", 1, "budget", "delete", "food")
        self.err("not_found", 1, "budget", "delete", "missing")

    # --- forecast / goal ----------------------------------------------
    def test_forecast(self):
        self.ok("income", "10000000", "salary", "-d", "2026-11-06")
        self.ok("plan", "add", "Rent", "3000000", "housing", "--due", "2026-11-16")
        self.ok("plan", "add", "Trip", "4000000", "travel", "--due", "2026-12-20")
        self.ok("plan", "add", "Old", "1000000", "misc", "--due", "2026-11-01")

        p = self.ok("forecast")
        self.assert_command(p, "forecast")
        self.assert_keys(p["data"], {"today", "balance", "days", "rows", "lowest"})
        data = p["data"]
        self.assertEqual(data["today"], TODAY)
        self.assertEqual(data["balance"], 10000000)
        self.assertEqual(data["days"], 90)
        self.assertEqual(len(data["rows"]), 2)
        for row in data["rows"]:
            self.assert_keys(row, {"date", "name", "amount", "balance"}, exact=True)
        self.assertEqual(data["rows"][0]["date"], "2026-11-16")
        self.assertEqual(data["rows"][0]["name"], "Rent")
        self.assertEqual(data["rows"][0]["amount"], -3000000)
        self.assertEqual(data["rows"][0]["balance"], 7000000)
        self.assertEqual(data["rows"][1]["date"], "2026-12-20")
        self.assertEqual(data["lowest"], {"date": "2026-12-20", "balance": 3000000})

        p = self.ok("forecast", "--days", "30")
        self.assertEqual(len(p["data"]["rows"]), 1)
        self.assertEqual(p["data"]["lowest"], {"date": "2026-11-16", "balance": 7000000})

        p = self.ok("forecast", "--days", "0")
        self.assertEqual(p["data"]["days"], 0)
        self.assertEqual(p["data"]["rows"], [])
        self.assertIsNone(p["data"]["lowest"])

    # --- history -------------------------------------------------------
    def test_history_defaults_empty(self):
        p = self.ok("history")
        self.assert_command(p, "history")
        self.assert_keys(p["data"], {"today", "series", "forecast"}, exact=True)
        data = p["data"]
        self.assertEqual(data["today"], TODAY)
        self.assertEqual(len(data["series"]), 90)
        self.assertEqual(data["series"][0]["date"], "2026-08-09")
        self.assertEqual(data["series"][-1]["date"], TODAY)
        self.assertEqual(len(data["forecast"]), 90)
        self.assertEqual(data["forecast"][0]["date"], "2026-11-07")
        self.assertEqual(data["forecast"][-1]["date"], "2027-02-04")
        for row in data["series"]:
            self.assert_keys(row, {"date", "balance", "income", "expense"}, exact=True)
            self.assertEqual(row["balance"], 0)
        for row in data["forecast"]:
            self.assert_keys(row, {"date", "balance"}, exact=True)
            self.assertEqual(row["balance"], 0)

    def test_history_series_balances(self):
        self.ok("income", "1000000", "salary", "-d", "2026-11-04")
        self.ok("expense", "200000", "food", "-d", "2026-11-05")
        self.ok("expense", "100000", "food", "-d", "2026-11-06")

        p = self.ok("history", "--days", "3", "--ahead", "0")
        data = p["data"]
        self.assertEqual([r["date"] for r in data["series"]],
                         ["2026-11-04", "2026-11-05", "2026-11-06"])
        self.assertEqual(data["series"][0],
                         {"date": "2026-11-04", "balance": 1000000,
                          "income": 1000000, "expense": 0})
        self.assertEqual(data["series"][1],
                         {"date": "2026-11-05", "balance": 800000,
                          "income": 0, "expense": 200000})
        self.assertEqual(data["series"][2],
                         {"date": "2026-11-06", "balance": 700000,
                          "income": 0, "expense": 100000})
        self.assertEqual(data["forecast"], [])

    def test_history_days_zero_starts_at_first_transaction(self):
        self.ok("income", "500000", "salary", "-d", "2026-10-01")
        self.ok("expense", "100000", "food", "-d", "2026-11-06")

        p = self.ok("history", "--days", "0", "--ahead", "0")
        series = p["data"]["series"]
        self.assertEqual(len(series), 37)
        self.assertEqual(series[0]["date"], "2026-10-01")
        self.assertEqual(series[0]["balance"], 500000)
        self.assertEqual(series[-1]["date"], TODAY)
        self.assertEqual(series[-1]["balance"], 400000)

    def test_history_forecast_step_values(self):
        self.ok("income", "1000000", "salary", "-d", "2026-11-04")
        self.ok("expense", "200000", "food", "-d", "2026-11-05")
        self.ok("expense", "100000", "food", "-d", "2026-11-06")
        self.ok("plan", "add", "Bill", "300000", "bills", "--due", "2026-11-08")
        self.ok("plan", "add", "Pay", "1000000", "job", "--due", "2026-11-10", "--income")

        p = self.ok("history", "--days", "1", "--ahead", "5")
        forecast = p["data"]["forecast"]
        self.assertEqual([r["date"] for r in forecast],
                         ["2026-11-07", "2026-11-08", "2026-11-09",
                          "2026-11-10", "2026-11-11"])
        self.assertEqual([r["balance"] for r in forecast],
                         [700000, 400000, 400000, 1400000, 1400000])

    def test_history_invalid(self):
        self.err("invalid", 2, "history", "--days", "-1")
        self.err("invalid", 2, "history", "--ahead", "-1")

    def test_goal(self):
        self.ok("income", "2000000", "salary", "-d", "2026-11-06")

        p = self.ok("goal", "10000000", "--by", "2027-02-06")
        self.assert_command(p, "goal")
        self.assert_keys(p["data"], {"target", "by", "needed", "months_left", "per_month"})
        data = p["data"]
        self.assertEqual(data["target"], 10000000)
        self.assertEqual(data["by"], "2027-02-06")
        self.assertEqual(data["needed"], 8000000)
        self.assertEqual(data["months_left"], 3)
        self.assertEqual(data["per_month"], 2666667)

        p = self.ok("goal", "1000000", "--by", "2027-02-06")
        self.assertEqual(p["data"]["needed"], 0)
        self.assertEqual(p["data"]["per_month"], 0)

    def test_goal_invalid(self):
        self.err("invalid", 2, "goal", "abc", "--by", "2027-02-06")
        self.err("invalid", 2, "goal", "1000000", "--by", "not-a-date")

    # --- dash ----------------------------------------------------------
    def test_dash(self):
        self.ok("income", "20000000", "salary", "-d", "2026-11-01")
        self.ok("expense", "150000", "food", "-d", "2026-11-02")
        self.ok("plan", "add", "Overdue", "1000000", "bills", "--due", "2026-11-01")
        self.ok("plan", "add", "Soon", "2000000", "bills", "--due", "2026-11-16")
        self.ok("budget", "set", "food", "3000000")

        p = self.ok("dash")
        self.assert_command(p, "dash")
        data = p["data"]
        self.assert_keys(data, {"today", "balance", "month", "overdue",
                                "budgets", "upcoming", "lowest"})
        self.assertEqual(data["today"], TODAY)
        self.assertEqual(data["balance"], 19850000)
        self.assert_summary(data["month"])
        self.assertEqual(data["month"]["month"], "2026-11")
        self.assertEqual(data["month"]["income"], 20000000)
        self.assertEqual(data["month"]["expense"], 150000)
        self.assertEqual(len(data["overdue"]), 1)
        self.assertEqual(data["overdue"][0]["name"], "Overdue")
        self.assert_plan(data["overdue"][0])
        self.assertEqual(len(data["budgets"]), 1)
        self.assert_keys(data["budgets"][0], BUDGET_ROW_KEYS)
        self.assertEqual(len(data["upcoming"]), 1)
        self.assertEqual(data["upcoming"][0]["name"], "Soon")
        self.assertIsNotNone(data["lowest"])
        self.assert_keys(data["lowest"], {"date", "balance"}, exact=True)

    def test_dash_empty_db(self):
        p = self.ok("dash")
        data = p["data"]
        self.assertEqual(data["today"], TODAY)
        self.assertEqual(data["balance"], 0)
        self.assert_summary(data["month"])
        self.assertEqual(data["month"]["income"], 0)
        self.assertEqual(data["month"]["expense"], 0)
        self.assertEqual(data["month"]["net"], 0)
        self.assertEqual(data["overdue"], [])
        self.assertEqual(data["budgets"], [])
        self.assertEqual(data["upcoming"], [])
        self.assertIsNone(data["lowest"])

    # --- categories ----------------------------------------------------
    def test_categories(self):
        p = self.ok("categories")
        self.assert_command(p, "categories")
        self.assert_keys(p["data"], {"expense", "income"}, exact=True)
        self.assertEqual(p["data"], {"expense": [], "income": []})

        self.ok("income", "1000000", "salary", "-d", "2026-11-01")
        self.ok("expense", "100", "food", "-d", "2026-11-02")
        self.ok("expense", "100", "food", "-d", "2026-11-03")
        self.ok("expense", "100", "transport", "-d", "2026-11-04")
        self.ok("plan", "add", "Rent", "1000", "housing", "--due", "2026-12-01")
        self.ok("plan", "add", "Bonus", "1000", "job", "--due", "2026-12-01", "--income")
        self.ok("budget", "set", "bills", "100000")

        p = self.ok("categories")
        data = p["data"]
        self.assertEqual(data["expense"], ["food", "transport", "bills", "housing"])
        self.assertEqual(data["income"], ["salary", "job"])

    # --- icons ---------------------------------------------------------
    def test_icons_default_set_and_get(self):
        p = self.ok("icons")
        self.assert_command(p, "icons")
        self.assert_keys(p["data"], {"icons"}, exact=True)
        self.assertEqual(p["data"]["icons"], "symbol")

        p = self.ok("icons", "emoji")
        self.assertEqual(p["data"]["icons"], "emoji")
        p = self.ok("icons")
        self.assertEqual(p["data"]["icons"], "emoji")

        p = self.ok("icons", "off")
        self.assertEqual(p["data"]["icons"], "off")
        p = self.ok("icons")
        self.assertEqual(p["data"]["icons"], "off")

        p = self.ok("icons", "symbol")
        self.assertEqual(p["data"]["icons"], "symbol")

    def test_icons_invalid(self):
        proc = self.run_cli("icons", "rainbow")
        self.assertEqual(proc.returncode, 2)

    # --- envelope details ---------------------------------------------
    def test_stdout_is_one_json_object_without_ansi(self):
        proc = self.run_cli("dash")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(proc.stdout.strip().startswith("{"))
        self.assertTrue(proc.stdout.strip().endswith("}"))
        self.assertNotIn("\x1b[", proc.stdout)
        self.payload(proc)

    def test_eco_json_env_var(self):
        p = self.ok("dash", json_mode=False, env={"ECO_JSON": "1"})
        self.assertIs(p["ok"], True)

    def test_json_mode_does_not_import_rich(self):
        script = (
            "import sys\n"
            "from manage_eco import cli\n"
            "rc = cli.main(['--json', '--db', %r, '--today', %r, 'dash'])\n"
            "bad = sorted(m for m in sys.modules if m == 'rich' or m.startswith('rich.'))\n"
            "if bad:\n"
            "    print('rich imported: ' + ','.join(bad), file=sys.stderr)\n"
            "    sys.exit(3)\n"
            "sys.exit(rc)\n"
        ) % (self.db, TODAY)
        clean = os.environ.copy()
        clean.pop("ECO_DB", None)
        clean.pop("ECO_JSON", None)
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT, env=clean, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0,
                         "stdout=%r stderr=%r" % (proc.stdout, proc.stderr))
        self.assertNotIn("rich imported", proc.stderr)

    def test_transaction_optional_category(self):
        p = self.ok("expense", "50000", "-d", "2026-11-02")
        tx = p["data"]["transaction"]
        self.assertEqual(tx["amount"], 50000)
        self.assertEqual(tx["category"], "")

        p = self.ok("summary", "--month", "2026-11")
        cats = [c["category"] for c in p["data"]["by_category"]]
        self.assertIn("Khác", cats)

        p2 = self.ok("income", "100000", "salary", "-d", "2026-11-01")
        tid = p2["data"]["transaction"]["id"]
        p3 = self.ok("edit", str(tid), "--category", "")
        self.assertEqual(p3["data"]["transaction"]["category"], "")

    def test_goal_jars_flow(self):
        p = self.ok("goal", "list")
        self.assertEqual(p["data"]["goals"], [])
        self.assertEqual(p["data"]["total_saved"], 0)

        p = self.ok("goal", "add", "Laptop", "30000000", "--by", "2027-12-31")
        self.assert_command(p, "goal add")
        g = p["data"]["goal"]
        gid = g["id"]
        self.assertEqual(g["name"], "Laptop")
        self.assertEqual(g["target"], 30000000)
        self.assertEqual(g["saved"], 0)
        self.assertEqual(g["remaining"], 30000000)
        self.assertEqual(g["pct"], 0.0)

        p = self.ok("goal", "save", str(gid), "10000000")
        self.assert_command(p, "goal save")
        self.assertEqual(p["data"]["saved_added"], 10000000)
        self.assertEqual(p["data"]["goal"]["saved"], 10000000)
        self.assertEqual(p["data"]["total_saved"], 10000000)

        p = self.ok("goal", "take", str(gid), "2000000")
        self.assert_command(p, "goal take")
        self.assertEqual(p["data"]["taken"], 2000000)
        self.assertEqual(p["data"]["goal"]["saved"], 8000000)

        self.err("invalid", 2, "goal", "take", str(gid), "50000000")

        p = self.ok("goal", "edit", str(gid), "--name", "MacBook", "--target", "35000000")
        self.assert_command(p, "goal edit")
        self.assertEqual(p["data"]["goal"]["name"], "MacBook")
        self.assertEqual(p["data"]["goal"]["target"], 35000000)

        p = self.ok("dash")
        self.assertIn("goals", p["data"])
        self.assertEqual(p["data"]["total_saved"], 8000000)

        p = self.ok("goal", "rm", str(gid))
        self.assert_command(p, "goal rm")
        self.assertEqual(p["data"]["deleted"], gid)


if __name__ == "__main__":
    unittest.main()
