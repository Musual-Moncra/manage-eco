"""Background HTTP server and Server-Sent Events (SSE) broadcaster for Manage Eco.

Never imports rich. Pure standard library (http.server, threading, queue).
"""
import json
import queue
import secrets
import threading
import time
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Set
from urllib.parse import parse_qs, urlparse

from manage_eco.share_data import ALL_SHAREABLE_TABS, get_shared_snapshot

DEFAULT_ALLOWED_TABS: Set[str] = {"overview", "cashflow", "budgets", "goals", "chart"}


class ShareServer:
    def __init__(
        self,
        store: Any,
        today: date,
        port: int = 0,
        pin: Optional[str] = None,
        allowed_tabs: Optional[Set[str]] = None,
        active_tab: str = "overview",
        sync_mode: str = "free",
        allowed_edits: Optional[Set[str]] = None,
        on_mutation: Optional[Callable[[], None]] = None,
    ):
        self.store = store
        self.today = today
        self.requested_port = port
        self.pin = pin or f"{secrets.randbelow(9000) + 1000}"
        self.allowed_tabs: Set[str] = set(allowed_tabs if allowed_tabs is not None else DEFAULT_ALLOWED_TABS)
        self.active_tab: str = active_tab
        self.sync_mode: str = sync_mode
        self.allowed_edits: Set[str] = set(allowed_edits if allowed_edits is not None else {"expense"})
        self.on_mutation = on_mutation

        self._lock = threading.Lock()
        self._db_lock = threading.RLock()
        self._clients: List[queue.Queue] = []
        self._failed_attempts = 0
        self._locked_until = 0.0
        self._running = False
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port: int = 0

    def start(self) -> "ShareServer":
        with self._lock:
            if self._running:
                return self
            server_self = self

            class RequestHandler(BaseHTTPRequestHandler):
                def log_message(self, format: str, *args: Any) -> None:
                    # Suppress console logging to keep terminal TUI clean
                    pass

                def handle(self) -> None:
                    try:
                        super().handle()
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                        pass

                def _verify_pin(self, query_params: Dict[str, List[str]]) -> bool:
                    with server_self._lock:
                        now = time.monotonic()
                        if now < server_self._locked_until:
                            return False
                        provided = query_params.get("pin", [""])[0]
                        if secrets.compare_digest(provided, server_self.pin):
                            server_self._failed_attempts = 0
                            return True
                        server_self._failed_attempts += 1
                        if server_self._failed_attempts >= 5:
                            server_self._locked_until = now + 60.0
                        return False

                def do_GET(self) -> None:
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)

                    if parsed.path == "/":
                        # Serves HTML client, hydrated with initial snapshot when valid PIN is given
                        initial_snap = None
                        if self._verify_pin(params):
                            try:
                                initial_snap = server_self.get_snapshot()
                            except Exception:
                                initial_snap = None
                        html = server_self._render_index_html(initial_snap)
                        content = html.encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return

                    if parsed.path == "/api/data":
                        if not self._verify_pin(params):
                            self.send_response(HTTPStatus.UNAUTHORIZED)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": "Invalid or missing PIN"}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return
                        snap = server_self.get_snapshot()
                        body = json.dumps(snap, ensure_ascii=False).encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                        return

                    if parsed.path == "/api/stream":
                        if not self._verify_pin(params):
                            self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid or missing PIN")
                            return
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()

                        q = queue.Queue(maxsize=50)
                        server_self._add_client(q)
                        try:
                            # Initial handshake
                            self.wfile.write(b": connected\n\n")
                            # Send current snapshot on connection
                            init_payload = json.dumps(server_self.get_snapshot(), ensure_ascii=False)
                            self.wfile.write(f"event: init\ndata: {init_payload}\n\n".encode("utf-8"))
                            self.wfile.flush()

                            while server_self._running:
                                try:
                                    event = q.get(timeout=10.0)
                                    ev_type = event.get("type", "update")
                                    ev_data = json.dumps(event.get("data", {}), ensure_ascii=False)
                                    msg = f"event: {ev_type}\ndata: {ev_data}\n\n".encode("utf-8")
                                    self.wfile.write(msg)
                                    self.wfile.flush()
                                except queue.Empty:
                                    # Send keep-alive comment
                                    self.wfile.write(b": keepalive\n\n")
                                    self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                            pass
                        finally:
                            server_self._remove_client(q)
                        return

                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

                def do_POST(self) -> None:
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)

                    if parsed.path == "/api/action":
                        if not self._verify_pin(params):
                            self.send_response(HTTPStatus.UNAUTHORIZED)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": "Invalid or missing PIN"}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        try:
                            content_len = int(self.headers.get("Content-Length", 0))
                        except (ValueError, TypeError):
                            content_len = -1

                        if content_len < 0 or content_len > 65536:
                            status = HTTPStatus.REQUEST_ENTITY_TOO_LARGE if content_len > 65536 else HTTPStatus.BAD_REQUEST
                            self.send_response(status)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            err_msg = "Payload too large (max 64KB)" if content_len > 65536 else "Invalid Content-Length"
                            resp_body = json.dumps({"ok": False, "error": err_msg}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        body_bytes = self.rfile.read(content_len)
                        try:
                            payload = json.loads(body_bytes.decode("utf-8"))
                        except Exception:
                            self.send_response(HTTPStatus.BAD_REQUEST)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": "Invalid JSON payload"}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        if not isinstance(payload, dict):
                            self.send_response(HTTPStatus.BAD_REQUEST)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": "JSON payload must be an object"}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        action = payload.get("action")
                        action_params = payload.get("params", {})
                        if not isinstance(action_params, dict):
                            self.send_response(HTTPStatus.BAD_REQUEST)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": "params must be an object"}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        with server_self._lock:
                            allowed = set(server_self.allowed_edits)

                        perm_map = {
                            "expense": "expense",
                            "income": "expense",
                            "plan_done": "cashflow",
                            "goal_save": "goals",
                            "tx_delete": "edit_tx",
                        }

                        required_perm = perm_map.get(action)
                        if not required_perm or required_perm not in allowed:
                            self.send_response(HTTPStatus.FORBIDDEN)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({
                                "ok": False,
                                "error": f"Hành động '{action}' chưa được cấp quyền từ máy tính"
                            }, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        cmd_map = {
                            "expense": "expense",
                            "income": "income",
                            "plan_done": "plan done",
                            "goal_save": "goal save",
                            "tx_delete": "rm",
                        }
                        cmd = cmd_map[action]

                        try:
                            from manage_eco import api
                            with server_self._db_lock:
                                res = api.execute(cmd, action_params, server_self.store, server_self.today)
                        except Exception as exc:
                            self.send_response(HTTPStatus.BAD_REQUEST)
                            self.send_header("Content-Type", "application/json; charset=utf-8")
                            resp_body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                            self.send_header("Content-Length", str(len(resp_body)))
                            self.end_headers()
                            self.wfile.write(resp_body)
                            return

                        server_self.broadcast_update()

                        if server_self.on_mutation:
                            try:
                                server_self.on_mutation()
                            except Exception:
                                pass

                        resp_body = json.dumps({"ok": True, "command": cmd, "data": res}, ensure_ascii=False).encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Content-Length", str(len(resp_body)))
                        self.end_headers()
                        self.wfile.write(resp_body)
                        return

                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

            class _EcoHTTPServer(ThreadingHTTPServer):
                request_queue_size = 64
                daemon_threads = True

            self._server = _EcoHTTPServer(("0.0.0.0", self.requested_port), RequestHandler)
            self.port = self._server.server_address[1]
            self._running = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            return self

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            if self._server:
                self._server.shutdown()
                self._server.server_close()
            # Unblock all SSE clients
            for q in list(self._clients):
                try:
                    q.put_nowait({"type": "close", "data": {}})
                except queue.Full:
                    pass
            self._clients.clear()

    def _add_client(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.append(q)

    def _remove_client(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clients:
                self._clients.remove(q)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def get_snapshot(self) -> Dict[str, Any]:
        with self._db_lock:
            with self._lock:
                tabs = set(self.allowed_tabs)
                active = self.active_tab
                mode = self.sync_mode
                edits = set(self.allowed_edits)
            return get_shared_snapshot(
                self.store,
                self.today,
                tabs,
                active_tab=active,
                sync_mode=mode,
                allowed_edits=edits,
            )

    def update_config(
        self,
        allowed_tabs: Optional[Set[str]] = None,
        active_tab: Optional[str] = None,
        sync_mode: Optional[str] = None,
        allowed_edits: Optional[Set[str]] = None,
    ) -> None:
        with self._lock:
            if allowed_tabs is not None:
                self.allowed_tabs = set(allowed_tabs)
            if active_tab is not None:
                self.active_tab = active_tab
            if sync_mode is not None:
                self.sync_mode = sync_mode
            if allowed_edits is not None:
                self.allowed_edits = set(allowed_edits)
        self.notify_change("config_changed")

    def broadcast_update(self) -> None:
        self.notify_change("update")

    def notify_change(self, event_type: str = "update") -> None:
        snap = self.get_snapshot()
        msg = {"type": event_type, "data": snap}
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def _render_index_html(self, initial_snapshot: Optional[Dict[str, Any]] = None) -> str:
        hydration_tag = ""
        if initial_snapshot is not None:
            snap_json = json.dumps(initial_snapshot, ensure_ascii=False)
            hydration_tag = f'<script id="initialData" type="application/json">{snap_json}</script>'
        return _HTML_TEMPLATE.replace("<!-- HYDRATION_PLACEHOLDER -->", hydration_tag)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Manage Eco • Cùng quan sát</title>
    <style>
        :root {
            --bg: #1e1b2e;
            --card-bg: #26223b;
            --card-border: #3b3363;
            --accent: #c4b5fd;
            --pink: #f9a8d4;
            --mint: #86efac;
            --coral: #fca5a5;
            --peach: #fdba74;
            --muted: #a8a2c4;
            --pill: #352d5c;
        }
        * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
        body {
            background: var(--bg);
            color: #f1f0f7;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 0 0 40px 0;
        }
        header {
            position: sticky;
            top: 0;
            background: rgba(30, 27, 46, 0.95);
            backdrop-filter: blur(8px);
            z-index: 100;
            border-bottom: 1px solid var(--card-border);
            padding: 12px 16px;
        }
        .header-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 8px;
        }
        .logo {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--pink);
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .badge-live {
            background: rgba(134, 239, 172, 0.15);
            color: var(--mint);
            font-size: 0.75rem;
            font-weight: 600;
            padding: 3px 8px;
            border-radius: 12px;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }
        .pulse-dot {
            width: 7px;
            height: 7px;
            background: var(--mint);
            border-radius: 50%;
            animation: pulse 1.8s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.9); opacity: 0.7; box-shadow: 0 0 0 0 rgba(134,239,172,0.6); }
            70% { transform: scale(1.1); opacity: 1; box-shadow: 0 0 0 6px rgba(134,239,172,0); }
            100% { transform: scale(0.9); opacity: 0.7; }
        }
        .tab-nav {
            display: flex;
            gap: 8px;
            overflow-x: auto;
            scrollbar-width: none;
            padding: 4px 0;
        }
        .tab-nav::-webkit-scrollbar { display: none; }
        .tab-btn {
            background: var(--pill);
            color: var(--muted);
            border: 1px solid var(--card-border);
            padding: 6px 14px;
            border-radius: 18px;
            font-size: 0.85rem;
            font-weight: 500;
            white-space: nowrap;
            cursor: pointer;
            transition: all 0.2s;
        }
        .tab-btn.active {
            background: var(--accent);
            color: #1e1b2e;
            font-weight: 700;
            border-color: var(--accent);
        }
        main {
            padding: 16px;
            max-width: 600px;
            margin: 0 auto;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 16px;
            padding: 16px;
            margin-bottom: 14px;
        }
        .card-title {
            font-size: 0.82rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .big-number {
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--accent);
            margin: 4px 0 10px 0;
        }
        .row-split {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
            margin-top: 10px;
        }
        .stat-sub {
            background: rgba(53, 45, 92, 0.4);
            border-radius: 10px;
            padding: 10px;
        }
        .stat-sub .lbl { font-size: 0.75rem; color: var(--muted); }
        .stat-sub .val { font-size: 1.05rem; font-weight: 600; margin-top: 2px; }
        .val.income { color: var(--mint); }
        .val.expense { color: var(--coral); }
        .progress-bar {
            height: 8px;
            background: #352d5c;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 6px;
        }
        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        .list-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(59, 51, 99, 0.4);
        }
        .list-item:last-child { border-bottom: none; }
        .notice-private {
            text-align: center;
            padding: 40px 20px;
            color: var(--muted);
        }
        .notice-private .heart {
            font-size: 2.2rem;
            color: var(--pink);
            margin-bottom: 12px;
        }
        .fab-add {
            position: fixed;
            bottom: 24px;
            right: 20px;
            background: linear-gradient(135deg, var(--accent), var(--pink));
            color: #1e1b2e;
            border: none;
            border-radius: 28px;
            padding: 12px 20px;
            font-size: 0.95rem;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 8px;
            box-shadow: 0 4px 16px rgba(196, 181, 253, 0.4);
            cursor: pointer;
            z-index: 99;
            transition: transform 0.15s;
        }
        .fab-add:active { transform: scale(0.95); }
        .modal-backdrop {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(15, 13, 24, 0.7);
            backdrop-filter: blur(4px);
            z-index: 1000;
            display: none;
            align-items: flex-end;
            justify-content: center;
        }
        .modal-backdrop.active { display: flex; }
        .modal-sheet {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 20px 20px 0 0;
            width: 100%;
            max-width: 600px;
            padding: 20px;
            max-height: 85vh;
            overflow-y: auto;
            animation: slideUp 0.25s ease-out;
        }
        @keyframes slideUp {
            from { transform: translateY(100%); }
            to { transform: translateY(0); }
        }
        .form-group { margin-bottom: 14px; }
        .form-label { font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; display: block; font-weight: 600; }
        .form-input {
            width: 100%;
            background: #1e1b2e;
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 10px 12px;
            color: #fff;
            font-size: 1rem;
            outline: none;
        }
        .form-input:focus { border-color: var(--accent); }
        .chip-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
        .chip-btn {
            background: var(--pill);
            border: 1px solid var(--card-border);
            color: var(--muted);
            border-radius: 12px;
            padding: 5px 10px;
            font-size: 0.8rem;
            cursor: pointer;
        }
        .chip-btn.selected {
            background: var(--accent);
            color: #1e1b2e;
            font-weight: 700;
            border-color: var(--accent);
        }
        .btn-submit {
            width: 100%;
            background: var(--accent);
            color: #1e1b2e;
            border: none;
            border-radius: 12px;
            padding: 12px;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            margin-top: 10px;
        }
        .btn-sub-action {
            background: rgba(196, 181, 253, 0.15);
            border: 1px solid var(--accent);
            color: var(--accent);
            border-radius: 12px;
            padding: 4px 10px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
        }
        .btn-del {
            background: rgba(247, 118, 142, 0.15);
            border: 1px solid var(--coral);
            color: var(--coral);
            border-radius: 8px;
            padding: 2px 8px;
            font-size: 0.75rem;
            cursor: pointer;
        }
        .toast-msg {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(38, 34, 59, 0.95);
            border: 1px solid var(--accent);
            color: #fff;
            padding: 10px 18px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
            box-shadow: 0 4px 16px rgba(0,0,0,0.4);
            z-index: 2000;
            display: none;
        }
    </style>
</head>
<body>
    <div id="toast" class="toast-msg"></div>

    <button id="fabAdd" class="fab-add" style="display: none;" onclick="openExpenseModal()">
        <span>+</span> Ghi chi tiêu
    </button>

    <div id="expenseModal" class="modal-backdrop">
        <div class="modal-sheet">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
                <div style="font-weight: 700; font-size: 1.1rem; color: var(--accent);">Ghi nhận khoản chi</div>
                <button style="background: none; border: none; color: var(--muted); font-size: 1.2rem; cursor: pointer;" onclick="closeExpenseModal()">✕</button>
            </div>
            <div class="form-group">
                <label class="form-label">Số tiền (ví dụ: 50k, 120k, 1.5tr)</label>
                <input id="inputAmount" class="form-input" placeholder="50k" />
                <div class="chip-grid">
                    <button type="button" class="chip-btn" onclick="setFormAmount('50k')">50k</button>
                    <button type="button" class="chip-btn" onclick="setFormAmount('100k')">100k</button>
                    <button type="button" class="chip-btn" onclick="setFormAmount('200k')">200k</button>
                    <button type="button" class="chip-btn" onclick="setFormAmount('500k')">500k</button>
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">Danh mục</label>
                <input id="inputCategory" class="form-input" placeholder="ăn uống, mua sắm..." />
                <div class="chip-grid" id="catChips">
                    <button type="button" class="chip-btn" onclick="setFormCat('ăn uống')">🍜 Ăn uống</button>
                    <button type="button" class="chip-btn" onclick="setFormCat('mua sắm')">🛒 Mua sắm</button>
                    <button type="button" class="chip-btn" onclick="setFormCat('đi lại')">🛵 Đi lại</button>
                    <button type="button" class="chip-btn" onclick="setFormCat('hoá đơn')">💡 Hoá đơn</button>
                    <button type="button" class="chip-btn" onclick="setFormCat('nhà cửa')">🏠 Nhà cửa</button>
                </div>
            </div>
            <div class="form-group" id="groupAccount" style="display: none;">
                <label class="form-label">Tài khoản / Ví</label>
                <select id="inputAccount" class="form-input">
                    <option value="">Mặc định (Ví chính)</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">Ghi chú (tuỳ chọn)</label>
                <input id="inputNote" class="form-input" placeholder="mua trà sữa, siêu thị..." />
            </div>
            <button class="btn-submit" onclick="submitExpenseForm()">Lưu chi tiêu</button>
        </div>
    </div>
    <header>
        <div class="header-top">
            <div class="logo">🌿 Manage Eco</div>
            <div class="badge-live">
                <span class="pulse-dot"></span>
                <span id="liveStatusText">Trực tiếp</span>
            </div>
        </div>
        <nav class="tab-nav" id="tabNav"></nav>
    </header>

    <main id="mainContainer">
        <!-- HYDRATION_PLACEHOLDER -->
        <div class="tab-content" id="tabContent">
            <div style="text-align: center; padding: 40px; color: var(--muted);">Đang kết nối...</div>
        </div>
    </main>

    <script>
        const urlParams = new URLSearchParams(window.location.search);
        let pin = urlParams.get('pin') || '';
        if (!pin) {
            pin = prompt('Nhập mã PIN để xem:', '');
            if (pin) {
                const newUrl = window.location.pathname + '?pin=' + encodeURIComponent(pin);
                window.history.replaceState(null, '', newUrl);
            }
        }

        let state = {
            allowed_tab_keys: [],
            tab_labels: {},
            tabs: {},
            active_tab: 'overview',
            sync_mode: 'free'
        };

        let currentSelectedTab = 'overview';

        let txState = {
            search: '',
            filterKind: 'all',
            monthFilter: 'all',
            limit: 30
        };

        function setTxKindFilter(k) {
            txState.filterKind = k;
            renderContent();
        }

        function setTxMonthFilter(m) {
            txState.monthFilter = m;
            renderContent();
        }

        function onTxSearch(val) {
            txState.search = val;
            const listEl = document.getElementById('txListContainer');
            const tabData = (state.tabs && state.tabs.transactions) || null;
            if (listEl && tabData) {
                listEl.innerHTML = renderTxItemsHtml(tabData);
            } else {
                renderContent();
            }
        }

        function loadMoreTx(step) {
            txState.limit = (txState.limit || 30) + (step || 30);
            renderContent();
        }

        function loadAllTx() {
            txState.limit = 999999;
            renderContent();
        }

        function collapseTx() {
            txState.limit = 30;
            renderContent();
        }

        function fmtMoney(n) {
            if (n === null || n === undefined) return '0 ₫';
            const num = Math.round(Number(n));
            return num.toLocaleString('vi-VN') + ' ₫';
        }

        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function renderNav() {
            const nav = document.getElementById('tabNav');
            nav.innerHTML = '';
            if (!state.allowed_tab_keys || state.allowed_tab_keys.length === 0) {
                return;
            }

            if (!state.allowed_tab_keys.includes(currentSelectedTab)) {
                currentSelectedTab = state.allowed_tab_keys[0];
            }

            state.allowed_tab_keys.forEach(key => {
                const btn = document.createElement('button');
                btn.className = 'tab-btn' + (key === currentSelectedTab ? ' active' : '');
                btn.textContent = state.tab_labels[key] || key;
                btn.onclick = () => {
                    currentSelectedTab = key;
                    renderNav();
                    renderContent();
                };
                nav.appendChild(btn);
            });
        }

        function renderOverview(data) {
            if (!data) return '<div class="card">Chưa có dữ liệu</div>';
            const bal = data.balance || 0;
            const m = data.month || {};
            const inc = m.income || 0;
            const exp = m.expense || 0;
            const net = m.net || (inc - exp);
            const totalSaved = data.total_saved || 0;
            const freeBal = bal - totalSaved;

            let catsHtml = '';
            if (m.by_category && m.by_category.length > 0) {
                catsHtml = '<div class="card"><div class="card-title">Top chi tiêu tháng này</div>';
                const maxAmt = Math.max(...m.by_category.map(c => c.amount), 1);
                m.by_category.slice(0, 5).forEach(c => {
                    const pct = Math.round((c.amount / (exp || 1)) * 100);
                    const fillPct = Math.min(100, Math.round((c.amount / maxAmt) * 100));
                    catsHtml += `
                        <div class="list-item">
                            <div style="flex: 1; padding-right: 12px;">
                                <div style="display: flex; justify-content: space-between; font-size: 0.9rem;">
                                    <span>${c.category || 'Khác'}</span>
                                    <span style="color: var(--coral); font-weight: 600;">${fmtMoney(c.amount)} (${pct}%)</span>
                                </div>
                                <div class="progress-bar"><div class="progress-fill" style="width: ${fillPct}%; background: var(--coral);"></div></div>
                            </div>
                        </div>
                    `;
                });
                catsHtml += '</div>';
            }

            return `
                <div class="card">
                    <div class="card-title">Tổng tài sản</div>
                    <div class="big-number">${fmtMoney(bal)}</div>
                    <div class="row-split">
                        <div class="stat-sub">
                            <div class="lbl">Tiền tự do</div>
                            <div class="val" style="color: var(--accent);">${fmtMoney(freeBal)}</div>
                        </div>
                        <div class="stat-sub">
                            <div class="lbl">Đã gom vào hũ</div>
                            <div class="val" style="color: var(--pink);">${fmtMoney(totalSaved)}</div>
                        </div>
                    </div>
                </div>

                <div class="card">
                    <div class="card-title">Thu chi tháng này (${data.month ? data.month.month : ''})</div>
                    <div class="row-split">
                        <div class="stat-sub">
                            <div class="lbl">Tổng Thu</div>
                            <div class="val income">+${fmtMoney(inc)}</div>
                        </div>
                        <div class="stat-sub">
                            <div class="lbl">Tổng Chi</div>
                            <div class="val expense">-${fmtMoney(exp)}</div>
                        </div>
                    </div>
                    <div style="margin-top: 10px; font-size: 0.85rem; color: var(--muted); text-align: right;">
                        Ròng: <strong style="color: ${net >= 0 ? 'var(--mint)' : 'var(--coral)'}">${net >= 0 ? '+' : ''}${fmtMoney(net)}</strong>
                    </div>
                </div>

                ${catsHtml}
            `;
        }

        function renderBudgets(data) {
            if (!data || !data.budgets || data.budgets.length === 0) {
                return '<div class="card"><div class="card-title">Ngân sách</div><p style="color: var(--muted);">Chưa cài hạn mức ngân sách nào.</p></div>';
            }
            let html = '<div class="card"><div class="card-title">Hạn mức chi tiêu tháng này</div>';
            data.budgets.forEach(b => {
                const pct = b.pct || 0;
                let barColor = 'var(--mint)';
                if (pct >= 100) barColor = 'var(--coral)';
                else if (pct >= 80) barColor = 'var(--peach)';

                html += `
                    <div style="margin-bottom: 14px;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.95rem; font-weight: 600;">
                            <span>${b.category}</span>
                            <span style="color: ${barColor}">${pct.toFixed(0)}%</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: var(--muted); margin-top: 2px;">
                            <span>Đã tiêu: ${fmtMoney(b.spent)}</span>
                            <span>Hạn mức: ${fmtMoney(b.limit)}</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.min(100, pct)}%; background: ${barColor};"></div>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            return html;
        }

        function renderGoals(data) {
            if (!data || !data.goals || data.goals.length === 0) {
                return '<div class="card"><div class="card-title">Hũ tiết kiệm</div><p style="color: var(--muted);">Chưa có hũ tiết kiệm nào.</p></div>';
            }
            const canSave = state.allowed_edits && state.allowed_edits.includes('goals');
            let html = '<div class="card"><div class="card-title">Các mục tiêu tích luỹ</div>';
            data.goals.forEach(g => {
                const pct = Math.min(100, Math.round((g.saved / (g.target || 1)) * 100));
                const saveBtn = canSave ? `<button class="btn-sub-action" onclick="promptGoalSave(${g.id})">+ Góp</button>` : '';
                html += `
                    <div style="margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.95rem; font-weight: 600;">
                            <span style="color: var(--pink)">${escapeHtml(g.name)}</span>
                            <span>${fmtMoney(g.saved)} / ${fmtMoney(g.target)}</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${pct}%; background: var(--pink);"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; color: var(--muted); margin-top: 4px;">
                            <span>Tiến độ: ${pct}% • Hạn: ${g.by || ''}</span>
                            ${saveBtn}
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            return html;
        }

        function renderCashflow(data) {
            if (!data || !data.plans || data.plans.length === 0) {
                return '<div class="card"><div class="card-title">Dòng tiền</div><p style="color: var(--muted);">Không có khoản sắp tới hạn nào.</p></div>';
            }
            const canDone = state.allowed_edits && state.allowed_edits.includes('cashflow');
            let html = '<div class="card"><div class="card-title">Khoản thu chi sắp tới hạn</div>';
            data.plans.forEach(p => {
                const isInc = p.kind === 'income';
                const doneBtn = canDone ? `<button class="btn-sub-action" onclick="submitPlanDone(${p.id})">✓ Xong</button>` : '';
                html += `
                    <div class="list-item">
                        <div>
                            <div style="font-weight: 600; font-size: 0.95rem;">${p.name}</div>
                            <div style="font-size: 0.78rem; color: var(--muted);">${p.due_date || ''} • ${p.category || 'Khác'}</div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div style="font-weight: 700; color: ${isInc ? 'var(--mint)' : 'var(--coral)'}; font-size: 1rem;">
                                ${isInc ? '+' : '-'}${fmtMoney(p.amount)}
                            </div>
                            ${doneBtn}
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            return html;
        }

        function renderAccounts(data) {
            if (!data || !data.accounts || data.accounts.length === 0) {
                return '<div class="card"><div class="card-title">Tài khoản</div><p style="color: var(--muted);">Chưa có tài khoản nào.</p></div>';
            }
            let html = '<div class="card"><div class="card-title">Danh sách ví / tài khoản</div>';
            data.accounts.forEach(a => {
                html += `
                    <div class="list-item">
                        <div>
                            <div style="font-weight: 600; font-size: 0.95rem;">${a.name} ${a.is_default ? '★' : ''}</div>
                            <div style="font-size: 0.78rem; color: var(--muted);">Tỷ lệ: ${a.pct || 0}%</div>
                        </div>
                        <div style="font-weight: 700; color: var(--accent); font-size: 1rem;">
                            ${fmtMoney(a.balance)}
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            return html;
        }

        function getFilteredTransactions(data) {
            if (!data || !data.transactions) return [];
            const sorted = [...data.transactions].sort((a, b) => {
                const da = a.date || '';
                const db = b.date || '';
                if (db !== da) return db.localeCompare(da);
                return (b.id || 0) - (a.id || 0);
            });

            const curMonth = (state.today || '').slice(0, 7) || (state.month || '');

            return sorted.filter(t => {
                if (txState.filterKind === 'expense' && t.kind !== 'expense') return false;
                if (txState.filterKind === 'income' && t.kind !== 'income') return false;

                if (txState.monthFilter === 'current' && curMonth) {
                    if (!t.date || !t.date.startsWith(curMonth)) return false;
                } else if (txState.monthFilter !== 'all' && txState.monthFilter) {
                    if (!t.date || !t.date.startsWith(txState.monthFilter)) return false;
                }

                if (txState.search) {
                    const q = txState.search.toLowerCase().trim();
                    const cat = (t.category || '').toLowerCase();
                    const note = (t.note || '').toLowerCase();
                    const amt = String(t.amount || '');
                    const d = (t.date || '');
                    if (!cat.includes(q) && !note.includes(q) && !amt.includes(q) && !d.includes(q)) {
                        return false;
                    }
                }

                return true;
            });
        }

        function getTxStats(list) {
            let inc = 0;
            let exp = 0;
            list.forEach(t => {
                if (t.kind === 'income') inc += (t.amount || 0);
                else exp += (t.amount || 0);
            });
            return { count: list.length, inc: inc, exp: exp, net: inc - exp };
        }

        function renderTxItemsHtml(data) {
            const allTxs = (data && data.transactions) || [];
            if (allTxs.length === 0) {
                return '<p style="color: var(--muted); text-align: center; padding: 20px 0;">Chưa có giao dịch nào.</p>';
            }

            const filtered = getFilteredTransactions(data);
            const stats = getTxStats(filtered);
            const canDel = state.allowed_edits && state.allowed_edits.includes('edit_tx');
            const limit = txState.limit || 30;
            const visible = filtered.slice(0, limit);

            let html = '';

            html += `
                <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.8rem; color: var(--muted); padding-bottom: 8px; border-bottom: 1px solid rgba(59, 51, 99, 0.4); margin-bottom: 6px;">
                    <span>Hiển thị <strong>${visible.length}</strong> / <strong>${filtered.length}</strong> giao dịch</span>
                    <span>
                        <span style="color: var(--mint);">+${fmtMoney(stats.inc)}</span> • 
                        <span style="color: var(--coral);">-${fmtMoney(stats.exp)}</span>
                    </span>
                </div>
            `;

            if (filtered.length === 0) {
                html += '<p style="color: var(--muted); text-align: center; padding: 24px 0;">Không tìm thấy giao dịch nào phù hợp.</p>';
                return html;
            }

            visible.forEach(t => {
                const isInc = t.kind === 'income';
                const delBtn = canDel ? `<button class="btn-del" onclick="confirmDeleteTx(${t.id})" title="Xoá">✕</button>` : '';
                const catEsc = escapeHtml(t.category || 'Khác');
                const noteEsc = escapeHtml(t.note || '');
                html += `
                    <div class="list-item">
                        <div style="flex: 1; padding-right: 8px;">
                            <div style="font-weight: 600; font-size: 0.9rem;">${catEsc}</div>
                            <div style="font-size: 0.75rem; color: var(--muted); margin-top: 2px;">
                                ${t.date} ${noteEsc ? '• ' + noteEsc : ''}
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div style="font-weight: 700; color: ${isInc ? 'var(--mint)' : 'var(--coral)'}; font-size: 0.95rem; white-space: nowrap;">
                                ${isInc ? '+' : '-'}${fmtMoney(t.amount)}
                            </div>
                            ${delBtn}
                        </div>
                    </div>
                `;
            });

            if (filtered.length > limit) {
                const remaining = filtered.length - limit;
                const nextChunk = Math.min(30, remaining);
                html += `
                    <div style="display: flex; gap: 8px; margin-top: 14px;">
                        <button type="button" class="btn-sub-action" style="flex: 1; padding: 10px; font-size: 0.85rem;" onclick="loadMoreTx(30)">
                            Xem thêm (+${nextChunk} giao dịch, còn ${remaining})
                        </button>
                        <button type="button" class="btn-sub-action" style="padding: 10px 14px; font-size: 0.85rem;" onclick="loadAllTx()">
                            Xem tất cả (${filtered.length})
                        </button>
                    </div>
                `;
            } else if (filtered.length > 30) {
                html += `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 12px; font-size: 0.8rem; color: var(--muted);">
                        <span>Đã hiển thị tất cả ${filtered.length} giao dịch</span>
                        <button type="button" class="btn-sub-action" style="font-size: 0.75rem; padding: 4px 10px;" onclick="collapseTx()">Thu gọn</button>
                    </div>
                `;
            }

            return html;
        }

        function renderTransactions(data) {
            if (!data || !data.transactions || data.transactions.length === 0) {
                return '<div class="card"><div class="card-title">Giao dịch</div><p style="color: var(--muted);">Chưa có giao dịch nào.</p></div>';
            }

            const curMonth = (state.today || '').slice(0, 7) || (state.month || '');
            const allTxs = data.transactions;
            const curMonthCount = curMonth ? allTxs.filter(t => t.date && t.date.startsWith(curMonth)).length : 0;

            const isAllMonth = (txState.monthFilter === 'all');
            const isCurMonth = (txState.monthFilter === 'current');

            const isAllKind = (txState.filterKind === 'all');
            const isExp = (txState.filterKind === 'expense');
            const isInc = (txState.filterKind === 'income');

            return `
                <div class="card">
                    <div class="card-title">
                        <span>Danh sách giao dịch</span>
                        <span style="font-size: 0.78rem; font-weight: normal; color: var(--muted);">${allTxs.length} giao dịch</span>
                    </div>

                    <div style="margin-bottom: 8px;">
                        <input id="txSearchInput" class="form-input" style="font-size: 0.88rem; padding: 8px 12px;"
                               placeholder="🔍 Tìm kiếm giao dịch, ghi chú, số tiền..."
                               value="${escapeHtml(txState.search)}"
                               oninput="onTxSearch(this.value)" />
                    </div>

                    <div style="display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px;">
                        <button type="button" class="chip-btn ${isAllMonth ? 'selected' : ''}" onclick="setTxMonthFilter('all')">
                            Tất cả (${allTxs.length})
                        </button>
                        ${curMonth ? `
                        <button type="button" class="chip-btn ${isCurMonth ? 'selected' : ''}" onclick="setTxMonthFilter('current')">
                            Tháng ${curMonth.slice(5)} (${curMonthCount})
                        </button>` : ''}
                        <button type="button" class="chip-btn ${isAllKind ? 'selected' : ''}" onclick="setTxKindFilter('all')">
                            Mọi loại
                        </button>
                        <button type="button" class="chip-btn ${isExp ? 'selected' : ''}" onclick="setTxKindFilter('expense')">
                            Chi tiêu
                        </button>
                        <button type="button" class="chip-btn ${isInc ? 'selected' : ''}" onclick="setTxKindFilter('income')">
                            Thu nhập
                        </button>
                    </div>

                    <div id="txListContainer">
                        ${renderTxItemsHtml(data)}
                    </div>
                </div>
            `;
        }

        function renderChart(data) {
            if (!data || (!data.series && !data.forecast)) {
                return '<div class="card"><div class="card-title">Biểu đồ dòng tiền</div><p style="color: var(--muted);">Chưa có đủ dữ liệu lịch sử để vẽ biểu đồ.</p></div>';
            }
            const series = data.series || [];
            const forecast = data.forecast || [];
            if (series.length === 0 && forecast.length === 0) {
                return '<div class="card"><div class="card-title">Biểu đồ dòng tiền</div><p style="color: var(--muted);">Chưa có dữ liệu giao dịch.</p></div>';
            }

            // Stats
            const curBal = series.length > 0 ? series[series.length - 1].balance : 0;
            let totalInc = 0;
            let totalExp = 0;
            series.forEach(s => {
                totalInc += (s.income || 0);
                totalExp += (s.expense || 0);
            });

            let minForecast = curBal;
            if (forecast.length > 0) {
                minForecast = Math.min(...forecast.map(f => f.balance));
            }

            // Chart range calculations
            const allPoints = [];
            series.forEach(s => allPoints.push({ date: s.date, balance: s.balance, isForecast: false }));
            forecast.forEach(f => allPoints.push({ date: f.date, balance: f.balance, isForecast: true }));

            let minVal = Math.min(...allPoints.map(p => p.balance));
            let maxVal = Math.max(...allPoints.map(p => p.balance));
            if (minVal === maxVal) {
                minVal -= 100000;
                maxVal += 100000;
            }
            const pad = (maxVal - minVal) * 0.12;
            const yMin = minVal - pad;
            const yMax = maxVal + pad;
            const yRange = (yMax - yMin) || 1;

            const w = 500;
            const h = 230;
            const chartL = 40;
            const chartR = 470;
            const chartT = 30;
            const chartB = 180;
            const chartW = chartR - chartL;
            const chartH = chartB - chartT;

            function getX(idx, total) {
                if (total <= 1) return chartL;
                return chartL + (idx / (total - 1)) * chartW;
            }
            function getY(val) {
                return chartB - ((val - yMin) / yRange) * chartH;
            }

            // Coordinates
            const sCoords = series.map((s, idx) => ({
                x: getX(idx, allPoints.length),
                y: getY(s.balance),
                b: s.balance,
                d: s.date
            }));

            const fCoords = forecast.map((f, idx) => ({
                x: getX(series.length + idx, allPoints.length),
                y: getY(f.balance),
                b: f.balance,
                d: f.date
            }));

            // SVG Paths
            let seriesPathD = '';
            let seriesAreaD = '';
            if (sCoords.length > 0) {
                seriesPathD = `M ${sCoords[0].x.toFixed(1)} ${sCoords[0].y.toFixed(1)}`;
                sCoords.slice(1).forEach(pt => {
                    seriesPathD += ` L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
                });
                const lastS = sCoords[sCoords.length - 1];
                seriesAreaD = `${seriesPathD} L ${lastS.x.toFixed(1)} ${chartB} L ${sCoords[0].x.toFixed(1)} ${chartB} Z`;
            }

            let forecastPathD = '';
            if (fCoords.length > 0) {
                const startPt = sCoords.length > 0 ? sCoords[sCoords.length - 1] : fCoords[0];
                forecastPathD = `M ${startPt.x.toFixed(1)} ${startPt.y.toFixed(1)}`;
                fCoords.forEach(pt => {
                    forecastPathD += ` L ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`;
                });
            }

            const todayX = sCoords.length > 0 ? sCoords[sCoords.length - 1].x : chartL;
            const todayY = sCoords.length > 0 ? sCoords[sCoords.length - 1].y : chartB;
            const zeroY = (0 >= yMin && 0 <= yMax) ? getY(0) : null;

            const firstDate = allPoints[0].date.slice(5);
            const todayDate = data.today ? data.today.slice(5) : '';
            const lastDate = allPoints[allPoints.length - 1].date.slice(5);

            return `
                <div class="card">
                    <div class="card-title">Biểu đồ tài chính & Dự báo 30 ngày</div>
                    <div class="big-number">${fmtMoney(curBal)}</div>
                    <div class="row-split">
                        <div class="stat-sub">
                            <div class="lbl">Điểm thấp nhất 30 ngày tới</div>
                            <div class="val" style="color: ${minForecast < 0 ? 'var(--coral)' : 'var(--mint)'}">${fmtMoney(minForecast)}</div>
                        </div>
                        <div class="stat-sub">
                            <div class="lbl">Tổng chi 30 ngày qua</div>
                            <div class="val" style="color: var(--coral)">-${fmtMoney(totalExp)}</div>
                        </div>
                    </div>
                </div>

                <div class="card" style="padding: 16px 8px 12px 8px;">
                    <div style="display: flex; justify-content: space-between; padding: 0 10px; font-size: 0.8rem; color: var(--muted); margin-bottom: 6px;">
                        <span><span style="display: inline-block; width: 10px; height: 10px; background: var(--accent); border-radius: 50%; margin-right: 4px;"></span>Quá khứ</span>
                        <span><span style="display: inline-block; width: 10px; height: 10px; border-bottom: 2px dashed var(--pink); margin-right: 4px;"></span>Dự báo tương lai</span>
                    </div>

                    <svg viewBox="0 0 ${w} ${h}" style="width: 100%; height: auto; display: block; overflow: visible;">
                        <defs>
                            <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stop-color="var(--accent)" stop-opacity="0.35"/>
                                <stop offset="100%" stop-color="var(--accent)" stop-opacity="0.0"/>
                            </linearGradient>
                        </defs>

                        <!-- Grid & Zero Line -->
                        <line x1="${chartL}" y1="${chartT}" x2="${chartR}" y2="${chartT}" stroke="rgba(255,255,255,0.07)" stroke-dasharray="2,2"/>
                        <line x1="${chartL}" y1="${chartB}" x2="${chartR}" y2="${chartB}" stroke="rgba(255,255,255,0.07)"/>
                        ${zeroY !== null ? `<line x1="${chartL}" y1="${zeroY.toFixed(1)}" x2="${chartR}" y2="${zeroY.toFixed(1)}" stroke="rgba(247, 118, 142, 0.4)" stroke-width="1.5" stroke-dasharray="4,3"/>` : ''}

                        <!-- Axis Value Labels -->
                        <text x="${chartL}" y="${(chartT - 8)}" fill="var(--muted)" font-size="11" font-family="sans-serif">${fmtMoney(maxVal)}</text>
                        <text x="${chartL}" y="${(chartB + 14)}" fill="var(--muted)" font-size="11" font-family="sans-serif">${fmtMoney(minVal)}</text>

                        <!-- Historical Area & Line -->
                        ${seriesAreaD ? `<path d="${seriesAreaD}" fill="url(#chartGrad)"/>` : ''}
                        ${seriesPathD ? `<path d="${seriesPathD}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>` : ''}

                        <!-- Forecast Line -->
                        ${forecastPathD ? `<path d="${forecastPathD}" fill="none" stroke="var(--pink)" stroke-width="2" stroke-dasharray="4,4"/>` : ''}

                        <!-- Today Marker Line & Dot -->
                        <line x1="${todayX.toFixed(1)}" y1="${chartT}" x2="${todayX.toFixed(1)}" y2="${chartB}" stroke="rgba(196, 181, 253, 0.5)" stroke-width="1" stroke-dasharray="2,2"/>
                        <circle cx="${todayX.toFixed(1)}" cy="${todayY.toFixed(1)}" r="4.5" fill="var(--accent)" stroke="#1e1b2e" stroke-width="2"/>
                        <text x="${todayX.toFixed(1)}" y="${(chartB + 15)}" fill="var(--pink)" font-size="11" font-weight="bold" text-anchor="middle" font-family="sans-serif">Hôm nay</text>

                        <!-- Date range labels -->
                        <text x="${chartL}" y="${(chartB + 15)}" fill="var(--muted)" font-size="10" font-family="sans-serif">${firstDate}</text>
                        <text x="${chartR}" y="${(chartB + 15)}" fill="var(--muted)" font-size="10" text-anchor="end" font-family="sans-serif">${lastDate}</text>
                    </svg>
                </div>
            `;
        }

        function renderContent() {
            const container = document.getElementById('tabContent');
            if (!state.allowed_tab_keys.includes(currentSelectedTab)) {
                container.innerHTML = `
                    <div class="card notice-private">
                        <div class="heart">♡</div>
                        <div style="font-weight: 600; font-size: 1rem; color: var(--pink);">Khu vực riêng tư</div>
                        <p style="font-size: 0.85rem; margin-top: 6px;">Người yêu bạn đang thao tác ở tab chưa bật chia sẻ.</p>
                    </div>
                `;
                return;
            }

            const tabData = (state.tabs && state.tabs[currentSelectedTab]) || null;
            if (currentSelectedTab === 'overview') container.innerHTML = renderOverview(tabData);
            else if (currentSelectedTab === 'budgets') container.innerHTML = renderBudgets(tabData);
            else if (currentSelectedTab === 'goals') container.innerHTML = renderGoals(tabData);
            else if (currentSelectedTab === 'cashflow') container.innerHTML = renderCashflow(tabData);
            else if (currentSelectedTab === 'accounts') container.innerHTML = renderAccounts(tabData);
            else if (currentSelectedTab === 'transactions') container.innerHTML = renderTransactions(tabData);
            else if (currentSelectedTab === 'chart') container.innerHTML = renderChart(tabData);
            else container.innerHTML = `<div class="card"><div class="card-title">${state.tab_labels[currentSelectedTab] || currentSelectedTab}</div><p style="color: var(--muted);">Đang cập nhật...</p></div>`;
        }

        function showToast(msg, isError) {
            const t = document.getElementById('toast');
            if (!t) return;
            t.textContent = msg;
            t.style.borderColor = isError ? 'var(--coral)' : 'var(--mint)';
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 2500);
        }

        function submitAction(action, params) {
            if (!pin) return Promise.reject(new Error("No PIN"));
            return fetch('/api/action?pin=' + encodeURIComponent(pin), {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action: action, params: params})
            })
            .then(r => r.json().then(data => ({status: r.status, ok: r.ok, data: data})))
            .then(res => {
                if (!res.ok) {
                    showToast(res.data.error || 'Thao tác không thành công', true);
                    return false;
                } else {
                    showToast('Đã lưu thành công! ✨', false);
                    return true;
                }
            })
            .catch(err => {
                showToast('Lỗi kết nối máy chủ', true);
                return false;
            });
        }

        function openExpenseModal() {
            document.getElementById('expenseModal').classList.add('active');
            document.getElementById('inputAmount').focus();
        }

        function closeExpenseModal() {
            document.getElementById('expenseModal').classList.remove('active');
            document.getElementById('inputAmount').value = '';
            document.getElementById('inputCategory').value = '';
            document.getElementById('inputNote').value = '';
            const acc = document.getElementById('inputAccount');
            if (acc) acc.selectedIndex = 0;
        }

        function setFormAmount(amt) {
            document.getElementById('inputAmount').value = amt;
        }

        function setFormCat(cat) {
            document.getElementById('inputCategory').value = cat;
        }

        function submitExpenseForm() {
            const amount = document.getElementById('inputAmount').value.trim();
            const category = document.getElementById('inputCategory').value.trim();
            const note = document.getElementById('inputNote').value.trim();
            const accEl = document.getElementById('inputAccount');
            const account = accEl ? accEl.value.trim() : '';
            if (!amount) {
                showToast('Vui lòng nhập số tiền', true);
                return;
            }
            const p = {amount: amount, category: category, note: note};
            if (account) p.account = account;
            submitAction('expense', p).then(ok => {
                if (ok) closeExpenseModal();
            });
        }

        function submitPlanDone(planId) {
            if (confirm('Đánh dấu đã hoàn thành khoản dòng tiền này?')) {
                submitAction('plan_done', {id: planId});
            }
        }

        function promptGoalSave(goalId) {
            let name = "hũ";
            if (state && state.tabs && state.tabs.goals && state.tabs.goals.goals) {
                const found = state.tabs.goals.goals.find(x => x.id === goalId);
                if (found && found.name) name = found.name;
            }
            const amt = prompt('Nhập số tiền muốn nạp vào hũ "' + name + '" (ví dụ 200k, 500k):', '200k');
            if (amt && amt.trim()) {
                submitAction('goal_save', {id: goalId, amount: amt.trim()});
            }
        }

        function confirmDeleteTx(txId) {
            if (confirm('Bạn có chắc muốn xoá giao dịch này không?')) {
                submitAction('tx_delete', {id: txId});
            }
        }

        function updateAccountSelect() {
            const grp = document.getElementById('groupAccount');
            const sel = document.getElementById('inputAccount');
            if (!grp || !sel) return;
            let accs = [];
            if (state.accounts && state.accounts.length > 0) {
                accs = state.accounts;
            } else if (state.tabs && state.tabs.accounts && state.tabs.accounts.accounts) {
                accs = state.tabs.accounts.accounts;
            } else if (state.tabs && state.tabs.overview && state.tabs.overview.accounts) {
                accs = state.tabs.overview.accounts;
            }
            if (!accs || accs.length === 0) {
                grp.style.display = 'none';
                return;
            }
            grp.style.display = 'block';
            const curVal = sel.value;
            sel.innerHTML = '<option value="">Mặc định (Ví chính)</option>';
            accs.forEach(a => {
                const opt = document.createElement('option');
                opt.value = a.name;
                opt.textContent = a.name + (a.is_default ? ' (Mặc định)' : '');
                sel.appendChild(opt);
            });
            if (curVal) sel.value = curVal;
        }

        function applyState(newState) {
            state = newState;
            if (state.sync_mode === 'follow' && state.active_tab && state.allowed_tab_keys.includes(state.active_tab)) {
                currentSelectedTab = state.active_tab;
            }
            const fab = document.getElementById('fabAdd');
            if (fab) {
                const canAdd = state.allowed_edits && state.allowed_edits.includes('expense');
                fab.style.display = canAdd ? 'flex' : 'none';
            }
            updateAccountSelect();
            renderNav();
            renderContent();
        }

        function initSSE() {
            if (!pin) return;
            const es = new EventSource('/api/stream?pin=' + encodeURIComponent(pin));
            es.addEventListener('init', e => {
                applyState(JSON.parse(e.data));
            });
            es.addEventListener('update', e => {
                applyState(JSON.parse(e.data));
            });
            es.addEventListener('config_changed', e => {
                applyState(JSON.parse(e.data));
            });
            es.onopen = () => {
                document.getElementById('liveStatusText').textContent = 'Trực tiếp';
            };
            es.onerror = () => {
                document.getElementById('liveStatusText').textContent = 'Đang nối lại...';
            };
        }

        // Instant hydration if initialData was injected by server
        const initialEl = document.getElementById('initialData');
        let hydrated = false;
        if (initialEl) {
            try {
                const initData = JSON.parse(initialEl.textContent);
                if (initData && initData.allowed_tab_keys && initData.allowed_tab_keys.length > 0) {
                    applyState(initData);
                    hydrated = true;
                }
            } catch (e) {
                console.error(e);
            }
        }

        // Connect SSE and fetch only if not already hydrated
        if (pin) {
            if (hydrated) {
                initSSE();
            } else {
                fetch('/api/data?pin=' + encodeURIComponent(pin))
                    .then(r => {
                        if (!r.ok) throw new Error('Unauthorized');
                        return r.json();
                    })
                    .then(data => {
                        applyState(data);
                        initSSE();
                    })
                    .catch(() => {
                        document.getElementById('tabContent').innerHTML = '<div class="card" style="text-align: center; color: var(--coral);">Mã PIN không đúng hoặc phiên chia sẻ đã kết thúc.</div>';
                    });
            }
        }
    </script>
</body>
</html>"""


def start_share_server(
    store: Any,
    today: date,
    port: int = 0,
    pin: Optional[str] = None,
    allowed_tabs: Optional[Set[str]] = None,
    active_tab: str = "overview",
    sync_mode: str = "free",
    allowed_edits: Optional[Set[str]] = None,
    on_mutation: Optional[Callable[[], None]] = None,
) -> ShareServer:
    server = ShareServer(
        store=store,
        today=today,
        port=port,
        pin=pin,
        allowed_tabs=allowed_tabs,
        active_tab=active_tab,
        sync_mode=sync_mode,
        allowed_edits=allowed_edits,
        on_mutation=on_mutation,
    )
    return server.start()
