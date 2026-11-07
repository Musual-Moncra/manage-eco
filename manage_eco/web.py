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
        return """<!DOCTYPE html>
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
    </style>
</head>
<body>
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

        function fmtMoney(n) {
            if (n === null || n === undefined) return '0 ₫';
            const num = Math.round(Number(n));
            return num.toLocaleString('vi-VN') + ' ₫';
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
            let html = '<div class="card"><div class="card-title">Các mục tiêu tích luỹ</div>';
            data.goals.forEach(g => {
                const pct = Math.min(100, Math.round((g.saved / (g.target || 1)) * 100));
                html += `
                    <div style="margin-bottom: 16px;">
                        <div style="display: flex; justify-content: space-between; font-size: 0.95rem; font-weight: 600;">
                            <span style="color: var(--pink)">${g.name}</span>
                            <span>${fmtMoney(g.saved)} / ${fmtMoney(g.target)}</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${pct}%; background: var(--pink);"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--muted); margin-top: 4px;">
                            <span>Tiến độ: ${pct}%</span>
                            <span>Hạn: ${g.by || ''}</span>
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
            let html = '<div class="card"><div class="card-title">Khoản thu chi sắp tới hạn</div>';
            data.plans.forEach(p => {
                const isInc = p.kind === 'income';
                html += `
                    <div class="list-item">
                        <div>
                            <div style="font-weight: 600; font-size: 0.95rem;">${p.name}</div>
                            <div style="font-size: 0.78rem; color: var(--muted);">${p.due_date || ''} • ${p.category || 'Khác'}</div>
                        </div>
                        <div style="font-weight: 700; color: ${isInc ? 'var(--mint)' : 'var(--coral)'}; font-size: 1rem;">
                            ${isInc ? '+' : '-'}${fmtMoney(p.amount)}
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

        function renderTransactions(data) {
            if (!data || !data.transactions || data.transactions.length === 0) {
                return '<div class="card"><div class="card-title">Giao dịch</div><p style="color: var(--muted);">Chưa có giao dịch tháng này.</p></div>';
            }
            let html = '<div class="card"><div class="card-title">Giao dịch gần đây</div>';
            data.transactions.slice(0, 15).forEach(t => {
                const isInc = t.kind === 'income';
                html += `
                    <div class="list-item">
                        <div>
                            <div style="font-weight: 600; font-size: 0.9rem;">${t.category || 'Khác'}</div>
                            <div style="font-size: 0.75rem; color: var(--muted);">${t.date} ${t.note ? '• ' + t.note : ''}</div>
                        </div>
                        <div style="font-weight: 700; color: ${isInc ? 'var(--mint)' : 'var(--coral)'}; font-size: 0.95rem;">
                            ${isInc ? '+' : '-'}${fmtMoney(t.amount)}
                        </div>
                    </div>
                `;
            });
            html += '</div>';
            return html;
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
            else container.innerHTML = `<div class="card"><div class="card-title">${state.tab_labels[currentSelectedTab] || currentSelectedTab}</div><p style="color: var(--muted);">Đang cập nhật...</p></div>`;
        }

        function applyState(newState) {
            state = newState;
            if (state.sync_mode === 'follow' && state.active_tab && state.allowed_tab_keys.includes(state.active_tab)) {
                currentSelectedTab = state.active_tab;
            }
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

        // Initial fetch
        if (pin) {
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
