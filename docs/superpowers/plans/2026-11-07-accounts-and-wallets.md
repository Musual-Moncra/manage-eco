# Accounts and Wallets (Quản lý Nguồn tiền & Tài khoản) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to divide, track, and transfer money across distinct wallets and accounts (cash, bank accounts, e-wallets) with automatic balance calculations, a dedicated TUI tab, frictionless quick entry, and zero disruption to monthly income/expense metrics.

**Architecture:** Add `Account` and `Transfer` entities in SQLite with an `account_id` foreign key on `transactions`. Expose account operations (`add`, `list`, `edit`, `rm`, `transfer`, `transfers`, `set-default`) and `--account` flags in Python API, CLI (`--json` and rich views), and introduce a dedicated "Tài khoản" tab (Tab 2) in the TUI along with account chips in the transaction form.

**Tech Stack:** Python 3.9, SQLite3, stdlib (`dataclasses`, `datetime`), `rich` (views/TUI only), `unittest`.

**Spec:** [`docs/superpowers/specs/2026-11-07-accounts-and-wallets-design.md`](file:///Users/musual/(%20App%20)%20Manage%20Eco/docs/superpowers/specs/2026-11-07-accounts-and-wallets-design.md)

## Global Constraints

- Python 3.9 compatibility (no `match`, no `X | Y` union type syntax; use `Optional[...]`, `Union[...]`).
- stdlib + `rich` only. No external dependencies.
- `--json` mode must never import `rich`, prints exactly one JSON object on stdout, and exits 0 (ok), 1 (not_found), 2 (invalid).
- All amounts are integers in VND (đồng). Dates are ISO strings `YYYY-MM-DD`.
- Transfers between internal accounts must never appear as expenses or incomes in monthly summary, cashflow, or charts.
- RAM RSS budget: `eco --json dash` < 25 MB max RSS; `eco ui` < 45 MB.
- Test runner: `python3 -m unittest discover -s tests -v` with `Store(":memory:")`.

## Review Focus

1. **Transfer to self (`from_account == to_account`):** Must be rejected with a clear error and not modify any balances.
2. **Account deletion with dependencies:** Attempting to delete an account that has associated transactions or transfer history must be prevented with a descriptive error.
3. **Sole default account deletion:** Deleting the only account or deleting an account marked as default without another default being designated must be blocked.
4. **Frictionless quick entry fallback:** When creating a transaction without specifying an account, it must automatically bind to the default account (or `None` if no accounts exist yet for backward compatibility).
5. **Transfer integrity:** Account balance calculation must accurately sum `initial_balance + sum(income) - sum(expense) + sum(transfers_in) - sum(transfers_out)` without double-counting.

---

### Task 1: Data Models and Store Layer for Accounts & Transfers

**Files:**
- Modify: `manage_eco/models.py:1-68`
- Modify: `manage_eco/db.py:1-212`
- Test: `tests/test_accounts_db.py`

**Interfaces:**
- Consumes: `models.py`, `db.py`
- Produces:
  - `models.Account(name: str, initial_balance: int = 0, is_default: bool = False, id: Optional[int] = None)`
  - `models.Transfer(date: date, amount: int, from_account_id: int, to_account_id: int, note: str = "", id: Optional[int] = None)`
  - `models.Transaction` with `account_id: Optional[int] = None`
  - `Store.add_account(account: Account) -> int`
  - `Store.list_accounts() -> List[Account]`
  - `Store.get_account(account_id: int) -> Optional[Account]`
  - `Store.get_account_by_name(name: str) -> Optional[Account]`
  - `Store.get_default_account() -> Optional[Account]`
  - `Store.update_account(account: Account) -> None`
  - `Store.delete_account(account_id: int) -> bool`
  - `Store.set_default_account(account_id: int) -> None`
  - `Store.add_transfer(transfer: Transfer) -> int`
  - `Store.list_transfers(account_id: Optional[int] = None, start: Optional[date] = None, end: Optional[date] = None) -> List[Transfer]`
  - `Store.delete_transfer(transfer_id: int) -> bool`
  - `Store.account_balance(account_id: int, as_of: Optional[date] = None) -> int`
  - `Store.total_balance(as_of: Optional[date] = None) -> int`
  - Updated `Store.balance(as_of: Optional[date] = None) -> int` (returns `total_balance(as_of)` when accounts exist, or fallback when none exist).

- [ ] **Step 1: Write the failing tests in `tests/test_accounts_db.py`**
  Covering account creation, auto-default for first account, balance calculation with income/expense/transfers, delete protection for referenced accounts, and transaction `account_id` persistence.

- [ ] **Step 2: Run test to verify it fails**
  Run: `python3 -m unittest tests/test_accounts_db.py -v`
  Expected: FAIL with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement `Account`, `Transfer`, and `Store` account/transfer methods**
  - Add dataclasses in `manage_eco/models.py`.
  - Update `SCHEMA` and migration in `manage_eco/db.py` (`ALTER TABLE transactions ADD COLUMN account_id INTEGER`).
  - Implement account and transfer CRUD methods and balance calculations in `manage_eco/db.py`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `python3 -m unittest tests/test_accounts_db.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add manage_eco/models.py manage_eco/db.py tests/test_accounts_db.py
  git commit -m "feat(db): add Account, Transfer models and database store methods"
  ```

---

### Task 2: Service API Layer (`manage_eco/api.py`)

**Files:**
- Modify: `manage_eco/api.py:1-550`
- Test: `tests/test_accounts_api.py`

**Interfaces:**
- Consumes: Task 1 `Account`, `Transfer`, and `Store` methods.
- Produces:
  - `execute("account add", params, store, today) -> {"account": dict}`
  - `execute("account list", params, store, today) -> {"accounts": list, "total_balance": int}`
  - `execute("account edit", params, store, today) -> {"account": dict}`
  - `execute("account rm", params, store, today) -> {"deleted": int}`
  - `execute("account transfer", params, store, today) -> {"transfer": dict, "from_balance": int, "to_balance": int}`
  - `execute("account transfers", params, store, today) -> {"transfers": list}`
  - `execute("account set-default", params, store, today) -> {"account": dict}`
  - Updated `execute("income", ...)` & `execute("expense", ...)`: accept `params.get("account")` (name or id) and populate `transaction.account_id`.
  - Updated `execute("edit", ...)`: accept `params.get("account")`.
  - Updated `execute("dash", ...)`: include `"accounts": [...]` in returned dashboard dict.

- [ ] **Step 1: Write the failing tests in `tests/test_accounts_api.py`**
  Covering account management API, transfers between accounts (by ID and by name), self-transfer rejection, expense/income attribution to account, and dash payload.

- [ ] **Step 2: Run test to verify it fails**
  Run: `python3 -m unittest tests/test_accounts_api.py -v`
  Expected: FAIL with `ValueError: unknown command 'account add'`.

- [ ] **Step 3: Implement account & transfer API handlers in `manage_eco/api.py`**
  Add command handlers for `"account add"`, `"account list"`, `"account edit"`, `"account rm"`, `"account transfer"`, `"account transfers"`, `"account set-default"`, update `income`, `expense`, `edit`, and update `dash`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `python3 -m unittest tests/test_accounts_api.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add manage_eco/api.py tests/test_accounts_api.py
  git commit -m "feat(api): add account and transfer api command handlers"
  ```

---

### Task 3: CLI Subcommand, Renderers & JSON Contract (`cli.py`, `views.py`, `AGENTS.md`)

**Files:**
- Modify: `manage_eco/cli.py:1-250`
- Modify: `manage_eco/views.py:1-350`
- Modify: `AGENTS.md`
- Test: `tests/test_accounts_cli.py`

**Interfaces:**
- Consumes: Task 2 API commands.
- Produces:
  - CLI subcommand `eco account <add|list|edit|rm|transfer|transfers|set-default>`
  - `--account` / `-a` flag on `eco income`, `eco expense`, `eco edit`, `eco plan done`
  - `--json` mode support for all new commands and flags without importing `rich`
  - Rich table views for `eco account list` and `eco account transfers`
  - Agent documentation in `AGENTS.md`

- [ ] **Step 1: Write failing CLI and JSON tests in `tests/test_accounts_cli.py`**
  Covering command line execution, `--json` envelope, non-json table formatting, and exit codes (0 for success, 1 for not found, 2 for invalid input).

- [ ] **Step 2: Run test to verify it fails**
  Run: `python3 -m unittest tests/test_accounts_cli.py -v`
  Expected: FAIL with unrecognized command or argument.

- [ ] **Step 3: Implement CLI parser, rich views, and update `AGENTS.md`**
  - Add `account` subparser and `--account` flags in `manage_eco/cli.py`.
  - Add `render_account_list` and `render_account_transfers` in `manage_eco/views.py`.
  - Update `AGENTS.md` with full usage examples for `account`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `python3 -m unittest tests/test_accounts_cli.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add manage_eco/cli.py manage_eco/views.py AGENTS.md tests/test_accounts_cli.py
  git commit -m "feat(cli): add account subcommand, rich renderers, and AGENTS documentation"
  ```

---

### Task 4: TUI "Tài khoản" Tab, Dialog Forms & Overview Integration (`manage_eco/tui.py`)

**Files:**
- Modify: `manage_eco/tui.py:1-2400`
- Test: `tests/test_accounts_tui.py`

**Interfaces:**
- Consumes: Task 2 API commands, Task 1 models.
- Produces:
  - 7 tabs in TUI: `["Tổng quan", "Tài khoản", "Giao dịch", "Dòng tiền", "Ngân sách", "Hũ tiết kiệm", "Biểu đồ"]` (Tab index 1).
  - Tab 1 ("Tài khoản"):
    - Header cards: Total assets, account count.
    - Action bar: `[+ Thêm a]`, `[⇄ Chuyển tiền t]`, `[✎ Sửa e]`, `[★ Mặc định s]`, `[✕ Xóa d]`.
    - Main table: Account name, current balance, initial balance, percent allocation bar, `[Mặc định]` badge.
    - Transfers list: Recent transfer history table (`date`, `from -> to`, `amount`, `note`).
  - Account dialog forms:
    - Add Account: name, initial_balance, is_default checkbox.
    - Edit Account: name, initial_balance, is_default checkbox.
    - Transfer: from_account, to_account, amount (with quick chips `50k`, `100k`, `200k`, `500k`, `1tr`, `2tr`, `5tr`), note, date.
  - Transaction form in Tab 2 ("Giao dịch"):
    - Account chip row `[Tài khoản: Tiền mặt | ZaloPay | Techcombank...]`, pre-selecting default account.
  - Tab 0 ("Tổng quan"):
    - Account summary widget showing current balances across active accounts.

- [ ] **Step 1: Write failing TUI integration tests in `tests/test_accounts_tui.py`**
  Covering tab 1 navigation, rendering account cards, opening and submitting Add Account form, opening and submitting Transfer form, and transaction form account chips.

- [ ] **Step 2: Run test to verify it fails**
  Run: `python3 -m unittest tests/test_accounts_tui.py -v`
  Expected: FAIL.

- [ ] **Step 3: Implement Account tab and interactions in `manage_eco/tui.py`**
  - Update `TABS`, `TABS_SHORT`, and `ICON_SETS` to include "Tài khoản".
  - Implement `render_accounts_tab()` with account list and transfer table.
  - Implement `open_add_account_form()`, `open_edit_account_form()`, and `open_transfer_form()`.
  - Add account chips in transaction form and overview widget in `render_overview()`.
  - Handle keybindings (`a`, `t`, `e`, `d`, `s`) and mouse clicks for the new tab and forms.

- [ ] **Step 4: Run test to verify it passes**
  Run: `python3 -m unittest tests/test_accounts_tui.py -v`
  Expected: PASS

- [ ] **Step 5: Run full test suite to verify no regressions**
  Run: `python3 -m unittest discover -s tests -v`
  Expected: All new tests pass, no regressions.

- [ ] **Step 6: Commit**
  ```bash
  git add manage_eco/tui.py tests/test_accounts_tui.py
  git commit -m "feat(tui): add Tài khoản tab, account/transfer forms, and overview integration"
  ```
