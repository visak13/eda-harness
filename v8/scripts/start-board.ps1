# Start the edp8 board locally (no docker) and register the default participants.
param([int]$Port = 9400, [string]$AdminToken = "dev", [string]$OwnerHandle = "owner")
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot
$env:EDP8_PORT = "$Port"; $env:EDP8_ADMIN_TOKEN = $AdminToken; $env:EDP8_HOME = $v8
$env:EDP8_DB = Join-Path $v8 ".data\edp8.db"
New-Item -ItemType Directory -Force (Join-Path $v8 ".data") | Out-Null
$log = Join-Path $v8 ".data\board.log"
$p = Start-Process -FilePath "uv" -ArgumentList @("run","--directory",$v8,"edp8-board") -WindowStyle Hidden -PassThru -RedirectStandardOutput $log -RedirectStandardError (Join-Path $v8 ".data\board.err")
Set-Content (Join-Path $v8 ".data\board.pid") $p.Id
$base = "http://127.0.0.1:$Port"
for ($i=0; $i -lt 40; $i++) { try { Invoke-RestMethod "$base/healthz" | Out-Null; break } catch { Start-Sleep -Milliseconds 250 } }
uv run --directory $v8 python -m edp8.bootstrap --board $base --admin $AdminToken --owner $OwnerHandle
Write-Host "edp8 board up at $base (pid $($p.Id)); log: $log"
