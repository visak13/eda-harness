$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\bridge.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Write-Host "stopped bridge pid $id"; Remove-Item $pidFile -Force }
else { Write-Host "no bridge pid file" }
