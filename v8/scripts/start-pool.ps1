# Start edp-pool pinned to the v8 agent home (spawned shells cwd = v8, load v8/.mcp.json + v8/.claude).
param([int]$Port = 9301, [string]$BoardUrl = "http://127.0.0.1:9400")
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$poolDir = Join-Path $root "edp-pool"
$py = Join-Path $poolDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "edp-pool venv missing: $py (run uv sync in edp-pool)" }
New-Item -ItemType Directory -Force (Join-Path $v8 ".data\pool-logs") | Out-Null
$env:EDP_POOL_AGENT_HOME = $v8
$env:EDP_POOL_HOST = "127.0.0.1"; $env:EDP_POOL_PORT = "$Port"
$env:EDP_POOL_LOG_DIR = Join-Path $v8 ".data\pool-logs"
$env:EDP_POOL_STATE = Join-Path $v8 ".data\pool-logs\pool-state.json"
$env:EDP_SPAWN_MODE = "monitor"; $env:EDP_SKIP_PERMISSIONS = "1"
$env:EDP_MAX_WORKERS = "4"; $env:EDP_MAX_PLANNERS = "4"; $env:EDP_MAX_TOTAL_SHELLS = "10"
$env:EDP8_BOARD_URL = $BoardUrl; $env:EDP8_HOME = $v8
$env:EDP_POOL_URL = "http://127.0.0.1:$Port"
$log = Join-Path $v8 ".data\pool.log"
$p = Start-Process -FilePath $py -ArgumentList @("-m","edp_pool.main") -WorkingDirectory $poolDir -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\pool.err")
Set-Content (Join-Path $v8 ".data\pool.pid") $p.Id
for ($i=0; $i -lt 60; $i++) { try { Invoke-RestMethod "http://127.0.0.1:$Port/v1/doctor" | Out-Null; break } catch { Start-Sleep -Milliseconds 300 } }
Write-Host "edp-pool up at http://127.0.0.1:$Port (pid $($p.Id)); agent home $v8; log: $log"
