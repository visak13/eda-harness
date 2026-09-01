# Start edp-broker (:9300) — the delivery/wake plane: shell inboxes, channels, SSE events.
# The pool's resume watchdog wakes parked shells on inbox growth; the board mirrors
# addressed messages/gates into these inboxes.
param([int]$Port = 9300,
      [string]$BindHost = $(if ($env:EDP8_BIND) { $env:EDP8_BIND } else { "127.0.0.1" }))  # teammates over Tailscale: EDP8_BIND=0.0.0.0 + firewall scoped to the tailnet
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$brokerDir = Join-Path $root "edp-broker"
New-Item -ItemType Directory -Force (Join-Path $v8 ".data\broker-data") | Out-Null
$env:EDP_BROKER_HOST = $BindHost; $env:EDP_BROKER_PORT = "$Port"
$env:EDP_BROKER_DATA = Join-Path $v8 ".data\broker-data"
$log = Join-Path $v8 ".data\broker.log"
$p = Start-Process -FilePath "uv" -ArgumentList @("run","--directory",$brokerDir,"python","-m","edp_broker.main") -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\broker.err")
Set-Content (Join-Path $v8 ".data\broker.pid") $p.Id
for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod "http://127.0.0.1:$Port/v1/health" | Out-Null; break } catch { Start-Sleep -Milliseconds 250 } }
Write-Host "edp-broker up at http://127.0.0.1:$Port (pid $($p.Id)); data: $env:EDP_BROKER_DATA; log: $log"
