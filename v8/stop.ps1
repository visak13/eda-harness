# edp8 fleet — bring everything down (the launcher owns the shared services; design §22).
#   .\stop.ps1            stop supervisor + bridge + mcp + pool + broker + board
#   .\stop.ps1 -Only mcp  stop just one
# Stops by the launcher's pid file (v8/.run) and, as a backstop, by the listener on each port.
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

foreach ($svc in $order) {
  $rec = & $py -c "import json;from edp8 import run_state;r=run_state.read('$svc');print(json.dumps(r) if r else '')" 2>$null
  $stopped = $false
  if ($rec) {
    $o = $rec | ConvertFrom-Json
    # Scoped stop (c-c0f2ceea9b): kill only THIS fleet's OWN recorded pid. For the port-less bridge,
    # verify the pid is still a slack_bridge first — a stale/reused pid, or the LIVE fleet's bridge,
    # is never taskkilled by a private fleet. The old machine-global CommandLine sweep (which killed
    # every slack_bridge on the box, the live one included) is gone.
    $killable = $true
    if ($svc -eq "bridge" -and $o.pid) {
      $killable = [bool](& $py -c "from edp8 import run_state; print('1' if run_state.pid_cmdline_matches($($o.pid),'edp8.slack_bridge') else '')" 2>$null)
    }
    if ($o.pid -and $killable) { if (Get-Process -Id $o.pid -ErrorAction SilentlyContinue) { & cmd /c "taskkill /PID $o.pid /T /F >nul 2>&1" }; $stopped = $true }
    if ($o.port) {
      Get-NetTCPConnection -LocalPort $o.port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { if (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue) { & cmd /c "taskkill /PID $_.OwningProcess /T /F >nul 2>&1" }; $stopped = $true }
    }
    & $py -c "from edp8 import run_state; run_state.clear('$svc')" 2>$null
  }
  Write-Host ("{0,-11} {1}" -f $svc, $(if ($stopped) { "stopped" } else { "not running" }))
}
