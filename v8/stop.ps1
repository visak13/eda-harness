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
    if ($o.pid) { & taskkill /PID $o.pid /T /F 2>$null | Out-Null; $stopped = $true }
    if ($o.port) {
      Get-NetTCPConnection -LocalPort $o.port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { & taskkill /PID $_.OwningProcess /T /F 2>$null | Out-Null; $stopped = $true }
    }
    & $py -c "from edp8 import run_state; run_state.clear('$svc')" 2>$null
  }
  # bridge has no port and its pid file can be stale — sweep by command line too
  if ($svc -eq "bridge") {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
      Where-Object { $_.CommandLine -match 'edp8\.slack_bridge' } |
      ForEach-Object { & taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null; $stopped = $true }
  }
  Write-Host ("{0,-11} {1}" -f $svc, $(if ($stopped) { "stopped" } else { "not running" }))
}
