@echo off
rem ============================================================================
rem  v8 one-shot entrypoint: board (:9400) + pool (:9301) + YOUR owner shell.
rem  Idempotent — already-running services are left alone. Close the shell and
rem  run stop-v8.bat when you want the stack down.
rem ============================================================================
setlocal
set "ROOT=%~dp0"

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
echo [owner.bat] board UI:  http://127.0.0.1:9400/ui
echo [owner.bat] you are:   owner   (type /owner in the shell, then state your goal)
echo.

rem --- your shell --------------------------------------------------------------
cd /d "%ROOT%v8"
set "EDP_HANDLE=owner"
set "EDP_ROLE=owner"
set "EDP8_BOARD_URL=http://127.0.0.1:9400"
claude
endlocal
