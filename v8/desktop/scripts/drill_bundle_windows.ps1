# S8 (s-6dcf78f803) Briefcase service re-entry drill (strategyhl-5af811e7bd §3 spike, criterion c-eb38e8c949).
# Drives a built or installed Windows bundle in a CLEAN temp profile on free ports; nothing touches the fleet,
# the real profile or this checkout:
#   heronry version / doctor (headless CLI) -> init --harness claude -> start -> every service process is the
#   bundle's own exe re-entered with --heronry-service <svc> -> status up -> /v1/health 200 -> stop -> no process
#   from the bundle left, ports free.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\desktop\scripts\drill_bundle_windows.ps1 -AppDir <dir>
# <dir> holds heronry.exe (the console CLI) and "Heronry Desktop.exe" (the GUI stub): build\heronry\windows\app\src
# after `briefcase build`, or the MSI's install dir.
param([Parameter(Mandatory = $true)][string]$AppDir, [switch]$Keep)
$ErrorActionPreference = "Continue"
$AppDir = (Resolve-Path $AppDir).Path
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-bundle-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }

Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
foreach ($d in "profile", "profile\AppData\Local", "profile\AppData\Roaming") { New-Item -ItemType Directory -Force -Path (Join-Path $T $d) | Out-Null }
$env:USERPROFILE = "$T\profile"; $env:HOME = "$T\profile"
$env:LOCALAPPDATA = "$T\profile\AppData\Local"; $env:APPDATA = "$T\profile\AppData\Roaming"
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:HERONRY_NO_BROWSER = "1"; $env:EDP8_EMBEDDER = "none"; $env:PYTHONIOENCODING = "utf-8"
$env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort
Set-Location $T
$h = Join-Path $AppDir "heronry.exe"
"bundle $AppDir; temp profile $T; ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT"
Check (Test-Path $h) "heronry.exe (console CLI) is in the bundle"
Check (Test-Path (Join-Path $AppDir "Heronry Desktop.exe")) "Heronry Desktop.exe (GUI stub) is in the bundle"

"== heronry version"
$o = & $h version 2>&1 | Out-String; "   $($o.Trim())"
Check ($LASTEXITCODE -eq 0 -and $o -match "^Heronry \d+\.\d+\.\d+") "version prints 'Heronry <ver>' on the console"
"== heronry init --harness claude"
$o = & $h init --harness claude 2>&1 | Out-String; $o -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "init exit 0"
"== heronry doctor"
$o = & $h doctor 2>&1 | Out-String; $o -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $_" }
Check ($o -match "Heronry doctor" -and $o -match "prerequisites") "doctor runs headless from the bundle and prints its report"
$script:ours = @()
try {
  "== heronry start"
  & $h start 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "start exit 0"
  "== heronry status"
  & $h status 2>&1 | ForEach-Object { "   $_" }
  $rows = & $h status --json | Out-String | ConvertFrom-Json
  foreach ($svc in "board", "mcp", "pool", "broker") {
    $r = @($rows | Where-Object { $_.service -eq $svc })[0]
    Check ($r.state -eq "up" -and $r.pid -and $r.url -match "^http://127\.0\.0\.1:\d+$") "status: $svc up with pid $($r.pid) and url $($r.url)"
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($r.pid)"
    $script:ours += [int]$r.pid
    "   $svc pid $($r.pid): $($proc.CommandLine)"
    Check ($proc.ExecutablePath -and $proc.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) -and
           $proc.CommandLine -match "--heronry-service\s+$svc\b") "re-entry: $svc runs as the bundle exe with --heronry-service $svc"
  }
  $sup = @($rows | Where-Object { $_.service -eq "supervisor" })[0]
  if ($sup.pid) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($sup.pid)"; $script:ours += [int]$sup.pid
    "   supervisor pid $($sup.pid): $($proc.CommandLine)"
    Check ($proc.CommandLine -match "--heronry-service\s+supervisor") "re-entry: the supervisor runs as the bundle exe with --heronry-service supervisor"
  } else { Check $false "the supervisor is up" }
  $code = 0; try { $code = (Invoke-WebRequest "http://127.0.0.1:$env:EDP8_PORT/v1/health" -UseBasicParsing -TimeoutSec 10).StatusCode } catch { }
  Check ($code -eq 200) "/v1/health returns 200"
  $code = 0; try { $code = (Invoke-WebRequest "http://127.0.0.1:$env:EDP8_PORT/ui/" -UseBasicParsing -TimeoutSec 10).StatusCode } catch { }
  Check ($code -eq 200) "/ui/ (the prebuilt SPA) returns 200"
} finally {
  "== heronry stop"
  & $h stop --force 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "stop exit 0"
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) -and
  ($_.CommandLine -match "--heronry-service") })
$left | ForEach-Object { "   left: $($_.ProcessId) $($_.CommandLine)" }
Check ($left.Count -eq 0) "stop leaves no service process of the bundle running ($($left.Count) found)"
foreach ($p in @($env:EDP8_PORT, $env:EDP8_MCP_PORT, $env:EDP_POOL_PORT, $env:EDP_BROKER_PORT)) {
  Check (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) "port $p is free"
}
if (-not $Keep) { Set-Location $env:TEMP; Remove-Item -Recurse -Force $T -ErrorAction SilentlyContinue }
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
