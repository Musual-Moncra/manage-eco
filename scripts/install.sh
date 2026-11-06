#!/usr/bin/env bash
# Install an `eco` launcher into ~/.local/bin that runs this checkout (edits apply immediately).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="${ECO_BIN_DIR:-$HOME/.local/bin}"
PY="$(command -v python3)"
"$PY" -c "import rich" 2>/dev/null || "$PY" -m pip install --user "rich>=12"
mkdir -p "$BIN"
cat > "$BIN/eco" <<LAUNCHER
#!/bin/sh
PYTHONPATH="$ROOT\${PYTHONPATH:+:\$PYTHONPATH}" exec "$PY" -m manage_eco "\$@"
LAUNCHER
chmod +x "$BIN/eco"
echo "Đã cài: $BIN/eco  (gõ 'eco' để mở giao diện)"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Thêm vào PATH: export PATH=\"$BIN:\$PATH\"";; esac
