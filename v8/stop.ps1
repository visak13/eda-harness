# edp8 fleet — bring everything down (the launcher owns the shared services; design §22).
#   .\stop.ps1            stop supervisor + bridge + mcp + pool + broker + board
#   .\stop.ps1 -Only mcp  stop just one
# Stops by the launcher's pid file (v8/.run) and, as a backstop, by the listener on each port;
# verifies every pid is gone before printing "stopped" and exits 1 naming any survivor.
[CmdletBinding()]
param([string]$Only)
$ErrorActionPreference = "Stop"
$v8 = $PSScriptRoot
$py = Join-Path $v8 ".venv\Scripts\python.exe"
function Env($n, $d) { $v = [Environment]::GetEnvironmentVariable($n, "Process"); if ($v) { $v } else { $d } }
$HOMEDIR = Env "EDP8_HOME" $v8
$env:EDP8_RUN_DIR = Env "EDP8_RUN_DIR" (Join-Path $HOMEDIR ".run")
$env:PYTHONPATH = Join-Path $v8 "src"

# supervisor first, so it does not restart a service we are stopping
$order = @("supervisor", "bridge", "mcp", "pool", "broker", "board")
if ($Only) { $order = @($Only) }

$failed = $false
foreach ($svc in $order) {
  # One implementation for stop.ps1 and stop.sh (c-c0f2ceea9b): run_state.stop_service kills the
  # recorded pid tree + the port's listener, WAITS, and clears the record only when nothing is
  # left. "stopped" is printed only after the pids are verified gone (qa drill 2026-09-10 found
  # the old script printing "stopped" while every service survived).
  $res = & $py -c "import json;from edp8 import run_state;print(json.dumps(run_state.stop_service('$svc')))" | ConvertFrom-Json
  if (-not $res.recorded) { Write-Host ("{0,-11} not running" -f $svc); continue }
  if ($res.still_running.Count -gt 0) {
    Write-Host ("{0,-11} still running: {1} pid {2}" -f $svc, $svc, ($res.still_running -join ", "))
    $failed = $true
  } else {
    Write-Host ("{0,-11} stopped{1}" -f $svc, $(if ($res.killed.Count) { " (pid " + ($res.killed -join ", ") + ")" } else { " (already gone)" }))
  }
}
if ($failed) { [Console]::Error.WriteLine("edp8: some services are still running — see above"); exit 1 }
