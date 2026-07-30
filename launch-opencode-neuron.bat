@echo off
rem ==========================================================================
rem  launch-opencode-neuron.bat [--auto]
rem
rem  The SOL NEURON seat - a 1:1 copy of opening a Claude shell and typing
rem  /neuron. This launcher is a DUMB TERMINAL: it hosts the session server
rem  and attaches your TUI. It decides NOTHING.
rem
rem    - The NEURON resolves which recipe to drive (resolve_recipe), or
rem      starts new work from your first message - free-flowing, its call.
rem    - The NEURON arms its own cadence at adoption via the NATIVE driver
rem      tools (edp_cron_create + edp_monitor_arm from the edp-drivers
rem      plugin) - the same self-arming a Claude neuron does with
rem      CronCreate + Monitor. EDP_DRIVER_HOST=1 below makes THIS server
rem      host the firing engine: server closed = seat closed = driving
rem      holds (the seat gate, now structural). Fallback if the plugin is
rem      ever broken: arm_external_driver + neuron_heartbeat.py.
rem    - Driver-fired turns render LIVE in your attached TUI.
rem
rem  default:  attach the TUI. Nothing runs until you type - exactly like
rem            a fresh Claude shell.
rem  --auto:   unattended - one neutral kickoff turn so the neuron grounds
rem            and self-arms without you; supervise via panel / rx log.
rem ==========================================================================
if not defined WT_SESSION (
  where wt >nul 2>nul
  if not errorlevel 1 (
    wt -d "%~dp0." cmd /k "%~f0" %*
    exit /b 0
  )
)
setlocal
set "ROOT=%~dp0"
set "CLAUDE_DIR=%ROOT%claude"
set "WS=%ROOT%opencode-fleet"
set "PORT=4747"
set "URL=http://127.0.0.1:%PORT%"
set "EDP_ROLE=neuron"
set "EDP_BROKER_URL=http://127.0.0.1:9300"
set "EDP_POOL_URL=http://127.0.0.1:9301"
set "EDP_AGENT_HOME=%CLAUDE_DIR%"
set "EDP_NEURON_URL=%URL%"
set "XDG_DATA_HOME=%WS%\.fleet-data"
rem The seat's serve hosts the edp-drivers firing engine (native cron/monitor).
set "EDP_DRIVER_HOST=1"

if not exist "%WS%\.opencode\agents\edp-neuron.md" (
  echo [error] fleet workspace not found at %WS%
  pause
  exit /b 1
)

set "OC_EXE="
"%CLAUDE_DIR%\.venv\Scripts\python.exe" "%WS%\resolve_opencode.py" > "%TEMP%\edp_oc_path.txt" 2>nul
if not errorlevel 1 set /p OC_EXE=<"%TEMP%\edp_oc_path.txt"
if not defined OC_EXE (
  echo [error] real opencode.exe not found. Set EDP_OPENCODE_BIN and relaunch.
  pause
  exit /b 1
)
echo        opencode: %OC_EXE%

echo [1/2] neuron server on %URL%...
curl -s -o nul --max-time 2 %URL%/ 2>nul
if not errorlevel 1 (
  echo        server already running - reusing it.
  goto srvup
)
rem /d %WS% is LOAD-BEARING: serve takes its PROJECT from its working dir,
rem and the fleet project carries the edp agents + pinned non-fast models.
start "edp-neuron-server" /min /d "%WS%" cmd /k call "%OC_EXE%" serve --port %PORT%
set /a TRIES=0
:waitsrv
curl -s -o nul --max-time 2 %URL%/ 2>nul
if errorlevel 1 (
  set /a TRIES+=1
  if %TRIES% GEQ 30 ( echo [error] server never came up - read its window. & pause & exit /b 1 )
  timeout /t 1 /nobreak >nul
  goto waitsrv
)
:srvup

if /I "%~1"=="--auto" (
  echo [auto] one neutral kickoff turn - the neuron grounds and self-arms...
  "%OC_EXE%" run "Follow your protocol from the top: ground against the store, resolve or start the recipe with resolve_recipe, and arm your wake cadence exactly as your agent instructions specify. End the turn naming what you are waiting for." --attach %URL% --agent edp-neuron --variant medium --auto --title edp-neuron-live --dir "%WS%"
  echo [auto] supervise via the panel; attach anytime: opencode attach %URL%
  pause
  exit /b 0
)

echo [2/2] attaching your TUI - type to drive; driver-fired turns render live.
echo        YOU choose the session: ctrl+p then "sessions" opens the picker
echo        (resume the neuron session there); or press Tab to select the
echo        Edp-Neuron agent and type a goal to start NEW work.
"%OC_EXE%" attach %URL%
echo.
echo [exit] TUI detached. The server window keeps the session alive.
pause
endlocal
