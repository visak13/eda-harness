@echo off
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\stop-pool.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\stop-board.ps1"
endlocal
