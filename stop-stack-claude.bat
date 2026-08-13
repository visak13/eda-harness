@echo off
setlocal enabledelayedexpansion
title Stop claude stack
cd /d "%~dp0"

rem ============================================================
rem  stop-stack-claude.bat - guaranteed stack teardown.
rem  (1) tracked PIDs from .logs\stack-pids.json (tree-kill), then
rem  (2) whatever still LISTENS on :9300/:9301 (port-scoped force
rem  kill - the orphaned-broker case; never a name-wide kill).
rem  Idempotent: safe to run when nothing is up.
rem ============================================================

set "KILLED=0"

rem (1) tracked pids, if the launcher left a pidfile
if exist ".logs\stack-pids.json" (
    for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Content '.logs\stack-pids.json' | ConvertFrom-Json).pids.PSObject.Properties.Value"`) do (
        taskkill /F /T /PID %%p >nul 2>nul && (
            echo   killed tracked pid %%p ^(with children^)
            set "KILLED=1"
        )
    )
    del /f /q ".logs\stack-pids.json" >nul 2>nul
)

rem (2) force-kill whatever still owns the stack ports (orphans)
for %%P in (9300 9301) do (
    for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique"`) do (
        taskkill /F /T /PID %%i >nul 2>nul && (
            echo   killed orphan pid %%i holding port %%P
            set "KILLED=1"
        )
    )
)

rem (3) verify
set "STILL="
for %%P in (9300 9301) do (
    powershell -NoProfile -Command "exit [int](@(Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue).Count -gt 0)" >nul 2>nul
    if errorlevel 1 set "STILL=%%P"
)
echo.
if defined STILL (
    echo [ERROR] something still listens on :%STILL% - investigate by hand:
    echo         Get-NetTCPConnection -LocalPort %STILL% -State Listen
    pause
    exit /b 1
)
if "%KILLED%"=="1" (
    echo Stack stopped. Ports 9300/9301 are free.
) else (
    echo Nothing was running. Ports 9300/9301 are free.
)
echo You can now run update-claude.bat ^(after closing Claude shells^).
pause
exit /b 0
