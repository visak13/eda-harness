@echo off
setlocal enabledelayedexpansion
title Claude Code updater
cd /d "%~dp0"

rem ============================================================
rem  update-claude.bat - safe manual update for the Claude Code
rem  binary. The fleet pins DISABLE_AUTOUPDATER=1 because the
rem  auto-updater has left <1MB stub binaries behind (see
rem  pty_launcher._MIN_HEALTHY_BIN_BYTES); updates are MANUAL,
rem  through this script, with the stack down and no shells
rem  running (Windows locks a running exe - updating under a
rem  live shell is exactly how the install breaks).
rem ============================================================

rem (1) refuse while the stack is up
rem (PowerShell probe, not findstr: an unquoted space in a findstr /r
rem  pattern means OR, so ":9300 .*LISTENING" matched EVERY listening
rem  socket on the machine - false refusals on a clean box.)
powershell -NoProfile -Command "exit [int](@(Get-NetTCPConnection -LocalPort 9300 -State Listen -ErrorAction SilentlyContinue).Count -gt 0)"
if errorlevel 1 (
    echo [ERROR] edp-broker is listening on :9300 - run stop-stack-claude.bat first.
    goto :die
)
powershell -NoProfile -Command "exit [int](@(Get-NetTCPConnection -LocalPort 9301 -State Listen -ErrorAction SilentlyContinue).Count -gt 0)"
if errorlevel 1 (
    echo [ERROR] edp-pool is listening on :9301 - run stop-stack-claude.bat first.
    goto :die
)

rem (2) refuse while ANY claude shell is running (incl. the foreground one)
tasklist /fi "imagename eq claude.exe" 2>nul | find /i "claude.exe" >nul
if not errorlevel 1 (
    echo [ERROR] claude.exe is running. Close every Claude Code shell
    echo         ^(including the one you may be reading this from^) and re-run.
    goto :die
)

rem (3) record the current version
echo Current version:
call claude --version 2>nul || echo   ^(claude not on PATH or broken^)

rem (4) update
echo.
echo Updating @anthropic-ai/claude-code ...
call npm install -g @anthropic-ai/claude-code@latest
if errorlevel 1 (
    echo [ERROR] npm install failed - binary left as-is.
    goto :die
)

rem (5) verify: version answers AND the binary is not an updater stub
echo.
echo New version:
call claude --version
if errorlevel 1 (
    echo [ERROR] claude --version failed after update - the install may be
    echo         a broken stub. Re-run this script, or repair via:
    echo         npm uninstall -g @anthropic-ai/claude-code ^&^& npm install -g @anthropic-ai/claude-code
    goto :die
)
for /f "usebackq delims=" %%r in (`npm root -g`) do set "NPMROOT=%%r"
set "BIN=%NPMROOT%\@anthropic-ai\claude-code\bin\claude.exe"
if exist "%BIN%" (
    for %%F in ("%BIN%") do set "BINSIZE=%%~zF"
    if !BINSIZE! LSS 1000000 (
        echo [ERROR] %BIN% is !BINSIZE! bytes - an auto-update stub, not a
        echo         healthy binary. Re-run this script to reinstall.
        goto :die
    )
    echo Binary healthy: %BIN% ^(!BINSIZE! bytes^)
)

rem (6) update the Codex CLI too. The Sol/Astra bridge resolves the `codex`
rem     on PATH (the npm copy) ahead of the ChatGPT app's bundled one, because
rem     a NEW model (gpt-6-astra) is served only to a new-enough client and
rem     the bundled copy lags the app. Refuse if a bridge call is still running
rem     (npm cannot replace a locked exe).
echo.
echo Current codex version:
call codex --version 2>nul || echo   ^(codex not on PATH yet - will be installed^)
echo.
echo Updating @openai/codex ...
call npm install -g @openai/codex@latest
if errorlevel 1 (
    echo [ERROR] npm install of @openai/codex failed - claude was updated,
    echo         codex left as-is. Re-run to retry.
    goto :die
)
echo.
echo New codex version:
call codex --version
if errorlevel 1 (
    echo [ERROR] codex --version failed after update. Repair via:
    echo         npm uninstall -g @openai/codex ^&^& npm install -g @openai/codex
    goto :die
)
call codex login status 2>nul || echo [WARN] codex is not logged in - run: codex login

echo.
echo Done. Every shell spawned from now on runs the new version -
echo restart the stack ^(start-stack-claude.bat^) and your foreground
echo session ^(eda^) to pick it up. Version skew between already-running
echo shells and new spawns is what this script exists to prevent.
goto :ok

:ok
echo.
pause
exit /b 0

:die
echo.
echo Nothing was changed.
pause
exit /b 1