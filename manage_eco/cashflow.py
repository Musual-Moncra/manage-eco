"""Cash flow reports: monthly summaries, category breakdowns and plan forecasts."""
import calendar
from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from manage_eco.models import DAILY, EXPENSE, INCOME, MONTHLY, ONCE, PENDING, WEEKLY, Plan


def month_range(year: int, month: int) -> Tuple[date, date]:
    """First and last day of the given month."""
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def summary(store, start: date, end: date) -> Dict[str, int]:
    income = expense = 0
    for t in store.list_transactions(start, end):
        if t.kind == INCOME:
            income += t.amount
        else:
            expense += t.amount
    return {"income": income, "expense": expense, "net": income - expense}


def by_category(store, start: date, end: date, kind: str = EXPENSE) -> List[Tuple[str, int]]:
    """Totals per category, largest first (ties by name). Empty category groups as 'Khác'."""
    totals = defaultdict(int)  # type: Dict[str, int]
    for t in store.list_transactions(start, end):
        if t.kind == kind:
            cat = t.category if t.category else "Khác"
            totals[cat] += t.amount
    return sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))


def _add_months(d: date, months: int, day: int) -> date:
    """Same `day` `months` after d's month, clamped to that month's end."""
    m = d.month - 1 + months
    year, month = d.year + m // 12, m % 12 + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def expand_plan(plan: Plan, start: date, end: date) -> List[date]:
    """Occurrences of a pending plan within [start, end]."""
    if plan.status != PENDING or start > end:
        return []
    due = plan.due_date
    if plan.recurrence == ONCE:
        return [due] if start <= due <= end else []
    out = []  # type: List[date]
    if plan.recurrence == DAILY:
        d = due
        if d < start:
            d += timedelta(days=(start - d).days)
        while d <= end:
            out.append(d)
            d += timedelta(days=1)
    elif plan.recurrence == WEEKLY:
        d = due
        if d < start:
            d += timedelta(days=-(-(start - d).days // 7) * 7)
        while d <= end:
            out.append(d)
            d += timedelta(days=7)
    elif plan.recurrence == MONTHLY:
        anchor = plan.anchor_day
        n = 0
        if due < start:
            n = max(0, (start.year - due.year) * 12 + start.month - due.month - 1)
        d = _add_months(due, n, anchor)
        while d <= end:
            if d >= start:
                out.append(d)
            n += 1
            d = _add_months(due, n, anchor)
    return out


def forecast(store, today: date, days: int) -> List[Tuple[date, str, int, int]]:
    """Chronological (date, plan name, signed amount, running balance) for pending plans in (today, today+days]."""
    events = []
    for p in store.list_plans(PENDING):
        signed = p.amount if p.kind == INCOME else -p.amount
        for d in expand_plan(p, today + timedelta(days=1), today + timedelta(days=days)):
            events.append((d, p.id or 0, p.name, signed))
    events.sort(key=lambda e: (e[0], e[1]))
    running = store.balance(today)
    rows = []
    for d, _, name, signed in events:
        running += signed
        rows.append((d, name, signed, running))
    return rows


def lowest_point(rows: List[Tuple[date, str, int, int]]) -> Optional[Tuple[date, int]]:
    """Earliest row with the minimum running balance, or None if no rows."""
    if not rows:
        return None
    low = min(rows, key=lambda r: r[3])
    return low[0], low[3]
