"""Plan lifecycle, budgets and savings goals."""
import calendar
from datetime import date, timedelta
from typing import List, Optional

from manage_eco.models import (
    CANCELLED,
    DAILY,
    DONE,
    EXPENSE,
    MONTHLY,
    ONCE,
    PENDING,
    WEEKLY,
    Plan,
    Transaction,
)


def _month_end(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def _month_bounds(year: int, month: int):
    return date(year, month, 1), date(year, month, _month_end(year, month))


def _add_month(d: date, day: int) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(day, _month_end(year, month)))


def _advance(plan: Plan) -> date:
    """Next due date after completing one occurrence (anchor day keeps monthly from drifting)."""
    if plan.recurrence == DAILY:
        return plan.due_date + timedelta(days=1)
    if plan.recurrence == WEEKLY:
        return plan.due_date + timedelta(days=7)
    if plan.recurrence == MONTHLY:
        if plan.day is None:
            plan.day = plan.anchor_day
        return _add_month(plan.due_date, plan.anchor_day)
    return plan.due_date


def complete_plan(store, plan_id: int, on: date, account_id: Optional[int] = None) -> Transaction:
    plan = store.get_plan(plan_id)
    if plan is None:
        raise ValueError("plan not found: %s" % plan_id)
    if plan.status != PENDING:
        raise ValueError("plan %s is not pending (status=%s)" % (plan_id, plan.status))

    txn = Transaction(
        date=on,
        amount=plan.amount,
        kind=plan.kind,
        category=plan.category,
        note="plan:%s" % plan.name,
        account_id=account_id,
    )
    store.add_transaction(txn)

    if plan.recurrence == ONCE:
        plan.status = DONE
    else:
        plan.due_date = _advance(plan)
    store.update_plan(plan)
    return txn


def cancel_plan(store, plan_id: int) -> None:
    plan = store.get_plan(plan_id)
    if plan is None:
        raise ValueError("plan not found: %s" % plan_id)
    plan.status = CANCELLED
    store.update_plan(plan)


def overdue(store, today: date) -> List[Plan]:
    return [p for p in store.list_plans(PENDING) if p.due_date < today]


def budget_status(store, year: int, month: int) -> List[dict]:
    start, end = _month_bounds(year, month)
    expenses = [t for t in store.list_transactions(start, end) if t.kind == EXPENSE]
    result = []
    for budget in store.list_budgets():
        spent = sum(t.amount for t in expenses if t.category == budget.category)
        result.append({
            "category": budget.category,
            "limit": budget.limit,
            "spent": spent,
            "remaining": budget.limit - spent,
            "pct": spent / budget.limit * 100,
        })
    return result


def savings_goal(store, target: int, by: date, today: date) -> dict:
    needed = max(0, target - store.balance(today))
    months_left = max(1, (by.year - today.year) * 12 + (by.month - today.month))
    per_month = (needed + months_left - 1) // months_left
    return {"needed": needed, "months_left": months_left, "per_month": per_month}


def goal_dict(g, store=None, today: Optional[date] = None) -> dict:
    target = getattr(g, "target", 0) if not isinstance(g, dict) else g.get("target", 0)
    saved = getattr(g, "saved", 0) if not isinstance(g, dict) else g.get("saved", 0)
    name = getattr(g, "name", "") if not isinstance(g, dict) else g.get("name", "")
    gid = getattr(g, "id", None) if not isinstance(g, dict) else g.get("id")
    by_val = getattr(g, "by", today or date.today()) if not isinstance(g, dict) else g.get("by")
    by_date = by_val if isinstance(by_val, date) else date.fromisoformat(str(by_val))

    rem = max(0, target - saved)
    pct = round(saved / target * 100.0, 1) if target > 0 else 100.0
    res = {
        "id": gid,
        "name": name,
        "target": target,
        "saved": saved,
        "by": by_date.isoformat(),
        "remaining": rem,
        "pct": pct,
    }
    if today is not None:
        days_left = (by_date - today).days
        months_left = max(1, (by_date.year - today.year) * 12 + (by_date.month - today.month))
        per_month = (rem + months_left - 1) // months_left if rem > 0 else 0
        res["days_left"] = max(0, days_left)
        res["months_left"] = months_left
        res["per_month"] = per_month
        if rem <= 0:
            res["on_track"] = True
        elif days_left < 0:
            res["on_track"] = False
        elif store is not None:
            from manage_eco import cashflow
            days = max(1, days_left)
            fc = cashflow.forecast(store, today, days)
            bal_at_by = fc[-1][3] if fc else store.balance(today)
            total_saved = store.total_saved() if hasattr(store, "total_saved") else 0
            other_saved = max(0, total_saved - saved)
            free_at_by = bal_at_by - other_saved
            res["on_track"] = free_at_by >= rem
        else:
            res["on_track"] = True
    return res
