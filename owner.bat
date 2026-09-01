@echo off
rem ============================================================================
rem  v8 one-shot entrypoint: board (:9400) + pool (:9301) + YOUR owner shell.
rem
rem  Usage:
rem    owner.bat                     350k auto-compact window, model claude-opus-4-8
rem    owner.bat 500000              extend this session's window to 500k
rem    owner.bat 350000 claude-fable-5   window + model override
rem  Env overrides (win over defaults, lose to args):
rem    EDP8_ACW=<tokens>   EDP8_OWNER_MODEL=<model id>
rem  The same 350k standard applies to every pool-spawned shell via v8\models.json
rem  (per-seat auto_compact) — this bat only governs YOUR shell.
rem ============================================================================
setlocal
set "ROOT=%~dp0"

rem --- session knobs -----------------------------------------------------------
set "ACW=%EDP8_ACW%"
if not "%~1"=="" set "ACW=%~1"
if "%ACW%"=="" set "ACW=350000"
set "MODEL=%EDP8_OWNER_MODEL%"
if not "%~2"=="" set "MODEL=%~2"
if "%MODEL%"=="" set "MODEL=claude-opus-4-8"

rem --- broker (skip if already answering) -------------------------------------
powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:9300/v1/health -TimeoutSec 2 | Out-Null } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [owner.bat] starting broker...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-broker.ps1"
) else (
  echo [owner.bat] broker already up.
)

rem --- board (skip if already answering) --------------------------------------
powershell -NoProfile -Command "try { (Invoke-RestMethod http://127.0.0.1:9400/healthz -TimeoutSec 2).ok } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [owner.bat] starting board...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-board.ps1"
) else (
  echo [owner.bat] board already up.
)

rem --- pool (skip if already answering) ---------------------------------------
powershell -NoProfile -Command "try { Invoke-RestMethod http://127.0.0.1:9301/v1/health -TimeoutSec 2 | Out-Null } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo [owner.bat] starting pool...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-pool.ps1"
) else (
  echo [owner.bat] pool already up.
)

echo.
echo [owner.bat] board UI:   http://127.0.0.1:9400/ui
echo [owner.bat] model:      %MODEL%    auto-compact window: %ACW% tokens
echo [owner.bat] settings:   v8\.claude\settings.json + v8\.mcp.json apply to this shell
echo [owner.bat] you are:    owner  --  type /owner, then state your goal
echo [owner.bat] restart with a bigger window any time:  owner.bat 500000
echo.

rem --- your shell --------------------------------------------------------------
cd /d "%ROOT%v8"
set "EDP_HANDLE=owner"
set "EDP_ROLE=owner"
set "EDP8_BOARD_URL=http://127.0.0.1:9400"
set "EDP_BROKER_URL=http://127.0.0.1:9300"
set "EDP_POOL_URL=http://127.0.0.1:9301"
set "CLAUDE_CODE_AUTO_COMPACT_WINDOW=%ACW%"
set "FORCE_COLOR=1"
claude --model %MODEL%
endlocal
