#!/usr/bin/env bash
# TUI idle check (SPEC v5, section C): drive `eco` in a pty, save one item,
# wait for animations to finish, then require ~0 CPU and max RSS < 45 MB.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMIT_MB="${IDLE_RSS_MB:-45}"
CPU_LIMIT="${IDLE_CPU_PCT:-2.0}"
DB="$(mktemp -t eco-idlecheck.XXXXXX)"
trap 'rm -f "$DB"' EXIT
cd "$ROOT"

python3 - "$DB" "$LIMIT_MB" "$CPU_LIMIT" <<'PY'
import fcntl
import os
import pty
import select
import signal
import sqlite3
import struct
import subprocess
import sys
import termios
import threading
import time

db, limit_mb, cpu_limit = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
cols, rows = 100, 30

pid, master = pty.fork()
if pid == 0:  # child: run the TUI on the pty slave
    env = os.environ.copy()
    env.pop("ECO_DB", None)
    env.pop("ECO_JSON", None)
    env["ECO_SOUND"] = "0"  # never play real audio during the check
    env.setdefault("TERM", "xterm-256color")
    os.execvpe(sys.executable, [sys.executable, "-m", "manage_eco", "--db", db], env)

fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

screen = bytearray()
reading = True


def drain() -> None:
    while reading:
        try:
            ready, _, _ = select.select([master], [], [], 0.1)
        except (OSError, ValueError):
            break
        if not ready:
            continue
        try:
            chunk = os.read(master, 65536)
        except OSError:  # EIO once the child is gone
            break
        if not chunk:
            break
        screen.extend(chunk)
        if len(screen) > 2_000_000:
            del screen[:-1_000_000]


def sample():
    try:
        out = subprocess.run(
            ["ps", "-o", "%cpu=,rss=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
    except Exception:
        return None
    if len(out) < 2:
        return None
    try:
        return float(out[0]), int(out[1])
    except ValueError:
        return None


state = {"idle": False, "cpu": [], "rss_kb": 0, "stop": False}
lock = threading.Lock()


def monitor() -> None:
    while not state["stop"]:
        probe = sample()
        if probe:
            cpu, rss = probe
            with lock:
                state["rss_kb"] = max(state["rss_kb"], rss)
                if state["idle"]:
                    state["cpu"].append(cpu)
        time.sleep(0.25)


threading.Thread(target=drain, daemon=True).start()
threading.Thread(target=monitor, daemon=True).start()


def send(data: bytes, pause: float = 0.25) -> None:
    os.write(master, data)
    time.sleep(pause)


# Let the first frame settle, then save one expense: amount 50k, category "test".
time.sleep(1.0)
send(b"a")
send(b"50k")
send(b"\t")
send(b"test")
send(b"\r", 3.0)  # save + let the toast/sparkle animation finish

with lock:
    state["idle"] = True
time.sleep(3.0)  # sample CPU for 3 s while the TUI must be blocked on input
with lock:
    state["idle"] = False
    cpu_samples = list(state["cpu"])
    rss_kb = state["rss_kb"]

# Quit and wait for a clean exit.
try:
    os.write(master, b"q")
except OSError:
    pass
status = None
for _ in range(100):  # up to 10 s
    wpid, st = os.waitpid(pid, os.WNOHANG)
    if wpid == pid:
        status = st
        break
    time.sleep(0.1)
if status is None:
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)

state["stop"] = True
reading = False

try:
    conn = sqlite3.connect(db)
    saved = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()
except Exception:
    saved = -1

max_cpu = max(cpu_samples) if cpu_samples else -1.0
rss_mb = rss_kb / 1024.0
exit_code = os.WEXITSTATUS(status) if status is not None and os.WIFEXITED(status) else None

problems = []
if saved < 1:
    problems.append("no transaction saved (form submit failed?)")
if max_cpu < 0:
    problems.append("could not read CPU samples")
elif max_cpu > cpu_limit:
    problems.append("idle CPU %.1f%% > %.1f%%" % (max_cpu, cpu_limit))
if rss_kb <= 0:
    problems.append("could not read RSS")
elif rss_mb > limit_mb:
    problems.append("max RSS %.1f MB > %.0f MB" % (rss_mb, limit_mb))
if exit_code != 0:
    problems.append("exit code %r (expected 0)" % (exit_code,))

print("idlecheck: saved transactions: %d" % saved)
print("idlecheck: idle CPU samples (3s): %s -> max %.1f%% (limit %.1f%%)"
      % (["%.1f" % c for c in cpu_samples], max_cpu, cpu_limit))
print("idlecheck: max RSS: %.1f MB (limit %.0f MB)" % (rss_mb, limit_mb))
print("idlecheck: exit code: %r" % (exit_code,))

if problems:
    print("idlecheck: FAIL - " + "; ".join(problems), file=sys.stderr)
    tail = bytes(screen[-800:]).decode("utf-8", "replace")
    print("--- screen tail ---\n%s\n-------------------" % tail, file=sys.stderr)
    sys.exit(1)
print("idlecheck: OK")
PY
