@echo off
rem ============================================================================
rem  Starts the Heronry services (broker, board, pool, MCP server) and prints the
rem  board UI address. It does NOT open a Claude shell: the owner is a person, and
rem  no path launches an agent as the owner role (owner m-da9a2ae62f). Act as the
rem  owner in the web UI; seats are spawned from it.
rem  The one ops script is edp.ps1 (status / start / stop / restart / update).
rem ============================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" start all
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0edp.ps1" status
echo.
echo [owner.bat] board UI:   http://127.0.0.1:9400/ui   (act as the owner there)
