# t-cd13d98674 installed-build check (S8 step 6 findings c and d, m-baed3c1589): on a built or installed Windows
# bundle, in CLEAN temp profiles on a spare port block, nothing touches the fleet, the real profile or tailscale:
#   (c) the board the launcher starts carries no EDP8_HOST, so Admin -> Remote access applies (a FAKE tailscale.cmd
#       first on PATH answers status/serve; the drill refuses to apply unless the board sees the fake's name) and
#       writes board.host + network.public_url to config.toml; remove undoes it;
#   (d) init pins code_server.port per home (block + 10); a second home's init pins another port; the Code tab
#       (/v1/code) reports foreign=true, running=false for a listener that reports another home's id, and
#       running=false with nothing listening;
#   then stop leaves no bundle process and every port is free.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\desktop\scripts\drill_remote_code_port_windows.ps1 -AppDir <dir>
# <dir> holds heronry.exe: build\heronry\windows\app\src after `briefcase build`, or the MSI's install dir.
param([Parameter(Mandatory = $true)][string]$AppDir, [int]$From = 29400, [switch]$Keep)
$ErrorActionPreference = "Continue"
$AppDir = (Resolve-Path $AppDir).Path
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-t-cd13-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function Free($p) { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $p); try { $l.Start(); $l.Stop(); $true } catch { $false } }
function Profile($name) {
  $p = Join-Path $T $name
  foreach ($d in "", "AppData\Local", "AppData\Roaming") { New-Item -ItemType Directory -Force -Path (Join-Path $p $d) | Out-Null }
  $env:USERPROFILE = $p; $env:HOME = $p; $env:LOCALAPPDATA = "$p\AppData\Local"; $env:APPDATA = "$p\AppData\Roaming"
  return "$p\AppData\Local\heronry\config"
}
function Toml($cfgDir) { Get-Content (Join-Path $cfgDir "config.toml") -Raw -ErrorAction SilentlyContinue }
function CodePort($cfgDir) {
  $m = [regex]::Match((Toml $cfgDir), "(?ms)^\[code_server\]\s*\r?\n(?:[^\[]*?\r?\n)?port\s*=\s*(\d+)")
  if ($m.Success) { [int]$m.Groups[1].Value } else { $null }
}

Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:HERONRY_NO_BROWSER = "1"; $env:EDP8_EMBEDDER = "none"; $env:PYTHONIOENCODING = "utf-8"

# the fake tailscale: first on PATH for every process this drill starts; the real one is never run
$fake = Join-Path $T "fake-bin"; New-Item -ItemType Directory -Path $fake | Out-Null
$FAKE_NAME = "drill-fake.tail0000.ts.net"
$log = Join-Path $T "fake-tailscale.log"
@"
@echo off
echo %*>>"$log"
if "%1 %2"=="status --json" (echo {"BackendState":"Running","Self":{"DNSName":"$FAKE_NAME."},"CertDomains":["$FAKE_NAME"],"Peer":{}}& exit /b 0)
if "%1 %2 %3"=="serve status --json" (echo {}& exit /b 0)
if "%1 %2"=="serve --bg" exit /b 0
if "%1 %2"=="serve reset" exit /b 0
exit /b 1
"@ | Set-Content -Path (Join-Path $fake "tailscale.cmd") -Encoding ascii
$env:PATH = "$fake;$env:PATH"

# a spare block: board N, mcp N+2, pool N-99, broker N-100, code N+10 all free
function BlockFree($n) { foreach ($p in @($n, ($n + 2), ($n - 99), ($n - 100), ($n + 10))) { if (-not (Free $p)) { return $false } }; $true }
$N = $From; while ($N -lt 60000 -and -not (BlockFree $N)) { $N += 1000 }
$h = Join-Path $AppDir "heronry.exe"
"bundle $AppDir; temp $T; block board=$N mcp=$($N + 2) pool=$($N - 99) broker=$($N - 100) code=$($N + 10)"
Check (Test-Path $h) "heronry.exe (console CLI) is in the bundle"

# ---- home A
$cfgA = Profile "a"
"== [a] heronry init --harness claude --ports $N"
& $h init --harness claude --ports $N 2>&1 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "[a] init exit 0"
$codeA = CodePort $cfgA
Check ($codeA -eq ($N + 10)) "[a] init pinned code_server.port = $codeA (block + 10 = $($N + 10))"
$B = "http://127.0.0.1:$N"
$xadm = @{ "X-Admin" = (Get-Content (Join-Path $cfgA "secrets\admin.token") -Raw).Trim() }  # never printed
# Admin -> Remote access is an admin HUMAN's route: the first human init minted (owner), by its token
$ownerTok = (Get-Content (Join-Path $cfgA "secrets\tokens.json") -Raw | ConvertFrom-Json).owner
$adm = @{ "X-Participant" = "owner"; "X-Token" = "$ownerTok" }
$listener = $null
$reached = $false  # the whole sequence ran; an exception that skips to the stop is a failure, never a pass
try {
  "== [a] heronry start"
  & $h start 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "[a] start exit 0"

  # (d) the Code tab: nothing on the code port, then a listener of another home
  $null = Invoke-RestMethod "$B/v1/participants" -Method Post -Headers $xadm -ContentType "application/json" `
    -Body '{"id":"drill.agent","handle":"drill.agent","role":"engineer","type":"agent"}' -ErrorAction SilentlyContinue
  $who = @{ "X-Participant" = "drill.agent" }
  $v = (Invoke-RestMethod "$B/v1/code" -Headers $who).value
  "   /v1/code (nothing listening): port=$($v.port) running=$($v.running) foreign=$($v.foreign)"
  Check ($v.port -eq $codeA -and -not $v.running -and -not $v.foreign) "[a] /v1/code reads its own pinned port $codeA, not running"
  $listener = Start-Job -ArgumentList $codeA -ScriptBlock {
    param($port)
    $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port); $l.Start()
    while ($true) {
      $c = $l.AcceptTcpClient(); $s = $c.GetStream(); $r = [IO.StreamReader]::new($s)
      $line = $r.ReadLine(); while (($x = $r.ReadLine()) -and $x -ne "") { }
      $body = if ($line -match "^GET /__edp/home ") { '{"home_id":"0000000000000000"}' } elseif ($line -match "^GET /healthz ") { '{"status":"alive"}' } else { "" }
      $st = if ($body) { "200 OK" } else { "404 Not Found" }
      $b = [Text.Encoding]::ASCII.GetBytes("HTTP/1.1 $st`r`nContent-Length: $($body.Length)`r`nConnection: close`r`n`r`n$body")
      $s.Write($b, 0, $b.Length); $c.Close()
    }
  }
  Start-Sleep -Seconds 2
  $v = (Invoke-RestMethod "$B/v1/code" -Headers $who).value
  "   /v1/code (another home's listener on $codeA): running=$($v.running) foreign=$($v.foreign)"
  Check (-not $v.running -and $v.foreign) "[a] another home's code-server on the port is foreign, never adopted"

  # (d) a second home: its own code port while home a runs
  $cfgB = Profile "b"
  "== [b] heronry init --harness claude (defaults; home a holds its block)"
  & $h init --harness claude 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "[b] init exit 0"
  $codeB = CodePort $cfgB
  Check ($codeB -and $codeB -ne $codeA -and $codeB -ne 9410) "[b] init pinned its own code_server.port = $codeB (a has $codeA; never the 9410 default)"
  $null = Profile "a"

  # (c) Remote access applies on the launched board
  $tn = (Invoke-RestMethod "$B/v1/admin/tailnet" -Headers $adm).value
  "   /v1/admin/tailnet: tailnet_url=$($tn.tailnet_url) public_mode=$($tn.public_mode)"
  if ($tn.tailnet_url -ne "https://$FAKE_NAME") {
    Check $false "the board sees the FAKE tailscale (refusing to apply against a real one)"
  } else {
    # public mode needs a human and an agent credential (service.public_startup_error); a fresh home that has
    # never spawned a seat has no agent secret yet: seed drill entries into THIS temp home's tokens.json only
    $tokf = Join-Path (Join-Path $cfgA "secrets") "tokens.json"
    $tok = if (Test-Path $tokf) { Get-Content $tokf -Raw | ConvertFrom-Json } else { [pscustomobject]@{} }
    $humans = @($tok.PSObject.Properties | Where-Object { $_.Name -ne "agents" })
    if (-not $humans) { $tok | Add-Member -NotePropertyName "drill-owner" -NotePropertyValue ([guid]::NewGuid().ToString("N")) }
    if (-not $tok.agents -or -not @($tok.agents.PSObject.Properties).Count) {
      $tok | Add-Member -Force -NotePropertyName "agents" -NotePropertyValue ([pscustomobject]@{ "drill.agent" = [guid]::NewGuid().ToString("N") })
      "   seeded an agent credential into the temp home's tokens.json (a fresh home has none before its first spawn)"
    }
    # no BOM (PS 5.1's -Encoding utf8 writes one, and the board's JSON read then fails: every token "invalid")
    [IO.File]::WriteAllText($tokf, ($tok | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
    $code = 0; $text = ""
    try { $r = Invoke-WebRequest "$B/v1/admin/tailnet/apply" -Method Post -Headers $adm -ContentType "application/json" -Body '{"force":true}' -UseBasicParsing; $code = $r.StatusCode; $text = $r.Content }
    catch { $code = [int]$_.Exception.Response.StatusCode; $text = $_.ErrorDetails.Message }
    "   apply: $code $text"
    Check ($code -eq 200 -and $text -notmatch "set by the environment") "[a] Admin -> Remote access applies: no 'EDP8_HOST is set by the environment' refusal"
    $cfgText = Toml $cfgA  # never $t: PowerShell names are case-insensitive and $T is the temp root
    Check ($cfgText -match '(?m)^host\s*=\s*"127\.0\.0\.1"' -and $cfgText -match "public_url\s*=\s*`"https://$([regex]::Escape($FAKE_NAME))`"") "[a] config.toml now holds board.host and network.public_url"
    Check ((Get-Content $log -Raw) -match "serve --bg --https=443 http://127\.0\.0\.1:$N") "[a] the fake tailscale got 'serve --bg --https=443 http://127.0.0.1:$N'"
    $code = 0; try { $code = (Invoke-WebRequest "$B/v1/admin/tailnet/remove" -Method Post -Headers $adm -UseBasicParsing).StatusCode } catch { }
    Check ($code -eq 200 -and (Toml $cfgA) -notmatch "public_url") "[a] remove undoes it (trusted mode again)"
  }
  $reached = $true
} catch {
  "   error: $($_.Exception.Message) $($_.ErrorDetails.Message)"
} finally {
  Check $reached "the drill ran every step (no error cut it short)"
  if ($listener) { Stop-Job $listener; Remove-Job $listener -Force }
  $null = Profile "a"
  "== [a] heronry stop"
  & $h stop --force 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "[a] stop exit 0"
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($AppDir, [StringComparison]::OrdinalIgnoreCase) -and
  ($_.CommandLine -match "--heronry-service") })
$left | ForEach-Object { "   left: $($_.ProcessId) $($_.CommandLine)" }
Check ($left.Count -eq 0) "stop leaves no service process of the bundle running ($($left.Count) found)"
foreach ($p in @($N, ($N + 2), ($N - 99), ($N - 100), ($N + 10))) { Check (Free $p) "port $p is free" }
if (-not $Keep) { Set-Location $env:TEMP; Remove-Item -Recurse -Force $T -ErrorAction SilentlyContinue }
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
