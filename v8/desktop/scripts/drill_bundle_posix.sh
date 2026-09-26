#!/usr/bin/env bash
# S8 (s-6dcf78f803) Briefcase service re-entry drill, POSIX twin of drill_bundle_windows.ps1 (strategyhl-5af811e7bd §3
# spike on macOS and Linux, criterion c-eb38e8c949). Headless: only the CLI and the services run, no window.
#   bash v8/desktop/scripts/drill_bundle_posix.sh <bundle executable>
# macOS: "build/heronry/macos/app/Heronry Desktop.app/Contents/MacOS/Heronry Desktop"; Linux (installed deb): /usr/bin/heronry.
# Clean temp HOME, EDP*/HERONRY* scrubbed, free ports: version -> init -> doctor -> start -> every service is the
# bundle executable re-entered with --heronry-service <svc> -> /v1/health + /ui 200 -> stop -> nothing left.
set -u
EXE="$1"
T="$(mktemp -d)"; FAIL=0
check() { if [ "$1" = 0 ]; then echo "PASS  $2"; else echo "FAIL  $2"; FAIL=$((FAIL + 1)); fi; }
free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'; }
cmdline() { ps -o command= -p "$1" 2>/dev/null; }

for v in $(env | cut -d= -f1 | grep -E '^(EDP|HERONRY)'); do unset "$v"; done
unset CLAUDE_CONFIG_DIR PYTHONPATH VIRTUAL_ENV PYTHONHOME
export HOME="$T/home" HERONRY_NO_UPDATE_CHECK=1 HERONRY_NO_BROWSER=1 EDP8_EMBEDDER=none
export XDG_DATA_HOME="$T/home/.local/share" XDG_CONFIG_HOME="$T/home/.config" XDG_STATE_HOME="$T/home/.local/state"
mkdir -p "$HOME"
export EDP8_PORT="$(free_port)" EDP8_MCP_PORT="$(free_port)" EDP_POOL_PORT="$(free_port)" EDP_BROKER_PORT="$(free_port)"
cd "$T"
echo "bundle $EXE; temp HOME $T; ports board=$EDP8_PORT mcp=$EDP8_MCP_PORT pool=$EDP_POOL_PORT broker=$EDP_BROKER_PORT"
[ -x "$EXE" ]; check $? "the bundle executable exists"
case "$(uname)" in Darwin) file "$EXE"; lipo -archs "$EXE" 2>/dev/null | sed 's/^/   archs: /';; esac

echo "== heronry version"
OUT="$("$EXE" version 2>&1)"; RC=$?; echo "   $OUT"
[ $RC = 0 ] && echo "$OUT" | grep -Eq '^Heronry [0-9]+\.[0-9]+\.[0-9]+'; check $? "version prints 'Heronry <ver>'"
echo "== heronry init --harness claude"
"$EXE" init --harness claude 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "init exit 0"
echo "== heronry doctor"
OUT="$("$EXE" doctor 2>&1)"; echo "$OUT" | sed 's/^/   /'
echo "$OUT" | grep -q "Heronry doctor" && echo "$OUT" | grep -q "prerequisites"; check $? "doctor runs headless from the bundle"

echo "== heronry start"
"$EXE" start 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "start exit 0"
echo "== heronry status"
"$EXE" status 2>&1 | sed 's/^/   /'
JSON="$("$EXE" status --json 2>/dev/null)"
for svc in board mcp pool broker supervisor; do
  PID="$(printf '%s' "$JSON" | python3 -c "import json,sys; r=[x for x in json.load(sys.stdin) if x['service']=='$svc']; print((r[0].get('pid') or '') if r and r[0].get('state')=='up' else '')")"
  [ -n "$PID" ]; check $? "status: $svc up (pid ${PID:-none})"
  CMD="$(cmdline "$PID")"; echo "   $svc: $CMD"
  echo "$CMD" | grep -q -- "--heronry-service $svc"; check $? "re-entry: $svc runs as the bundle with --heronry-service $svc"
done
curl -fsS -o /dev/null "http://127.0.0.1:$EDP8_PORT/v1/health"; check $? "/v1/health returns 200"
curl -fsS -o /dev/null "http://127.0.0.1:$EDP8_PORT/ui/"; check $? "/ui/ (the prebuilt SPA) returns 200"

echo "== heronry stop"
"$EXE" stop --force 2>&1 | sed 's/^/   /'; check "${PIPESTATUS[0]}" "stop exit 0"
sleep 2
LEFT="$(ps -eo pid=,command= | grep -- '--heronry-service' | grep -v grep || true)"
[ -z "$LEFT" ]; check $? "stop leaves no --heronry-service process"
[ -n "$LEFT" ] && echo "$LEFT" | sed 's/^/   left: /'
for p in "$EDP8_PORT" "$EDP8_MCP_PORT" "$EDP_POOL_PORT" "$EDP_BROKER_PORT"; do
  ! python3 -c "import socket,sys; s=socket.socket(); sys.exit(0 if s.connect_ex(('127.0.0.1', $p)) == 0 else 1)"; check $? "port $p is free"
done
rm -rf "$T"
if [ "$FAIL" != 0 ]; then echo "RESULT: $FAIL check(s) FAILED"; exit 1; fi
echo "RESULT: all checks passed"
