$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\pool.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Remove-Item $pidFile -Force }
# the recorded pid can go stale (wrapper exits, restarts lose it) — also kill by port
$live = Get-NetTCPConnection -LocalPort 9301 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $live) { & taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null; Write-Host "stopped pool pid $($c.OwningProcess) (port 9301)" }
if (-not $live) { Write-Host "pool not listening on 9301" }
