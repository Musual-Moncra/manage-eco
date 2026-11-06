"""Command layer returning plain dicts — shared by the CLI (--json and human), the TUI and agents.

Usage from Python:
    from manage_eco import api
    from manage_eco.db import Store
    api.execute("expense", {"amount": "150k", "category": "an uong"}, Store(), date.today())

Raises LookupError (not found) or ValueError (bad input). Never imports rich.
"""
from datetime import date
from typing import Any, Callable, Dict, Optional

from manage_eco import cashflow, plans
from manage_eco.fmt import parse_date, parse_money
from manage_eco.models import (
    DAILY, EXPENSE, INCOME, MONTHLY, ONCE, PENDING, WEEKLY, Budget, Plan, Transaction,
)

RECURRENCES = (ONCE, DAILY, WEEKLY, MONTHLY)


def tx_dict(t: Transaction) -> dict:
    return {"id": t.id, "date": t.date.isoformat(), "amount": t.amount, "kind": t.kind,
            "category": t.category, "note": t.note, "signed": t.signed}


def plan_dict(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "amount": p.amount, "kind": p.kind, "due_date": p.due_date.isoformat(),
            "category": p.category, "recurrence": p.recurrence, "status": p.status, "day": p.day}


def _amount(v: Any) -> int:
    if isinstance(v, int) and not isinstance(v, bool):
        if v <= 0:
            raise ValueError("số tiền phải > 0")
        return v
    return parse_money(str(v))


def _date(v: Any, today: date) -> date:
    if v is None:
        return today
    if isinstance(v, date):
        return v
    return parse_date(str(v), today)


def _month(v: Optional[str], today: date):
    if not v:
        return today.year, today.month
    try:
        y, m = (int(x) for x in str(v).split("-"))
        if not 1 <= m <= 12:
            raise ValueError
        return y, m
    except ValueError:
        raise ValueError("tháng phải có dạng YYYY-MM: %r" % v)


def _require(params: dict, *keys: str) -> None:
    missing = [k for k in keys if params.get(k) in (None, "")]
    if missing:
        raise ValueError("thiếu tham số: %s" % ", ".join(missing))


def _record(kind: str, params: dict, store, today: date) -> dict:
    _require(params, "amount", "category")
    t = Transaction(_date(params.get("date"), today), _amount(params["amount"]), kind,
                    str(params["category"]), str(params.get("note") or ""))
    store.add_transaction(t)
    return {"transaction": tx_dict(t), "balance": store.balance()}


def income(params, store, today):
    return _record(INCOME, params, store, today)


def expense(params, store, today):
    return _record(EXPENSE, params, store, today)


def list_(params, store, today):
    if params.get("all"):
        txs = store.list_transactions()
    else:
        txs = store.list_transactions(*cashflow.month_range(*_month(params.get("month"), today)))
    return {"transactions": [tx_dict(t) for t in txs], "balance": store.balance()}


def rm(params, store, today):
    _require(params, "id")
    tid = int(params["id"])
    if not store.delete_transaction(tid):
        raise LookupError("không tìm thấy giao dịch #%d" % tid)
    return {"deleted": tid, "balance": store.balance()}


def summary(params, store, today):
    y, m = _month(params.get("month"), today)
    start, end = cashflow.month_range(y, m)
    s = cashflow.summary(store, start, end)
    s["month"] = "%d-%02d" % (y, m)
    s["by_category"] = [{"category": c, "amount": a} for c, a in cashflow.by_category(store, start, end)]
    return s


def _next_day_of_month(day: int, today: date) -> date:
    """First date >= today falling on `day` of its month (clamped to month end)."""
    y, m = today.year, today.month
    while True:
        d = date(y, m, min(day, cashflow.month_range(y, m)[1].day))
        if d >= today:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def plan_add(params, store, today):
    every = params.get("every") or ONCE
    if every not in RECURRENCES:
        raise ValueError("--every phải là %s" % "|".join(RECURRENCES))
    day = params.get("day")
    if day not in (None, ""):
        day = int(day)
        if every != MONTHLY:
            raise ValueError("--day chỉ dùng với --every monthly")
        if not 1 <= day <= 31:
            raise ValueError("--day phải từ 1 đến 31")
    else:
        day = None
    _require(params, "name", "amount", "category", *(() if day else ("due",)))
    due = _date(params["due"], today) if params.get("due") else _next_day_of_month(day, today)
    p = Plan(str(params["name"]), _amount(params["amount"]), INCOME if params.get("income") else EXPENSE,
             due, str(params["category"]), every, day=day)
    store.add_plan(p)
    return {"plan": plan_dict(p)}


def plan_list(params, store, today):
    return {"plans": [plan_dict(p) for p in store.list_plans(status=None if params.get("all") else PENDING)]}


def _plan_or_raise(store, pid: int) -> Plan:
    p = store.get_plan(pid)
    if p is None:
        raise LookupError("không tìm thấy dòng tiền #%d" % pid)
    return p


def plan_done(params, store, today):
    _require(params, "id")
    pid = int(params["id"])
    _plan_or_raise(store, pid)
    t = plans.complete_plan(store, pid, _date(params.get("date"), today))
    return {"transaction": tx_dict(t), "plan": plan_dict(store.get_plan(pid))}


def plan_cancel(params, store, today):
    _require(params, "id")
    pid = int(params["id"])
    _plan_or_raise(store, pid)
    plans.cancel_plan(store, pid)
    return {"plan": plan_dict(store.get_plan(pid))}


def budget_set(params, store, today):
    _require(params, "category", "amount")
    b = Budget(str(params["category"]), _amount(params["amount"]))
    store.set_budget(b)
    return {"budget": {"category": b.category, "limit": b.limit}}


def budget_status(params, store, today):
    y, m = _month(params.get("month"), today)
    return {"month": "%d-%02d" % (y, m), "budgets": plans.budget_status(store, y, m)}


def _rows(rows):
    return [{"date": d.isoformat(), "name": n, "amount": a, "balance": b} for d, n, a, b in rows]


def _lowest(rows):
    low = cashflow.lowest_point(rows)
    return {"date": low[0].isoformat(), "balance": low[1]} if low else None


def forecast(params, store, today):
    days = int(90 if params.get("days") is None else params["days"])
    if days < 0:
        raise ValueError("--days phải >= 0")
    rows = cashflow.forecast(store, today, days)
    return {"today": today.isoformat(), "balance": store.balance(today), "days": days,
            "rows": _rows(rows), "lowest": _lowest(rows)}


def goal(params, store, today):
    _require(params, "target", "by")
    target, by = _amount(params["target"]), _date(params["by"], today)
    g = plans.savings_goal(store, target, by, today)
    return dict(g, target=target, by=by.isoformat())


def dash(params, store, today):
    month = summary({}, store, today)
    return {
        "today": today.isoformat(),
        "balance": store.balance(today),
        "month": month,
        "overdue": [plan_dict(p) for p in plans.overdue(store, today)],
        "budgets": plans.budget_status(store, today.year, today.month),
        "upcoming": _rows(cashflow.forecast(store, today, 30)),
        "lowest": _lowest(cashflow.forecast(store, today, 90)),
    }


def categories(params, store, today):
    """Categories by use count (most used first), split by kind — for pick lists in UIs."""
    counts = {INCOME: {}, EXPENSE: {}}  # type: Dict[str, Dict[str, int]]
    for t in store.list_transactions():
        counts[t.kind][t.category] = counts[t.kind].get(t.category, 0) + 1
    for p in store.list_plans(status=None):
        counts[p.kind].setdefault(p.category, 0)
    for b in store.list_budgets():
        counts[EXPENSE].setdefault(b.category, 0)
    rank = lambda c: [k for k, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"expense": rank(counts[EXPENSE]), "income": rank(counts[INCOME])}


def sound(params, store, today):
    """Get or set sound effects: params {"state": "on"|"off"} or {} to read."""
    state = params.get("state")
    if state not in (None, ""):
        state = str(state).lower()
        if state not in ("on", "off"):
            raise ValueError("sound phải là on|off")
        store.set_setting("sound", state)
    return {"sound": store.get_setting("sound", "on") == "on"}


COMMANDS = {
    "income": income, "expense": expense, "list": list_, "rm": rm, "summary": summary,
    "plan add": plan_add, "plan list": plan_list, "plan done": plan_done, "plan cancel": plan_cancel,
    "budget set": budget_set, "budget status": budget_status,
    "forecast": forecast, "goal": goal, "dash": dash, "categories": categories, "sound": sound,
}  # type: Dict[str, Callable[[dict, Any, date], dict]]


def execute(cmd: str, params: Optional[dict], store, today: Optional[date] = None) -> dict:
    fn = COMMANDS.get(cmd)
    if fn is None:
        raise ValueError("lệnh không hợp lệ: %r (có: %s)" % (cmd, ", ".join(COMMANDS)))
    return fn(params or {}, store, today or date.today())
