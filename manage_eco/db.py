"""SQLite storage. Default path: $ECO_DB or ~/.manage_eco.db."""
import os
import sqlite3
from datetime import date
from typing import List, Optional

from manage_eco.models import Account, Budget, Goal, Plan, Transaction, Transfer, PENDING

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
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    initial_balance INTEGER NOT NULL DEFAULT 0 CHECK (initial_balance >= 0),
    is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1))
);
CREATE TABLE IF NOT EXISTS transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    from_account_id INTEGER NOT NULL REFERENCES accounts(id),
    to_account_id INTEGER NOT NULL REFERENCES accounts(id),
    note TEXT NOT NULL DEFAULT '',
    CHECK (from_account_id != to_account_id)
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
        tx_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(transactions)")}
        if "account_id" not in tx_cols:
            self.conn.execute("ALTER TABLE transactions ADD COLUMN account_id INTEGER")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # --- transactions ---
    def add_transaction(self, t: Transaction) -> int:
        cur = self.conn.execute(
            "INSERT INTO transactions (date, amount, kind, category, note, account_id) VALUES (?, ?, ?, ?, ?, ?)",
            (t.date.isoformat(), t.amount, t.kind, t.category, t.note, t.account_id),
        )
        self.conn.commit()
        t.id = cur.lastrowid
        return t.id

    def list_transactions(self, start: Optional[date] = None, end: Optional[date] = None, account_id: Optional[int] = None) -> List[Transaction]:
        """Transactions with start <= date <= end (both optional), oldest first."""
        sql, args = "SELECT * FROM transactions WHERE 1=1", []
        if start:
            sql += " AND date >= ?"
            args.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            args.append(end.isoformat())
        if account_id is not None:
            sql += " AND account_id = ?"
            args.append(account_id)
        rows = self.conn.execute(sql + " ORDER BY date, id", args).fetchall()
        return [
            Transaction(
                date.fromisoformat(r["date"]),
                r["amount"],
                r["kind"],
                r["category"],
                r["note"],
                r["id"],
                r["account_id"] if "account_id" in r.keys() else None,
            )
            for r in rows
        ]

    def get_transaction(self, tid: int) -> Optional[Transaction]:
        r = self.conn.execute("SELECT * FROM transactions WHERE id = ?", (tid,)).fetchone()
        if r is None:
            return None
        return Transaction(
            date.fromisoformat(r["date"]),
            r["amount"],
            r["kind"],
            r["category"],
            r["note"],
            r["id"],
            r["account_id"] if "account_id" in r.keys() else None,
        )

    def update_transaction(self, t: Transaction) -> None:
        self.conn.execute(
            "UPDATE transactions SET date=?, amount=?, kind=?, category=?, note=?, account_id=? WHERE id=?",
            (t.date.isoformat(), t.amount, t.kind, t.category, t.note, t.account_id, t.id),
        )
        self.conn.commit()

    def delete_transaction(self, tid: int) -> bool:
        cur = self.conn.execute("DELETE FROM transactions WHERE id = ?", (tid,))
        self.conn.commit()
        return cur.rowcount > 0

    def balance(self, as_of: Optional[date] = None) -> int:
        accs = self.list_accounts()
        if accs:
            return self.total_balance(as_of)
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

    # --- accounts ---
    def add_account(self, a: Account) -> int:
        count = self.conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
        if count == 0:
            a.is_default = True
        elif a.is_default:
            self.conn.execute("UPDATE accounts SET is_default = 0")
        cur = self.conn.execute(
            "INSERT INTO accounts (name, initial_balance, is_default) VALUES (?, ?, ?)",
            (a.name, a.initial_balance, 1 if a.is_default else 0),
        )
        self.conn.commit()
        a.id = cur.lastrowid
        return a.id

    def list_accounts(self) -> List[Account]:
        rows = self.conn.execute("SELECT * FROM accounts ORDER BY is_default DESC, id ASC").fetchall()
        return [Account(r["name"], r["initial_balance"], bool(r["is_default"]), r["id"]) for r in rows]

    def get_account(self, aid: int) -> Optional[Account]:
        r = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
        if r is None:
            return None
        return Account(r["name"], r["initial_balance"], bool(r["is_default"]), r["id"])

    def get_account_by_name(self, name: str) -> Optional[Account]:
        r = self.conn.execute("SELECT * FROM accounts WHERE LOWER(name) = LOWER(?)", (name.strip(),)).fetchone()
        if r is None:
            return None
        return Account(r["name"], r["initial_balance"], bool(r["is_default"]), r["id"])

    def get_default_account(self) -> Optional[Account]:
        r = self.conn.execute("SELECT * FROM accounts WHERE is_default = 1").fetchone()
        if r:
            return Account(r["name"], r["initial_balance"], bool(r["is_default"]), r["id"])
        r = self.conn.execute("SELECT * FROM accounts ORDER BY id ASC LIMIT 1").fetchone()
        if r:
            return Account(r["name"], r["initial_balance"], bool(r["is_default"]), r["id"])
        return None

    def update_account(self, a: Account) -> None:
        if a.is_default:
            self.conn.execute("UPDATE accounts SET is_default = 0 WHERE id != ?", (a.id,))
        self.conn.execute(
            "UPDATE accounts SET name=?, initial_balance=?, is_default=? WHERE id=?",
            (a.name, a.initial_balance, 1 if a.is_default else 0, a.id),
        )
        self.conn.commit()

    def set_default_account(self, aid: int) -> None:
        if not self.get_account(aid):
            raise LookupError(f"Account {aid} not found")
        self.conn.execute("UPDATE accounts SET is_default = 0")
        self.conn.execute("UPDATE accounts SET is_default = 1 WHERE id = ?", (aid,))
        self.conn.commit()

    def delete_account(self, aid: int) -> bool:
        acc = self.get_account(aid)
        if not acc:
            return False
        tx_count = self.conn.execute("SELECT COUNT(*) AS c FROM transactions WHERE account_id = ?", (aid,)).fetchone()["c"]
        if tx_count > 0:
            raise ValueError("Không thể xóa tài khoản đã có giao dịch")
        tr_count = self.conn.execute(
            "SELECT COUNT(*) AS c FROM transfers WHERE from_account_id = ? OR to_account_id = ?",
            (aid, aid)
        ).fetchone()["c"]
        if tr_count > 0:
            raise ValueError("Không thể xóa tài khoản đã có lịch sử chuyển tiền")
        total_accs = self.conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"]
        if total_accs == 1 and acc.is_default:
            raise ValueError("Không thể xóa tài khoản duy nhất")
        if acc.is_default and total_accs > 1:
            raise ValueError("Vui lòng đặt tài khoản khác làm mặc định trước khi xóa")
        cur = self.conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- transfers ---
    def add_transfer(self, tr: Transfer) -> int:
        if tr.from_account_id == tr.to_account_id:
            raise ValueError("Không thể chuyển tiền đến cùng tài khoản")
        if tr.amount <= 0:
            raise ValueError("Số tiền chuyển phải lớn hơn 0")
        if not self.get_account(tr.from_account_id):
            raise LookupError(f"Tài khoản nguồn {tr.from_account_id} không tồn tại")
        if not self.get_account(tr.to_account_id):
            raise LookupError(f"Tài khoản đích {tr.to_account_id} không tồn tại")
        cur = self.conn.execute(
            "INSERT INTO transfers (date, amount, from_account_id, to_account_id, note) VALUES (?, ?, ?, ?, ?)",
            (tr.date.isoformat(), tr.amount, tr.from_account_id, tr.to_account_id, tr.note),
        )
        self.conn.commit()
        tr.id = cur.lastrowid
        return tr.id

    def list_transfers(
        self,
        account_id: Optional[int] = None,
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> List[Transfer]:
        sql, args = "SELECT * FROM transfers WHERE 1=1", []
        if account_id is not None:
            sql += " AND (from_account_id = ? OR to_account_id = ?)"
            args.extend([account_id, account_id])
        if start:
            sql += " AND date >= ?"
            args.append(start.isoformat())
        if end:
            sql += " AND date <= ?"
            args.append(end.isoformat())
        rows = self.conn.execute(sql + " ORDER BY date DESC, id DESC", args).fetchall()
        return [
            Transfer(
                date.fromisoformat(r["date"]),
                r["amount"],
                r["from_account_id"],
                r["to_account_id"],
                r["note"],
                r["id"],
            )
            for r in rows
        ]

    def delete_transfer(self, tid: int) -> bool:
        cur = self.conn.execute("DELETE FROM transfers WHERE id = ?", (tid,))
        self.conn.commit()
        return cur.rowcount > 0

    # --- account balances ---
    def account_balance(self, account_id: int, as_of: Optional[date] = None) -> int:
        acc = self.get_account(account_id)
        if not acc:
            raise LookupError(f"Tài khoản {account_id} không tồn tại")
        is_def = 1 if acc.is_default else 0
        date_clause = " AND date <= ?" if as_of else ""
        date_args = [as_of.isoformat()] if as_of else []

        inc_args = [account_id, is_def] + date_args
        inc_row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
            "WHERE kind = 'income' AND (account_id = ? OR (? = 1 AND account_id IS NULL))" + date_clause,
            inc_args,
        ).fetchone()
        income = inc_row["total"] if inc_row else 0

        exp_args = [account_id, is_def] + date_args
        exp_row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transactions "
            "WHERE kind = 'expense' AND (account_id = ? OR (? = 1 AND account_id IS NULL))" + date_clause,
            exp_args,
        ).fetchone()
        expense = exp_row["total"] if exp_row else 0

        tr_in_args = [account_id] + date_args
        tr_in_row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transfers WHERE to_account_id = ?" + date_clause,
            tr_in_args,
        ).fetchone()
        tr_in = tr_in_row["total"] if tr_in_row else 0

        tr_out_args = [account_id] + date_args
        tr_out_row = self.conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM transfers WHERE from_account_id = ?" + date_clause,
            tr_out_args,
        ).fetchone()
        tr_out = tr_out_row["total"] if tr_out_row else 0

        return acc.initial_balance + income - expense + tr_in - tr_out

    def total_balance(self, as_of: Optional[date] = None) -> int:
        accs = self.list_accounts()
        if not accs:
            return sum(t.signed for t in self.list_transactions(end=as_of))
        return sum(self.account_balance(a.id, as_of) for a in accs)
