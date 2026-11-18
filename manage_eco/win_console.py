"""Windows console raw-input and VT100 support for `eco ui`.

Uses `kernel32` Console APIs via `ctypes` so `tui.py` receives the same VT100/SGR
escape sequences, UTF-8 characters, `"resize"` events, and thread wakeups as on POSIX.
Only imported on `sys.platform == "win32"`.
"""
import ctypes
from ctypes import wintypes
import sys
from typing import Callable, Optional

STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11

ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_MOUSE_INPUT = 0x0010
ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200

ENABLE_PROCESSED_OUTPUT = 0x0001
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

KEY_EVENT = 0x0001
WINDOW_BUFFER_SIZE_EVENT = 0x0004

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF
CP_UTF8 = 65001


class _COORD(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _UCHAR(ctypes.Union):
    _fields_ = [("UnicodeChar", wintypes.WCHAR), ("AsciiChar", ctypes.c_char)]


class _KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", wintypes.BOOL),
        ("wRepeatCount", wintypes.WORD),
        ("wVirtualKeyCode", wintypes.WORD),
        ("wVirtualScanCode", wintypes.WORD),
        ("uChar", _UCHAR),
        ("dwControlKeyState", wintypes.DWORD),
    ]


class _MOUSE_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("dwMousePosition", _COORD),
        ("dwButtonState", wintypes.DWORD),
        ("dwControlKeyState", wintypes.DWORD),
        ("dwEventFlags", wintypes.DWORD),
    ]


class _WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
    _fields_ = [("dwSize", _COORD)]


class _EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", _KEY_EVENT_RECORD),
        ("MouseEvent", _MOUSE_EVENT_RECORD),
        ("WindowBufferSizeEvent", _WINDOW_BUFFER_SIZE_RECORD),
    ]


class _INPUT_RECORD(ctypes.Structure):
    _fields_ = [
        ("EventType", wintypes.WORD),
        ("Event", _EVENT_UNION),
    ]


class WinConsole:
    """Manages Windows console raw/VT mode, UTF-8 codepage, and a thread-safe wake event."""

    def __init__(self) -> None:
        self._k32 = ctypes.windll.kernel32
        self.h_in = self._k32.GetStdHandle(STD_INPUT_HANDLE)
        self.h_out = self._k32.GetStdHandle(STD_OUTPUT_HANDLE)
        self.h_wake = self._k32.CreateEventW(None, False, False, None)

        self._orig_in = wintypes.DWORD()
        self._orig_out = wintypes.DWORD()
        self._has_in_mode = bool(self._k32.GetConsoleMode(self.h_in, ctypes.byref(self._orig_in)))
        self._has_out_mode = bool(self._k32.GetConsoleMode(self.h_out, ctypes.byref(self._orig_out)))
        self._orig_cp_in = self._k32.GetConsoleCP()
        self._orig_cp_out = self._k32.GetConsoleOutputCP()

    def enter(self) -> None:
        self._k32.SetConsoleCP(CP_UTF8)
        self._k32.SetConsoleOutputCP(CP_UTF8)
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                try:
                    stream.reconfigure(encoding="utf-8")
                except Exception:
                    pass
        if self._has_out_mode:
            out_mode = self._orig_out.value | ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            self._k32.SetConsoleMode(self.h_out, out_mode)
        if self._has_in_mode:
            in_mode = (
                (self._orig_in.value & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT | ENABLE_QUICK_EDIT_MODE))
                | ENABLE_EXTENDED_FLAGS
                | ENABLE_WINDOW_INPUT
                | ENABLE_VIRTUAL_TERMINAL_INPUT
            )
            self._k32.SetConsoleMode(self.h_in, in_mode)

    def wake(self) -> None:
        if self.h_wake:
            self._k32.SetEvent(self.h_wake)

    def close(self) -> None:
        if self._has_in_mode:
            self._k32.SetConsoleMode(self.h_in, self._orig_in.value)
        if self._has_out_mode:
            self._k32.SetConsoleMode(self.h_out, self._orig_out.value)
        if self._orig_cp_in:
            self._k32.SetConsoleCP(self._orig_cp_in)
        if self._orig_cp_out:
            self._k32.SetConsoleOutputCP(self._orig_cp_out)
        if self.h_wake:
            self._k32.CloseHandle(self.h_wake)
            self.h_wake = None


class WinKeyReader:
    """Windows counterpart to `tui.KeyReader` using `WaitForMultipleObjects` + `ReadConsoleInputW`."""

    def __init__(self, console: WinConsole, parse_fn: Callable[[bytes], tuple]):
        self.console = console
        self.parse_fn = parse_fn
        self.buf = b""
        self._handles = (wintypes.HANDLE * 2)(console.h_in, console.h_wake)

    def _drain_input(self) -> bool:
        k32 = self.console._k32
        avail = wintypes.DWORD(0)
        if not k32.GetNumberOfConsoleInputEvents(self.console.h_in, ctypes.byref(avail)) or avail.value == 0:
            return False
        count = min(avail.value, 64)
        recs = (_INPUT_RECORD * count)()
        read_count = wintypes.DWORD(0)
        if not k32.ReadConsoleInputW(self.console.h_in, recs, count, ctypes.byref(read_count)):
            return False
        saw_resize = False
        for i in range(read_count.value):
            rec = recs[i]
            if rec.EventType == KEY_EVENT:
                ke = rec.Event.KeyEvent
                if ke.bKeyDown and ke.uChar.UnicodeChar != "\x00":
                    rep = max(1, int(ke.wRepeatCount))
                    self.buf += (ke.uChar.UnicodeChar * rep).encode("utf-8", "replace")
            elif rec.EventType == WINDOW_BUFFER_SIZE_EVENT:
                saw_resize = True
        return saw_resize

    def next(self, timeout: Optional[float] = None):
        k32 = self.console._k32
        while True:
            event, n = self.parse_fn(self.buf)
            if n:
                self.buf = self.buf[n:]
                return event
            if self.buf:
                wait_ms = 50
            elif timeout is None:
                wait_ms = INFINITE
            else:
                wait_ms = max(0, int(timeout * 1000))
            rc = k32.WaitForMultipleObjects(2, self._handles, False, wait_ms)
            if rc == WAIT_OBJECT_0 + 1:
                return "resize"
            if rc == WAIT_OBJECT_0:
                saw_resize = self._drain_input()
                if saw_resize and not self.buf:
                    return "resize"
                continue
            # Timeout (or wait failure)
            if self.buf:
                lone_esc, self.buf = self.buf == b"\x1b", b""
                return "esc" if lone_esc else ""
            return "tick"
