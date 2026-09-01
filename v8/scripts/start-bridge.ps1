# Start the Slack doorbell (no LLM, no tokens): broker inbox growth -> Slack ping.
# Needs v8\slack_map.json (shape: see src/edp8/slack_bridge.py header).
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $v8 "slack_map.json"))) { Write-Host "no v8\slack_map.json - bridge not started"; exit 0 }
$env:EDP8_HOME = $v8
if (-not $env:EDP_BROKER_URL) { $env:EDP_BROKER_URL = "http://127.0.0.1:9300" }
$py = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "v8 venv missing: run uv sync in v8" }
$log = Join-Path $v8 ".data\bridge.log"
$env:PYTHONPATH = Join-Path $v8 "src"
$p = Start-Process -FilePath $py -ArgumentList @("-m","edp8.slack_bridge") -WorkingDirectory $v8 -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\bridge.err")
Set-Content (Join-Path $v8 ".data\bridge.pid") $p.Id
Write-Host "slack bridge up (pid $($p.Id)); log: $log"
