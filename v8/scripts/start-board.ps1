# Start the edp8 board locally (no docker) and register the default participants.
# The board process must know BOTH planes: EDP_POOL_URL (session mirror thread)
# and EDP_BROKER_URL (addressed messages/gates are republished to broker inboxes,
# which is what wakes parked shells) — set them HERE, in the board's own env.
param([int]$Port = 9400, [string]$AdminToken = "dev", [string]$OwnerHandle = "owner",
      [string]$PoolUrl = "http://127.0.0.1:9301", [string]$BrokerUrl = "http://127.0.0.1:9300",
      [string]$BindHost = $(if ($env:EDP8_BIND) { $env:EDP8_BIND } else { "127.0.0.1" }))  # teammates over Tailscale: EDP8_BIND=0.0.0.0 + firewall scoped to the tailnet
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
$env:EDP8_HOST = $BindHost
$env:EDP8_PORT = "$Port"; $env:EDP8_ADMIN_TOKEN = $AdminToken; $env:EDP8_HOME = $v8
$env:EDP8_DB = Join-Path $v8 ".data\edp8.db"
$env:EDP_POOL_URL = $PoolUrl; $env:EDP_BROKER_URL = $BrokerUrl
New-Item -ItemType Directory -Force (Join-Path $v8 ".data") | Out-Null
$log = Join-Path $v8 ".data\board.log"
$p = Start-Process -FilePath "uv" -ArgumentList @("run","--directory",$v8,"edp8-board") -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\board.err")
Set-Content (Join-Path $v8 ".data\board.pid") $p.Id
$base = "http://127.0.0.1:$Port"
for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod "$base/healthz" | Out-Null; break } catch { Start-Sleep -Milliseconds 250 } }
uv run --directory $v8 python -m edp8.bootstrap --board $base --admin $AdminToken --owner $OwnerHandle
Write-Host "edp8 board up at $base (pid $($p.Id)); log: $log"
