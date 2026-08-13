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
netstat -ano | findstr /r ":9300 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [ERROR] edp-broker is listening on :9300 - stop the stack first.
    exit /b 1
)
netstat -ano | findstr /r ":9301 .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [ERROR] edp-pool is listening on :9301 - stop the stack first.
    exit /b 1
)

rem (2) refuse while ANY claude shell is running (incl. the foreground one)
tasklist /fi "imagename eq claude.exe" 2>nul | find /i "claude.exe" >nul
if not errorlevel 1 (
    echo [ERROR] claude.exe is running. Close every Claude Code shell
    echo         ^(including the one you may be reading this from^) and re-run.
    exit /b 1
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
    exit /b 1
)

rem (5) verify: version answers AND the binary is not an updater stub
echo.
echo New version:
call claude --version
if errorlevel 1 (
    echo [ERROR] claude --version failed after update - the install may be
    echo         a broken stub. Re-run this script, or repair via:
    echo         npm uninstall -g @anthropic-ai/claude-code ^&^& npm install -g @anthropic-ai/claude-code
    exit /b 1
)
for /f "usebackq delims=" %%r in (`npm root -g`) do set "NPMROOT=%%r"
set "BIN=%NPMROOT%\@anthropic-ai\claude-code\bin\claude.exe"
if exist "%BIN%" (
    for %%F in ("%BIN%") do set "BINSIZE=%%~zF"
    if !BINSIZE! LSS 1000000 (
        echo [ERROR] %BIN% is !BINSIZE! bytes - an auto-update stub, not a
        echo         healthy binary. Re-run this script to reinstall.
        exit /b 1
    )
    echo Binary healthy: %BIN% ^(!BINSIZE! bytes^)
)

echo.
echo Done. Every shell spawned from now on runs the new version -
echo restart the stack ^(start-stack-claude.bat^) and your foreground
echo session ^(eda^) to pick it up. Version skew between already-running
echo shells and new spawns is what this script exists to prevent.
exit /b 0
