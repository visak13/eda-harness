$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\board.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Remove-Item $pidFile -Force }
# uv exits after spawning the real server, so the pid file may be stale — also kill by port
$live = Get-NetTCPConnection -LocalPort 9400 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $live) { & taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null; Write-Host "stopped board pid $($c.OwningProcess) (port 9400)" }
if (-not $live) { Write-Host "board not listening on 9400" }
