$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\broker.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Remove-Item $pidFile -Force }
# uv exits after spawning the real server, so the pid file may be stale — also kill by port
$live = Get-NetTCPConnection -LocalPort 9300 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $live) { & taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null; Write-Host "stopped broker pid $($c.OwningProcess) (port 9300)" }
if (-not $live) { Write-Host "broker not listening on 9300" }
