# Design Spec: Selective Write Permissions for Live Share Web Viewer

**Date**: 2026-11-08  
**Status**: Approved (in review)  
**Author**: Google DeepMind / Antigravity

---

## 1. Context & User Intent

Manage Eco provides a terminal-first personal finance app and currently supports a read-only live web viewer for partners/girlfriends to observe financial data over local Wi-Fi or Tailscale Funnel.

The user wants to grant **selective write/edit permissions** to their partner so she can also record or edit specific financial items from her phone, but **strictly controlled by the user from the terminal**. The user can toggle which specific actions she is allowed to perform; any unpermitted action remains hidden and strictly blocked by the server.

---

## 2. Requirements & Acceptance Criteria

### Functional Requirements
1. **Granular Edit Permission Matrix on Terminal Tab 8**:
   - The user can toggle independent action permissions:
     - `expense` (key `a` / click): Add new expenses or incomes (`+Chi / +Thu`).
     - `cashflow` (key `d` / click): Mark cashflow plans as done (`✓ Xong Dòng tiền`).
     - `goals` (key `g` / click): Deposit / contribute to savings jars (`+Góp Hũ`).
     - `edit_tx` (key `x` / click): Delete transactions (`Xoá giao dịch`).
   - Default when starting share: `{"expense"}` enabled, others disabled unless explicitly toggled by user.
   - Real-time config broadcast: toggling permissions in the TUI immediately updates active web clients via SSE.

2. **Mobile Web Client Thao Tác (Action UI)**:
   - **When `expense` is allowed**:
     - Display a Floating Action Button (FAB) `[ + Chi tiêu ]` in the bottom-right corner.
     - Tapping the FAB opens an accessible Bottom Sheet / Modal form:
       - Amount input supporting natural Manage Eco shortcuts (`50k`, `120k`, `1.5tr`, arithmetic `30k+20k`) + quick chips (`50k`, `100k`, `200k`, `500k`).
       - Category picker with icons (`🍜 Ăn uống`, `🛒 Mua sắm`, `🛵 Đi lại`, `💡 Hoá đơn`, etc.).
       - Account / Wallet selector (defaults to primary account).
       - Optional note field.
       - "Lưu chi tiêu" button submitting `POST /api/action?pin=...`.
   - **When `cashflow` is allowed**:
     - In the Cashflow tab, each pending item displays a `[✓ Xong]` button.
     - Tapping triggers `POST /api/action?pin=...` to complete the plan and deduct wallet balance.
   - **When `goals` is allowed**:
     - In the Goals tab, each jar displays a `[+ Góp tiền]` button.
     - Tapping prompts/opens an amount input dialog to save money into the jar.
   - **When `edit_tx` is allowed**:
     - In the Transactions tab, each item displays a `[✕]` delete icon with confirmation.

3. **Strict Server-Side Enforcement (Security)**:
   - Endpoint: `POST /api/action?pin=...`.
   - Requires valid PIN; enforced by 5-attempt brute-force lockout.
   - Validates that the requested action is permitted in `server.allowed_edits`.
   - Unauthorized attempts return `403 Forbidden` (`{"ok": false, "error": "Hành động này chưa được cấp quyền từ máy tính"}`).
   - All mutations execute through core engine `manage_eco.api.execute(cmd, params, store, today)`.
   - Non-whitelisted commands (e.g. settings changes, account deletions) are rejected.

4. **Bi-Directional Real-Time Synchronization**:
   - On mutation from web:
     - SQLite database updates.
     - Web server broadcasts updated snapshot over SSE to all connected clients.
     - Web client auto-refreshes data and closes form.
     - Terminal TUI receives mutation callback, updates `State`, reloads data, redraws immediately, and plays a positive chime sound (`sfx.play("save")`).

### Non-Functional Requirements
- **Memory Consumption**: Strictly below 25 MB max RSS (`memcheck.sh`).
- **Dependencies**: Zero new third-party libraries (pure standard library: `http.server`, `json`, `sqlite3`).
- **Compatibility**: All existing 268 tests must pass with zero regressions.

---

## 3. Architecture & Data Flow

```text
┌─────────────────────────┐                         ┌──────────────────────────┐
│   Mobile Web Browser    │                         │       Terminal TUI       │
│  (Girlfriend's Phone)   │                         │    (Tab 8: Chia sẻ)      │
└────────────┬────────────┘                         └────────────┬─────────────┘
             │                                                   │
             │ 1. POST /api/action?pin=...                       │ User toggles:
             │    {action: "expense", params: {...}}             │ [✓ a: Chi tiêu]
             ▼                                                   │ [✓ d: Xong dòng]
┌────────────────────────────────────────────────────────┐       │ [✓ g: Góp hũ]
│                     ShareServer                        │       │ [  x: Xoá gd]
│                                                        │◄──────┘
│  - Step 1: Verify PIN & Rate Limit                     │
│  - Step 2: Verify action in server.allowed_edits       │
│  - Step 3: Call manage_eco.api.execute(...)            │
└────────────────────────────┬───────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────┐
│                   Store (SQLite DB)                    │
└────────────────────────────┬───────────────────────────┘
                             │
             ┌───────────────┴───────────────┐
             ▼                               ▼
┌─────────────────────────┐     ┌──────────────────────────┐
│  SSE Broadcast (Update) │     │   TUI On-Mutation Hook   │
│  - Push new snapshot    │     │   - state.dirty = True   │
│  - Mobile web re-renders│     │   - Redraw frame         │
│  - Modal closes smoothly│     │   - Play sound (sfx)     │
└─────────────────────────┘     └──────────────────────────┘
```

---

## 4. API Specification

### Endpoint: `POST /api/action?pin=...`

#### Headers
- `Content-Type: application/json`

#### Request Body
```json
{
  "action": "expense",
  "params": {
    "amount": "50k",
    "category": "ăn uống",
    "account": "Tiền mặt",
    "note": "mua trà sữa"
  }
}
```

#### Supported Actions & Required Permissions
| `action` | Required Permission | Engine Command | Params Mapping |
| :--- | :--- | :--- | :--- |
| `"expense"` | `"expense"` | `expense` | `amount`, `category`, `note`, `account` |
| `"income"` | `"expense"` | `income` | `amount`, `category`, `note`, `account` |
| `"plan_done"` | `"cashflow"` | `plan done` | `id`, `account`, `date` |
| `"goal_save"` | `"goals"` | `goal save` | `id`, `amount` |
| `"tx_delete"` | `"edit_tx"` | `rm` | `id` |

#### Responses
- **Success (200 OK)**:
  ```json
  {"ok": true, "command": "expense", "data": {...}, "snapshot": {...}}
  ```
- **Unauthorized PIN (401 Unauthorized)**:
  ```json
  {"ok": false, "error": "Invalid or missing PIN"}
  ```
- **Forbidden Action (403 Forbidden)**:
  ```json
  {"ok": false, "error": "Quyền này chưa được cấp phép từ máy tính"}
  ```
- **Invalid Payload / Execution Error (400 Bad Request)**:
  ```json
  {"ok": false, "error": "Số tiền không hợp lệ"}
  ```

---

## 5. UI Components & Layout

### 5.1 Terminal TUI (Tab 8)
- Added section under `CÁC TAB ĐƯỢC PHÉP XEM`:
  ```text
   CÁC QUYỀN ĐƯỢC PHÉP CHỈNH SỬA TRÊN WEB (nhấp chuột hoặc phím tắt):
     [✓ Ghi chi tiêu a]     [✓ Xong dòng tiền d]
     [✓ Góp vào hũ g]       [  Sửa/Xoá giao dịch x]
  ```
- Keys `a`, `d`, `g`, `x` toggle the respective permission when active on Tab 8.
- Clicking on the chip directly toggles the permission.

### 5.2 Mobile Web Client
- CSS pastel design matching Tokyo Night / Manage Eco theme (`#1e1b2e`, `#26223b`, `#c4b5fd`, `#f9a8d4`, `#86efac`, `#fca5a5`).
- Floating Action Button (FAB) at bottom-right `[ + Chi tiêu ]` with glowing subtle mint/lavender accent.
- Modal bottom-sheet with slide-up transition (`transform: translateY(0)`).
- Instant input validation and optimistic visual feedback.
- Interactive alerts and error toasts on mobile.

---

## 6. Testing Strategy

1. **Unit Tests (`tests/test_web.py`)**:
   - `test_action_endpoint_verifies_pin`: Rejects invalid PIN with 401.
   - `test_action_endpoint_enforces_permissions`: Rejects unpermitted actions with 403.
   - `test_action_expense_creates_transaction`: Creates expense transaction when `expense` is permitted.
   - `test_action_plan_done_executes`: Completes plan when `cashflow` is permitted.
   - `test_action_goal_save_executes`: Contributes to jar when `goals` is permitted.
   - `test_action_tx_delete_executes`: Deletes transaction when `edit_tx` is permitted.
2. **TUI Tests (`tests/test_tui_share.py`)**:
   - `test_tab_8_edit_permission_toggles`: Keypresses (`a`, `d`, `g`, `x`) toggle permissions.
   - `test_tab_8_renders_edit_permission_chips`: Renders chips with checkmarks.
3. **Web Template Tests (`tests/test_web_template.py`)**:
   - `test_web_renders_fab_when_expense_permitted`: FAB appears when permitted, hidden when not.
   - `test_web_renders_plan_done_buttons_when_permitted`: `✓ Xong` appears in cashflow when permitted.
4. **Integration & Memory Tests**:
   - `scripts/memcheck.sh`: RSS stays under 25 MB.
   - `python3 -m unittest discover tests`: All tests pass.
