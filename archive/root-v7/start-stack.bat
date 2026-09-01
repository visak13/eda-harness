@echo off
rem ============================================================================
rem  RETIRED (v7 ruling, 2026-08-05): this legacy mixed-fleet launcher armed
rem  the opencode sol fleet by default (EDP_OPENCODE_ROLES below), which is
rem  now frozen as an experiment record. Use start-stack-claude.bat.
rem  This script exits without starting anything.
rem ============================================================================
echo RETIRED: use start-stack-claude.bat (the opencode fleet is frozen).
exit /b 1
rem ============================================================================
rem  eda-base3 stack: broker (:9300) + pool (:9301) + RuleSupervisor
rem
rem  Thin wrapper over `python -m edp_claude.stack_launcher`, which owns the
rem  real lifecycle: dependency-ordered, health-gated startup (broker -> pool
rem  -> supervisor), one tracked PID per service, and graceful->hard teardown
rem  of ONLY those tracked PIDs on Ctrl-C or failure (never a name-wide kill).
rem  Each service runs from its own project dir with its own .venv; the
rem  launcher threads EDP_BROKER_URL / EDP_POOL_URL / EDP_AGENT_HOME through
rem  so broker, pool, supervisor and all rule drivers agree.
rem
rem  Usage (from the eda-base3 root):
rem    start-stack.bat                    broker + pool + supervisor
rem    start-stack.bat --no-supervisor    broker + pool only
rem    start-stack.bat --max-runtime 30   bring up, hold 30s, tear down
rem  Ctrl-C stops all three cleanly.
rem ============================================================================
setlocal

set "ROOT=%~dp0"
set "CLAUDE_DIR=%ROOT%claude"
set "PY=%CLAUDE_DIR%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem P2 tiered storage (2026-06-10): write-side ON. Recipe/plan saves move
rem long texts to sidecar files; reads hydrate them back transparently.
rem (The MCP servers get this from .mcp.json env; setting it here keeps the
rem stack's own processes consistent.)
set "EDP_TIER_WRITE=1"

rem DESIGN-v7 1.2 capacity model ? three knobs, set EXPLICITLY so the live
rem stack never silently rides a code default. EDP_MAX_WORKERS/PLANNERS are
rem per-role throughput caps; EDP_MAX_TOTAL_SHELLS is the true host-resource
rem guard (every live shell is a full claude process). role=reviewer is
rem exempt from the per-role caps and counts under the total only.
set "EDP_MAX_WORKERS=6"
set "EDP_MAX_PLANNERS=4"
set "EDP_MAX_TOTAL_SHELLS=10"

rem DESIGN-v7 P0 ? role scoping is ENFORCED (a shell's MCP registry is
rem filtered to its role's toolset; off-set tools are absent, not warned).
rem Set explicitly so the live stack states its mode; "warn" is the
rem diagnostic opt-out if a run needs to observe violations instead.
set "EDP_ROLE_SCOPE=enforce"

rem MODEL TIERING (USER RULING 2026-07-16) - Opus is the default for every role;
rem Sonnet is opt-in only, and the Sonnet the planner opts into is 4.6 (Sonnet 5
rem is token-hungry). Set explicitly so the stack states which Sonnet it tiers to
rem rather than riding the code default. See docs/design/MODEL-TIERING-BENCHMARK.md
rem section 9.
set "EDP_WORKER_SONNET_MODEL=claude-sonnet-4-6"

rem PORT-OPENCODE (2026-07-18) - mixed-fleet backend. Roles listed here are
rem spawned as OPENCODE/gpt-5.6 shells (the Sol fleet) instead of Claude
rem shells; empty = 100% Claude, zero behavior change. Proven: "worker"
rem (M1 live round trip). See claude/docs/design/PORT-OPENCODE.md.
rem Full sol fleet (every spawned role on opencode/gpt-5.6; the neuron seat
rem is launch-opencode-neuron.bat). Trim the list to mix Claude back in.
set "EDP_OPENCODE_ROLES=worker,planner,reviewer,specialist,consult,curiosity,goal_keeper,pattern_observer"

rem Visible consoles for opencode shells (operator ruling 2026-07-19): the
rem listed roles open a real console window streaming their turn, like the
rem claude harness's monitor spawns. "*" = watch EVERY role; "" = all
rem headless (panel + logs only).
set "EDP_OPENCODE_MONITOR_ROLES=consult,curiosity,specialist"

rem Heartbeat CRON = 30-min SAFETY NET at every level (operator ruling
rem 2026-07-20: monitor is the driving force, cron never burns tokens on
rem a short leash). The 5s watchdog/SSE monitor planes are FREE (no LLM
rem call); only an actual wake spends tokens.
set "EDP_PARKED_HEARTBEAT_SECS=1800"
set "EDP_TURN_TIMEOUT_SECS=2400"

rem Spawn caps (operator ruling 2026-07-19: workers 3, planners 1 for now).
rem Runtime-adjustable in the panel (Spawn config -> Spawn caps); a panel
rem override persists across restarts and WINS over these env values.
set "EDP_MAX_WORKERS=3"
set "EDP_MAX_PLANNERS=1"

rem Role-model mapping (operator ruling 2026-07-19): neuron/reviewer/
rem consult and all judgment seats = sol, planner = terra, worker = terra (luna retired 2026-07-21: quality).
rem NEVER a -fast variant (the fleet config lists only sol/terra/luna).
rem This override makes the engine's Sonnet-class worker tiers land on
rem luna too, matching the worker wrapper.
set "EDP_OPENCODE_MODEL_SONNET=openai/gpt-5.6-terra"

rem SOL BRIDGE (v7 follow-up, 2026-07-16). Visual/3D/image assets go through Sol
rem (GPT) via the Codex CLI: workers call sol_author_asset, consults call
rem sol_consult. NO API key is needed - the Codex CLI is already logged in with
rem ChatGPT, and Sol spend bills that plan's quota. The engine auto-resolves the
rem correct codex.exe (the copy with codex-code-mode-host.exe beside it); these
rem knobs are OPTIONAL overrides:
rem   set "EDP_SOL_CODEX_BIN=C:\...\codex.exe"   (pin the binary explicitly)
rem   set "EDP_SOL_TIMEOUT_SECS=900"             (per-turn wall-clock ceiling)
rem   set "EDP_SOL_CODE_ROOTS=C:\path;C:\path2"  (extra code trees Sol may NOT write into)

rem PANEL APPROVALS (v7 follow-up). When 1, every pool-spawned shell parks its
rem permission-worthy tool calls (Bash/PowerShell/Write/Edit) on the panel's
rem Approvals view for ~50s before falling back to its own console prompt ?
rem so the floating panel is the one place you approve from. Fail-open: the
rem panel being closed/ignored only means the console prompt appears as today.
set "EDP_PANEL_APPROVALS=0"

rem Spawn mode for shells the POOL launches (planners/workers/curiosity...).
rem "monitor" = each shell gets a VISIBLE console window you can watch.
rem "headless" = drained ConPTY, output goes to edp-pool\.pool-logs\*.log
rem only. The pool defaults to headless when this is unset ? which is why
rem shells "disappeared" after moving to this launcher. Per-spawn override
rem via the spawn request body still wins over this.
set "EDP_SPAWN_MODE=monitor"

rem AUTONOMY in monitor mode. Headless shells always launch with
rem --dangerously-skip-permissions (no window to click-approve); MONITOR
rem shells launch WITHOUT it unless this is set ? meaning every visible
rem planner/worker would freeze at its first permission prompt waiting for
rem a human click. Set 1 for autonomous runs; unset/0 if you deliberately
rem want to click-approve each tool use while watching.
set "EDP_SKIP_PERMISSIONS=0"

cd /d "%CLAUDE_DIR%"
"%PY%" -m edp_claude.stack_launcher %*
if errorlevel 1 (
  echo.
  echo [stack] launcher exited with error %errorlevel% - read the output
  echo         above. Most common cause: a previous stack generation still
  echo         holds the ports - check .logs\stack-pids.json.
  pause
)

endlocal
