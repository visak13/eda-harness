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

failed=0
for svc in "${ORDER[@]}"; do
  # One implementation for stop.ps1 and stop.sh (c-c0f2ceea9b): run_state.stop_service kills the
  # recorded pid tree + the port's listener, WAITS, and clears the record only when nothing is left;
  # "stopped" is printed only after the pids are verified gone.
  line="$("$PY" -c "
from edp8 import run_state
r = run_state.stop_service('$svc')
if not r['recorded']: print('not running')
elif r['still_running']: print('still running: $svc pid ' + ', '.join(map(str, r['still_running'])))
else: print('stopped' + (' (pid ' + ', '.join(map(str, r['killed'])) + ')' if r['killed'] else ' (already gone)'))
")"
  echo "$svc $line"
  case "$line" in "still running"*) failed=1;; esac
done
if [ "$failed" = "1" ]; then echo "edp8: some services are still running — see above" >&2; exit 1; fi
