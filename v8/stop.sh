#!/usr/bin/env bash
# edp8 fleet - bring everything down: a thin wrapper over `heronry stop` (edp8.cli; S3 s-870e401942).
#   ./stop.sh               stop supervisor + bridge + mcp + pool + broker + board
#   ./stop.sh --only mcp    stop just one
#   --force                 needed when the pool has live seats (a pool stop takes them offline)
set -euo pipefail
V8="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$V8/.venv/Scripts/python.exe" ]; then PY="$V8/.venv/Scripts/python.exe"; else PY="$V8/.venv/bin/python"; fi
[ -x "$PY" ] || { echo "edp8: no venv at $PY - run: uv sync --directory v8" >&2; exit 2; }
if [ -z "${EDP_HOME:-}" ] && [ -z "${EDP8_HOME:-}" ]; then export EDP_HOME="$V8"; fi
ONLY=""; FLAGS=()
while [ $# -gt 0 ]; do case "$1" in
  --only) ONLY="$2"; shift 2;;
  --force) FLAGS+=(--force); shift;;
  *) echo "edp8: unknown argument '$1'" >&2; exit 5;;
esac; done
exec "$PY" -m edp8.cli stop ${ONLY:+"$ONLY"} ${FLAGS[@]+"${FLAGS[@]}"}
