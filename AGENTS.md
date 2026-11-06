# AGENTS.md — operating Manage Eco from an AI agent

Manage Eco is a terminal app for personal expenses, cash flow and planned
spending. This file is the contract for agents: **always talk to it through
`--json`**, never scrape the human-facing tables.

## Rules

1. Always pass `--json` (or set `ECO_JSON=1`). JSON mode prints exactly one
   JSON object on stdout and never imports `rich`.
2. Always pass `--db PATH` to isolate state, and `--today YYYY-MM-DD` for
   deterministic results. Global flags go **before** the subcommand.
3. Amounts are integers in VND (đồng). Dates are ISO `YYYY-MM-DD` strings.
4. Exit code is the source of truth: `0` ok, `1` not found, `2` invalid input.
   stdout is still valid JSON on errors — parse it, don't parse stderr.
5. Do not edit the SQLite file directly. Use the commands below.

## Invocation

```bash
python3 -m manage_eco --json --db /tmp/eco.db --today 2026-11-06 <command> [args]
```

Global flags:

| Flag | Meaning |
| --- | --- |
| `--json` | machine output (or env `ECO_JSON=1`) |
| `--db PATH` | SQLite file; default `$ECO_DB` or `~/.manage_eco.db` |
| `--today YYYY-MM-DD` | "today" for relative dates and default month |

Amounts accept integers, unit suffixes (`20000000`, `1.250.000`, `1,250,000`,
`1.5tr`/`1.5m`, `200k`) and arithmetic (rounded to đồng):

| Input | Value |
| --- | --- |
| `50k+20k` | 70.000 ₫ |
| `3x150k` | 450.000 ₫ |
| `1tr:4` | 250.000 ₫ |
| `(2tr-500k)*2` | 3.000.000 ₫ |

Operators `+ - x X × * : / ÷`, parentheses, spaces and unary minus; no `eval`.

Dates accept ISO `2026-11-06`, `06/11/2026`, `today`/`hom nay`, `+7`, and
(case/diacritics-insensitive):

| Input | Meaning |
| --- | --- |
| `hôm qua` / `qua` | yesterday |
| `mai` / `ngày mai` | tomorrow |
| `mốt` / `ngày kia` | +2 days |
| `-3` / `+7` | days from today |
| `15` | day 15 of this month (clamped) |
| `15/11` or `15-11` | 15 Nov, this year |
| `15/11/26` | 15 Nov 2026 |
| `thứ 6` / `t6` | next Friday (today excluded) |
| `chủ nhật` / `cn` | next Sunday |
| `tuần sau` | +7 days |
| `tháng sau` | same day next month (clamped) |
| `đầu tháng sau` | 1st of next month |
| `cuối tháng` | last day of this month |

## Envelope and errors

Success (exit 0):

```json
{"ok": true, "command": "income", "data": {"transaction": {"id": 1, "date": "2026-11-01", "amount": 20000000, "kind": "income", "category": "salary", "note": "luong", "signed": 20000000}, "balance": 20000000}}
```

Error (exit 1 `not_found`, exit 2 `invalid`):

```json
{"ok": false, "error": "transaction 999 not found", "code": "not_found"}
```

`transaction` objects always have
`{id,date,amount,kind,category,note,signed}`.
`plan` objects always have
`{id,name,amount,kind,due_date,category,recurrence,status,day}`.
"Plan" is shown to users as **"Dòng tiền"**; the command stays `plan`.

## Commands

### `income` / `expense AMOUNT CATEGORY [-n NOTE] [-d DATE]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 \
  income 20000000 salary -n luong -d 2026-11-01
```

```json
{"ok": true, "command": "income", "data": {"transaction": {"id": 1, "date": "2026-11-01", "amount": 20000000, "kind": "income", "category": "salary", "note": "luong", "signed": 20000000}, "balance": 20000000}}
```

`expense` is identical with `kind: "expense"` and a negative `signed`.

### `list [--month YYYY-MM | --all]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 list --all
```

```json
{"ok": true, "command": "list", "data": {"transactions": [{"id": 1, "date": "2026-11-01", "amount": 20000000, "kind": "income", "category": "salary", "note": "luong", "signed": 20000000}], "balance": 20000000}}
```

Default month is the month of `--today`.

### `rm ID`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 rm 1
```

```json
{"ok": true, "command": "rm", "data": {"deleted": 1, "balance": 0}}
```

### `summary [--month YYYY-MM]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 summary --month 2026-11
```

```json
{"ok": true, "command": "summary", "data": {"month": "2026-11", "income": 20000000, "expense": 6000000, "net": 14000000, "by_category": [{"category": "food", "amount": 6000000}]}}
```

`by_category` lists expenses only, largest first.

### `plan add NAME AMOUNT CATEGORY [--due DATE] [--every once|daily|weekly|monthly] [--day N] [--income]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 \
  plan add Rent 25000000 housing --due 2026-12-01 --every monthly
```

```json
{"ok": true, "command": "plan add", "data": {"plan": {"id": 1, "name": "Rent", "amount": 25000000, "kind": "expense", "due_date": "2026-12-01", "category": "housing", "recurrence": "monthly", "status": "pending", "day": null}}}
```

`--income` makes it planned income; default recurrence is `once`.
`--every monthly --day N` fixes the monthly day (1..31, clamped, never
drifts); `--due` is then optional and defaults to the next date ≥ today on
day N. `--day` with any other recurrence is invalid (exit 2).

```bash
# daily, and monthly on a fixed day without --due
plan add Coffee 20k food --due +1 --every daily
plan add Rent 25tr housing --every monthly --day 31
```

### `plan list [--all]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 plan list --all
```

```json
{"ok": true, "command": "plan list", "data": {"plans": [{"id": 1, "name": "Rent", "amount": 25000000, "kind": "expense", "due_date": "2026-12-01", "category": "housing", "recurrence": "monthly", "status": "pending", "day": null}]}}
```

Without `--all`, only `pending` plans are returned.

### `plan done ID [-d DATE]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 plan done 1 -d 2026-11-06
```

```json
{"ok": true, "command": "plan done", "data": {"transaction": {"id": 2, "date": "2026-11-06", "amount": 25000000, "kind": "expense", "category": "housing", "note": "plan:Rent", "signed": -25000000}, "plan": {"id": 1, "name": "Rent", "amount": 25000000, "kind": "expense", "due_date": "2027-01-01", "category": "housing", "recurrence": "monthly", "status": "pending", "day": null}}}
```

A `once` plan becomes `done`; `daily`/`weekly`/`monthly` plans advance
`due_date` and stay `pending` (month-end is clamped, e.g. 31 → 28/30, and
monthly keeps the anchor day so it returns to 31).

### `plan cancel ID`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 plan cancel 1
```

```json
{"ok": true, "command": "plan cancel", "data": {"plan": {"id": 1, "name": "Rent", "amount": 25000000, "kind": "expense", "due_date": "2026-12-01", "category": "housing", "recurrence": "monthly", "status": "cancelled", "day": null}}}
```

### `budget set CATEGORY AMOUNT`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 budget set food 3000000
```

```json
{"ok": true, "command": "budget set", "data": {"budget": {"category": "food", "limit": 3000000}}}
```

### `budget status [--month YYYY-MM]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 budget status
```

```json
{"ok": true, "command": "budget status", "data": {"month": "2026-11", "budgets": [{"category": "food", "limit": 3000000, "spent": 1500000, "remaining": 1500000, "pct": 50.0}]}}
```

`pct` is a percentage float; it can exceed 100.

### `forecast [--days N]`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 forecast --days 30
```

```json
{"ok": true, "command": "forecast", "data": {"today": "2026-11-06", "balance": 20000000, "days": 30, "rows": [{"date": "2026-11-16", "name": "Rent", "amount": -3000000, "balance": 17000000}], "lowest": {"date": "2026-11-16", "balance": 17000000}}}
```

`rows` are pending plans in `(today, today+days]`, chronological, with the
running balance. `lowest` is the minimum running balance, or `null` when there
are no rows.

### `goal TARGET --by DATE`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 goal 10000000 --by 2027-02-06
```

```json
{"ok": true, "command": "goal", "data": {"target": 10000000, "by": "2027-02-06", "needed": 8000000, "months_left": 3, "per_month": 2666667}}
```

`needed = max(0, target - balance)`; `per_month` rounds up so the goal is
reachable.

### `dash`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 dash
```

```json
{"ok": true, "command": "dash", "data": {"today": "2026-11-06", "balance": 19850000, "month": {"month": "2026-11", "income": 20000000, "expense": 150000, "net": 19850000, "by_category": [{"category": "food", "amount": 150000}]}, "overdue": [], "budgets": [{"category": "food", "limit": 3000000, "spent": 150000, "remaining": 2850000, "pct": 5.0}], "upcoming": [], "lowest": null}}
```

`month` is a summary object; `upcoming` is the 30-day forecast; `lowest` is the
90-day minimum running balance.

### `categories`

```bash
python3 -m manage_eco --json --db eco.db --today 2026-11-06 categories
```

```json
{"ok": true, "command": "categories", "data": {"expense": ["food", "transport", "bills", "housing"], "income": ["salary", "job"]}}
```

Categories split by kind, most used first (ties alphabetical). Plan and budget
categories are included with count 0.

## Python API

`manage_eco.api.execute(cmd, params, store, today)` returns the same `data`
dict the CLI prints (not the envelope). It raises `LookupError` for missing
records and `ValueError` for bad input. Plain dicts only — ISO date strings,
integer VND amounts.

```python
from datetime import date
from manage_eco.db import Store
from manage_eco.api import execute

store = Store(":memory:")  # or Store("/tmp/eco.db")
today = date(2026, 11, 6)

tx = execute("income", {"amount": 20_000_000, "category": "salary",
                        "note": "luong", "date": "2026-11-01"}, store, today)
print(tx["transaction"]["id"], tx["balance"])

print(execute("summary", {"month": "2026-11"}, store, today))
print(execute("plan add", {"name": "Rent", "amount": 25_000_000,
                           "category": "housing", "due": "2026-12-01",
                           "every": "monthly"}, store, today))
print(execute("forecast", {"days": 30}, store, today))
print(execute("dash", {}, store, today))
```

Params mirror the CLI arguments: `amount`, `category`, `note`, `date`, `id`,
`month`, `all`, `name`, `due`, `every`, `day`, `income`, `target`, `by`, `days`.
`store` is a `manage_eco.db.Store`; `today` is a `datetime.date`.

## Memory

`eco --json dash` must stay under 25 MB max RSS. Check with
`scripts/memcheck.sh` (uses `/usr/bin/time -l`).
