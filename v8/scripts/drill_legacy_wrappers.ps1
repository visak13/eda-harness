# S3 (s-870e401942) evidence drill: the legacy wrappers (edp.ps1, v8\start.ps1, v8\stop.ps1, stop-v8.bat)
# drive `heronry` on a PRIVATE instance - a temp EDP_HOME, free ports, the fleet env scrubbed - and leave
# no listener behind. Safe on the shared host: it never touches the fleet's home or ports.
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_legacy_wrappers.ps1
$ErrorActionPreference = "Continue"
$root = "C:\Projects\Learning\eda-base3"
$t = Join-Path $env:TEMP ("s3-wrap-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory $t | Out-Null
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -eq "CLAUDE_CONFIG_DIR" -or $_.Name -eq "PYTHONPATH" } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:EDP_HOME = "$t\home"; $env:EDP_CLAUDE_CONFIG_DIR = "$t\claude"; $env:HERONRY_NO_UPDATE_CHECK = "1"; $env:EDP8_EMBEDDER = "none"
$env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort
$env:EDP_POOL_PYTHON = "$root\edp-pool\.venv\Scripts\python.exe"; $env:EDP_BROKER_PYTHON = "$root\edp-broker\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
"ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT home=$env:EDP_HOME"
& "$root\v8\.venv\Scripts\python.exe" -m edp8.cli init --harness claude --agent-home-source "$root\v8" | Select-Object -Last 2
function Run($label, [scriptblock]$b) { "== $label"; & $b 2>&1 | ForEach-Object { "$_" }; "   (exit $LASTEXITCODE)" }
Run "edp.ps1 start all -WhatIf" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" start all -WhatIf }
Run "v8\start.ps1" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\v8\start.ps1" }
Run "edp.ps1 status" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" status }
Run "edp.ps1 restart board" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" restart board }
Run "edp.ps1 restart pool (no seats)" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" restart pool }
Run "edp.ps1 stop mcp" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" stop mcp }
Run "v8\start.ps1 -Only mcp" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\v8\start.ps1" -Only mcp }
Run "v8\start.ps1 -Restart broker" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\v8\start.ps1" -Restart broker }
Run "v8\stop.ps1" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\v8\stop.ps1" }
Run "edp.ps1 start all" { powershell -NoProfile -ExecutionPolicy Bypass -File "$root\edp.ps1" start all }
Run "stop-v8.bat" { cmd /c "$root\stop-v8.bat" }
Run "final status --json" { & "$root\v8\.venv\Scripts\python.exe" -m edp8.cli status --json }
foreach ($p in @($env:EDP8_PORT, $env:EDP8_MCP_PORT, $env:EDP_POOL_PORT, $env:EDP_BROKER_PORT)) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  "port $p listening: $([bool]$c)"
}
