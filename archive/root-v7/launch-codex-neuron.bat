@echo off
rem ==========================================================================
rem  RETIRED (v7 ruling, 2026-08-05): codex seat frozen as experiment record
rem  (superseded 2026-07-19 by the opencode seat, itself now frozen). Codex
rem  serves as a BRIDGE backend (sol delegate) instead. Neuron seat = eda.bat.
rem ==========================================================================
echo RETIRED: codex neuron seat is frozen. Use eda.bat; sol joins via the bridge.
exit /b 1
rem ==========================================================================
rem  launch-codex-neuron.bat [--auto]
rem
rem  default:  a NORMAL, interactive codex window (Windows Terminal when
rem            available) that starts working immediately: the kickoff
rem            prompt is passed as the first message, so the neuron
rem            discovers the live recipe and runs its first turn while you
rem            watch - and you can chat with it at any time (/neuron works
rem            too). Close it whenever; state lives in the recipe store.
rem
rem  --auto:   the unattended lifecycle: one non-interactive kickoff turn,
rem            then the heartbeat driver resumes the session every 30 min
rem            AND instantly on broker traffic. Supervise via the panel.
rem ==========================================================================
setlocal
if not defined WT_SESSION (
  where wt >nul 2>nul
  if not errorlevel 1 (
    rem %~dp0 ends with a backslash which would escape the -d closing quote
    rem and swallow the rest of the line; the trailing dot neutralizes it.
    wt -d "%~dp0." cmd /k "%~f0" %*
    exit /b 0
  )
)
set "CODEX=C:\Users\aksou\AppData\Local\OpenAI\Codex\bin\a7c12ebff69fb123\codex.exe"
set "ROOT=%~dp0"
set "CLAUDE_DIR=%ROOT%claude"
set "WS=%ROOT%neuron-sol"
set "TPL=%CLAUDE_DIR%\docs\templates\AGENTS-external-neuron.md"
set "KICKOFF=You are the neuron in UNATTENDED mode - the operator chose auto-adoption by launching --auto. Follow AGENTS.md: adopt the single live recipe via query_objects type=recipe, ground with get_recipe_digest, then run one full turn: reconcile, then next_action, obey wait_hint, and end the turn with a one-paragraph status."

if not exist "%CODEX%" (
  echo [error] codex.exe not found at %CODEX%
  echo         Find the new versioned dir: dir "%%LOCALAPPDATA%%\OpenAI\Codex\bin" /s /b
  pause
  exit /b 1
)

if not exist "%WS%" mkdir "%WS%"
copy /y "%TPL%" "%WS%\AGENTS.md" >nul
echo [ok] workspace ready: %WS%

if /I not "%~1"=="--auto" (
  echo [launch] normal codex window. Nothing runs until YOU trigger it:
  echo          type /neuron to take over the live recipe - same semantics
  echo          as the Claude neuron command. --auto = unattended lifecycle.
  "%CODEX%" -C "%WS%"
  echo.
  echo [exit] codex session ended.
  pause
  exit /b 0
)

echo [1/2] kickoff turn - non-interactive, output below...
"%CODEX%" exec -C "%WS%" --skip-git-repo-check --color never -c model_reasoning_effort="high" "%KICKOFF%"
if errorlevel 1 (
  echo [error] kickoff turn failed - read the output above. Common causes:
  echo         stack not running - run start-stack.bat first - or the codex
  echo         MCP servers erroring; test interactively without --auto.
  pause
  exit /b 1
)

echo [2/2] heartbeat armed - turns fire every 30 min + on broker traffic.
echo        Ctrl-C stops it. Supervise via panel-window.bat.
cd /d "%CLAUDE_DIR%"
uv run python scripts\neuron_heartbeat.py --auto --cmd "\"%CODEX%\" exec resume --last -C \"%WS%\" --skip-git-repo-check --color never -c model_reasoning_effort=\"high\" {PROMPT}" --heartbeat-secs 1800
echo [exit] heartbeat driver stopped.
pause
endlocal
