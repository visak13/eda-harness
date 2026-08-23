$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\board.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Host "stopped board pid $id" } catch { Write-Host "board pid $id not running" }; Remove-Item $pidFile -Force }
else { Write-Host "no board pid file" }
