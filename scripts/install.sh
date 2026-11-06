#!/usr/bin/env bash
# Install an `eco` launcher that runs this checkout (edits apply immediately).
# Prefers /usr/local/bin (in /etc/paths → every shell/terminal app sees it), else ~/.local/bin.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3)"
if [ -n "${ECO_BIN_DIR:-}" ]; then BIN="$ECO_BIN_DIR"
elif [ -w /usr/local/bin ]; then BIN=/usr/local/bin
else BIN="$HOME/.local/bin"; fi
"$PY" -c "import rich" 2>/dev/null || "$PY" -m pip install --user "rich>=12"
mkdir -p "$BIN"
cat > "$BIN/eco" <<LAUNCHER
#!/bin/sh
# Manage Eco launcher (scripts/install.sh)
PYTHONIOENCODING=utf-8 PYTHONPATH="$ROOT\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m manage_eco "\$@"
LAUNCHER
chmod +x "$BIN/eco"
echo "Đã cài: $BIN/eco  (gõ 'eco' để mở giao diện)"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Thêm vào PATH: export PATH=\"$BIN:\$PATH\"";; esac
