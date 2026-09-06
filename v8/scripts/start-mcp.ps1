# Start the ONE shared edp8 MCP server (streamable-http, stateless) every shell talks to.
# One process for the whole fleet: restart it to hot-reload tool code for every seat.
param([int]$Port = 9402, [string]$BoardUrl = "http://127.0.0.1:9400",
      [string]$PoolUrl = "http://127.0.0.1:9301", [string]$BrokerUrl = "http://127.0.0.1:9300")
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
$py = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "v8 venv missing: run uv sync in v8" }
try { $h = Invoke-RestMethod "http://127.0.0.1:$Port/healthz" -TimeoutSec 2; Write-Host "mcp server already up on :$Port (version $($h.version)) - not starting another"; exit 0 } catch {}
New-Item -ItemType Directory -Force (Join-Path $v8 ".data") | Out-Null
$env:EDP8_HOME = $v8; $env:EDP8_BOARD_URL = $BoardUrl; $env:EDP_POOL_URL = $PoolUrl; $env:EDP_BROKER_URL = $BrokerUrl
$env:EDP8_MCP_PORT = "$Port"; $env:EDP8_MCP_HOST = "127.0.0.1"
$env:PYTHONPATH = Join-Path $v8 "src"
$log = Join-Path $v8 ".data\mcp.log"
$p = Start-Process -FilePath $py -ArgumentList @("-m","edp8.mcp_server") -WorkingDirectory $v8 -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\mcp.err")
Set-Content (Join-Path $v8 ".data\mcp.pid") $p.Id
for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod "http://127.0.0.1:$Port/healthz" | Out-Null; break } catch { Start-Sleep -Milliseconds 250 } }
$h = Invoke-RestMethod "http://127.0.0.1:$Port/healthz"
Write-Host "edp8 mcp server up at http://127.0.0.1:$Port/mcp/<role> (pid $($p.Id), version $($h.version)); log: $log"
