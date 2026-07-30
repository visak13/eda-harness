@echo off
rem ============================================================================
rem  CLAUDE SEAT stack: broker (:9300) + pool (:9301) + RuleSupervisor
rem
rem  Every spawned role is a CLAUDE CODE PTY shell on the host default model
rem  (Opus). Pair this with the Claude Code neuron seat (eda.bat / the
rem  claude-personal launcher).
rem
rem  For the GPT/sol fleet use start-stack-sol.bat instead. The two launchers
rem  are deliberately INDEPENDENT and self-contained: neither reads nor edits
rem  the other, so switching seats is "stop the stack, start the other one"
rem  with no hand-editing. Only ONE may run at a time (both bind :9300/:9301).
rem
rem  Usage (from the eda-base3 root):
rem    start-stack-claude.bat                    broker + pool + supervisor
rem    start-stack-claude.bat --no-supervisor    broker + pool only
rem    start-stack-claude.bat --max-runtime 30   bring up, hold 30s, tear down
rem  Ctrl-C stops all three cleanly (tracked PIDs only, never a name-wide kill).
rem
rem  Audited 2026-07-21. See the FLEET and TRAPS blocks below for why each
rem  value is what it is; every line here was verified against the source.
rem ============================================================================
setlocal

set "ROOT=%~dp0"
set "CLAUDE_DIR=%ROOT%claude"
set "PY=%CLAUDE_DIR%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem --- FLEET -----------------------------------------------------------------
rem EMPTY = 100%% Claude. edp-pool main.py builds SubprocessSpawner (the Claude
rem PTY path) unconditionally and only wraps it in CompositeSpawner when this
rem list is non-empty. Empty means CompositeSpawner is never constructed and
rem every role launches claude.exe with NO --model, i.e. the host default Opus.
set "EDP_OPENCODE_ROLES="

rem Claude model tier table. NOTE: this must stay a CLAUDE model id on BOTH
rem stacks - the engine's tier table only ever speaks Claude ids, and the
rem opencode backend TRANSLATES them (map_model matches on the substring
rem "sonnet"). Putting a gpt id here would be emitted verbatim as
rem "--model openai/..." to claude.exe, and nothing in the stack validates it.
set "EDP_WORKER_SONNET_MODEL=claude-sonnet-4-6"

rem --- TRAPS THIS LAUNCHER DISARMS -------------------------------------------
rem Visible consoles for every spawned shell (you watch the agents work).
set "EDP_SPAWN_MODE=monitor"

rem THE BIG ONE. Headless Claude shells always get --dangerously-skip-
rem permissions (no window to click), but MONITOR shells do NOT unless this is
rem set - so every visible planner/worker would freeze at its first Bash/Write
rem prompt waiting for a human click, looking identical to a healthy slow
rem worker. The opencode fleet never hits this (it passes --auto always), which
rem is why the sol launcher can leave it at 0 and this one cannot.
rem Set to 0 ONLY if you deliberately want to click-approve each tool use.
set "EDP_SKIP_PERMISSIONS=1"

rem Panel-side approvals are a CLAUDE PreToolUse hook, so they only mean
rem anything on this stack. 0 = approve in the shell's own console.
set "EDP_PANEL_APPROVALS=0"

rem --- CAPACITY --------------------------------------------------------------
rem Per-role throughput caps + the true host-resource guard (every live shell
rem is a full claude process). Exceeding these fails LOUDLY
rem (POOL_CAPACITY_EXCEEDED names the knob), so tune here, not by guessing.
rem WARNING: a panel override (Spawn config -> Spawn caps) PERSISTS in
rem edp-pool\.pool-logs\pool-state.json under "limit_overrides" and WINS over
rem these values silently. Clear it from the panel to hand control back here.
set "EDP_MAX_WORKERS=3"
set "EDP_MAX_PLANNERS=1"
set "EDP_MAX_TOTAL_SHELLS=10"

rem --- ENGINE ----------------------------------------------------------------
rem Role scoping ENFORCED: each shell's MCP registry is filtered to its role's
rem toolset (off-set tools are absent, not warned). The role->toolset table is
rem backend-neutral - a Claude worker and an opencode worker get a byte-
rem identical toolset. "warn" is the diagnostic opt-out.
set "EDP_ROLE_SCOPE=enforce"

rem P2 tiered storage write-side ON (long texts move to sidecars, reads
rem hydrate transparently). Matches what the MCP servers get from .mcp.json.
set "EDP_TIER_WRITE=1"

rem Heartbeat cron = safety net only; the monitor/SSE planes are the driving
rem force and are free (no LLM call). Only an actual wake spends tokens.
set "EDP_PARKED_HEARTBEAT_SECS=1800"
set "EDP_TURN_TIMEOUT_SECS=2400"

rem --- DELIBERATELY NOT SET --------------------------------------------------
rem EDP_ROLE / EDP_NEURON_URL : seat identity, belongs to the NEURON launcher.
rem                             EDP_ROLE leaking in would scope the pool's own
rem                             MCP calls.
rem EDP_SOL_CODEX_BIN et al   : the Sol bridge (sol_author_asset / sol_consult)
rem                             is a SEPARATE bridge to the Codex CLI and works
rem                             on a 100%% Claude stack with zero env - it
rem                             auto-resolves the right codex.exe. Those tools
rem                             stay available to workers/consults here.
rem EDP_OPENCODE_*            : nothing on this stack reads them.

cd /d "%CLAUDE_DIR%"
"%PY%" -m edp_claude.stack_launcher %*
if errorlevel 1 (
  echo.
  echo [stack:claude] launcher exited with error %errorlevel% - read the output
  echo                above. Most common cause: a previous stack generation
  echo                still holds the ports - check .logs\stack-pids.json.
  echo                Also check no sol stack is running: only one may bind
  echo                :9300/:9301.
  pause
)

endlocal
