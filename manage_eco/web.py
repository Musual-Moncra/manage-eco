"""Background HTTP server and Server-Sent Events (SSE) broadcaster for Manage Eco.

Never imports rich. Pure standard library (http.server, threading, queue).
"""
import json
import queue
import secrets
import threading
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Set
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
    ):
        self.store = store
        self.today = today
        self.requested_port = port
        self.pin = pin or f"{secrets.randbelow(9000) + 1000}"
        self.allowed_tabs: Set[str] = set(allowed_tabs if allowed_tabs is not None else DEFAULT_ALLOWED_TABS)
        self.active_tab: str = active_tab
        self.sync_mode: str = sync_mode

        self._lock = threading.Lock()
        self._clients: List[queue.Queue] = []
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
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                def _verify_pin(self, query_params: Dict[str, List[str]]) -> bool:
                    provided = query_params.get("pin", [""])[0]
                    return secrets.compare_digest(provided, server_self.pin)

                def do_GET(self) -> None:
                    parsed = urlparse(self.path)
                    params = parse_qs(parsed.query)

                    if parsed.path == "/":
                        # Serves HTML client
                        html = server_self._render_index_html()
                        content = html.encode("utf-8")
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(content)))
                        self.end_headers()
                        self.wfile.write(content)
                        return

                    if parsed.path == "/api/data":
                        if not self._verify_pin(params):
                            self.send_error(HTTPStatus.UNAUTHORIZED, "Invalid or missing PIN")
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
                                    event = q.get(timeout=1.0)
                                    ev_type = event.get("type", "update")
                                    ev_data = json.dumps(event.get("data", {}), ensure_ascii=False)
                                    msg = f"event: {ev_type}\ndata: {ev_data}\n\n".encode("utf-8")
                                    self.wfile.write(msg)
                                    self.wfile.flush()
                                except queue.Empty:
                                    # Send keep-alive comment
                                    self.wfile.write(b": keepalive\n\n")
                                    self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        finally:
                            server_self._remove_client(q)
                        return

                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

            self._server = ThreadingHTTPServer(("0.0.0.0", self.requested_port), RequestHandler)
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
        with self._lock:
            return get_shared_snapshot(
                self.store,
                self.today,
                self.allowed_tabs,
                active_tab=self.active_tab,
                sync_mode=self.sync_mode,
            )

    def update_config(
        self,
        allowed_tabs: Optional[Set[str]] = None,
        active_tab: Optional[str] = None,
        sync_mode: Optional[str] = None,
    ) -> None:
        with self._lock:
            if allowed_tabs is not None:
                self.allowed_tabs = set(allowed_tabs)
            if active_tab is not None:
                self.active_tab = active_tab
            if sync_mode is not None:
                self.sync_mode = sync_mode
        self.notify_change("config_changed")

    def notify_change(self, event_type: str = "update") -> None:
        snap = self.get_snapshot()
        msg = {"type": event_type, "data": snap}
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def _render_index_html(self) -> str:
        # Default placeholder HTML for Task 2, expanded in Task 3
        return f"""<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Eco • Cùng quan sát</title>
    <style>
        body {{ background: #1e1b2e; color: #c4b5fd; font-family: system-ui, sans-serif; margin: 0; padding: 20px; }}
        h1 {{ color: #f9a8d4; }}
    </style>
</head>
<body>
    <h1>🌿 Manage Eco</h1>
    <p>Chế độ xem trực tiếp</p>
    <div id="app"></div>
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
) -> ShareServer:
    server = ShareServer(
        store=store,
        today=today,
        port=port,
        pin=pin,
        allowed_tabs=allowed_tabs,
        active_tab=active_tab,
        sync_mode=sync_mode,
    )
    return server.start()
