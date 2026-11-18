"""Tiny synthesized sound effects, played fire-and-forget by the OS audio player.

Sounds are generated once with the stdlib (wave + math) into a cache dir, then played by
`afplay` (macOS), `paplay`/`pw-play`/`aplay` (Linux). Playback runs in a child process, so the
TUI never blocks and its own memory is unaffected. Muted by `ECO_SOUND=0` or the stored setting.
"""
import math
import os
import shutil
import struct
import subprocess
import sys
import threading
import time
import wave
from typing import Dict, List, Optional, Tuple

RATE = 22050
EVENTS = ("save", "done", "delete", "error", "tab", "warn", "click")

# (frequency Hz, duration s, volume 0..1) notes per event; 0 Hz = rest
_NOTES = {
    "save": [(1046.5, 0.07, 0.5), (1568.0, 0.14, 0.45)],                      # C6 → G6 chime
    "done": [(1318.5, 0.06, 0.45), (1568.0, 0.06, 0.45), (2093.0, 0.18, 0.4)],  # E6 G6 C7 coin
    "delete": [(880.0, 0.06, 0.4), (587.3, 0.12, 0.35)],                       # A5 → D5 drop
    "error": [(196.0, 0.09, 0.45), (0, 0.04, 0), (196.0, 0.12, 0.45)],         # low double buzz
    "tab": [(2637.0, 0.018, 0.18)],                                            # soft tick
    "warn": [(659.3, 0.09, 0.35), (523.3, 0.16, 0.35)],                        # E5 → C5
    "click": [(1760.0, 0.012, 0.22), (2349.3, 0.05, 0.16)],                    # tiny "ping"
}  # type: Dict[str, List[Tuple[float, float, float]]]

_SQUARE = {"error"}  # buzzier timbre

_lock = threading.Lock()
_last = {}  # type: Dict[str, float]
_procs = []  # type: List[subprocess.Popen]


def cache_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "manage_eco", "sfx")


def synth(event: str) -> bytes:
    """16-bit mono PCM for an event: sine (or square) notes with a fast attack and exponential decay."""
    out = bytearray()
    for freq, dur, vol in _NOTES[event]:
        n = int(RATE * dur)
        for i in range(n):
            t = i / RATE
            if freq <= 0:
                s = 0.0
            else:
                env = min(1.0, i / (RATE * 0.004)) * math.exp(-4.0 * i / n)
                w = math.sin(2 * math.pi * freq * t)
                if event in _SQUARE:
                    w = 1.0 if w >= 0 else -1.0
                    w *= 0.5
                else:
                    w += 0.25 * math.sin(4 * math.pi * freq * t)  # a little sparkle overtone
                s = vol * env * w / 1.25
            out += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
    return bytes(out)


def sound_path(event: str) -> str:
    """Path to the event's WAV, generating it on first use."""
    path = os.path.join(cache_dir(), "%s.wav" % event)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(synth(event))
        os.replace(tmp, path)
    return path


def player() -> Optional[List[str]]:
    """Command prefix for the first available audio player, or None."""
    if sys.platform == "win32":
        return ["__winsound__"]
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay", "-v", "0.6"]
    for cmd in (["paplay"], ["pw-play"], ["aplay", "-q"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def env_enabled() -> bool:
    return os.environ.get("ECO_SOUND", "1").lower() not in ("0", "off", "false", "no")


def play(event: str, enabled: bool = True) -> bool:
    """Play an event sound without blocking. Returns True if a sound was started."""
    if not enabled or not env_enabled() or event not in _NOTES:
        return False
    now = time.monotonic()
    with _lock:
        if event in _last and now - _last[event] < 0.08:  # debounce key repeat
            return False
        _last[event] = now
        _procs[:] = [p for p in _procs if p.poll() is None]  # reap finished players
        if len(_procs) >= 4:
            return False
        cmd = player()
        try:
            if cmd is None:
                if event == "error":  # only the error falls back to the terminal bell
                    sys.__stdout__.write("\a")
                    sys.__stdout__.flush()
                    return True
                return False
            if cmd == ["__winsound__"]:
                import winsound
                winsound.PlaySound(sound_path(event), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
                return True
            _procs.append(subprocess.Popen(cmd + [sound_path(event)], stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                           start_new_session=True))
            return True
        except OSError:
            return False
