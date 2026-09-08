#!/usr/bin/env bash
# edp8 fleet launcher (Linux / macOS / Git Bash). One command from one .env brings up board,
# broker, pool, MCP and the Slack bridge; idempotent; builds the web app when dist is missing;
# leaves a health supervisor running. Design §15/§22 (S17).
#
#   ./start.sh                 bring the fleet up (skip what is already running)
#   ./start.sh --restart board restart ONE service through the launcher (records service_restarted)
#   ./start.sh --only mcp       (re)start just one service
#   ./start.sh --no-supervisor  do not leave the supervisor running
#
# Seats never start/stop shared services (design §22) — that is the human's or this launcher's job.
set -euo pipefail
V8="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$V8")"

RESTART=""; ONLY=""; NO_SUPERVISOR=0
while [ $# -gt 0 ]; do case "$1" in
  --restart) RESTART="$2"; shift 2;;
  --only) ONLY="$2"; shift 2;;
  --no-supervisor) NO_SUPERVISOR=1; shift;;
  *) echo "edp8: unknown argument '$1'" >&2; exit 5;;
esac; done

# ── one .env (real environment wins) ─────────────────────────────────────────────────────────────
if [ -f "$V8/.env" ]; then
  while IFS= read -r line; do
    line="${line%%$'\r'}"; case "$line" in ''|\#*) continue;; esac
    key="${line%%=*}"; val="${line#*=}"; key="$(echo "$key" | xargs)"
    val="${val%%[[:space:]]#*}"; val="${val%"${val##*[![:space:]]}"}"  # drop an inline comment + trailing blanks
    [ -z "${!key:-}" ] && export "$key=$val" || true
  done < "$V8/.env"
fi

env_or() { local v="${!1:-}"; if [ -n "$v" ]; then echo "$v"; else echo "$2"; fi; }
HOMEDIR="$(env_or EDP8_HOME "$V8")"
DATA="$(env_or EDP8_DATA "$HOMEDIR/.data")"
RUN="$(env_or EDP8_RUN_DIR "$HOMEDIR/.run")"
BOARD_PORT="$(env_or EDP8_PORT 9400)"
BROKER_PORT="$(env_or EDP_BROKER_PORT 9300)"
POOL_PORT="$(env_or EDP_POOL_PORT 9301)"
MCP_PORT="$(env_or EDP8_MCP_PORT 9402)"
ADMIN="$(env_or EDP8_ADMIN_TOKEN dev)"
OWNER="$(env_or EDP8_OWNER owner)"
PUBLIC="$(env_or EDP8_PUBLIC_URL '')"
if [ -n "$PUBLIC" ]; then BIND="$(env_or EDP8_HOST 0.0.0.0)"; else BIND="$(env_or EDP8_HOST 127.0.0.1)"; fi
export EDP8_HOME="$HOMEDIR" EDP8_RUN_DIR="$RUN"
mkdir -p "$DATA" "$RUN"

# venv python: Scripts on Git Bash/Windows, bin elsewhere
if [ -x "$V8/.venv/Scripts/python.exe" ]; then PY="$V8/.venv/Scripts/python.exe"; else PY="$V8/.venv/bin/python"; fi

# ── prerequisites: a missing tool is a one-line plain message + non-zero exit ─────────────────────
need() { command -v "$1" >/dev/null 2>&1 || { echo "edp8: '$1' is not on PATH. Install it (see README) and re-run ./start.sh" >&2; exit 3; }; }
need uv; need node; need npm

probe() { curl -fsS --max-time 2 "http://127.0.0.1:$1$2" >/dev/null 2>&1; }
# Record the REAL process pid, not bash's `$!` — on Git Bash/MSYS `$!` is the shim, not the Windows
# child (S17 c-c0f2ceea9b). For a ported service we record the pid owning the listener; for the
# port-less bridge, the newest edp8.slack_bridge; both fall back to the passed pid when psutil can't.
write_state() { # $1 svc  $2 fallback-pid  $3 port (empty for the bridge)
  "$PY" - "$1" "${2:-}" "${3:-}" 2>/dev/null <<'PYEOF' || true
import sys
from edp8 import run_state
svc, fallback, port = sys.argv[1], sys.argv[2], sys.argv[3]
port_i = int(port) if port else None
pid = run_state.listener_pid(port_i) if port_i else run_state.process_pid_matching("edp8.slack_bridge")
if not pid:
    try: pid = int(fallback)
    except (ValueError, TypeError): pid = 0
run_state.write(svc, pid=pid, port=port_i, git_rev=run_state.git_rev())
PYEOF
}

build_web() {
  [ -f "$V8/src/edp8/webapp/dist/index.html" ] && return 0
  echo "web/ dist missing — building the SPA (npm ci + build)..."
  npm --prefix "$V8/web" ci
  npm --prefix "$V8/web" run build
  [ -f "$V8/src/edp8/webapp/dist/index.html" ] || { echo "edp8: web build did not produce dist/index.html" >&2; exit 4; }
}

start_board() {
  probe "$BOARD_PORT" /v1/health && { write_state board "" "$BOARD_PORT"; echo "board    already running on :$BOARD_PORT"; return; }
  EDP8_HOST="$BIND" EDP8_PORT="$BOARD_PORT" EDP8_ADMIN_TOKEN="$ADMIN" EDP8_HOME="$HOMEDIR" \
    EDP8_DB="$DATA/edp8.db" EDP_POOL_URL="http://127.0.0.1:$POOL_PORT" EDP_BROKER_URL="http://127.0.0.1:$BROKER_PORT" \
    nohup uv run --directory "$HOMEDIR" edp8-board >"$DATA/board.log" 2>"$DATA/board.err" &
  local pid=$!; for _ in $(seq 1 60); do probe "$BOARD_PORT" /v1/health && break; sleep 0.25; done
  write_state board "$pid" "$BOARD_PORT"
  uv run --directory "$HOMEDIR" python -m edp8.bootstrap --board "http://127.0.0.1:$BOARD_PORT" --admin "$ADMIN" --owner "$OWNER" >/dev/null 2>&1 || true
  echo "board    up   pid $pid  http://127.0.0.1:$BOARD_PORT  (SPA: /app)"
}

start_broker() {
  probe "$BROKER_PORT" /v1/health && { write_state broker "" "$BROKER_PORT"; echo "broker   already running on :$BROKER_PORT"; return; }
  [ -d "$ROOT/edp-broker" ] || { echo "broker   skipped (no $ROOT/edp-broker)"; return; }
  mkdir -p "$DATA/broker-data"
  EDP_BROKER_HOST="$BIND" EDP_BROKER_PORT="$BROKER_PORT" EDP_BROKER_DATA="$DATA/broker-data" \
    nohup uv run --directory "$ROOT/edp-broker" python -m edp_broker.main >"$DATA/broker.log" 2>"$DATA/broker.err" &
  local pid=$!; for _ in $(seq 1 40); do probe "$BROKER_PORT" /v1/health && break; sleep 0.25; done
  write_state broker "$pid" "$BROKER_PORT"
  echo "broker   up   pid $pid  http://127.0.0.1:$BROKER_PORT"
}

start_pool() {
  probe "$POOL_PORT" /v1/health && { write_state pool "" "$POOL_PORT"; echo "pool     already running on :$POOL_PORT"; return; }
  local ppy="$ROOT/edp-pool/.venv/bin/python"; [ -x "$ppy" ] || ppy="$ROOT/edp-pool/.venv/Scripts/python.exe"
  [ -x "$ppy" ] || { echo "pool     skipped (no edp-pool venv)"; return; }
  mkdir -p "$DATA/pool-logs"
  EDP_POOL_AGENT_HOME="$HOMEDIR" EDP_POOL_HOST=127.0.0.1 EDP_POOL_PORT="$POOL_PORT" \
    EDP_POOL_LOG_DIR="$DATA/pool-logs" EDP_POOL_STATE="$DATA/pool-logs/pool-state.json" \
    EDP_SPAWN_MODE=monitor EDP_SKIP_PERMISSIONS=1 CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1 \
    EDP8_BOARD_URL="http://127.0.0.1:$BOARD_PORT" EDP_POOL_URL="http://127.0.0.1:$POOL_PORT" EDP_BROKER_URL="http://127.0.0.1:$BROKER_PORT" \
    nohup "$ppy" -m edp_pool.main >"$DATA/pool.log" 2>"$DATA/pool.err" &
  local pid=$!; for _ in $(seq 1 60); do probe "$POOL_PORT" /v1/health && break; sleep 0.3; done
  write_state pool "$pid" "$POOL_PORT"
  echo "pool     up   pid $pid  http://127.0.0.1:$POOL_PORT"
}

start_mcp() {
  probe "$MCP_PORT" /healthz && { write_state mcp "" "$MCP_PORT"; echo "mcp      already running on :$MCP_PORT"; return; }
  EDP8_HOME="$HOMEDIR" EDP8_BOARD_URL="http://127.0.0.1:$BOARD_PORT" EDP_POOL_URL="http://127.0.0.1:$POOL_PORT" \
    EDP_BROKER_URL="http://127.0.0.1:$BROKER_PORT" EDP8_MCP_PORT="$MCP_PORT" EDP8_MCP_HOST=127.0.0.1 PYTHONPATH="$V8/src" \
    nohup "$PY" -m edp8.mcp_server >"$DATA/mcp.log" 2>"$DATA/mcp.err" &
  local pid=$!; for _ in $(seq 1 40); do probe "$MCP_PORT" /healthz && break; sleep 0.25; done
  write_state mcp "$pid" "$MCP_PORT"
  echo "mcp      up   pid $pid  http://127.0.0.1:$MCP_PORT/mcp/<role>"
}

start_bridge() {
  [ -f "$V8/slack_map.json" ] || { echo "bridge   skipped (no slack_map.json)"; return; }
  # Scoped detection (c-c0f2ceea9b): adopt ONLY the bridge pid THIS fleet recorded in its run dir,
  # and only if it is still a live slack_bridge — never a machine-global `pgrep`, which would let a
  # private fleet adopt (and stop.sh later kill) the LIVE Slack bridge. pgrep/fuser are also absent
  # on this Git Bash, so the old scan was always false and started a duplicate every run.
  local rec_pid; rec_pid="$("$PY" -c "from edp8 import run_state; r=run_state.read('bridge'); print((r or {}).get('pid') or '')" 2>/dev/null || true)"
  if [ -n "$rec_pid" ] && "$PY" -c "import sys;from edp8 import run_state;sys.exit(0 if run_state.pid_cmdline_matches($rec_pid,'edp8.slack_bridge') else 1)" 2>/dev/null; then
    echo "bridge   already running pid $rec_pid"; return
  fi
  local pub=""; [ -n "$PUBLIC" ] && pub="$PUBLIC"
  EDP8_HOME="$HOMEDIR" EDP_BROKER_URL="http://127.0.0.1:$BROKER_PORT" EDP8_PUBLIC_URL="$pub" PYTHONPATH="$V8/src" \
    nohup "$PY" -m edp8.slack_bridge >"$DATA/bridge.log" 2>"$DATA/bridge.err" &
  local pid=$!; write_state bridge "$pid" ""
  echo "bridge   up   pid $pid  (Slack doorbell)"
}

start_supervisor() {
  [ "$NO_SUPERVISOR" = "1" ] && return
  local st; st="$("$PY" -c "from edp8 import run_state; r=run_state.read('supervisor'); print(r['pid'] if r else '')" 2>/dev/null || true)"
  [ -n "$st" ] && { echo "supervisor already running pid $st"; return; }
  EDP8_BOARD_URL="http://127.0.0.1:$BOARD_PORT" EDP8_ADMIN_TOKEN="$ADMIN" PYTHONPATH="$V8/src" \
    nohup "$PY" -m edp8.supervisor >"$DATA/supervisor.log" 2>"$DATA/supervisor.err" &
  echo "supervisor up pid $!  (probes every 15s; restarts through this launcher)"
}

svc_fn() { case "$1" in board) start_board;; broker) start_broker;; pool) start_pool;; mcp) start_mcp;; bridge) start_bridge;;
  *) echo "edp8: unknown service '$1' (board|broker|pool|mcp|bridge)" >&2; exit 5;; esac; }

stop_one() {
  local svc="$1" rec pid port
  rec="$("$PY" -c "import json;from edp8 import run_state;r=run_state.read('$svc');print(json.dumps(r) if r else '')" 2>/dev/null || true)"
  [ -z "$rec" ] && return
  pid="$(echo "$rec" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('pid') or '')")"
  port="$(echo "$rec" | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('port') or '')")"
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  [ -n "$port" ] && { command -v fuser >/dev/null 2>&1 && fuser -k "${port}/tcp" 2>/dev/null || true; }
}

restart_one() {
  local svc="$1" by="${USER:-human}"
  echo "restarting $svc (by $by)..."; stop_one "$svc"; sleep 0.5; svc_fn "$svc"
  "$PY" -c "from edp8 import run_state; run_state.mark_restart('$svc','manual restart via start.sh', git_rev=run_state.git_rev())" 2>/dev/null || true
  local rev; rev="$("$PY" -c "from edp8 import run_state;print(run_state.git_rev())" 2>/dev/null || echo unknown)"
  curl -fsS --max-time 10 -X POST "http://127.0.0.1:$BOARD_PORT/v1/service_event" \
    -H "X-Admin: $ADMIN" -H "Content-Type: application/json" \
    -d "{\"service\":\"$svc\",\"reason\":\"manual restart via start.sh --restart\",\"by\":\"$by\",\"git_rev\":\"$rev\"}" >/dev/null 2>&1 \
    && echo "recorded service_restarted {$svc, by=$by}" || echo "note: could not record service_restarted"
}

# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────
if [ -n "$RESTART" ]; then restart_one "$RESTART"; exit 0; fi
build_web
if [ -n "$ONLY" ]; then svc_fn "$ONLY"; else
  for s in board broker pool mcp bridge; do svc_fn "$s"; done
  start_supervisor
fi
echo ""; echo "fleet state (edp8 status):"
PYTHONPATH="$V8/src" EDP8_RUN_DIR="$RUN" "$PY" -m edp8.cli status
[ -n "$PUBLIC" ] && echo "" && echo "public reach: $PUBLIC  (board bound $BIND; TLS at your reverse proxy — see README)"
exit 0
