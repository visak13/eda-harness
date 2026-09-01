@echo off
rem v8 stack: broker (:9300, inboxes/wake plane) + board (:9400, web UI at /ui) + pool (:9301) pinned to the v8 agent home.
setlocal
set "ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-broker.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-board.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-pool.ps1"
if exist "%ROOT%v8\slack_map.json" powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%v8\scripts\start-bridge.ps1"
echo.
echo v8 up: broker http://127.0.0.1:9300/v1/health   board http://127.0.0.1:9400/ui   pool http://127.0.0.1:9301/v1/doctor
echo owner shell:  cd v8 ^&^& set EDP_HANDLE=owner ^&^& claude   then type /owner
endlocal
