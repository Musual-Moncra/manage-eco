# Selective Write Permissions for Live Share Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable granular edit permissions on the Manage Eco live share viewer so partners can selectively record expenses, complete cashflow plans, save into jars, or delete transactions based on explicit checkboxes toggled by the user on Terminal Tab 8.

**Architecture:** Extend `ShareServer` with a secured `POST /api/action?pin=...` endpoint governed by a strict whitelist of allowed edit actions (`server.allowed_edits`), dispatching approved actions to `manage_eco.api.execute(...)`, broadcasting real-time updates via SSE, and notifying the TUI event loop via an `on_mutation` callback. Enhance Tab 8 in `tui.py` with edit permission chips (`a`, `d`, `g`, `x`), and embed responsive mobile forms (Floating Action Button + Bottom Sheet modal + inline action buttons) into the single-page web template.

**Tech Stack:** Python 3 standard library (`http.server`, `json`, `sqlite3`, `threading`), vanilla HTML5/CSS3/JavaScript (CSS Grid/Flexbox, SSE `EventSource`, `fetch`).

**Spec:** [`docs/superpowers/specs/2026-11-08-selective-write-permissions-design.md`](file:///Users/musual/(%20App%20)%20Manage%20Eco/docs/superpowers/specs/2026-11-08-selective-write-permissions-design.md)

## Global Constraints
- Maximum process RSS must remain strictly under 25 MB (`scripts/memcheck.sh`).
- Zero new external runtime dependencies in `pyproject.toml`.
- All amounts formatted as integers in VND; dates as ISO `YYYY-MM-DD`.
- Strict read-write separation: unauthorized actions rejected with HTTP 403 Forbidden.
- Non-blocking execution: no heavy computations or network calls on TUI render loop.

## Review Focus
1. Attempting an unpermitted mutation (e.g. `expense` when only `cashflow` is allowed) returns `403 Forbidden` with a friendly Vietnamese error message.
2. Malformed or negative amounts submitted via the mobile web form trigger clean error toasts without crashing the server thread.
3. Rapid concurrent actions from mobile web do not deadlock SQLite (`check_same_thread=False` and thread-safe store access).
4. Toggling permissions on Tab 8 immediately propagates to active mobile browser sessions without requiring a page reload.
5. Deleting transactions from mobile web prompts a confirmation dialog to prevent accidental deletion.

---

### Task 1: Backend Data Model & Snapshot Extension

**Files:**
- Modify: `manage_eco/share_data.py:10-50`
- Test: `tests/test_share_data.py`

**Interfaces:**
- Produces:
  - `ALL_ACTION_PERMISSIONS: Dict[str, str] = {"expense": "Ghi chi tiêu", "cashflow": "Xong dòng tiền", "goals": "Góp vào hũ", "edit_tx": "Sửa/Xoá giao dịch"}`
  - `get_shared_snapshot(..., allowed_edits: Optional[Set[str]] = None) -> Dict[str, Any]` returning `"allowed_edits": sorted(list(allowed_edits or set()))`

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_share_data.py
def test_snapshot_includes_allowed_edits(self):
    from manage_eco.share_data import get_shared_snapshot, ALL_ACTION_PERMISSIONS
    self.assertIn("expense", ALL_ACTION_PERMISSIONS)
    self.assertIn("cashflow", ALL_ACTION_PERMISSIONS)
    snap = get_shared_snapshot(self.store, self.today, allowed_tabs={"overview"}, allowed_edits={"expense", "goals"})
    self.assertEqual(snap["allowed_edits"], ["expense", "goals"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_share_data.py`  
Expected: FAIL with `KeyError: 'allowed_edits'` or `ImportError: cannot import name 'ALL_ACTION_PERMISSIONS'`

- [ ] **Step 3: Implement data structures in `manage_eco/share_data.py`**

Define `ALL_ACTION_PERMISSIONS` and update `get_shared_snapshot` signature and return payload to include `"allowed_edits"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_share_data.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/share_data.py tests/test_share_data.py
git commit -m "feat(share): add action permission constants and snapshot field"
```

---

### Task 2: Server-Side Mutation API & Granular Permission Guard

**Files:**
- Modify: `manage_eco/web.py:30-170`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `ALL_ACTION_PERMISSIONS`, `manage_eco.api.execute`
- Produces:
  - `ShareServer.__init__(..., allowed_edits: Optional[Set[str]] = None, on_mutation: Optional[Callable[[], None]] = None)`
  - `ShareServer.update_config(..., allowed_edits: Optional[Set[str]] = None)`
  - HTTP `POST /api/action?pin=...` endpoint

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_web.py
def test_action_endpoint_forbidden_without_permission(self):
    import urllib.request, json
    # Server initialized with allowed_edits={"cashflow"} (no expense)
    url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
    payload = json.dumps({"action": "expense", "params": {"amount": "50k", "category": "food"}}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with self.assertRaises(urllib.error.HTTPError) as ctx:
        urllib.request.urlopen(req)
    self.assertEqual(ctx.exception.code, 403)

def test_action_endpoint_executes_when_permitted(self):
    import urllib.request, json
    # Reconfigure server with expense permitted
    self.server.update_config(allowed_edits={"expense"})
    url = f"http://127.0.0.1:{self.port}/api/action?pin=1234"
    payload = json.dumps({"action": "expense", "params": {"amount": "50k", "category": "food", "note": "cafe"}}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    self.assertTrue(res["ok"])
    self.assertEqual(res["command"], "expense")
    # Verify transaction added
    snap = self.server.get_snapshot()
    self.assertIn("transactions", snap["tabs"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_web.py`  
Expected: FAIL with `404 Not Found` (no `do_POST` handler) or `AttributeError`

- [ ] **Step 3: Implement `do_POST` and mutation dispatch in `manage_eco/web.py`**

1. Add `allowed_edits` and `on_mutation` attributes to `ShareServer`.
2. Add `do_POST` in `RequestHandler`:
   - Verify PIN and check lockout.
   - Read and parse JSON body.
   - Validate `action` against `self.allowed_edits`:
     - `"expense"` or `"income"` -> requires `"expense"` in `allowed_edits`
     - `"plan_done"` -> requires `"cashflow"` in `allowed_edits`
     - `"goal_save"` -> requires `"goals"` in `allowed_edits`
     - `"tx_delete"` -> requires `"edit_tx"` in `allowed_edits`
   - Map payload to `api.execute(cmd, params, self.store, self.today)`.
   - Call `self.broadcast_update()`.
   - If `self.on_mutation` is set, invoke it in a try/except block.
   - Return 200 OK JSON `{"ok": True, "command": cmd, "data": res}`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_web.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/web.py tests/test_web.py
git commit -m "feat(web): add POST /api/action endpoint with permission enforcement and engine dispatch"
```

---

### Task 3: Terminal TUI Tab 8 Controls & Hotkeys

**Files:**
- Modify: `manage_eco/tui.py:460-500,1750-1810,2480-2550`
- Test: `tests/test_tui_share.py`

**Interfaces:**
- Consumes: `ALL_ACTION_PERMISSIONS`, `ShareServer.update_config`
- Produces:
  - `State.share_allowed_edits: Set[str]`
  - `State.toggle_share_edit(edit_key: str) -> None`
  - Hotkeys `a`, `d`, `g`, `x` when on Tab 8

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_tui_share.py
def test_tab_8_edit_permission_toggles(self):
    self.state.tab = 7  # Tab 8
    self.assertIn("expense", self.state.share_allowed_edits)
    # Press 'a' to toggle expense
    tui.handle_key(self.state, "a", lambda cmd, p: {})
    self.assertNotIn("expense", self.state.share_allowed_edits)
    tui.handle_key(self.state, "a", lambda cmd, p: {})
    self.assertIn("expense", self.state.share_allowed_edits)

def test_tab_8_renders_edit_permission_chips(self):
    self.state.tab = 7
    f = tui.build_frame(self.state, 80, 24)
    plain = "\n".join(l.plain for l in f.lines)
    self.assertIn("Ghi chi tiêu a", plain)
    self.assertIn("Xong dòng d", plain)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_tui_share.py`  
Expected: FAIL with `AttributeError: 'State' object has no attribute 'share_allowed_edits'`

- [ ] **Step 3: Implement edit permission chips and keybindings in `manage_eco/tui.py`**

1. In `State.__init__`: add `self.share_allowed_edits = {"expense"}`.
2. In `State.toggle_share_edit(key)`: toggle key and update `self.share_server.update_config(allowed_edits=self.share_allowed_edits)` if active.
3. In `share_tab_lines`: render the edit permissions section with clickable chips:
   - `[✓ Ghi chi tiêu a]`, `[✓ Xong dòng d]`, `[✓ Góp hũ g]`, `[  Xoá gd x]`.
4. In `handle_key`: when `state.tab == 7`, handle `a`, `d`, `g`, `x` to toggle permissions.
5. In `handle_click`: support `("toggle_share_edit", key)` action.
6. Connect `on_mutation` callback to trigger `state.dirty = True` and sound chime.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_tui_share.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/tui.py tests/test_tui_share.py
git commit -m "feat(tui): add granular write permission chips and hotkeys on Tab 8"
```

---

### Task 4: Mobile Web Client Interactive Forms & Action Controls

**Files:**
- Modify: `manage_eco/web.py` (`_HTML_TEMPLATE`)
- Test: `tests/test_web_template.py`

**Interfaces:**
- Consumes: `POST /api/action?pin=...`, `allowed_edits` from snapshot
- Produces:
  - Mobile Floating Action Button (FAB) `[ + Chi tiêu ]`
  - Bottom-sheet modal form with quick chips, category selector, account selector, note
  - Inline `[✓ Xong]` in Cashflow tab when permitted
  - Inline `[+ Góp]` in Goals tab when permitted
  - Inline `[✕]` delete in Transactions tab when permitted

- [ ] **Step 1: Write the failing test**

```python
# In tests/test_web_template.py
def test_web_template_contains_mutation_controls(self):
    url = f"http://127.0.0.1:{self.port}/?pin=5678"
    with urllib.request.urlopen(url) as resp:
        content = resp.read().decode("utf-8")
    self.assertIn("fab-add", content)
    self.assertIn("modal-sheet", content)
    self.assertIn("submitAction", content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_web_template.py`  
Expected: FAIL with `AssertionError: 'fab-add' not found`

- [ ] **Step 3: Implement mobile web forms and action scripts in `manage_eco/web.py`**

1. In CSS: add styling for FAB button (`.fab-add`), modal bottom-sheet backdrop and sheet (`.modal-backdrop`, `.modal-sheet`), input fields, and category grid chips.
2. In HTML: add modal structure `#expenseModal` with amount input, quick amount chips, category selection buttons, account selector, and note.
3. In JavaScript:
   - Check `state.allowed_edits`:
     - If `"expense"` is in `allowed_edits`: show FAB; otherwise hide.
     - In Cashflow: render `[✓ Xong]` if `"cashflow"` is in `allowed_edits`.
     - In Goals: render `[+ Góp]` if `"goals"` is in `allowed_edits`.
     - In Transactions: render `[✕]` if `"edit_tx"` is in `allowed_edits`.
   - Implement `submitAction(action, params)` sending `fetch('/api/action?pin=' + encodeURIComponent(pin), {method: 'POST', body: ...})`.
   - Provide feedback toast on success or error.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_web_template.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/web.py tests/test_web_template.py
git commit -m "feat(web): add responsive action forms, floating action button, and inline edit controls"
```

---

### Task 5: Full Integration, End-to-End Test & Memory Verification

**Files:**
- Test: All tests across the project
- Script: `scripts/memcheck.sh`

- [ ] **Step 1: Run all live share unit and integration tests**

```bash
python3 -m unittest tests/test_share_data.py tests/test_web.py tests/test_web_template.py tests/test_tunnel.py tests/test_tui_share.py
```
Expected: PASS (all tests pass)

- [ ] **Step 2: Run memory constraint verification**

```bash
bash scripts/memcheck.sh
```
Expected: PASS (Max RSS strictly < 25 MB)

- [ ] **Step 3: Run full project test suite**

```bash
TERM=xterm-256color python3 -m unittest discover tests
```
Expected: PASS (All project tests pass)

- [ ] **Step 4: Final verification commit if needed**

```bash
git status
```
Confirm working tree is clean.
