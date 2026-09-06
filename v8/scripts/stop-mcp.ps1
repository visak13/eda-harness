$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\mcp.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Remove-Item $pidFile -Force }
# the pid can go stale across restarts - also kill by port
$live = Get-NetTCPConnection -LocalPort 9402 -State Listen -ErrorAction SilentlyContinue
foreach ($c in $live) { & taskkill /PID $c.OwningProcess /T /F 2>$null | Out-Null; Write-Host "stopped mcp server pid $($c.OwningProcess) (port 9402)" }
if (-not $live) { Write-Host "mcp server not listening on 9402" }
