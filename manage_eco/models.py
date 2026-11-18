"""Data models. Amounts are integers in VND (đồng), always positive."""
from dataclasses import dataclass
from datetime import date
from typing import Optional

INCOME = "income"
EXPENSE = "expense"

# Plan recurrence
ONCE = "once"
DAILY = "daily"
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
    category: str = ""
    note: str = ""
    id: Optional[int] = None
    account_id: Optional[int] = None

    @property
    def signed(self) -> int:
        return self.amount if self.kind == INCOME else -self.amount


@dataclass
class Plan:
    """A cash-flow item (shown as "Dòng tiền"): future planned income/expense, one-off or recurring."""
    name: str
    amount: int
    kind: str  # INCOME | EXPENSE
    due_date: date
    category: str
    recurrence: str = ONCE  # ONCE | DAILY | WEEKLY | MONTHLY
    status: str = PENDING
    id: Optional[int] = None
    day: Optional[int] = None  # MONTHLY: fixed day of month 1..31 (clamped to month end); None = due_date.day

    @property
    def anchor_day(self) -> int:
        return self.day or self.due_date.day


@dataclass
class Budget:
    """Monthly spending limit for one category."""
    category: str
    limit: int


@dataclass
class Goal:
    """A savings jar ("hũ tiết kiệm"): money set aside (`saved`) towards `target` by a date.

    Saved money stays part of the balance; "free" money = balance - total saved."""
    name: str
    target: int
    by: date
    saved: int = 0
    id: Optional[int] = None


@dataclass
class Account:
    """An account or wallet (tiền mặt, ngân hàng, ví điện tử...)."""
    name: str
    initial_balance: int = 0
    is_default: bool = False
    id: Optional[int] = None


@dataclass
class Transfer:
    """An internal transfer between two accounts."""
    date: date
    amount: int
    from_account_id: int
    to_account_id: int
    note: str = ""
    id: Optional[int] = None
    category: str = ""
