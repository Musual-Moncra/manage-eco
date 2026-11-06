"""Data models. Amounts are integers in VND (đồng), always positive."""
from dataclasses import dataclass
from datetime import date
from typing import Optional

INCOME = "income"
EXPENSE = "expense"

# Plan recurrence
ONCE = "once"
WEEKLY = "weekly"
MONTHLY = "monthly"

PENDING = "pending"
DONE = "done"
CANCELLED = "cancelled"


@dataclass
class Transaction:
    date: date
    amount: int
    kind: str  # INCOME | EXPENSE
    category: str
    note: str = ""
    id: Optional[int] = None

    @property
    def signed(self) -> int:
        return self.amount if self.kind == INCOME else -self.amount


@dataclass
class Plan:
    """A future planned income/expense (e.g. rent, buying a laptop)."""
    name: str
    amount: int
    kind: str  # INCOME | EXPENSE
    due_date: date
    category: str
    recurrence: str = ONCE  # ONCE | WEEKLY | MONTHLY
    status: str = PENDING
    id: Optional[int] = None


@dataclass
class Budget:
    """Monthly spending limit for one category."""
    category: str
    limit: int
