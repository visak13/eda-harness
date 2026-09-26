# S3 (s-870e401942) evidence drill: install.ps1 in a CLEAN temp profile, then the installed `heronry`
# end to end (criterion c-5fb36ba3db). Nothing touches the real profile, the fleet or this checkout:
#   * USERPROFILE / HOME / LOCALAPPDATA / APPDATA and every uv dir point into a temp folder;
#   * uv is taken off PATH, so install.ps1 installs its pinned uv (and verifies its SHA-256);
#   * EDP*/HERONRY* variables are scrubbed; the services get free ports; cwd is outside the repo.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_install_windows.ps1 -ReleaseDir <dir>
# <dir> holds the four wheels and SHA256SUMS (uv build --wheel of edp-contracts, edp-broker, edp-pool, v8).
param([Parameter(Mandatory = $true)][string]$ReleaseDir, [switch]$Keep)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-clean-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }

Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
foreach ($d in "profile", "profile\AppData\Local", "profile\AppData\Roaming") { New-Item -ItemType Directory -Force -Path (Join-Path $T $d) | Out-Null }
$env:USERPROFILE = "$T\profile"; $env:HOME = "$T\profile"
$env:LOCALAPPDATA = "$T\profile\AppData\Local"; $env:APPDATA = "$T\profile\AppData\Roaming"
$env:UV_TOOL_DIR = "$T\uv-tools"; $env:UV_TOOL_BIN_DIR = "$T\bin"; $env:UV_PYTHON_INSTALL_DIR = "$T\uv-python"
$env:UV_CACHE_DIR = "$T\uv-cache"; $env:UV_NO_MODIFY_PATH = "1"
$env:PATH = (($env:PATH -split ";") | Where-Object { $_ -and -not (Test-Path (Join-Path $_ "uv.exe")) -and -not (Test-Path (Join-Path $_ "heronry.exe")) }) -join ";"
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:EDP8_EMBEDDER = "none"; $env:PYTHONIOENCODING = "utf-8"
$env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort
Set-Location $T
"temp profile $T; ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT"
"uv on PATH before install: $([bool](Get-Command uv -ErrorAction SilentlyContinue))"

"== install.ps1 (clean profile)"
powershell -NoProfile -ExecutionPolicy Bypass -File "$root\install.ps1" -ReleaseUrl $ReleaseDir -NoModifyPath 2>&1 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "install.ps1 exit 0"
Check (Test-Path "$T\profile\.local\bin\uv.exe") "the pinned uv was installed into the temp profile"
$h = "$T\bin\heronry.exe"
Check (Test-Path $h) "heronry.exe in the temp tool bin dir"
"== install.ps1 again (idempotent)"
$again = powershell -NoProfile -ExecutionPolicy Bypass -File "$root\install.ps1" -ReleaseUrl $ReleaseDir -NoModifyPath 2>&1 | Out-String
$again -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $_" }
Check (($LASTEXITCODE -eq 0) -and ($again -match "already installed")) "a second run is a no-op"

"== heronry init (no harness)"
$o = & $h init 2>&1 | Out-String; "   $($o.Trim())"
Check ($LASTEXITCODE -eq 2 -and $o -match "no harness selected") "init with no harness refuses"
"== heronry init --harness claude (codex-less)"
$o = & $h init --harness claude 2>&1 | Out-String; $o -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0 -and $o -match "NOTICE:" -and $o -match "Fable") "codex-less init prints the Fable notice"
Check ($o -notmatch [regex]::Escape($root)) "the install home is outside the repo"
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
  }
  "== heronry start (again)"
  $o = & $h start 2>&1 | Out-String; $o -split "`n" | Where-Object { $_.Trim() } | ForEach-Object { "   $_" }
  Check (($o -split "`n" | Where-Object { $_ -match "^(board|mcp|pool|broker)\s+already running" }).Count -eq 4) "a second start says already running"
  $code = 0; try { $code = (Invoke-WebRequest "http://127.0.0.1:$env:EDP8_PORT/v1/health" -UseBasicParsing -TimeoutSec 10).StatusCode } catch { }
  Check ($code -eq 200) "/v1/health returns 200"
} finally {
  "== heronry stop"
  & $h stop --force 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "stop exit 0"
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase) })
Check ($left.Count -eq 0) "stop leaves no process running from the install ($($left.Count) found)"
foreach ($p in @($env:EDP8_PORT, $env:EDP8_MCP_PORT, $env:EDP_POOL_PORT, $env:EDP_BROKER_PORT)) {
  Check (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) "port $p is free"
}
if (-not $Keep) { Set-Location $env:TEMP; Remove-Item -Recurse -Force $T -ErrorAction SilentlyContinue }
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
