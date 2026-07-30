@echo off
rem shell_tui.cmd <opencode-exe> <port> <role> <handle>
rem One console per fleet shell: hosts the shell's server in the background
rem and runs an ATTACH TUI on it. ATTACH (not root TUI) is load-bearing:
rem v1.18.3's tui.session.select handler gates on workspace equality, the
rem select event carries no workspace, and only an attach client (workspace
rem undefined on both sides) obeys it - source- and event-bus-verified
rem 2026-07-20. Closing this window kills both attach and server; the pool
rem respects the close (window_dismissed).
title edp %3 %4
chcp 65001 >nul
rem ABSOLUTE interpreter (2026-07-21). Bare "python" resolved to the Windows
rem Store App Execution Alias on this host: it printed "Python was not found"
rem and returned NON-ZERO, so the gate below aborted this script before the
rem server (next line) and the attach TUI (last line) ever started - leaving a
rem dead console at an idle prompt while the turn ran on headless. The pool
rem also strips VIRTUAL_ENV / PYTHONPATH / PYTHONHOME / UV_* from our env
rem before spawning us (python-parent poisoning, opencode_launcher.py), so no
rem inherited python environment can be relied on here either.
set "FLEET_PY=%~dp0..\claude\.venv\Scripts\python.exe"
if not exist "%FLEET_PY%" (
  echo [shell_tui] fleet interpreter missing:
  echo             %FLEET_PY%
  echo             the claude venv is required. Create it with:
  echo               uv sync --directory "%~dp0..\claude"
  exit /b 1
)
"%FLEET_PY%" "%~dp0startup_contract.py" --role "%3" --handle "%4" || exit /b 1
start /b "" "%~1" serve --port %2 >nul 2>&1
:wait
curl -s -o nul --max-time 2 http://127.0.0.1:%2/ 2>nul
if errorlevel 1 ( timeout /t 1 /nobreak >nul & goto wait )
"%~1" attach http://127.0.0.1:%2
