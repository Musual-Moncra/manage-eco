"""SQLite storage. Default path: $ECO_DB or ~/.manage_eco.db."""
import os
import sqlite3
from datetime import date
from typing import List, Optional

from manage_eco.models import Budget, Goal, Plan, Transaction, PENDING

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    category TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    due_date TEXT NOT NULL,
    category TEXT NOT NULL,
    recurrence TEXT NOT NULL DEFAULT 'once',
    status TEXT NOT NULL DEFAULT 'pending',
    day INTEGER CHECK (day IS NULL OR day BETWEEN 1 AND 31)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
    category TEXT PRIMARY KEY,
    "limit" INTEGER NOT NULL CHECK ("limit" > 0)
);
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target INTEGER NOT NULL CHECK (target > 0),
    by_date TEXT NOT NULL,
    saved INTEGER NOT NULL DEFAULT 0 CHECK (saved >= 0)
);
"""


def default_path() -> str:
    return os.environ.get("ECO_DB") or os.path.expanduser("~/.manage_eco.db")


class Store:
    def __init__(self, path: Optional[str] = None):
        self.conn = sqlite3.connect(path or default_path())
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(plans)")}
        if "day" not in cols:  # migrate databases created before v4
            self.conn.execute("ALTER TABLE plans ADD COLUMN day INTEGER")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- transactions ---
    def add_transaction(self, t: Transaction) -> int:
        cur = self.conn.execute(
            "INSERT INTO transactions (date, amount, kind, category, note) VALUES (?, ?, ?, ?, ?)",
            (t.date.isoformat(), t.amount, t.kind, t.category, t.note),
        )
        self.conn.commit()
        t.id = cur.lastrowid
        return t.id

    def list_transactions(self, start: Optional[date] = None, end: Optional[date] = None) -> List[Transaction]:
        """Transactions with start <= date <= end (both optional), oldest first."""
        sql, args = "SELECT * FROM transactions WHERE 1=1", []
        if start:
            sql += " AND date >= ?"
            args.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            args.append(end.isoformat())
        rows = self.conn.execute(sql + " ORDER BY date, id", args).fetchall()
        return [
            Transaction(date.fromisoformat(r["date"]), r["amount"], r["kind"], r["category"], r["note"], r["id"])
            for r in rows
        ]

    def get_transaction(self, tid: int) -> Optional[Transaction]:
        r = self.conn.execute("SELECT * FROM transactions WHERE id = ?", (tid,)).fetchone()
        if r is None:
            return None
        return Transaction(date.fromisoformat(r["date"]), r["amount"], r["kind"], r["category"], r["note"], r["id"])

    def update_transaction(self, t: Transaction) -> None:
        self.conn.execute(
            "UPDATE transactions SET date=?, amount=?, kind=?, category=?, note=? WHERE id=?",
            (t.date.isoformat(), t.amount, t.kind, t.category, t.note, t.id),
        )
        self.conn.commit()

    def delete_transaction(self, tid: int) -> bool:
        cur = self.conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
        self.conn.commit()
        return cur.rowcount > 0

    def balance(self, as_of: Optional[date] = None) -> int:
        return sum(t.signed for t in self.list_transactions(end=as_of))

    # --- plans ---
    def add_plan(self, p: Plan) -> int:
        cur = self.conn.execute(
            "INSERT INTO plans (name, amount, kind, due_date, category, recurrence, status, day)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (p.name, p.amount, p.kind, p.due_date.isoformat(), p.category, p.recurrence, p.status, p.day),
        )
        self.conn.commit()
        p.id = cur.lastrowid
        return p.id

    def list_plans(self, status: Optional[str] = PENDING) -> List[Plan]:
        """Plans ordered by due date; status=None returns all."""
        sql, args = "SELECT * FROM plans", []
        if status:
            sql += " WHERE status = ?"
            args.append(status)
        rows = self.conn.execute(sql + " ORDER BY due_date, id", args).fetchall()
        return [
            Plan(r["name"], r["amount"], r["kind"], date.fromisoformat(r["due_date"]), r["category"],
                 r["recurrence"], r["status"], r["id"], r["day"])
            for r in rows
        ]

    def get_plan(self, pid: int) -> Optional[Plan]:
        return next((p for p in self.list_plans(status=None) if p.id == pid), None)

    def update_plan(self, p: Plan) -> None:
        self.conn.execute(
            "UPDATE plans SET name=?, amount=?, kind=?, due_date=?, category=?, recurrence=?, status=?, day=?"
            " WHERE id=?",
            (p.name, p.amount, p.kind, p.due_date.isoformat(), p.category, p.recurrence, p.status, p.day, p.id),
        )
        self.conn.commit()

    # --- budgets ---
    def set_budget(self, b: Budget) -> None:
        self.conn.execute(
            'INSERT INTO budgets (category, "limit") VALUES (?, ?)'
            ' ON CONFLICT(category) DO UPDATE SET "limit" = excluded."limit"',
            (b.category, b.limit),
        )
        self.conn.commit()

    def delete_budget(self, category: str) -> bool:
        cur = self.conn.execute("DELETE FROM budgets WHERE category = ?", (category,))
        self.conn.commit()
        return cur.rowcount > 0

    def list_budgets(self) -> List[Budget]:
        rows = self.conn.execute('SELECT category, "limit" FROM budgets ORDER BY category').fetchall()
        return [Budget(r["category"], r["limit"]) for r in rows]

    # --- goals ---
    def add_goal(self, g: Goal) -> int:
        cur = self.conn.execute(
            "INSERT INTO goals (name, target, by_date, saved) VALUES (?, ?, ?, ?)",
            (g.name, g.target, g.by.isoformat(), g.saved),
        )
        self.conn.commit()
        g.id = cur.lastrowid
        return g.id

    def list_goals(self) -> List[Goal]:
        rows = self.conn.execute("SELECT * FROM goals ORDER BY by_date, id").fetchall()
        return [
            Goal(r["name"], r["target"], date.fromisoformat(r["by_date"]), r["saved"], r["id"])
            for r in rows
        ]

    def get_goal(self, gid: int) -> Optional[Goal]:
        r = self.conn.execute("SELECT * FROM goals WHERE id = ?", (gid,)).fetchone()
        if r is None:
            return None
        return Goal(r["name"], r["target"], date.fromisoformat(r["by_date"]), r["saved"], r["id"])

    def update_goal(self, g: Goal) -> None:
        self.conn.execute(
            "UPDATE goals SET name=?, target=?, by_date=?, saved=? WHERE id=?",
            (g.name, g.target, g.by.isoformat(), g.saved, g.id),
        )
        self.conn.commit()

    def delete_goal(self, gid: int) -> bool:
        cur = self.conn.execute("DELETE FROM goals WHERE id = ?", (gid,))
        self.conn.commit()
        return cur.rowcount > 0

    def total_saved(self) -> int:
        row = self.conn.execute("SELECT COALESCE(SUM(saved), 0) AS total FROM goals").fetchone()
        return int(row["total"]) if row else 0

    # --- settings ---
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()
