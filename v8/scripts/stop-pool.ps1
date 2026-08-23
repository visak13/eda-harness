$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\pool.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Write-Host "stopped pool tree pid $id"; Remove-Item $pidFile -Force }
else { Write-Host "no pool pid file" }
