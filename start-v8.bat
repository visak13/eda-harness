@echo off
rem Thin wrapper: the one ops script is edp.ps1 (status / start / stop / restart / update).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" start all
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" status
echo owner shell:  cd v8 ^&^& set EDP_HANDLE=owner ^&^& claude   then type /owner
