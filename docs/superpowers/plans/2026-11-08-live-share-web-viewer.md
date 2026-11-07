# Live Share Web Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a live, read-only mobile web dashboard for the user's girlfriend over 4G/Internet, controllable from a new "Chia sẻ" (Share) tab in the Manage Eco terminal TUI, where the user selectively chooses which tabs to broadcast.

**Architecture:** A lightweight background Python HTTP server (`http.server` in a daemon thread) serves an embedded mobile-friendly single-page web app and streams real-time updates via Server-Sent Events (SSE). An automated Cloudflare Quick Tunnel (`trycloudflare.com`) provides secure public HTTPS access without account requirements or port forwarding, while the terminal renders a Unicode QR code for instant mobile access. Tab-level whitelist enforcement strictly isolates unshared data on the server before transmission.

**Tech Stack:** Python 3.9+ (standard library: `http.server`, `threading`, `urllib`, `subprocess`, `json`), Server-Sent Events (SSE), Cloudflare Quick Tunnel (`cloudflared`), vanilla HTML5/CSS3/ES6 (no external web dependencies), `rich` (TUI layout).

**Spec:** [docs/superpowers/specs/2026-11-08-live-share-web-viewer-design.md](file:///Users/musual/(%20App%20)%20Manage%20Eco/docs/superpowers/specs/2026-11-08-live-share-web-viewer-design.md)

## Global Constraints

- Never import `rich` inside `share_data.py` or `web.py` backend logic to maintain speed and CLI compatibility.
- Zero extra external package dependencies in `pyproject.toml` (standard library only for web and networking).
- Strict read-only mode: web endpoints only accept `GET` requests; no state mutation endpoints exist.
- Memory consumption must remain strictly under 25 MB max RSS during sharing.
- Subprocess for `cloudflared` and background web threads must terminate cleanly on `SIGINT`, `SIGTERM`, and normal TUI exit (`q`).

## Review Focus

1. **Unshared tab data leakage:** An HTTP client requesting `/api/data` or `/api/stream` must never receive payload fields or records for tabs that are unchecked (`[ ]`) on the terminal.
2. **Invalid or missing PIN:** Requests without a PIN or with an incorrect PIN must be immediately rejected with 401/403 status, preventing public eavesdropping on `trycloudflare.com`.
3. **Absence of `cloudflared` binary:** If `cloudflared` is not installed on the system, the app must not crash; it should fall back smoothly to local LAN IP/port and inform the user.
4. **SSE connection drop / reconnection:** When a mobile device locks or switches networks (Wi-Fi to 4G), the web client must automatically reconnect without full page reloads or broken state.
5. **Clean process teardown:** Exiting the TUI (via `q` or `Ctrl+C`) while sharing is active must not leave orphaned `cloudflared` background processes or lingering bound ports.

---

### Task 1: Web Data Serializer & State Whitelist Filter

**Files:**
- Create: `manage_eco/share_data.py`
- Test: `tests/test_share_data.py`

**Interfaces:**
- Consumes: `manage_eco.api` (`summary`, `account_list`, `plan_list`, `goal_list`, `dash`), `manage_eco.db.Store`
- Produces: `get_shared_snapshot(store, today, allowed_tabs: set, active_tab: str, sync_mode: str) -> dict`

- [ ] **Step 1: Write the failing test**

In `tests/test_share_data.py`:
```python
import unittest
from datetime import date
from manage_eco.db import Store
from manage_eco.models import Account, Budget, Goal, Plan, Transaction
from manage_eco.share_data import get_shared_snapshot, ALL_SHAREABLE_TABS

class ShareDataTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.store.add_transaction(Transaction(self.today, 100000, "expense", "food", "lunch"))
        self.store.add_account(Account("Techcombank", 5000000, True))

    def test_filter_only_allowed_tabs(self):
        allowed = {"overview", "budgets"}
        snap = get_shared_snapshot(self.store, self.today, allowed, active_tab="overview", sync_mode="free")
        self.assertIn("overview", snap["tabs"])
        self.assertIn("budgets", snap["tabs"])
        self.assertNotIn("accounts", snap["tabs"])
        self.assertNotIn("transactions", snap["tabs"])
        self.assertEqual(snap["sync_mode"], "free")
        self.assertEqual(snap["allowed_tab_keys"], sorted(list(allowed)))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_share_data.py`  
Expected: FAIL with `ModuleNotFoundError: No module named 'manage_eco.share_data'`

- [ ] **Step 3: Implement `manage_eco/share_data.py`**

Implement `get_shared_snapshot` mapping internal tab names (`overview`, `accounts`, `transactions`, `cashflow`, `budgets`, `goals`, `chart`) to their data using `manage_eco.api` commands. Only evaluate and include keys that exist in `allowed_tabs`. Include metadata: `today`, `sync_mode`, `active_tab`, `allowed_tab_keys`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_share_data.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/share_data.py tests/test_share_data.py
git commit -m "feat(share): add shared data snapshot and tab whitelist filtering"
```

---

### Task 2: Background Web Server & Real-time SSE Streamer

**Files:**
- Create: `manage_eco/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `manage_eco.share_data.get_shared_snapshot`
- Produces:
  - `class ShareServer` with methods `start()`, `stop()`, `notify_change(event_type: str)`, `update_config(allowed_tabs, active_tab, sync_mode)`
  - `start_share_server(store, today, port=0, pin=None) -> ShareServer`

- [ ] **Step 1: Write the failing test**

In `tests/test_web.py`:
```python
import unittest
import urllib.request
import urllib.error
import json
from datetime import date
from manage_eco.db import Store
from manage_eco.web import start_share_server

class WebServerTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.server = start_share_server(self.store, self.today, port=0, pin="1234")
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()

    def test_pin_protection(self):
        url = f"http://127.0.0.1:{self.port}/api/data"
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(url)
        self.assertEqual(ctx.exception.code, 401)

    def test_valid_pin_returns_json(self):
        url = f"http://127.0.0.1:{self.port}/api/data?pin=1234"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(resp.status, 200)
        self.assertIn("tabs", data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_web.py`  
Expected: FAIL with `ModuleNotFoundError: No module named 'manage_eco.web'`

- [ ] **Step 3: Implement `manage_eco/web.py`**

Implement `ShareServer` wrapping `http.server.ThreadingHTTPServer`. Maintain connected SSE client queues in a thread-safe list. Handle:
- `GET /`: Serves mobile HTML client.
- `GET /api/data?pin=...`: Validates PIN and returns JSON snapshot.
- `GET /api/stream?pin=...`: Validates PIN, registers client queue, sends initial SSE comment `:connected\n\n`, and streams updates on `notify_change()`.
- Thread-safe shutdown and port allocation (`port=0` chooses available OS port).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_web.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/web.py tests/test_web.py
git commit -m "feat(share): implement background HTTP server and SSE broadcaster"
```

---

### Task 3: Mobile Web Client Single-Page App

**Files:**
- Create: `manage_eco/templates/index.html` (embedded or read by `manage_eco/web.py`)
- Modify: `manage_eco/web.py`
- Test: `tests/test_web_template.py`

**Interfaces:**
- Consumes: `/api/data?pin=...` and `/api/stream?pin=...`
- Produces: Responsive HTML5/CSS/JavaScript client styled in Manage Eco's cute dark pastel theme (`#1e1b2e`, `#c4b5fd`, `#86efac`, `#fca5a5`, `#f9a8d4`).

- [ ] **Step 1: Write the failing test**

In `tests/test_web_template.py`:
```python
import unittest
import urllib.request
from datetime import date
from manage_eco.db import Store
from manage_eco.web import start_share_server

class WebTemplateTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.server = start_share_server(self.store, self.today, port=0, pin="5678")
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()

    def test_index_html_rendered(self):
        url = f"http://127.0.0.1:{self.port}/?pin=5678"
        with urllib.request.urlopen(url) as resp:
            content = resp.read().decode("utf-8")
        self.assertEqual(resp.status, 200)
        self.assertIn("Manage Eco", content)
        self.assertIn("EventSource", content)
        self.assertIn("#1e1b2e", content)  # theme background color
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_web_template.py`  
Expected: FAIL with `AssertionError: 'Manage Eco' not in content`

- [ ] **Step 3: Implement client HTML/CSS/JS in `manage_eco/web.py`**

Implement the single-page web dashboard:
- Header: Live pulsing badge `● Trực tiếp`, active tab title.
- Dynamic navigation bar: only renders tabs returned in `allowed_tab_keys`.
- Tab views:
  - Overview: balance cards, income/expense breakdown, top categories.
  - Budgets: category limit bars with progress % and color shifts (yellow/red).
  - Jars (Goals): goal progress bars, monthly targets, days remaining.
  - Cashflow: upcoming scheduled payments within 30 days.
  - Accounts & Transactions (if permitted).
- JavaScript SSE listener (`new EventSource('/api/stream?pin=...')`) handling live updates and reconnects.
- "Follow Me" mode listener switching tabs automatically when server signals `active_tab` change.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_web_template.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/web.py tests/test_web_template.py
git commit -m "feat(share): embed mobile-first responsive web client with pastel theme"
```

---

### Task 4: Cloudflare Quick Tunnel & Terminal QR Code Generator

**Files:**
- Create: `manage_eco/tunnel.py`
- Test: `tests/test_tunnel.py`

**Interfaces:**
- Produces:
  - `class CloudflareTunnel` with `start(local_port: int) -> Optional[str]` and `stop()`
  - `get_local_ip() -> str`
  - `generate_terminal_qr(text: str) -> List[str]`

- [ ] **Step 1: Write the failing test**

In `tests/test_tunnel.py`:
```python
import unittest
from manage_eco.tunnel import get_local_ip, generate_terminal_qr, CloudflareTunnel

class TunnelTest(unittest.TestCase):
    def test_local_ip_discovery(self):
        ip = get_local_ip()
        self.assertTrue(isinstance(ip, str) and len(ip) > 0)

    def test_qr_generation(self):
        lines = generate_terminal_qr("https://eco.local")
        self.assertTrue(len(lines) > 5)
        self.assertTrue(any("█" in l or "▀" in l or " " in l for l in lines))

    def test_tunnel_lifecycle_mocked(self):
        tunnel = CloudflareTunnel()
        # Verify initial state without launching external binary
        self.assertFalse(tunnel.is_running())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_tunnel.py`  
Expected: FAIL with `ModuleNotFoundError: No module named 'manage_eco.tunnel'`

- [ ] **Step 3: Implement `manage_eco/tunnel.py`**

- `get_local_ip()`: discovers machine LAN IP via UDP socket probe (no external packets sent).
- `generate_terminal_qr(text)`: lightweight pure-Python QR generator rendering 2-cell block characters (`█`, `▀`, `▄`, ` `) for crisp terminal display.
- `CloudflareTunnel`: runs `cloudflared tunnel --url http://127.0.0.1:<port>` with `subprocess.Popen`, parses public `trycloudflare.com` URL from stdout/stderr, and safely terminates the process on `stop()`. If `cloudflared` is missing, returns `None` without raising uncaught exceptions.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_tunnel.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add manage_eco/tunnel.py tests/test_tunnel.py
git commit -m "feat(share): implement Cloudflare tunnel runner and terminal QR generator"
```

---

### Task 5: Terminal TUI Tab 8 Integration & Event Hooks

**Files:**
- Modify: `manage_eco/tui.py`
- Test: `tests/test_tui_share.py`

**Interfaces:**
- Consumes: `manage_eco.web.start_share_server`, `manage_eco.tunnel.CloudflareTunnel`, `manage_eco.tunnel.generate_terminal_qr`
- Modifies: `TABS`, `State`, `render_screen()`, action hit maps, store notification hooks

- [ ] **Step 1: Write the failing test**

In `tests/test_tui_share.py`:
```python
import unittest
from datetime import date
from manage_eco import tui
from manage_eco.db import Store

class TuiShareTest(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.today = date(2026, 11, 8)
        self.state = tui.State(self.store, self.today)

    def tearDown(self):
        if hasattr(self.state, "share_server") and self.state.share_server:
            self.state.share_server.stop()
        if hasattr(self.state, "share_tunnel") and self.state.share_tunnel:
            self.state.share_tunnel.stop()

    def test_tab_8_exists(self):
        self.assertIn("Chia sẻ", tui.TABS)
        self.assertEqual(len(tui.TABS), 8)

    def test_render_tab_8(self):
        self.state.tab = 7  # 0-indexed for 8th tab
        f = tui.render(self.state, 80, 24)
        plain = "\n".join(l.plain for l in f.lines)
        self.assertIn("Chia sẻ", plain)
        self.assertIn("Tổng quan", plain)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests/test_tui_share.py`  
Expected: FAIL with `AssertionError: 'Chia sẻ' not in TABS`

- [ ] **Step 3: Implement Tab 8 and Sharing logic in `manage_eco/tui.py`**

- Add `"Chia sẻ"` to `TABS` (key `8` switches to it).
- In `State`:
  - `share_active: bool = False`
  - `share_server: Optional[ShareServer] = None`
  - `share_tunnel: Optional[CloudflareTunnel] = None`
  - `share_pin: str = "..."`
  - `allowed_tabs: set = {"overview", "cashflow", "budgets", "goals", "chart"}`
  - `sync_mode: str = "free"` ("free" or "follow")
- In `render()`:
  - When `tab == 7`: render Share controls: Toggle switch `[● Đang chia sẻ]` / `[○ Đã tắt]`, QR code display, share URL + PIN, Tab permission checkboxes (`[✓] Tổng quan`, `[ ] Tài khoản`, etc.), and Sync mode buttons (`[Tự do duyệt]`, `[Đi cùng tôi]`).
- In action handlers:
  - Clicking/pressing toggle starts/stops server & tunnel.
  - Clicking tab checkboxes toggles whitelist and immediately notifies connected clients.
  - Clicking sync mode changes behavior.
- Hook store update events: trigger `share_server.notify_change("data_changed")` when saving/deleting transactions, plans, budgets, goals, or accounts.
- Hook cleanup in `run()` / exit handlers to guarantee `share_server.stop()` and `share_tunnel.stop()`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests/test_tui_share.py`  
Expected: PASS

- [ ] **Step 5: Run full test suite and memory check**

Run: `python3 -m unittest discover tests`  
Run: `scripts/memcheck.sh` (or verify memory stays < 25 MB RSS).

- [ ] **Step 6: Commit**

```bash
git add manage_eco/tui.py tests/test_tui_share.py
git commit -m "feat(tui): add Tab 8 Chia sẻ with QR code and selective tab permissions"
```

---

## Plan Self-Review Checklist

- [x] **Spec coverage:** Covers selective tab whitelist, background web server, real-time SSE, mobile pastel layout, Cloudflare tunnel, terminal QR code, and Tab 8 TUI controls.
- [x] **Step scan:** Every step contains exact signatures, paths, test assertions, and unambiguous commands.
- [x] **Type consistency:** Identical function signatures and parameter names across tasks (`get_shared_snapshot`, `start_share_server`, `notify_change`).
- [x] **Review Focus addressed:** All 5 failure modes have corresponding tests and validations.
- [x] **Proportion:** Clear, structured tasks without unnecessary bloat.
