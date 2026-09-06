$v8 = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $v8 ".data\bridge.pid"
if (Test-Path $pidFile) { $id = Get-Content $pidFile; & taskkill /PID $id /T /F 2>$null | Out-Null; Write-Host "stopped bridge pid $id"; Remove-Item $pidFile -Force }
# the bridge has no port: every leftover instance is found by command line and stopped too
$stray = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -match 'edp8\.slack_bridge' }
foreach ($s in $stray) { & taskkill /PID $s.ProcessId /T /F 2>$null | Out-Null; Write-Host "stopped stray bridge pid $($s.ProcessId)" }
if (-not (Test-Path $pidFile) -and -not $stray) { Write-Host "no bridge running" }
