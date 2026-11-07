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
from manage_eco.fmt import money, parse_date, parse_money
from manage_eco.models import (
    DAILY, EXPENSE, INCOME, MONTHLY, ONCE, PENDING, WEEKLY, Account, Budget, Goal, Plan, Transaction, Transfer,
)

RECURRENCES = (ONCE, DAILY, WEEKLY, MONTHLY)


def tx_dict(t: Transaction) -> dict:
    d = {"id": t.id, "date": t.date.isoformat(), "amount": t.amount, "kind": t.kind,
         "category": t.category, "note": t.note, "signed": t.signed}
    if t.account_id is not None:
        d["account_id"] = t.account_id
    return d


def account_dict(a: Account, store=None, today: Optional[date] = None) -> dict:
    d = {
        "id": a.id,
        "name": a.name,
        "initial_balance": a.initial_balance,
        "is_default": a.is_default,
    }
    if store is not None:
        bal = store.account_balance(a.id, as_of=today)
        d["balance"] = bal
        tot = store.total_balance(as_of=today)
        d["pct"] = round((bal / tot * 100), 1) if tot > 0 else 0.0
    return d


def transfer_dict(tr: Transfer, store=None) -> dict:
    from_acc = store.get_account(tr.from_account_id) if store else None
    to_acc = store.get_account(tr.to_account_id) if store else None
    return {
        "id": tr.id,
        "date": tr.date.isoformat(),
        "amount": tr.amount,
        "from_account_id": tr.from_account_id,
        "from_account": from_acc.name if from_acc else str(tr.from_account_id),
        "to_account_id": tr.to_account_id,
        "to_account": to_acc.name if to_acc else str(tr.to_account_id),
        "note": tr.note,
    }


def plan_dict(p: Plan) -> dict:
    return {"id": p.id, "name": p.name, "amount": p.amount, "kind": p.kind, "due_date": p.due_date.isoformat(),
            "category": p.category, "recurrence": p.recurrence, "status": p.status, "day": p.day}


def _amount(v: Any) -> int:
    if isinstance(v, int) and not isinstance(v, bool):
        if v <= 0:
            raise ValueError("số tiền phải > 0")
        return v
    return parse_money(str(v))


def _initial_amount(v: Any) -> int:
    if v in (None, ""):
        return 0
    if isinstance(v, int) and not isinstance(v, bool):
        if v < 0:
            raise ValueError("số dư phải >= 0")
        return v
    return parse_money(str(v).strip(), allow_zero=True)


def _resolve_account_id(store, acc_val: Any) -> Optional[int]:
    if acc_val is None or acc_val == "":
        default_acc = store.get_default_account()
        return default_acc.id if default_acc else None
    if isinstance(acc_val, int):
        if not store.get_account(acc_val):
            raise LookupError(f"tài khoản {acc_val} không tồn tại")
        return acc_val
    s = str(acc_val).strip()
    if s.isdigit():
        aid = int(s)
        if store.get_account(aid):
            return aid
    acc = store.get_account_by_name(s)
    if not acc:
        raise LookupError(f"tài khoản {acc_val!r} không tồn tại")
    return acc.id


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
    _require(params, "amount")
    cat = str(params.get("category") or "").strip()
    acc_id = _resolve_account_id(store, params.get("account"))
    t = Transaction(_date(params.get("date"), today), _amount(params["amount"]), kind,
                    cat, str(params.get("note") or ""), account_id=acc_id)
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


def _kind(v: Any) -> str:
    v = str(v).lower()
    if v in ("income", "thu"):
        return INCOME
    if v in ("expense", "chi"):
        return EXPENSE
    raise ValueError("loại phải là income|expense")


def _given(params: dict, key: str) -> bool:
    return params.get(key) not in (None, "")


def edit(params, store, today):
    """Change fields of a transaction; only the given keys change (note may be set to "")."""
    _require(params, "id")
    tid = int(params["id"])
    t = store.get_transaction(tid)
    if t is None:
        raise LookupError("không tìm thấy giao dịch #%d" % tid)
    if _given(params, "amount"):
        t.amount = _amount(params["amount"])
    if "category" in params and params["category"] is not None:
        t.category = str(params["category"]).strip()
    if params.get("note") is not None:
        t.note = str(params["note"])
    if _given(params, "date"):
        t.date = _date(params["date"], today)
    if _given(params, "kind"):
        t.kind = _kind(params["kind"])
    if "account" in params:
        t.account_id = _resolve_account_id(store, params["account"])
    store.update_transaction(t)
    return {"transaction": tx_dict(t), "balance": store.balance()}


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
    p = _plan_or_raise(store, pid)
    if p.status != PENDING:
        raise ValueError("dòng tiền #%d không ở trạng thái chờ (status=%s)" % (pid, p.status))

    acc_id = None
    if params.get("account"):
        acc_id = _resolve_account_id(store, params["account"])
    elif store.get_default_account():
        acc_id = store.get_default_account().id

    d = _date(params.get("date"), today)

    # Validate sufficient balance for expense plans when account is used
    if p.kind == EXPENSE and acc_id is not None:
        bal = store.account_balance(acc_id)
        if bal < p.amount:
            acc = store.get_account(acc_id)
            acc_name = acc.name if acc else str(acc_id)
            raise ValueError("số dư tài khoản '%s' không đủ (%s < %s)" % (
                acc_name, money(bal), money(p.amount)
            ))

    t = plans.complete_plan(store, pid, d, account_id=acc_id)
    return {"transaction": tx_dict(t), "plan": plan_dict(store.get_plan(pid))}


def plan_cancel(params, store, today):
    _require(params, "id")
    pid = int(params["id"])
    _plan_or_raise(store, pid)
    plans.cancel_plan(store, pid)
    return {"plan": plan_dict(store.get_plan(pid))}


def plan_edit(params, store, today):
    """Change fields of a dòng tiền; only the given keys change."""
    _require(params, "id")
    pid = int(params["id"])
    p = _plan_or_raise(store, pid)
    if _given(params, "name"):
        p.name = str(params["name"])
    if _given(params, "amount"):
        p.amount = _amount(params["amount"])
    if _given(params, "category"):
        p.category = str(params["category"])
    if _given(params, "kind"):
        p.kind = _kind(params["kind"])
    if _given(params, "every"):
        if params["every"] not in RECURRENCES:
            raise ValueError("--every phải là %s" % "|".join(RECURRENCES))
        p.recurrence = params["every"]
        if p.recurrence != MONTHLY:
            p.day = None
    if _given(params, "day"):
        day = int(params["day"])
        if p.recurrence != MONTHLY:
            raise ValueError("--day chỉ dùng với --every monthly")
        if not 1 <= day <= 31:
            raise ValueError("--day phải từ 1 đến 31")
        p.day = day
        if not _given(params, "due"):
            p.due_date = _next_day_of_month(day, today)
    if _given(params, "due"):
        p.due_date = _date(params["due"], today)
    store.update_plan(p)
    return {"plan": plan_dict(p)}


def budget_set(params, store, today):
    _require(params, "category", "amount")
    b = Budget(str(params["category"]), _amount(params["amount"]))
    store.set_budget(b)
    return {"budget": {"category": b.category, "limit": b.limit}}


def budget_delete(params, store, today):
    _require(params, "category")
    if not store.delete_budget(str(params["category"])):
        raise LookupError("không có ngân sách cho %r" % params["category"])
    return {"deleted": str(params["category"])}


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


def history(params, store, today):
    """Daily balance series for charts.

    params: `days` back (default 90; 0 = from first transaction), `ahead` forecast days (default 90).
    → {today, series:[{date, balance, income, expense}] one row per day ending today,
       forecast:[{date, balance}] one row per day after today (step series from pending dòng tiền)}
    """
    from datetime import timedelta
    days = int(90 if params.get("days") is None else params["days"])
    ahead = int(90 if params.get("ahead") is None else params["ahead"])
    if days < 0 or ahead < 0:
        raise ValueError("days/ahead phải >= 0")
    txs = store.list_transactions(end=today)
    if days == 0:
        start = txs[0].date if txs else today
    else:
        start = today - timedelta(days=days - 1)
    per_day = {}  # type: Dict[date, list]
    running = 0
    for t in txs:
        if t.date < start:
            running += t.signed
        else:
            row = per_day.setdefault(t.date, [0, 0])
            row[0 if t.kind == INCOME else 1] += t.amount
    series = []
    d = start
    while d <= today:
        inc, exp = per_day.get(d, (0, 0))
        running += inc - exp
        series.append({"date": d.isoformat(), "balance": running, "income": inc, "expense": exp})
        d += timedelta(days=1)
    rows = cashflow.forecast(store, today, ahead)
    forecast, i, bal = [], 0, running
    for n in range(1, ahead + 1):
        d = today + timedelta(days=n)
        while i < len(rows) and rows[i][0] <= d:
            bal = rows[i][3]
            i += 1
        forecast.append({"date": d.isoformat(), "balance": bal})
    return {"today": today.isoformat(), "series": series, "forecast": forecast}


def goal(params, store, today):
    _require(params, "target", "by")
    target, by = _amount(params["target"]), _date(params["by"], today)
    g = plans.savings_goal(store, target, by, today)
    return dict(g, target=target, by=by.isoformat())


def goal_add(params, store, today):
    _require(params, "name", "target", "by")
    target = _amount(params["target"])
    by = _date(params["by"], today)
    saved = _amount(params["saved"]) if params.get("saved") not in (None, "", "0", 0) else 0
    g = Goal(str(params["name"]).strip(), target, by, saved)
    store.add_goal(g)
    return {"goal": plans.goal_dict(g, store, today)}


def goal_list(params, store, today):
    goals = [plans.goal_dict(g, store, today) for g in store.list_goals()] if hasattr(store, "list_goals") else []
    total_saved = store.total_saved() if hasattr(store, "total_saved") else 0
    bal = store.balance(today)
    return {"goals": goals, "total_saved": total_saved, "balance": bal, "free_balance": bal - total_saved}


def goal_save(params, store, today):
    _require(params, "id", "amount")
    gid = int(params["id"])
    g = store.get_goal(gid)
    if g is None:
        raise LookupError("không tìm thấy mục tiêu #%d" % gid)
    amt = _amount(params["amount"])
    g.saved += amt
    store.update_goal(g)
    total_saved = store.total_saved()
    return {"goal": plans.goal_dict(g, store, today), "saved_added": amt,
            "total_saved": total_saved, "free_balance": store.balance(today) - total_saved}


def goal_take(params, store, today):
    _require(params, "id", "amount")
    gid = int(params["id"])
    g = store.get_goal(gid)
    if g is None:
        raise LookupError("không tìm thấy mục tiêu #%d" % gid)
    amt = _amount(params["amount"])
    if amt > g.saved:
        raise ValueError("số tiền rút (%d) lớn hơn số đã góp (%d)" % (amt, g.saved))
    g.saved -= amt
    store.update_goal(g)
    total_saved = store.total_saved()
    return {"goal": plans.goal_dict(g, store, today), "taken": amt,
            "total_saved": total_saved, "free_balance": store.balance(today) - total_saved}


def goal_edit(params, store, today):
    _require(params, "id")
    gid = int(params["id"])
    g = store.get_goal(gid)
    if g is None:
        raise LookupError("không tìm thấy mục tiêu #%d" % gid)
    if _given(params, "name"):
        g.name = str(params["name"]).strip()
    if _given(params, "target"):
        g.target = _amount(params["target"])
    if _given(params, "by"):
        g.by = _date(params["by"], today)
    if _given(params, "saved"):
        g.saved = _amount(params["saved"]) if params["saved"] not in ("0", 0) else 0
    store.update_goal(g)
    return {"goal": plans.goal_dict(g, store, today)}


def goal_rm(params, store, today):
    _require(params, "id")
    gid = int(params["id"])
    if not store.delete_goal(gid):
        raise LookupError("không tìm thấy mục tiêu #%d" % gid)
    return {"deleted": gid, "total_saved": store.total_saved() if hasattr(store, "total_saved") else 0}


def account_add(params, store, today):
    _require(params, "name")
    name = str(params["name"]).strip()
    raw_bal = params.get("balance") if params.get("balance") is not None else params.get("initial_balance")
    init_bal = _initial_amount(raw_bal) if raw_bal is not None else 0
    is_def = bool(params.get("default", False))
    a = Account(name, init_bal, is_def)
    aid = store.add_account(a)
    return {"account": account_dict(store.get_account(aid), store, today)}


def account_list(params, store, today):
    accs = store.list_accounts()
    return {
        "accounts": [account_dict(a, store, today) for a in accs],
        "total_balance": store.total_balance(today),
    }


def account_edit(params, store, today):
    _require(params, "id")
    aid = _resolve_account_id(store, params["id"])
    if aid is None:
        raise LookupError("không tìm thấy tài khoản %s" % params["id"])
    a = store.get_account(aid)
    if a is None:
        raise LookupError("không tìm thấy tài khoản #%d" % aid)
    if _given(params, "name"):
        a.name = str(params["name"]).strip()
    if _given(params, "balance"):
        target_bal = _initial_amount(params["balance"])
        cur_bal = store.account_balance(aid)
        diff = target_bal - cur_bal
        a.initial_balance += diff
    elif _given(params, "initial_balance"):
        a.initial_balance = _initial_amount(params["initial_balance"])
    if params.get("default") is not None:
        a.is_default = bool(params["default"])
    store.update_account(a)
    return {"account": account_dict(store.get_account(aid), store, today)}


def account_set_balance(params, store, today):
    _require(params, "id", "balance")
    return account_edit(params, store, today)


def account_rm(params, store, today):
    _require(params, "id")
    aid = int(params["id"])
    if not store.delete_account(aid):
        raise LookupError("không tìm thấy tài khoản #%d" % aid)
    return {"deleted": aid}


def account_transfer(params, store, today):
    _require(params, "from", "to", "amount")
    from_id = _resolve_account_id(store, params["from"])
    to_id = _resolve_account_id(store, params["to"])
    if from_id is None:
        raise LookupError("tài khoản nguồn không tồn tại")
    if to_id is None:
        raise LookupError("tài khoản đích không tồn tại")
    if from_id == to_id:
        raise ValueError("không thể chuyển tiền đến cùng tài khoản")
    amt = _amount(params["amount"])
    d = _date(params.get("date"), today)
    note = str(params.get("note") or "").strip()
    tr = Transfer(d, amt, from_id, to_id, note)
    tid = store.add_transfer(tr)
    created_tr = next((t for t in store.list_transfers() if t.id == tid), tr)
    return {
        "transfer": transfer_dict(created_tr, store),
        "from_balance": store.account_balance(from_id),
        "to_balance": store.account_balance(to_id),
    }


def account_transfers(params, store, today):
    acc_val = params.get("account")
    acc_id = _resolve_account_id(store, acc_val) if acc_val else None
    start = _date(params["start"], today) if params.get("start") else None
    end = _date(params["end"], today) if params.get("end") else None
    trs = store.list_transfers(account_id=acc_id, start=start, end=end)
    return {"transfers": [transfer_dict(tr, store) for tr in trs]}


def account_set_default(params, store, today):
    _require(params, "id")
    aid = int(params["id"])
    store.set_default_account(aid)
    return {"account": account_dict(store.get_account(aid), store, today)}


def dash(params, store, today):
    month = summary({}, store, today)
    goals = [plans.goal_dict(g, store, today) for g in store.list_goals()] if hasattr(store, "list_goals") else []
    total_saved = store.total_saved() if hasattr(store, "total_saved") else 0
    bal = store.balance(today)
    accounts = [account_dict(a, store, today) for a in store.list_accounts()] if hasattr(store, "list_accounts") else []
    return {
        "today": today.isoformat(),
        "balance": bal,
        "total_saved": total_saved,
        "free_balance": bal - total_saved,
        "month": month,
        "accounts": accounts,
        "overdue": [plan_dict(p) for p in plans.overdue(store, today)],
        "budgets": plans.budget_status(store, today.year, today.month),
        "goals": goals,
        "upcoming": _rows(cashflow.forecast(store, today, 30)),
        "lowest": _lowest(cashflow.forecast(store, today, 90)),
    }


def categories(params, store, today):
    """Categories by use count (most used first), split by kind — for pick lists in UIs."""
    counts = {INCOME: {}, EXPENSE: {}}  # type: Dict[str, Dict[str, int]]
    for t in store.list_transactions():
        if t.category:
            counts[t.kind][t.category] = counts[t.kind].get(t.category, 0) + 1
    for p in store.list_plans(status=None):
        if p.category:
            counts[p.kind].setdefault(p.category, 0)
    for b in store.list_budgets():
        if b.category:
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


ICON_MODES = ("symbol", "emoji", "off")


def icons(params, store, today):
    """Get or set the TUI icon style: params {"mode": "symbol"|"emoji"|"off"} or {} to read."""
    mode = params.get("mode")
    if mode not in (None, ""):
        if mode not in ICON_MODES:
            raise ValueError("icons phải là %s" % "|".join(ICON_MODES))
        store.set_setting("icons", mode)
    return {"icons": store.get_setting("icons", "symbol")}


COMMANDS = {
    "income": income, "expense": expense, "list": list_, "rm": rm, "summary": summary,
    "plan add": plan_add, "plan list": plan_list, "plan done": plan_done, "plan cancel": plan_cancel,
    "edit": edit, "plan edit": plan_edit,
    "budget set": budget_set, "budget status": budget_status, "budget delete": budget_delete,
    "history": history,
    "forecast": forecast, "goal": goal,
    "goal add": goal_add, "goal list": goal_list, "goal save": goal_save, "goal take": goal_take,
    "goal edit": goal_edit, "goal rm": goal_rm, "goal delete": goal_rm,
    "account add": account_add, "account list": account_list, "account edit": account_edit,
    "account set-balance": account_set_balance,
    "account rm": account_rm, "account delete": account_rm, "account transfer": account_transfer,
    "account transfers": account_transfers, "account set-default": account_set_default,
    "dash": dash, "categories": categories, "sound": sound, "icons": icons,
}  # type: Dict[str, Callable[[dict, Any, date], dict]]


def execute(cmd: str, params: Optional[dict], store, today: Optional[date] = None) -> dict:
    fn = COMMANDS.get(cmd)
    if fn is None:
        raise ValueError("lệnh không hợp lệ: %r (có: %s)" % (cmd, ", ".join(COMMANDS)))
    return fn(params or {}, store, today or date.today())
