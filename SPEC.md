# Manage Eco — module contract

Python 3.9 (no `match`, no `X | Y` types), stdlib + `rich` only. Tests: `unittest` (no pytest) in `tests/test_<module>.py`, use `Store(":memory:")`.
Run all tests: `python3 -m unittest discover -s tests -v`

Done (do not edit, ask coordinator claude-1 for changes): `manage_eco/models.py`, `manage_eco/db.py`.

## manage_eco/cashflow.py — owner claude-2
- `month_range(year:int, month:int) -> Tuple[date, date]`  (first, last day)
- `summary(store, start:date, end:date) -> dict` → `{"income": int, "expense": int, "net": int}`
- `by_category(store, start, end, kind=EXPENSE) -> List[Tuple[str, int]]` sorted desc by amount
- `expand_plan(plan, start:date, end:date) -> List[date]`  occurrences of a pending plan in [start,end]; ONCE → due_date if in range; WEEKLY every 7 days from due_date; MONTHLY same day each month from due_date (clamp to month end, e.g. 31 → 30/28)
- `forecast(store, today:date, days:int) -> List[Tuple[date, str, int, int]]` → chronological (date, plan name, signed amount, running balance) starting from `store.balance(today)`, over pending plans in (today, today+days]
- `lowest_point(rows) -> Optional[Tuple[date,int]]` min running balance (to warn "sẽ âm tiền ngày X")

## manage_eco/plans.py — owner opencode-1
- `complete_plan(store, plan_id:int, on:date) -> Transaction` : records a Transaction from the plan (note="plan:<name>"); ONCE → status DONE; WEEKLY/MONTHLY → advance due_date by one period (same month-end clamping) and stay PENDING. Raise `ValueError` if not found / not pending.
- `cancel_plan(store, plan_id) -> None` → status CANCELLED (ValueError if not found)
- `overdue(store, today) -> List[Plan]` pending with due_date < today
- `budget_status(store, year, month) -> List[dict]` per budget: `{"category", "limit", "spent", "remaining", "pct"}` (pct = percent float, 85.0 = 85%, spent = expenses in that month)
- `savings_goal(store, target:int, by:date, today:date) -> dict` → `{"needed": int, "months_left": int, "per_month": int}` (needed = max(0, target - balance), months_left ≥ 1)

## manage_eco/fmt.py — owner antigravity-1
- `money(amount:int, signed=False) -> str` → `"1.250.000 ₫"`, signed adds `+`/`-`
- `parse_money(s:str) -> int` accepts `"1250000"`, `"1.250.000"`, `"1,250,000"`, `"1.5tr"`/`"1.5m"` (million), `"200k"` (thousand); ValueError on bad input or ≤0
- `parse_date(s:str, today:date) -> date` accepts ISO `2026-11-06`, `06/11/2026`, `today`/`hom nay`, `+7` (days from today)
- `progress_bar(pct:float, width=20) -> str` (pct is a percent, 85.0 = 85%) rich-markup bar, green <80%, yellow <100%, red ≥100%
- Also write `README.md` (Vietnamese, install `pip install -e .`, usage of every `eco` command listed below).

## manage_eco/cli.py — owner claude-1 (coordinator)
`eco income|expense`, `eco list`, `eco rm`, `eco summary [--month YYYY-MM]`, `eco plan add|list|done|cancel`, `eco budget set|status`, `eco forecast [--days 90]`, `eco goal`, `eco dash`.

## v2: agent-friendly + TUI + low RAM

Layers (owner claude-1 unless noted):
- `manage_eco/api.py` — `execute(cmd:str, params:dict, store, today) -> dict` + one function per command. Plain dicts only (dates ISO strings, amounts int VND). Raises `LookupError` (not found) / `ValueError` (bad input). Usable directly from Python by agents.
- `manage_eco/views.py` — rich renderables built from api dicts (`render(cmd, data) -> renderable`, `dashboard(data) -> renderable`). Only module (besides tui.py) that imports rich.
- `manage_eco/cli.py` — argparse → api → views. `eco --json <cmd> ...` prints exactly one JSON object to stdout and never imports rich.
- `manage_eco/tui.py` — owner claude-2. `eco ui`.

### JSON contract (`eco --json ...`, also `ECO_JSON=1`)
Success: `{"ok": true, "command": "<cmd>", "data": {...}}`, exit 0.
Error: `{"ok": false, "error": "<msg>", "code": "not_found"|"invalid"}`, exit 1 (not_found) / 2 (invalid).
Global flags: `--json`, `--db PATH` (else `$ECO_DB` or `~/.manage_eco.db`), `--today YYYY-MM-DD` (testing/agents).
Objects: transaction `{id,date,amount,kind,category,note,signed}`; plan `{id,name,amount,kind,due_date,category,recurrence,status}`.
Commands → data:
- `income|expense AMOUNT CATEGORY [-n NOTE] [-d DATE]` → `{transaction, balance}`
- `list [--month YYYY-MM|--all]` → `{transactions:[...], balance}`
- `rm ID` → `{deleted: id, balance}`
- `summary [--month]` → `{month:"YYYY-MM", income, expense, net, by_category:[{category, amount}]}`
- `plan add NAME AMOUNT CATEGORY --due DATE [--every once|weekly|monthly] [--income]` → `{plan}`
- `plan list [--all]` → `{plans:[...]}`; `plan done ID [-d DATE]` → `{transaction, plan}`; `plan cancel ID` → `{plan}`
- `budget set CATEGORY AMOUNT` → `{budget:{category,limit}}`; `budget status [--month]` → `{month, budgets:[{category,limit,spent,remaining,pct}]}`
- `forecast [--days N]` → `{today, balance, days, rows:[{date,name,amount,balance}], lowest:{date,balance}|null}`
- `goal TARGET --by DATE` → `{target, by, needed, months_left, per_month}`
- `categories` → `{expense:[names], income:[names]}` most used first (includes plan/budget categories)
- `dash` → `{today, balance, month:{...summary}, overdue:[plans], budgets:[...], upcoming:[forecast rows 30d], lowest:{...}|null (90d)}`

### RAM budget
`eco --json dash` max RSS < 25 MB; `eco ui` < 45 MB (measure: `/usr/bin/time -l`). No new dependencies.
