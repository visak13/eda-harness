@echo off
rem Thin wrapper: the one ops script is edp.ps1 (status / start / stop / restart / update).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" start all
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" status
echo board UI: http://127.0.0.1:9400/ui   (the owner acts in the web UI; no owner shell is launched)
