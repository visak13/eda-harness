@echo off
rem ============================================================================
rem  RETIRED (v7 ruling, 2026-08-05): the opencode/sol fleet is frozen as an
rem  experiment record. Sol (GPT-5.6) now joins via the in-shell provider
rem  bridge on the Claude stack — use start-stack-claude.bat.
rem  This script exits without starting anything. See plan: eda v7.
rem ============================================================================
echo RETIRED: sol fleet is frozen. Use start-stack-claude.bat (Sol joins via the bridge).
exit /b 1
rem ============================================================================
rem  SOL / GPT SEAT stack: broker (:9300) + pool (:9301) + RuleSupervisor
rem
rem  Every spawned role is an OPENCODE shell on gpt-5.6 (the Sol fleet). Pair
rem  this with the opencode neuron seat (launch-opencode-neuron.bat, which
rem  needs the neuron server on :4747).
rem
rem  For the Claude Code fleet use start-stack-claude.bat instead. The two
rem  launchers are deliberately INDEPENDENT and self-contained: neither reads
rem  nor edits the other, so switching seats is "stop the stack, start the
rem  other one" with no hand-editing. Only ONE may run at a time (both bind
rem  :9300/:9301).
rem
rem  This is the behavioral equivalent of the original start-stack.bat, with
rem  the audited fixes noted inline. Audited 2026-07-21.
rem
rem  Usage (from the eda-base3 root):
rem    start-stack-sol.bat                    broker + pool + supervisor
rem    start-stack-sol.bat --no-supervisor    broker + pool only
rem    start-stack-sol.bat --max-runtime 30   bring up, hold 30s, tear down
rem  Ctrl-C stops all three cleanly (tracked PIDs only, never a name-wide kill).
rem ============================================================================
setlocal

set "ROOT=%~dp0"
set "CLAUDE_DIR=%ROOT%claude"
set "PY=%CLAUDE_DIR%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem --- FLEET -----------------------------------------------------------------
rem Every role routed to the opencode/gpt-5.6 backend. Trim this list to mix
rem Claude back in per-role (a role NOT listed falls through to the Claude PTY
rem spawner, which is always constructed).
set "EDP_OPENCODE_ROLES=worker,planner,reviewer,specialist,consult,curiosity,goal_keeper,pattern_observer"

rem Role-model mapping (operator ruling 2026-07-19, luna retired 2026-07-21 on
rem quality): judgment seats = sol, planner/worker = terra. NEVER a -fast
rem variant. This override makes the engine's Sonnet-class tiers land on terra.
set "EDP_OPENCODE_MODEL_SONNET=openai/gpt-5.6-terra"

rem DO NOT SET EDP_OPENCODE_MODEL_OPUS. Leaving it unset lets each role's
rem wrapper frontmatter pin its own model; setting it overrides those per-role
rem pins for every Opus-tier spawn - the exact bug fixed 2026-07-20.

rem Kept as a CLAUDE model id ON PURPOSE, even on this stack. The engine's tier
rem table only speaks Claude ids and the opencode backend translates them
rem (map_model matches on the substring "sonnet" and returns the gpt
rem equivalent). A gpt id here only "works" via a passthrough branch and breaks
rem the moment this stack spawns a Claude role.
set "EDP_WORKER_SONNET_MODEL=claude-sonnet-4-6"

rem --- CONSOLES + PERMISSIONS ------------------------------------------------
rem Visible consoles for every spawned shell.
set "EDP_SPAWN_MODE=monitor"

rem NOTE: EDP_OPENCODE_MONITOR_ROLES is deliberately NOT set. It is DEAD while
rem EDP_SPAWN_MODE=monitor - the launcher computes
rem   monitor = (mode == "monitor" or role in monitor_roles())
rem so the mode alone already gives every role a window. The old three-role
rem list in start-stack.bat had no effect. Set EDP_SPAWN_MODE=headless first
rem if you want that list to mean anything.

rem EDP_SKIP_PERMISSIONS is intentionally absent: it is read on the CLAUDE path
rem only. Opencode shells always launch with --auto, so there is nothing to
rem disarm here. (EDP_PANEL_APPROVALS is likewise Claude-only - the mechanism
rem is a Claude PreToolUse hook and an opencode fleet runs no Claude hooks.)

rem --- CAPACITY --------------------------------------------------------------
rem Exceeding these fails LOUDLY (POOL_CAPACITY_EXCEEDED names the knob).
rem WARNING: a panel override (Spawn config -> Spawn caps) PERSISTS in
rem edp-pool\.pool-logs\pool-state.json under "limit_overrides" and WINS over
rem these values silently. Clear it from the panel to hand control back here.
set "EDP_MAX_WORKERS=3"
set "EDP_MAX_PLANNERS=1"
set "EDP_MAX_TOTAL_SHELLS=10"

rem --- ENGINE ----------------------------------------------------------------
rem Role scoping ENFORCED. The role->toolset table is backend-neutral: an
rem opencode worker and a Claude worker get a byte-identical toolset.
set "EDP_ROLE_SCOPE=enforce"

rem P2 tiered storage write-side ON.
set "EDP_TIER_WRITE=1"

rem Heartbeat cron = safety net only; the monitor/SSE planes drive.
set "EDP_PARKED_HEARTBEAT_SECS=1800"
set "EDP_TURN_TIMEOUT_SECS=2400"

rem --- DELIBERATELY NOT SET --------------------------------------------------
rem EDP_ROLE / EDP_NEURON_URL / XDG_DATA_HOME : seat identity, owned by
rem                             launch-opencode-neuron.bat. XDG_DATA_HOME is
rem                             also set per-spawn by the opencode launcher.
rem EDP_OPENCODE_WORKSPACE / _DATA / _BIN     : working defaults; set only to
rem                             override.
rem EDP_SOL_CODEX_BIN et al   : the Sol bridge auto-resolves the right
rem                             codex.exe. Independent of this fleet.

cd /d "%CLAUDE_DIR%"
"%PY%" -m edp_claude.stack_launcher %*
if errorlevel 1 (
  echo.
  echo [stack:sol] launcher exited with error %errorlevel% - read the output
  echo             above. Most common cause: a previous stack generation still
  echo             holds the ports - check .logs\stack-pids.json. Also check no
  echo             claude stack is running: only one may bind :9300/:9301.
  pause
)

endlocal
