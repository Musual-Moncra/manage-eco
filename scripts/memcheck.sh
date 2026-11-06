#!/usr/bin/env bash
# Measure max RSS of `eco --json dash`; fail if it exceeds 25 MB (SPEC v2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LIMIT_MB=25
TODAY="${ECO_TODAY:-2026-11-06}"
DB="$(mktemp -t eco-memcheck.XXXXXX)"
trap 'rm -f "$DB"' EXIT

cd "$ROOT"

# /usr/bin/time -l writes stats to stderr; keep the command's stdout off the
# capture so only the timing report is parsed.
STATS="$(/usr/bin/time -l python3 -m manage_eco --json --db "$DB" --today "$TODAY" dash 2>&1 >/dev/null)" || {
  echo "memcheck: FAIL - 'eco --json dash' exited non-zero" >&2
  exit 2
}

RSS_BYTES="$(printf '%s\n' "$STATS" | awk '/maximum resident set size/ {print $1; exit}')"
if [ -z "$RSS_BYTES" ]; then
  echo "memcheck: FAIL - could not read max RSS from /usr/bin/time -l" >&2
  exit 2
fi

RSS_MB="$(awk -v b="$RSS_BYTES" 'BEGIN {printf "%.2f", b / 1048576}')"
echo "eco --json dash max RSS: ${RSS_MB} MB (limit ${LIMIT_MB} MB)"

if awk -v r="$RSS_MB" -v l="$LIMIT_MB" 'BEGIN {exit !(r > l)}'; then
  echo "memcheck: FAIL - ${RSS_MB} MB exceeds ${LIMIT_MB} MB" >&2
  exit 1
fi

echo "memcheck: OK"
