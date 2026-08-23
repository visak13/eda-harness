$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\pool.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host "stopped pool pid $id" } catch { Write-Host "pool pid $id not running" }; Remove-Item $pidFile -Force }
else { Write-Host "no pool pid file" }
