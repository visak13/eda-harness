#!/usr/bin/env bash
# edp8 fleet launcher (Linux / macOS / Git Bash) - a thin wrapper over the one launcher,
# `heronry start|restart` (edp8.cli; S3 s-870e401942, design-e963c656f5 4.4).
#
#   ./start.sh                  bring the fleet up (skip what is already running) + the supervisor
#   ./start.sh --only mcp       start just one service
#   ./start.sh --restart board  restart ONE service (--force for the pool: it takes the seats offline)
#   ./start.sh --no-supervisor  do not leave the supervisor running
#
# This checkout is the home (dev mode: its .env, .data, .run) unless EDP_HOME says otherwise. Builds
# the web app first when dist is missing. Seats never start/stop shared services.
set -euo pipefail
V8="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$V8/.venv/Scripts/python.exe" ]; then PY="$V8/.venv/Scripts/python.exe"; else PY="$V8/.venv/bin/python"; fi
[ -x "$PY" ] || { echo "edp8: no venv at $PY - run: uv sync --directory v8" >&2; exit 2; }
if [ -z "${EDP_HOME:-}" ] && [ -z "${EDP8_HOME:-}" ]; then export EDP_HOME="$V8"; fi

RESTART=""; ONLY=""; FLAGS=()
while [ $# -gt 0 ]; do case "$1" in
  --restart) RESTART="$2"; shift 2;;
  --only) ONLY="$2"; shift 2;;
  --no-supervisor) FLAGS+=(--no-supervisor); shift;;
  --force) FLAGS+=(--force); shift;;
  *) echo "edp8: unknown argument '$1'" >&2; exit 5;;
esac; done

if [ ! -f "$V8/src/edp8/webapp/dist/index.html" ]; then
  echo "web/ dist missing - building the SPA (npm ci + build)..."
  npm --prefix "$V8/web" ci
  npm --prefix "$V8/web" run build
  [ -f "$V8/src/edp8/webapp/dist/index.html" ] || { echo "edp8: web build did not produce dist/index.html" >&2; exit 4; }
fi

if [ -n "$RESTART" ]; then
  exec "$PY" -m edp8.cli restart "$RESTART" ${FLAGS[@]+"${FLAGS[@]}"}
fi
exec "$PY" -m edp8.cli start ${ONLY:+"$ONLY"} ${FLAGS[@]+"${FLAGS[@]}"}
