#!/usr/bin/env bash
# S3 (s-870e401942) evidence drill, POSIX twin of drill_install_windows.ps1: install.sh in a CLEAN temp
# HOME, then the installed `heronry` end to end (criterion c-5fb36ba3db). Run by .github/workflows/install.yml
# on Linux and macOS; safe anywhere (temp HOME, uv dirs in temp, EDP*/HERONRY* scrubbed, free ports).
#   bash v8/scripts/drill_install_posix.sh <release-dir with the four wheels + SHA256SUMS>
set -u
REL="$(cd "$1" && pwd)"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
T="$(mktemp -d)"; FAIL=0
check() { if [ "$1" = 0 ]; then echo "PASS  $2"; else echo "FAIL  $2"; FAIL=$((FAIL + 1)); fi; }
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }

for v in $(env | cut -d= -f1 | grep -E '^(EDP|HERONRY|UV_)'); do unset "$v"; done
unset CLAUDE_CONFIG_DIR PYTHONPATH VIRTUAL_ENV PYTHONHOME
export HOME="$T/home" UV_TOOL_DIR="$T/uv-tools" UV_TOOL_BIN_DIR="$T/bin" UV_PYTHON_INSTALL_DIR="$T/uv-python"
export UV_CACHE_DIR="$T/uv-cache" UV_NO_MODIFY_PATH=1 HERONRY_NO_UPDATE_CHECK=1 EDP8_EMBEDDER=none
export XDG_DATA_HOME="$T/home/.local/share" XDG_CONFIG_HOME="$T/home/.config" XDG_STATE_HOME="$T/home/.local/state"
mkdir -p "$HOME"
# uv off PATH, so install.sh installs (and verifies) its pinned uv
NEWPATH=""; IFS=:; for d in $PATH; do [ -x "$d/uv" ] || NEWPATH="$NEWPATH${NEWPATH:+:}$d"; done; unset IFS
export PATH="$NEWPATH"
export EDP8_PORT="$(free_port)" EDP8_MCP_PORT="$(free_port)" EDP_POOL_PORT="$(free_port)" EDP_BROKER_PORT="$(free_port)"
cd "$T"
echo "temp HOME $T; ports board=$EDP8_PORT mcp=$EDP8_MCP_PORT pool=$EDP_POOL_PORT broker=$EDP_BROKER_PORT"

echo "== install.sh (clean HOME)"
sh "$ROOT/install.sh" --release-url "$REL" --no-modify-path 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "install.sh exit 0"
[ -x "$HOME/.local/bin/uv" ]; check $? "the pinned uv was installed into the temp HOME"
H="$T/bin/heronry"; [ -x "$H" ]; check $? "heronry in the temp tool bin dir"
echo "== install.sh again (idempotent)"
OUT="$(sh "$ROOT/install.sh" --release-url "$REL" --no-modify-path 2>&1)"; RC=$?; echo "$OUT" | sed 's/^/   /'
[ $RC = 0 ] && echo "$OUT" | grep -q "already installed"; check $? "a second run is a no-op"
echo "== install.sh with a tampered wheel"
mkdir "$T/bad" && cp "$REL"/* "$T/bad/" && printf x >> "$(ls "$T"/bad/edp_pool-*.whl)"
OUT="$(sh "$ROOT/install.sh" --release-url "$T/bad" --no-modify-path --force 2>&1)"; RC=$?; echo "$OUT" | tail -1 | sed 's/^/   /'
[ $RC != 0 ] && echo "$OUT" | grep -q "SHA-256 mismatch"; check $? "a tampered wheel is refused"

echo "== heronry init (no harness)"
OUT="$("$H" init 2>&1)"; RC=$?; echo "$OUT" | sed 's/^/   /'
[ $RC = 2 ] && echo "$OUT" | grep -q "no harness selected"; check $? "init with no harness refuses"
echo "== heronry init --harness claude (codex-less)"
OUT="$("$H" init --harness claude 2>&1)"; RC=$?; echo "$OUT" | sed 's/^/   /'
[ $RC = 0 ] && echo "$OUT" | grep -q "NOTICE:" && echo "$OUT" | grep -q "Fable"; check $? "codex-less init prints the Fable notice"
echo "$OUT" | grep -qF "$ROOT"; [ $? != 0 ]; check $? "the install home is outside the repo"

# The stub harness (edp-pool/tests/fixtures/stub_harness.py) stands in for claude: copied under $T and
# run by the tool's own python, so the leftover-process check below also covers the seat and its grandchild.
TOOLPY="$(ls "$UV_TOOL_DIR"/edp8/bin/python 2>/dev/null | head -1)"
cp "$ROOT/edp-pool/tests/fixtures/stub_harness.py" "$T/stub_harness.py"
printf '#!/bin/sh\nexec "%s" "%s" "$@"\n' "${TOOLPY:-python3}" "$T/stub_harness.py" > "$T/claude-stub" && chmod 755 "$T/claude-stub"
export EDP_CLAUDE_BIN="$T/claude-stub" EDP_SPAWN_MODE=headless EDP_SHADOW=0
echo "== heronry start"
"$H" start 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "start exit 0"
echo "== heronry status"
"$H" status 2>&1 | sed 's/^/   /'
"$H" status --json > "$T/status.json"
for svc in board mcp pool broker; do
  python3 - "$T/status.json" "$svc" <<'PY'
import json, re, sys
rows = [r for r in json.load(open(sys.argv[1])) if r.get("service") == sys.argv[2]]
ok = rows and rows[0].get("state") == "up" and rows[0].get("pid") and re.match(r"^http://127\.0\.0\.1:\d+$", rows[0].get("url") or "")
sys.exit(0 if ok else 1)
PY
  check $? "status: $svc up with a pid and a loopback url"
done
echo "== heronry start (again)"
OUT="$("$H" start 2>&1)"; echo "$OUT" | sed 's/^/   /'
[ "$(echo "$OUT" | grep -cE '^(board|mcp|pool|broker) +already running')" = 4 ]; check $? "a second start says already running"
CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$EDP8_PORT/v1/health")"
[ "$CODE" = 200 ]; check $? "/v1/health returns 200 (got $CODE)"
UI="$(curl -sL "http://127.0.0.1:$EDP8_PORT/ui/")"
echo "$UI" | grep -q "<title>Heronry"; check $? "/ui serves the Heronry SPA"
echo "== stub seat through the installed pool (S9 install smoke)"
POOL="http://127.0.0.1:$EDP_POOL_PORT"
R="$(curl -s -X POST -H 'Content-Type: application/json' -d '{"role":"worker","handle":"stub:smoke","mode":"headless"}' --max-time 90 "$POOL/v1/spawn")"
echo "   spawn: $R"
echo "$R" | grep -q '"session_id"'; check $? "the pool spawned a stub seat"
ST=""; for _ in $(seq 1 60); do
  ST="$(curl -s "$POOL/v1/liveness/stub:smoke" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("state",""))' 2>/dev/null)"
  case "$ST" in alive|active|busy|idle) break;; esac; sleep 0.5
done
case "$ST" in alive|active|busy|idle) true;; *) false;; esac; check $? "the stub seat is live (state=$ST)"
curl -s -X POST --max-time 60 "$POOL/v1/reap/stub:smoke" | sed 's/^/   reap: /'; echo
echo "== heronry stop"
"$H" stop --force 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "stop exit 0"
sleep 2
# -ww: never let ps cut command= short (run 36324602815: 0 found on macOS while all four ports still answered)
LEFT="$(ps -ww -eo pid=,command= | grep -F "$T" | grep -v grep | wc -l | tr -d ' ')"
[ "$LEFT" = 0 ]; check $? "stop leaves no process running from the install ($LEFT found)"
for p in "$EDP8_PORT" "$EDP8_MCP_PORT" "$EDP_POOL_PORT" "$EDP_BROKER_PORT"; do
  ! curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$p/"; check $? "port $p is free"
done
if [ $FAIL != 0 ]; then  # the service logs live in the temp HOME, gone after this run: print their tails
  echo "== python/heronry processes still running"
  ps -ww -eo pid=,ppid=,comm=,command= | grep -E "python|heronry|edp" | grep -v grep | sed 's/^/   /'
  find "$T/home" -name '*.log' -type f 2>/dev/null | sort | while read -r f; do
    echo "== tail of ${f#$T/}"; tail -n 60 "$f" | sed 's/^/   /'
  done
fi
[ "${KEEP:-0}" = 1 ] || rm -rf "$T"
if [ $FAIL != 0 ]; then echo "RESULT: $FAIL check(s) FAILED"; exit 1; fi
echo "RESULT: all checks passed"
