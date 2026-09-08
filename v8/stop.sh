#!/usr/bin/env bash
# edp8 fleet — bring everything down (the launcher owns the shared services; design §22).
#   ./stop.sh            stop supervisor + bridge + mcp + pool + broker + board
#   ./stop.sh --only mcp stop just one
set -euo pipefail
V8="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$V8/.venv/Scripts/python.exe" ]; then PY="$V8/.venv/Scripts/python.exe"; else PY="$V8/.venv/bin/python"; fi
env_or() { local v="${!1:-}"; if [ -n "$v" ]; then echo "$v"; else echo "$2"; fi; }
export EDP8_HOME="$(env_or EDP8_HOME "$V8")"
export EDP8_RUN_DIR="$(env_or EDP8_RUN_DIR "$EDP8_HOME/.run")"
export PYTHONPATH="$V8/src"

ONLY=""; [ "${1:-}" = "--only" ] && ONLY="${2:-}"
ORDER=(supervisor bridge mcp pool broker board); [ -n "$ONLY" ] && ORDER=("$ONLY")

for svc in "${ORDER[@]}"; do
  rec="$("$PY" -c "import json;from edp8 import run_state;r=run_state.read('$svc');print(json.dumps(r) if r else '')" 2>/dev/null || true)"
  stopped=0
  if [ -n "$rec" ]; then
    pid="$(echo "$rec" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('pid') or '')")"
    port="$(echo "$rec" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('port') or '')")"
    # Scoped stop (c-c0f2ceea9b): kill only THIS fleet's OWN recorded pid. For the port-less bridge,
    # verify it is still a slack_bridge first, so a private fleet never kills the LIVE Slack bridge.
    # The old machine-global `pkill -f edp8.slack_bridge` (which killed the live one too) is gone.
    kill_ok=1
    if [ "$svc" = "bridge" ] && [ -n "$pid" ]; then
      "$PY" -c "import sys;from edp8 import run_state;sys.exit(0 if run_state.pid_cmdline_matches($pid,'edp8.slack_bridge') else 1)" 2>/dev/null || kill_ok=0
    fi
    # Windows pids are not MSYS pids under Git Bash: terminate through psutil, fall back to kill
    [ -n "$pid" ] && [ "$kill_ok" = "1" ] && { "$PY" -c "import psutil,sys; psutil.Process(int(sys.argv[1])).terminate()" "$pid" 2>/dev/null || kill "$pid" 2>/dev/null; } && stopped=1 || true
    [ -n "$port" ] && command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" 2>/dev/null && stopped=1 || true
    "$PY" -c "from edp8 import run_state; run_state.clear('$svc')" 2>/dev/null || true
  fi
  if [ "$stopped" = "1" ]; then echo "$svc stopped"; else echo "$svc not running"; fi
done
