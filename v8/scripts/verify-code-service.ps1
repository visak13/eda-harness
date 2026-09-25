# Re-runnable evidence for the `code` service criteria (s-3c8c2512d6), for qa:
#
#   powershell -File v8\scripts\verify-code-service.ps1 [-OutDir <dir>]
#
# Starts/stops ONLY the `code` service, through edp.ps1. Prints PASS/FAIL per check, exits 1 on a FAIL.
#   c-45cd46ab9b  start code -> status healthy on 127.0.0.1:<port>; stop code -> port closed and no
#                 process from the install; board.json pid + started_at unchanged across both
#   c-ade7c62ee9  install is a no-op on a second run; a tampered lock checksum fails with nothing
#                 extracted; after a start --list-extensions over the service dir lists every pin
#   c-353bd62e1d  settings.json autolinks (t-, s-, epic-, m- -> board /ui/ticket/<id>) + the live blame
#                 hover and terminal-env checks in verify-code-service.mjs (Playwright, Chromium)
# Leaves the service running at the end, as it found it when it was running.
param([string]$OutDir = "")
# Continue: under PS 5.1 "Stop" turns any stderr line of a child powershell (edp.ps1 notes) into a
# terminating error, and the script would die before printing its FAIL lines
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$edp = Join-Path (Split-Path -Parent $v8) "edp.ps1"
if (-not $OutDir) { $OutDir = Join-Path $v8 ".data\code\s2-evidence" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$PORT = if ($env:EDP_CODE_PORT) { [int]$env:EDP_CODE_PORT } else { 9410 }
$RUN = if ($env:EDP8_RUN_DIR) { $env:EDP8_RUN_DIR } else { Join-Path $v8 ".run" }
$lock = Get-Content (Join-Path $v8 "vscode-ext\code-server.lock.json") -Raw | ConvertFrom-Json
$serverDir = Join-Path $v8 ".tools\code-server\$($lock.version)\$($lock.server_dir)"
$tools = ([IO.Path]::GetFullPath((Join-Path $v8 ".tools\code-server"))).TrimEnd("\") + "\"
$results = @()
function Check($ok, $msg) { $script:results += , @([bool]$ok, $msg); Write-Host ("{0} {1}" -f $(if ($ok) { "PASS" } else { "FAIL" }), $msg) }
function Board { $b = Get-Content (Join-Path $RUN "board.json") -Raw | ConvertFrom-Json; "pid=$($b.pid) started_at=$($b.started_at)" }
function Edp($verb) { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $edp $verb code 2>&1 | ForEach-Object { "$_" } }
function Listening { [bool](Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue) }
function FromInstall { @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($tools, [StringComparison]::OrdinalIgnoreCase) }).Count }

# -- c-45cd46ab9b: round-trip, board untouched -----------------------------------------------------
$b0 = Board
$stop = Edp "stop"; $stop | Set-Content (Join-Path $OutDir "edp-stop.log")
Check ((-not (Listening)) -and (FromInstall) -eq 0) "stop code: port $PORT closed, $(FromInstall) processes from the install"
$start = Edp "start"; $start | Set-Content (Join-Path $OutDir "edp-start.log")
$status = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $edp status 2>&1 | Out-String -Width 200
$status | Set-Content (Join-Path $OutDir "edp-status.log")
$row = ($status -split "`n" | Where-Object { $_ -match '^code\s' }) -join ""
Check ($row -match "^code\s+up\s+$PORT\s") "status after start: $($row.Trim())"
$health = try { (Invoke-WebRequest "http://127.0.0.1:$PORT/healthz" -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 0 }
$bind = @(Get-NetTCPConnection -LocalPort $PORT -State Listen | ForEach-Object { $_.LocalAddress }) -join ","
Check ($health -eq 200 -and $bind -eq "127.0.0.1") "GET /healthz = $health, listening on $bind only"
$b1 = Board
Check ($b0 -eq $b1) "board.json unchanged across stop+start: before $b0 / after $b1"

# -- c-ade7c62ee9: install idempotent, tamper fails, every pin listed --------------------------------
$inst = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-code-server.ps1") 2>&1 | Out-String
Check ($LASTEXITCODE -eq 0 -and $inst -match "\(no-op\)") "install second run: $($inst.Trim())"
$tmp = Join-Path $env:TEMP ("code-tamper-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force $tmp | Out-Null
$bad = Get-Content (Join-Path $v8 "vscode-ext\code-server.lock.json") -Raw | ConvertFrom-Json; $bad.sha256 = "0" * 64
$bad | ConvertTo-Json | Set-Content (Join-Path $tmp "lock.json") -Encoding ascii
$archive = Join-Path $v8 ".tools\code-server\_download\$($lock.asset)"
$t = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-code-server.ps1") -Lock (Join-Path $tmp "lock.json") -ToolsDir (Join-Path $tmp "tools") -Archive $archive 2>&1 | Out-String
$tcode = $LASTEXITCODE
Check ($tcode -eq 2 -and -not (Test-Path (Join-Path $tmp "tools\$($lock.version)"))) "tampered checksum: exit $tcode, no install dir; $(($t -split "`n" | Select-String 'mismatch') -join '')"
Remove-Item -Recurse -Force $tmp
$listed = @(& (Join-Path $serverDir $lock.node) $serverDir --user-data-dir (Join-Path $v8 ".data\code\user") --extensions-dir (Join-Path $v8 ".data\code\extensions") --list-extensions --show-versions 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '^[\w.-]+@\S+$' })
$listed | Set-Content (Join-Path $OutDir "list-extensions.txt")
$pins = @(Get-Content (Join-Path $v8 "vscode-ext\extensions.txt") | Where-Object { $_.Trim() -and -not $_.StartsWith("#") } | ForEach-Object { $_.Trim() })
$missing = @($pins | Where-Object { $listed -notcontains $_ })
Check ($missing.Count -eq 0) "--list-extensions --show-versions lists all $($pins.Count) pins$(if ($missing.Count) { '; missing: ' + ($missing -join ', ') })"

# -- c-353bd62e1d: autolinks in settings + live hover (and the terminal env) ---------------------------
$s = Get-Content (Join-Path $v8 ".data\code\user\User\settings.json") -Raw | ConvertFrom-Json
$links = @($s."gitlens.autolinks" | ForEach-Object { "$($_.prefix)=$($_.url)" })
$want = @("t-", "s-", "epic-", "m-" | ForEach-Object { "$_=http://127.0.0.1:9400/ui/ticket/$_<num>" })
Check (@($want | Where-Object { $links -notcontains $_ }).Count -eq 0) "settings.json gitlens.autolinks: $($links -join '; ')"
& node (Join-Path $PSScriptRoot "verify-code-service.mjs") $OutDir 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '^(PASS|FAIL) ' } | ForEach-Object {
  Check ($_.StartsWith("PASS")) ($_.Substring(5))
}

$failed = @($results | Where-Object { -not $_[0] }).Count
Write-Host "$($results.Count - $failed)/$($results.Count) checks passed; logs + screenshots in $OutDir"
if ($failed) { exit 1 } else { exit 0 }
