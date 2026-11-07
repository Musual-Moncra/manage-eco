"""Cloudflare tunnel integration and terminal QR code generator.

Never imports rich. Pure standard library (socket, subprocess, re, typing).
"""
import re
import socket
import subprocess
import threading
import time
from typing import Any, List, Optional, Tuple


def get_local_ip() -> str:
    """Discover local LAN IP without sending external packets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connecting to a public address sets the interface on the socket without sending data
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


# --- Pure Python QR Code Generator (Versions 1-5, Level L, Mask 0) ---

_GF_EXP = [1] * 512
_GF_LOG = [0] * 256
_x = 1
for _i in range(1, 255):
    _x <<= 1
    if _x & 256:
        _x ^= 0x11D
    _GF_EXP[_i] = _x
    _GF_LOG[_x] = _i
for _i in range(255, 512):
    _GF_EXP[_i] = _GF_EXP[_i - 255]


def _gf_mul(x: int, y: int) -> int:
    if x == 0 or y == 0:
        return 0
    return _GF_EXP[_GF_LOG[x] + _GF_LOG[y]]


def _rs_poly(n: int) -> List[int]:
    g = [1]
    for i in range(n):
        ng = [0] * (len(g) + 1)
        for j, c in enumerate(g):
            ng[j] ^= _gf_mul(c, _GF_EXP[i])
            ng[j + 1] ^= c
        g = ng
    return g


# Capacity for versions 1-5 with Error Correction Level L
_VERSION_SPECS = [
    # (version, size, total_codewords, data_codewords, ec_codewords, align_centers)
    (1, 21, 26, 19, 7, []),
    (2, 25, 44, 34, 10, [6, 18]),
    (3, 29, 70, 55, 15, [6, 22]),
    (4, 33, 100, 80, 20, [6, 26]),
    (5, 37, 134, 108, 26, [6, 30]),
]

_FORMAT_INFO_L_MASK0 = 0x77C4  # Level L, Mask 0 (0b111011111000100)


def _encode_qr_matrix(text: str) -> List[List[int]]:
    data_bytes = text.encode("utf-8")
    data_len = len(data_bytes)

    # Pick smallest fitting version
    selected = None
    for spec in _VERSION_SPECS:
        if data_len <= spec[3] - 2:  # 2 bytes for header (mode + count)
            selected = spec
            break
    if selected is None:
        selected = _VERSION_SPECS[-1]
        data_bytes = data_bytes[: selected[3] - 2]
        data_len = len(data_bytes)

    version, size, total_cw, data_cw, ec_cw, align_coords = selected

    # 1. Build data bit stream (Byte mode: '0100', 8-bit length for ver 1-9)
    bits = "0100" + f"{data_len:08b}"
    for b in data_bytes:
        bits += f"{b:08b}"

    # Terminator
    max_data_bits = data_cw * 8
    if len(bits) < max_data_bits:
        bits += "0000"[: max_data_bits - len(bits)]
    # Pad to multiple of 8
    if len(bits) % 8 != 0:
        bits += "0" * (8 - (len(bits) % 8))

    # Pad bytes (0xEC, 0x11)
    pad_bytes = [0xEC, 0x11]
    pad_idx = 0
    while len(bits) < max_data_bits:
        bits += f"{pad_bytes[pad_idx % 2]:08b}"
        pad_idx += 1

    data_codewords = [int(bits[i : i + 8], 2) for i in range(0, max_data_bits, 8)]

    # 2. Compute Reed-Solomon Error Correction
    poly = _rs_poly(ec_cw)
    remainder = list(data_codewords) + [0] * ec_cw
    for i in range(len(data_codewords)):
        coef = remainder[i]
        if coef != 0:
            for j in range(len(poly)):
                remainder[i + j] ^= _gf_mul(poly[j], coef)
    ec_codewords = remainder[-ec_cw:]
    all_codewords = data_codewords + ec_codewords

    # 3. Construct Matrix
    matrix = [[None] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    # Finder patterns
    def set_finder(r0: int, c0: int) -> None:
        for r in range(7):
            for c in range(7):
                val = 1 if (r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)) else 0
                matrix[r0 + r][c0 + c] = val
                reserved[r0 + r][c0 + c] = True
        # Separator borders
        for r in range(-1, 8):
            for c in range(-1, 8):
                rr, cc = r0 + r, c0 + c
                if 0 <= rr < size and 0 <= cc < size:
                    reserved[rr][cc] = True
                    if matrix[rr][cc] is None:
                        matrix[rr][cc] = 0

    set_finder(0, 0)
    set_finder(0, size - 7)
    set_finder(size - 7, 0)

    # Timing patterns
    for i in range(8, size - 8):
        v = 1 if i % 2 == 0 else 0
        if not reserved[6][i]:
            matrix[6][i] = v
            reserved[6][i] = True
        if not reserved[i][6]:
            matrix[i][6] = v
            reserved[i][6] = True

    # Alignment patterns
    if align_coords:
        for r in align_coords:
            for c in align_coords:
                # Skip if overlaps with finders
                if (r < 9 and c < 9) or (r < 9 and c > size - 9) or (r > size - 9 and c < 9):
                    continue
                for dr in range(-2, 3):
                    for dc in range(-2, 3):
                        rr, cc = r + dr, c + dc
                        val = 1 if (abs(dr) == 2 or abs(dc) == 2 or (dr == 0 and dc == 0)) else 0
                        matrix[rr][cc] = val
                        reserved[rr][cc] = True

    # Dark module
    matrix[size - 8][8] = 1
    reserved[size - 8][8] = True

    # Format info reserved areas
    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
    for i in range(size - 8, size):
        reserved[8][i] = True
        reserved[i][8] = True

    # 4. Fill Data Bits (Zigzag)
    bit_list: List[int] = []
    for cw in all_codewords:
        for b in range(7, -1, -1):
            bit_list.append((cw >> b) & 1)

    bit_idx = 0
    right = size - 1
    upward = True
    while right > 0:
        if right == 6:  # Skip vertical timing pattern column
            right -= 1
        cols = [right, right - 1]
        rows = range(size - 1, -1, -1) if upward else range(size)
        for r in rows:
            for c in cols:
                if not reserved[r][c]:
                    b = bit_list[bit_idx] if bit_idx < len(bit_list) else 0
                    bit_idx += 1
                    # Apply Mask 0: (row + col) % 2 == 0
                    if (r + c) % 2 == 0:
                        b ^= 1
                    matrix[r][c] = b
        upward = not upward
        right -= 2

    # 5. Write Format Information (Mask 0, Level L)
    fbits = f"{_FORMAT_INFO_L_MASK0:015b}"
    # Top-left and bottom-left / top-right
    for i in range(6):
        matrix[8][i] = int(fbits[i])
    matrix[8][7] = int(fbits[6])
    matrix[8][8] = int(fbits[7])
    matrix[7][8] = int(fbits[8])
    for i in range(9, 15):
        matrix[14 - i][8] = int(fbits[i])

    for i in range(7):
        matrix[size - 1 - i][8] = int(fbits[i])
    for i in range(8):
        matrix[8][size - 8 + i] = int(fbits[7 + i])

    # Convert any remaining None to 0
    res = []
    for row in matrix:
        res.append([0 if cell is None else cell for cell in row])
    return res


def generate_terminal_qr(text: str) -> List[str]:
    """Render QR code using 2-cell vertical Unicode blocks for terminal display."""
    matrix = _encode_qr_matrix(text)
    # Add quiet zone of 2 cells
    pad = 2
    full_size = len(matrix) + pad * 2
    padded = [[0] * full_size for _ in range(full_size)]
    for r, row in enumerate(matrix):
        for c, val in enumerate(row):
            padded[r + pad][c + pad] = val

    lines: List[str] = []
    # Combine pairs of rows vertically
    for r in range(0, full_size, 2):
        top_row = padded[r]
        bot_row = padded[r + 1] if r + 1 < full_size else [0] * full_size
        line = ""
        for c in range(full_size):
            top = top_row[c]
            bot = bot_row[c]
            # In inverted dark terminal:
            # 0 (white background): full block '█'
            # 1 (black foreground module): ' '
            if top == 0 and bot == 0:
                line += "█"
            elif top == 0 and bot == 1:
                line += "▀"
            elif top == 1 and bot == 0:
                line += "▄"
            else:
                line += " "
        lines.append(line)
    return lines


def find_tailscale_bin() -> Optional[str]:
    import shutil
    import os
    p = shutil.which("tailscale")
    if p:
        return p
    for candidate in ("/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"):
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class TailscaleTunnel:
    """Manages Tailscale Funnel / Serve to share local web server with Let's Encrypt HTTPS."""

    def __init__(self) -> None:
        self.url: Optional[str] = None
        self.provider_name: str = "Tailscale Funnel"
        self._running: bool = False
        self._bin: Optional[str] = find_tailscale_bin()

    def is_running(self) -> bool:
        return self._running and self.url is not None

    def start(self, local_port: int, wait_seconds: float = 3.0) -> Optional[str]:
        bin_path = self._bin or "tailscale"
        try:
            # 1. Run funnel directly in background (fast path, <0.07s)
            res = subprocess.run(
                [bin_path, "funnel", "--yes", "--bg", str(local_port)],
                capture_output=True,
                text=True,
                timeout=wait_seconds,
            )
            out = (res.stdout or "") + " " + (res.stderr or "")
            if "stopped" in out.lower():
                subprocess.run([bin_path, "up"], capture_output=True, text=True, timeout=2.0)
                res = subprocess.run(
                    [bin_path, "funnel", "--yes", "--bg", str(local_port)],
                    capture_output=True,
                    text=True,
                    timeout=wait_seconds,
                )
                out = (res.stdout or "") + " " + (res.stderr or "")

            m = re.search(r"https://[a-zA-Z0-9.-]+\.ts\.net", out)
            if m:
                self.url = m.group(0).rstrip("/")
                self._running = True
                self.provider_name = "Tailscale Funnel"
                return self.url

            # 3. Fallback: check funnel status json if available
            st_json = subprocess.run([bin_path, "funnel", "status", "--json"], capture_output=True, text=True, timeout=2.0)
            if st_json.returncode == 0:
                import json
                data = json.loads(st_json.stdout)
                web = data.get("Web", {})
                for host in web.keys():
                    domain = host.split(":")[0]
                    self.url = f"https://{domain}"
                    self._running = True
                    self.provider_name = "Tailscale Funnel"
                    return self.url
        except Exception:
            pass

        self._running = False
        self.url = None
        return None

    def stop(self) -> None:
        bin_path = self._bin or "tailscale"
        try:
            subprocess.run([bin_path, "funnel", "--https=443", "off"], capture_output=True, timeout=2.0)
        except Exception:
            pass
        self._running = False
        self.url = None


class CloudflareTunnel:
    """Manages an external cloudflared quick tunnel subprocess without blocking."""

    def __init__(self) -> None:
        self.proc: Optional[subprocess.Popen] = None
        self.url: Optional[str] = None
        self.provider_name: str = "Cloudflare"
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self, local_port: int, wait_seconds: float = 0.5) -> Optional[str]:
        if self.is_running():
            return self.url
        try:
            self._stop_event.clear()
            self.proc = subprocess.Popen(
                ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{local_port}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (FileNotFoundError, PermissionError):
            self.proc = None
            return None

        self._start_reader_thread()
        # Brief initial wait (e.g. 0.5s) in case it connects immediately
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait_seconds:
            if self.url or (self.proc and self.proc.poll() is not None):
                break
            time.sleep(0.05)
        return self.url

    def _start_reader_thread(self) -> None:
        def _read() -> None:
            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            if not self.proc or not self.proc.stderr:
                return
            for line in self.proc.stderr:
                if self._stop_event.is_set():
                    break
                m = url_pattern.search(line)
                if m:
                    self.url = m.group(0)
                    break

        self._thread = threading.Thread(target=_read, daemon=True)
        self._thread.start()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        self._stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
            self.url = None


class AutoTunnel:
    """Unified remote tunnel that automatically tries Tailscale Funnel, then Cloudflare Tunnel."""

    def __init__(self) -> None:
        self.active_tunnel: Optional[Any] = None
        self.url: Optional[str] = None
        self.provider_name: str = "Remote Tunnel"
        self._running: bool = False

    def is_running(self) -> bool:
        return self._running and self.url is not None

    def start(self, local_port: int, wait_seconds: float = 2.0) -> Optional[str]:
        # 1. Prefer Tailscale if available
        ts = TailscaleTunnel()
        url = ts.start(local_port, wait_seconds=wait_seconds)
        if url:
            self.active_tunnel = ts
            self.url = url
            self._running = True
            self.provider_name = getattr(ts, "provider_name", "Tailscale Funnel")
            return url

        # 2. Fall back to Cloudflare
        cf = CloudflareTunnel()
        url = cf.start(local_port, wait_seconds=wait_seconds)
        if url:
            self.active_tunnel = cf
            self.url = url
            self._running = True
            self.provider_name = getattr(cf, "provider_name", "Cloudflare")
            return url

        self._running = False
        return None

    def stop(self) -> None:
        if self.active_tunnel:
            try:
                self.active_tunnel.stop()
            except Exception:
                pass
            self.active_tunnel = None
        self.url = None
        self._running = False


def create_tunnel() -> AutoTunnel:
    """Create a smart tunnel that tries Tailscale Funnel, then Cloudflare Tunnel."""
    return AutoTunnel()
