# S2 spike (s-725ef36c03, design-b6a55eed13 §4.G): update in place on a PRIVATE install.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_update_in_place.ps1 -Phase build
#   ... -Phase upgrade | rollback-corrupt | rollback-held | rollback-unhealthy | tray | stopproof | scope | uv | clean
#   (S10: `tray` = the tray's Install update path: a private desktop window open, `heronry update --relaunch-app`, the
#   window closed and reopened by the runner; `stopproof` = a private `stop --force` while the fleet runs (fleet pids
#   unchanged) and a stop refused when an inherited EDP8_RUN_DIR points outside the home (c-1ccf55aec4); `scope` = the
#   scope pin and MajorUpgrade are in the built MSI)
#
# Never touches the installed fleet: the spike MSIs carry their own identity (bundle io.github.visak13.s2spike,
# "Heronry S2 Spike": a different UpgradeCode, install folder, Start-menu entry and HKCU key; a spike MSI built with
# the real bundle id gets the fleet's UpgradeCode and would MajorUpgrade the fleet's own install), no PATH component
# (its GUID and HKCU key are shared with the fleet), a private EDP_HOME and free ports picked at run time, and
# processes are only ever identified by an executable path or command line under the private folders.
#
# build: the working tree (HEAD + this worktree's changes) -> 4 wheels at 0.9.1 and at 0.9.2.dev0 -> one MSI each
#        (build_windows.ps1 -Fresh -NoCliPath), plus a release dir per version holding the MSI + SHA256SUMS.
param([ValidateSet("build", "install", "upgrade", "rollback-corrupt", "rollback-held", "rollback-unhealthy", "tray", "stopproof", "scope", "uv", "restart", "reinstall", "clean")]
  [string]$Phase = "build", [string[]]$Versions = @("0.9.1", "0.9.2.dev0"))
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$T = Join-Path $v8 ".data\s2-spike"
$Ev = Join-Path $v8 "docs\evidence\e0cec-s10"
New-Item -ItemType Directory -Force -Path $T, $Ev | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function Stamp { (Get-Date).ToString("HH:mm:ss") }
$sw = [Diagnostics.Stopwatch]::StartNew()
$mainV8 = Join-Path (Split-Path -Parent (Resolve-Path (git -C $root rev-parse --git-common-dir)).Path) "v8"   # the main checkout; read only (the served SPA dist for the edp8 wheel)

# ------------------------------------------------------------------------------------------ fleet safety (m-62718a64f5)
# Every phase runs as its own `powershell -NoProfile -File` process with every EDP*/HERONRY* variable wiped, so no
# inherited EDP8_RUN_DIR can point a private command at the fleet (the S2 incident, p-7d52c9cf). The fleet's records
# are only READ, to snapshot its pids before and after the phase; any change stops the drill.
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$FleetRun = Join-Path $env:LOCALAPPDATA "heronry\run"
$FleetApp = Join-Path $env:LOCALAPPDATA "Programs\Heronry contributors"
function FleetPids { foreach ($s in "board", "broker", "pool", "mcp", "bridge", "supervisor") {
  $f = Join-Path $FleetRun "$s.json"; if (Test-Path $f) { [int](Get-Content $f -Raw | ConvertFrom-Json).pid } } }
function FleetSnap {
  ((@("board", "broker", "pool", "mcp", "bridge", "supervisor") | ForEach-Object {
    $f = Join-Path $FleetRun "$_.json"
    $p = if (Test-Path $f) { (Get-Content $f -Raw | ConvertFrom-Json).pid } else { "none" }
    $alive = if ($p -ne "none" -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { "up" } else { "down" }
    "$_=$p/$alive" }) -join " ") + " seats=" + (FleetSeats)   # service pid files, then the live seat pids
}
function FleetSeats {  # the fleet's live seat processes, read-only from its pool's session list (c-1ccf55aec4: "every live seat")
  try {
    $port = (Get-Content (Join-Path $FleetRun "pool.json") -Raw | ConvertFrom-Json).port
    $rows = @(Invoke-RestMethod "http://127.0.0.1:$port/v1/sessions" -TimeoutSec 10 | ForEach-Object { $_ })
    $ids = @($rows | Where-Object { $_.proc -and $_.proc.pid -and $_.state -notin "done", "closed" } | ForEach-Object { [int]$_.proc.pid } |
      Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } | Sort-Object -Unique)
    "$($ids.Count):" + ($ids -join ",")
  } catch { "unreadable" }
}
function Under($pr, $dir) {
  ($pr.ExecutablePath -and $pr.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase)) -or
  ($pr.CommandLine -and $pr.CommandLine.IndexOf($dir, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}
function StopPrivate {
  # the private stack, by pid only, never `heronry stop` (architect STOP-RULE m-c201a683c9)
  $fleet = @(FleetPids)
  $ps = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (Under $_ $T) })
  "   private pids: $(($ps | ForEach-Object { "$($_.ProcessId):$($_.Name)" }) -join ' ')"
  foreach ($pr in $ps) {
    if ($fleet -contains [int]$pr.ProcessId -or (Under $pr $FleetApp)) { "ABORT pid $($pr.ProcessId) is the fleet's"; exit 3 }
  }
  foreach ($pr in $ps) { Stop-Process -Id $pr.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (Under $_ $T) })
  "   private pids left: $($left.Count)"
}
function PreCheck($homeDir) {
  # every record in the private run dir names a pid under the private folders (or a dead one), else abort
  $fleet = @(FleetPids)
  foreach ($f in Get-ChildItem (Join-Path $homeDir ".run") -Filter "*.json" -ErrorAction SilentlyContinue) {
    $rec = Get-Content $f.FullName -Raw | ConvertFrom-Json
    foreach ($p in @($rec.pid, $rec.root.pid) | Where-Object { $_ }) {
      if ($fleet -contains [int]$p) { "ABORT $($f.Name) names fleet pid $p"; exit 3 }
      $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
      if ($pr -and -not (Under $pr $T)) { "ABORT $($f.Name) names pid $p ($($pr.ExecutablePath)) outside $T"; exit 3 }
    }
  }
  "PASS  pre-check: every record in $homeDir\.run names a private (or dead) pid"
}
$Fleet0 = FleetSnap
"   fleet before: $Fleet0"

if ($Phase -eq "build") {
  foreach ($V in $Versions) {
    "== $(Stamp) build $V"
    $Src = Join-Path $T "src-$V"
    if (Test-Path $Src) { cmd /c rmdir /s /q "$Src" }
    New-Item -ItemType Directory -Path $Src | Out-Null
    & git -C $root archive --format=tar -o "$T\src.tar" HEAD edp-contracts edp-pool edp-broker v8 CHANGELOG.md LICENSE NOTICE
    & "$env:SystemRoot\System32\tar.exe" -xf "$T\src.tar" -C $Src
    Remove-Item "$T\src.tar"
    # overlay this worktree's uncommitted changes (the spike's updater code must be IN both versions' wheels)
    foreach ($f in @(& git -C $root diff --name-only HEAD) + @(& git -C $root ls-files --others --exclude-standard -- v8/src v8/desktop v8/scripts)) {
      if ($f -and (Test-Path (Join-Path $root $f))) { Copy-Item (Join-Path $root $f) (Join-Path $Src $f) -Force }
    }
    # stamp the version: the four packages' version, the sibling pins, edp8.__version__
    $files = "edp-contracts\pyproject.toml", "edp-pool\pyproject.toml", "edp-broker\pyproject.toml", "v8\pyproject.toml", "v8\src\edp8\__init__.py"
    foreach ($f in $files) {
      $p = Join-Path $Src $f
      $txt = [IO.File]::ReadAllText($p)
      $txt = $txt -replace '(?m)^version = "0\.9\.1"', "version = `"$V`"" -replace '==0\.9\.1"', "==$V`"" -replace '__version__ = "0\.9\.1"', "__version__ = `"$V`""
      [IO.File]::WriteAllText($p, $txt)
    }
    $dist = "$Src\v8\src\edp8\webapp\dist"
    robocopy "$mainV8\src\edp8\webapp\dist" $dist /E /NFL /NDL /NJH /NJS /NP | Out-Null
    Get-ChildItem -Recurse -File $dist | ForEach-Object { $_.LastWriteTime = Get-Date }
    $W = Join-Path $T "wheels-$V"
    if (Test-Path $W) { Remove-Item -Recurse -Force $W }
    $env:EDP8_WEB_AUTOBUILD = "0"
    foreach ($p in "edp-contracts", "edp-pool", "edp-broker", "v8") {
      & uv build --offline --wheel --out-dir $W "$Src\$p" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
    }
    Check (@(Get-ChildItem "$W\*.whl").Count -eq 4) "four wheels at $V ($((Get-ChildItem "$W\*.whl").Name -join ', '))"
    # the desktop project, with the spike identity
    $D = "$Src\v8\desktop"
    $txt = [IO.File]::ReadAllText("$D\pyproject.toml")
    $txt = $txt -replace 'bundle = "io\.github\.visak13"', 'bundle = "io.github.visak13.s2spike"' `
            -replace 'formal_name = "Heronry Desktop"', 'formal_name = "Heronry S2 Spike"' `
            -replace '(?m)^version = "0\.9\.1"', "version = `"$V`"" -replace '==0\.9\.1"', "==$V`""
    [IO.File]::WriteAllText("$D\pyproject.toml", $txt)
    Check ($txt -match 's2spike' -and $txt -match "edp8==$([regex]::Escape($V))") "spike identity + version pins in desktop\pyproject.toml"
    $bt = [Diagnostics.Stopwatch]::StartNew()
    Copy-Item "$mainV8\desktop\wheels\proxy_tools-0.1.0-py3-none-any.whl" $W -ErrorAction SilentlyContinue
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$D\scripts\build_windows.ps1" -Wheels $W -Fresh -NoCliPath `
        -BuildEnv "$mainV8\desktop\.buildenv" 2>&1 |
      Tee-Object -FilePath "$T\build-$V.log" | Select-String -Pattern "^==|^MSI|error|fail|throw" | ForEach-Object { "   $_" }
    "   build took $([math]::Round($bt.Elapsed.TotalSeconds))s (log $T\build-$V.log)"
    $msi = Get-ChildItem "$D\dist\*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
    Check ([bool]$msi) "an MSI for $V"
    if ($msi) {
      $R = Join-Path $T "release-$V"
      if (Test-Path $R) { Remove-Item -Recurse -Force $R }
      New-Item -ItemType Directory -Path $R | Out-Null
      Copy-Item $msi.FullName $R
      $h = (Get-FileHash (Join-Path $R $msi.Name) -Algorithm SHA256).Hash.ToLower()
      Set-Content -Path "$R\SHA256SUMS" -Value "$h  $($msi.Name)" -Encoding ascii
      Copy-Item "$D\build\heronry\windows\app\heronry.wxs" "$Ev\heronry-$V.wxs"
      "   $($msi.Name) $([math]::Round($msi.Length/1MB,1)) MB sha256 $h"
    }
  }
}
# ------------------------------------------------------------------------------------------ the private install
$Inst = Join-Path $T "install"          # INSTALLFOLDER of the spike product
$HomeDir = Join-Path $T "home"          # its EDP_HOME
$Exe = Join-Path $Inst "heronry.exe"
$Py = "$mainV8\.venv\Scripts\python.exe" # read only: runs the stub harness and the MSI queries, outside $Inst
$Seat = "engineer.s2-drill"
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function UseEnv($homeDir, $envFile) {
  Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "SLACK*" -or
    @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
  if (-not (Test-Path $envFile)) {
    $fleet = 9400, 9402, 9301, 9300, 19400, 19402, 19301, 19300
    $ports = @{}; foreach ($k in "EDP8_PORT", "EDP8_MCP_PORT", "EDP_POOL_PORT", "EDP_BROKER_PORT", "EDP_CODE_PORT") {
      do { $p = FreePort } while ($fleet -contains $p); $ports[$k] = $p }
    $ports | ConvertTo-Json | Set-Content -Path $envFile -Encoding ascii
  }
  $ports = Get-Content $envFile -Raw | ConvertFrom-Json
  foreach ($k in $ports.PSObject.Properties.Name) { Set-Item "Env:$k" ([string]$ports.$k) }
  $env:EDP_HOME = $homeDir
  $env:EDP8_HOST = "127.0.0.1"   # no EDP8_PUBLIC_URL: it switches a fresh home to public mode, which refuses start
  $env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
  $env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
  Copy-Item "$root\edp-pool\tests\fixtures\stub_harness.py" "$T\stub_harness.py" -Force
  Set-Content -Path "$T\claude-stub.cmd" -Value "@`"$Py`" `"$T\stub_harness.py`" %*" -Encoding ascii
  $env:EDP_CLAUDE_BIN = "$T\claude-stub.cmd"; $env:EDP_SPAWN_MODE = "headless"; $env:EDP_SHADOW = "0"
}
function Health { try { $h = Invoke-RestMethod "http://127.0.0.1:$env:EDP8_PORT/v1/health" -TimeoutSec 5; "$($h.version)$($h.value.version)" } catch { $null } }
function Installed { & $Py -c "import sys; sys.path.insert(0, sys.argv[2]); from edp8.update_helper import msi_property, related_products; print(','.join(r['code'] + '=' + r['version'] for r in related_products(msi_property(sys.argv[1], 'UpgradeCode'))))" (Get-ChildItem "$T\release-0.9.1\*.msi").FullName "$root\v8\src" }
function PoolRow($h) { try { @(Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10) | ForEach-Object { $_ } | Where-Object { $_.handle -eq $h } | Select-Object -Last 1 } catch { $null } }
function Live($h) { try { (Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/liveness/$h" -TimeoutSec 10).state } catch { $null } }
function EnsureUp {
  # a fresh private home needs `init` (admin token file, agent home) as every real install has had since first run
  if (-not (Test-Path (Join-Path $env:EDP_HOME "admin.token"))) {
    & $Exe init --harness claude --yes 2>&1 | ForEach-Object { "   init: $($_ -replace 'code=\S+', 'code=<redacted>')" } }
  if (-not (Health)) { & $Exe start --no-browser 2>&1 | ForEach-Object { "   $_" } }
  if ((Live $Seat) -ne "alive") {
    try { Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/reap/$Seat" -Method Post -TimeoutSec 30 | Out-Null } catch { }
    $b = @{ role = "engineer"; handle = $Seat; mode = "headless" } | ConvertTo-Json
    try { $out = Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/spawn" -Method Post -Body $b -ContentType "application/json" -TimeoutSec 90
      "   spawned stub seat $Seat : $($out | ConvertTo-Json -Compress -Depth 3)" } catch { "   spawn error: $($_.Exception.Message)" }
    Start-Sleep -Seconds 3
  }
  $row = PoolRow $Seat
  "   health $(Health); seat $Seat row $($row.state) pid $($row.proc.pid) liveness $(Live $Seat)"
}
function RunUpdate($label, $releaseDir, [hashtable]$extraEnv = @{}, [string[]]$extraArgs = @()) {
  $out = Join-Path $Ev $label
  if (Test-Path $out) { Remove-Item -Recurse -Force $out }
  New-Item -ItemType Directory -Path $out | Out-Null
  $result = Join-Path $HomeDir "update\update-result.json"
  $log = Join-Path $HomeDir ".data\logs\update.log"
  Remove-Item $result, (Join-Path $HomeDir "update\update-plan.json") -ErrorAction SilentlyContinue   # a plan with no result reads as "staged"
  if (Test-Path $log) { Remove-Item $log }
  foreach ($k in $extraEnv.Keys) { Set-Item "Env:$k" $extraEnv[$k] }
  $u = [Diagnostics.Stopwatch]::StartNew()
  "   $(Stamp) heronry update --release-url $releaseDir --previous-url $T\release-0.9.1"
  & $Exe update --release-url $releaseDir --previous-url "$T\release-0.9.1" @extraArgs 2>&1 | Tee-Object -FilePath "$out\cli.txt" | ForEach-Object { "   | $_" }
  $rc = $LASTEXITCODE
  foreach ($k in $extraEnv.Keys) { Remove-Item "Env:$k" }
  "   cli exit $rc after $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  if ($rc -ne 0) { $script:R = @{ rc = $rc; state = "refused"; res = [pscustomobject]@{ state = "refused"; reason = (Get-Content "$out\cli.txt" -Raw) }; out = $out }; return }
  $deadline = (Get-Date).AddMinutes(20)
  while (-not (Test-Path $result) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
  "   $(Stamp) outcome after $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  $res = if (Test-Path $result) { Get-Content $result -Raw | ConvertFrom-Json } else { $null }
  foreach ($f in $result, $log, (Join-Path $HomeDir "update\update-plan.json"), (Join-Path $HomeDir "update\update-helper.out")) {
    if (Test-Path $f) { Copy-Item $f $out }
  }
  Get-ChildItem (Join-Path $HomeDir ".data\logs") -Filter "msiexec-*.log" -ErrorAction SilentlyContinue | ForEach-Object { Move-Item $_.FullName $out -Force }
  if (Test-Path $log) { Get-Content $log | ForEach-Object { "   log $_" } }
  "   result: $($res | ConvertTo-Json -Compress -Depth 4)"
  if (-not $res) { $res = [pscustomobject]@{ state = "no-result"; reason = "no update-result.json within 20 min" } }
  $script:R = @{ rc = $rc; state = $res.state; res = $res; out = $out; seconds = [math]::Round($u.Elapsed.TotalSeconds, 1) }
}

if ($Phase -ne "build" -and $Phase -ne "uv") { PreCheck $HomeDir; UseEnv $HomeDir (Join-Path $T "env.json"); "   ports board=$env:EDP8_PORT pool=$env:EDP_POOL_PORT mcp=$env:EDP8_MCP_PORT broker=$env:EDP_BROKER_PORT; home $HomeDir" }

if ($Phase -eq "install") {
  "== $(Stamp) install 0.9.1 (spike identity) privately"
  Check (-not (Installed)) "no spike product installed yet"
  $msi = (Get-ChildItem "$T\release-0.9.1\*.msi").FullName
  $wxs = Get-Content "$Ev\heronry-0.9.1.wxs" -Raw
  Check ($wxs -notmatch "CustomAction") "the spike wxs runs no custom action (nothing touches a default home at install)"
  $u = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process msiexec -ArgumentList @("/i", "`"$msi`"", "/qb", "/norestart", "/l*v", "`"$Ev\msiexec-first-install-0.9.1.log`"",
    "MSIINSTALLPERUSER=1", "ALLUSERS=2", "INSTALLFOLDER=`"$Inst`"") -Wait -PassThru
  "   msiexec exit $($p.ExitCode) in $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  Check ($p.ExitCode -eq 0) "0.9.1 installed"
  Check (Test-Path $Exe) "heronry.exe at $Exe"
  "   installed: $(Installed)"
  & $Exe version 2>&1 | ForEach-Object { "   $_" }
  & $Exe init --harness claude --yes 2>&1 | Select-Object -Last 3 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "init exit 0"
  EnsureUp
  Check ((Health) -match "^0\.9\.1") "board healthy at 0.9.1"
  Check ((Live $Seat) -eq "alive") "a stub seat is live"
}

function GuiPids { @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Inst, [StringComparison]::OrdinalIgnoreCase) -and $_.Name -like "Heronry*Spike*.exe" } | ForEach-Object { [int]$_.ProcessId }) }

if ($Phase -like "rollback-*" -or $Phase -eq "upgrade" -or $Phase -eq "tray") {
  $before = Installed
  "== $(Stamp) $Phase from $before"
  EnsureUp
  $rel = "$T\release-0.9.2.dev0"
  $env_ = @{}
  $holder = $null
  if ($Phase -eq "rollback-corrupt") {
    $rel = "$T\release-corrupt"
    if (Test-Path $rel) { Remove-Item -Recurse -Force $rel }
    New-Item -ItemType Directory -Path $rel | Out-Null
    $src = Get-ChildItem "$T\release-0.9.2.dev0\*.msi"
    $dst = Join-Path $rel $src.Name
    Copy-Item $src.FullName $dst
    # damage the embedded cabinet (the bulk of the file) and re-list the sum: the package opens, the install fails.
    # One 64 KB hit at 60% was not enough: on one build it landed in a stretch the installer never checks
    # (CheckCRC=0), and the damaged package installed "fine". So there are eight hits, spread from 40% to 96%.
    $fs = [IO.File]::Open($dst, "Open", "ReadWrite"); $rnd = New-Object Random 7; $junk = New-Object byte[] 65536
    foreach ($at in 0.40, 0.48, 0.56, 0.64, 0.72, 0.80, 0.88, 0.96) {
      $fs.Position = [long]($fs.Length * $at); $rnd.NextBytes($junk); $fs.Write($junk, 0, $junk.Length) }
    $fs.Close()
    $h = (Get-FileHash $dst -Algorithm SHA256).Hash.ToLower()
    Set-Content -Path "$rel\SHA256SUMS" -Value "$h  $($src.Name)" -Encoding ascii
  }
  if ($Phase -eq "rollback-held") {
    $target = Join-Path $Inst "app\heronry\__main__.py"
    $holder = Start-Process powershell -ArgumentList @("-NoProfile", "-Command",
      "`$f = [IO.File]::Open('$target', 'Open', 'Read', 'Read'); Start-Sleep -Seconds 240; `$f.Close()") -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 2
    "   holder pid $($holder.Id) opened $target with read-only sharing (the app can still load it; nothing can replace it)"
  }
  if ($Phase -eq "rollback-unhealthy") { $env_ = @{ HERONRY_UPDATE_FAULT = "unhealthy" } }
  $xargs = @(); $guiBefore = @()
  if ($Phase -eq "tray") {
    # the tray's Install update calls updater.apply({"relaunch-app": True}); `--relaunch-app` is that same option from the CLI
    # (tests/test_desktop.py pins the tray's call). A private desktop window is opened first so there is a window to close.
    $xargs = @("--relaunch-app")
    Start-Process (Join-Path $Inst "Heronry S2 Spike.exe") -WindowStyle Minimized | Out-Null
    $d = (Get-Date).AddSeconds(60); while (-not (GuiPids) -and (Get-Date) -lt $d) { Start-Sleep -Seconds 1 }
    $guiBefore = @(GuiPids)
    "   private desktop window pids before: $($guiBefore -join ',')"
    Check ($guiBefore.Count -ge 1) "a private desktop window is open before the update"
  }
  RunUpdate $Phase $rel $env_ $xargs   # prints as it goes; the outcome lands in $script:R
  $r = $script:R
  if ($holder) { Stop-Process -Id $holder.Id -Force -ErrorAction SilentlyContinue }
  $after = Installed
  $row = PoolRow $Seat
  "   installed after: $after; health $(Health); seat $Seat row $($row.state) liveness $(Live $Seat)"
  $r.res | Add-Member -NotePropertyName installed_before -NotePropertyValue $before -Force
  $r.res | Add-Member -NotePropertyName installed_after -NotePropertyValue $after -Force
  $r.res | Add-Member -NotePropertyName seat_after -NotePropertyValue (Live $Seat) -Force
  $r.res | Add-Member -NotePropertyName drill_seconds -NotePropertyValue $r.seconds -Force
  $r.res | ConvertTo-Json -Depth 5 | Set-Content -Path "$($r.out)\summary.json" -Encoding utf8
  if ($Phase -eq "tray") {
    $d = (Get-Date).AddSeconds(60); while (-not (@(GuiPids | Where-Object { $guiBefore -notcontains $_ }).Count) -and (Get-Date) -lt $d) { Start-Sleep -Seconds 1 }
    $guiAfter = @(GuiPids)
    "   private desktop window pids after: $($guiAfter -join ',')"
    Check (@($guiBefore | Where-Object { $guiAfter -contains $_ }).Count -eq 0 -and $guiAfter.Count -ge 1) "the window was closed and the new version's window relaunched by the runner"
    Get-Process | Where-Object { $guiAfter -contains $_.Id } | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  if ($Phase -eq "upgrade" -or $Phase -eq "tray") {
    Check ($r.state -eq "ok") "update outcome ok"
    Check ($after -match "=0\.9\.2" -and $after -notmatch "0\.9\.1") "0.9.2 installed, 0.9.1 gone (one product: $after)"
    Check ((Health) -match "^0\.9\.2") "board healthy at 0.9.2 ($(Health))"
    Check ((Select-String -Path "$($r.out)\msiexec-install.log" -Pattern "RemoveExistingProducts" -Quiet)) "msiexec log: MajorUpgrade removed the old product inside the install transaction (no separate uninstall)"
    Check (@($r.res.parked).Count -ge 1 -and @($r.res.resumed).Count -eq @($r.res.parked).Count) "seats parked $(@($r.res.parked) -join ',') and resumed $(@($r.res.resumed) -join ',')"
    Check ((Live $Seat) -eq "alive") "the seat is live after the update"
  } else {
    Check ($r.state -eq "rolled_back") "outcome rolled_back"
    Check ([bool]$r.res.reason) "a plain reason: $($r.res.reason)"
    # the version, not the ProductCode: a rollback reinstalls the CACHED previous MSI, which may be another build
    Check (($after -replace '^\{[^}]*\}=', '') -eq ($before -replace '^\{[^}]*\}=', '')) "the previous version is installed ($after; before $before)"
    Check ((Health) -match "^0\.9\.1") "board healthy at 0.9.1 ($(Health))"
    Check ((Live $Seat) -eq "alive") "the seat is live again"
  }
  $plan = Get-Content "$($r.out)\update-plan.json" -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json
  $helperOut = Get-Content "$($r.out)\update-helper.out" -Raw -ErrorAction SilentlyContinue
  Check ($plan -and -not $plan.install_dir.Equals((Split-Path $plan.result), [StringComparison]::OrdinalIgnoreCase) -and
         (Split-Path $plan.result).StartsWith($HomeDir, [StringComparison]::OrdinalIgnoreCase)) "the runner ran from $HomeDir\update, outside $Inst"
}

if ($Phase -eq "reinstall") {
  # a rebuilt 0.9.1 over the installed 0.9.1 (AllowSameVersionUpgrades): the drill's own way to refresh the old side
  "== $(Stamp) reinstall the rebuilt 0.9.1 over $(Installed)"
  StopPrivate
  foreach ($row in (Installed) -split ",") {  # a newer spike product blocks the downgrade: remove it first
    if ($row -and $row -notmatch "=0\.9\.1$") { $code = ($row -split "=")[0]
      $p = Start-Process msiexec -ArgumentList @("/x", $code, "/qn", "/norestart", "/l*v", "`"$T\msiexec-reinstall-remove.log`"") -Wait -PassThru
      "   removed $row first: msiexec /x exit $($p.ExitCode)" }
  }
  $msi = (Get-ChildItem "$T\release-0.9.1\*.msi").FullName
  $p = Start-Process msiexec -ArgumentList @("/i", "`"$msi`"", "/qb", "/norestart", "/l*v", "`"$T\msiexec-reinstall-0.9.1.log`"",
    "MSIINSTALLPERUSER=1", "ALLUSERS=2", "INSTALLFOLDER=`"$Inst`"") -Wait -PassThru
  "   msiexec exit $($p.ExitCode); installed $(Installed)"
  Check ($p.ExitCode -eq 0) "rebuilt 0.9.1 installed"
  EnsureUp
  Check ((Health) -match "^0\.9\.1") "board healthy ($(Health))"
  Check ((Live $Seat) -eq "alive") "the stub seat is live"
}

if ($Phase -eq "restart") {
  "== $(Stamp) restart the private stack"
  StopPrivate
  EnsureUp
  Check ((Health) -match "^0\.9") "board healthy ($(Health))"
  Check ((Live $Seat) -eq "alive") "the stub seat is live"
}

if ($Phase -eq "stopproof") {
  "== $(Stamp) c-1ccf55aec4: a private stop only stops the private install, while the fleet runs"
  EnsureUp
  $mine = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (Under $_ $T) } | ForEach-Object { [int]$_.ProcessId })
  Check ($mine.Count -ge 3) "the private stack is running ($($mine.Count) processes under the private folders)"
  Check ((@(FleetPids)).Count -ge 1) "the fleet is running ($(FleetSnap))"
  # (1) an inherited EDP8_RUN_DIR outside the home (the S2 incident): a decoy run dir and a decoy process, NOT the fleet's
  $decoyRun = Join-Path $T "decoy-run"; New-Item -ItemType Directory -Force -Path $decoyRun | Out-Null
  $decoy = Start-Process powershell -ArgumentList @("-NoProfile", "-Command", "Start-Sleep -Seconds 120 # $T") -WindowStyle Hidden -PassThru
  foreach ($svc in "board", "pool", "broker", "mcp", "bridge", "supervisor") {
    @{ pid = $decoy.Id; root = @{ pid = $decoy.Id } } | ConvertTo-Json | Set-Content -Path (Join-Path $decoyRun "$svc.json") -Encoding ascii }
  $env:EDP8_RUN_DIR = $decoyRun
  $o = & $Exe stop --force 2>&1; $rc = $LASTEXITCODE
  Remove-Item Env:EDP8_RUN_DIR
  $o | ForEach-Object { "   | $_" }
  Check ($rc -eq 2 -and ($o -join " ") -match "refused") "stop with EDP8_RUN_DIR outside EDP_HOME is refused (exit $rc)"
  Check ([bool](Get-Process -Id $decoy.Id -ErrorAction SilentlyContinue)) "the process the foreign run dir named is still alive"
  Stop-Process -Id $decoy.Id -Force -ErrorAction SilentlyContinue
  Check (@($mine | Where-Object { -not (Get-Process -Id $_ -ErrorAction SilentlyContinue) }).Count -eq 0) "the private stack was not touched by the refused stop"
  # (2) the real thing: this install's own `stop --force` stops its own processes and nobody else's
  $o = & $Exe stop --force 2>&1; $rc = $LASTEXITCODE
  $o | ForEach-Object { "   | $_" }
  Check ($rc -eq 0) "the private stop --force exits 0"
  Start-Sleep -Seconds 3
  $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (Under $_ $T) -and $_.Name -notlike "powershell*" })
  Check ($left.Count -eq 0) "no private service is left ($($left.Count))"
  EnsureUp   # brings the private stack back for the next phases
}

if ($Phase -eq "scope") {
  "== $(Stamp) the scope pin and the MajorUpgrade in the built MSI (read-only)"
  $wxs = Get-Content "$Ev\heronry-0.9.1.wxs" -Raw
  Check ($wxs -match 'Id="HeronryScopePin"' -and $wxs -match "NOT \(ALLUSERS = 1\)" -and $wxs -match "<MajorUpgrade" -and $wxs -match 'Scope="perUserOrMachine"') "the generated heronry.wxs carries the scope pin, the MajorUpgrade and the per-user scope"
  # read-only: the built MSI's LaunchCondition and MajorUpgrade rows, through the Windows Installer COM database (no install,
  # so no elevation prompt can appear and nothing per-machine can be written)
  $msi = (Get-ChildItem "$T\release-0.9.2.dev0\*.msi").FullName
  $wi = New-Object -ComObject WindowsInstaller.Installer
  function Rows($db, $q) { $v = $db.GetType().InvokeMember("OpenView", "InvokeMethod", $null, $db, @($q)); $v.GetType().InvokeMember("Execute", "InvokeMethod", $null, $v, $null) | Out-Null
    $out = @(); while ($r = $v.GetType().InvokeMember("Fetch", "InvokeMethod", $null, $v, $null)) { $out += $r.GetType().InvokeMember("StringData", "GetProperty", $null, $r, @(1)) }; $v.GetType().InvokeMember("Close", "InvokeMethod", $null, $v, $null) | Out-Null; $out }
  $db = $wi.GetType().InvokeMember("OpenDatabase", "InvokeMethod", $null, $wi, @($msi, 0))
  $conds = @(Rows $db "SELECT Condition FROM LaunchCondition")
  "   LaunchCondition rows: $($conds -join ' | ')"
  Check (@($conds | Where-Object { $_ -match "NOT \(ALLUSERS = 1\)" }).Count -eq 1) "the built MSI has the launch condition that refuses ALLUSERS=1"
  $up = @(Rows $db "SELECT UpgradeCode FROM Upgrade")
  Check ($up.Count -ge 1) "the built MSI has an Upgrade table (MajorUpgrade: FindRelatedProducts + RemoveExistingProducts)"
  $seq = @(Rows $db "SELECT Action FROM InstallExecuteSequence WHERE Action='RemoveExistingProducts'")
  Check ($seq.Count -eq 1) "RemoveExistingProducts is in the install sequence (the old version is removed inside the install transaction)"
  [Runtime.InteropServices.Marshal]::ReleaseComObject($db) | Out-Null
}

if ($Phase -eq "uv") {
  # the uv-tool channel through the same entry (`heronry update` -> updater.apply), on private uv tool dirs
  "== $(Stamp) uv: private uv tool install 0.9.1 -> heronry update -> 0.9.2.dev0"
  $UH = Join-Path $T "home-uv"
  PreCheck $UH
  UseEnv $UH (Join-Path $T "env-uv.json")
  $env:UV_TOOL_DIR = Join-Path $T "uv-tools"; $env:UV_TOOL_BIN_DIR = Join-Path $T "uv-bin"
  # uv's own sockets are refused on this host (os error 10013) and its cache lacks the dependencies, so they come
  # from a wheelhouse pip fills (pip's sockets work), for the 3.12 the bundle ships; the update's own
  # `uv tool install --force` inherits the same variables
  $wh = Join-Path $T "wheelhouse"
  if (-not (Test-Path $wh)) {
    $deps = (Get-ChildItem "$T\wheels-0.9.1\*.whl" | Where-Object Name -notlike "proxy_tools*").FullName
    & "$mainV8\desktop\.buildenv\Scripts\python.exe" -m pip download --dest $wh --only-binary=:all: --python-version 3.12 --platform win_amd64 @deps 2>&1 | Select-Object -Last 1
    Remove-Item "$wh\edp*"
  }
  $env:UV_OFFLINE = "1"; $env:UV_NO_INDEX = "1"; $env:UV_FIND_LINKS = $wh
  $env:UV_PYTHON = "$env:APPDATA\uv\python\cpython-3.12.12-windows-x86_64-none\python.exe"
  foreach ($V in $Versions) {
    $R = Join-Path $T "uvrel-$V"
    if (Test-Path $R) { Remove-Item -Recurse -Force $R }
    New-Item -ItemType Directory -Path $R | Out-Null
    Copy-Item "$T\wheels-$V\*.whl" $R
    (Get-ChildItem "$R\*.whl" | ForEach-Object { "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower())  $($_.Name)" }) -join "`n" |
      Set-Content -Path "$R\SHA256SUMS" -Encoding ascii
  }
  $w = Get-ChildItem "$T\uvrel-0.9.1\*.whl"
  $main = ($w | Where-Object Name -like "edp8-*").FullName
  $with = @(); $w | Where-Object Name -notlike "edp8-*" | ForEach-Object { $with += "--with"; $with += $_.FullName }
  $u = [Diagnostics.Stopwatch]::StartNew()
  & uv tool install --force $main @with 2>&1 | Select-Object -Last 2 | ForEach-Object { "   $_" }
  "   uv tool install 0.9.1 took $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  $H = Join-Path $env:UV_TOOL_BIN_DIR "heronry.exe"
  Check (Test-Path $H) "heronry on the private uv bin dir"
  & $H init --harness claude --yes 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
  & $H start --no-browser 2>&1 | Select-Object -Last 2 | ForEach-Object { "   $_" }
  Check ((Health) -match "^0\.9\.1") "uv install healthy at 0.9.1 ($(Health))"
  $out = Join-Path $Ev "uv"
  if (Test-Path $out) { Remove-Item -Recurse -Force $out }
  New-Item -ItemType Directory -Path $out | Out-Null
  $u = [Diagnostics.Stopwatch]::StartNew()
  & $H update --release-url "$T\uvrel-0.9.2.dev0" --previous-url "$T\uvrel-0.9.1" 2>&1 | Tee-Object -FilePath "$out\cli.txt" | ForEach-Object { "   | $_" }
  $cliRc = $LASTEXITCODE
  "   cli exit $cliRc after $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  $deadline = if ($cliRc -eq 0) { (Get-Date).AddMinutes(15) } else { Get-Date }; $result = $null
  while (-not $result -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2; $result = Get-ChildItem $UH -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue | Select-Object -First 1 }
  "   outcome after $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  if ($result) { Copy-Item $result.FullName $out; $res = Get-Content $result.FullName -Raw | ConvertFrom-Json; "   result: $($res | ConvertTo-Json -Compress)" }
  $ulog = Get-ChildItem $UH -Recurse -Filter "update.log" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($ulog) { Copy-Item $ulog.FullName $out; Get-Content $ulog.FullName | ForEach-Object { "   log $_" } }
  Check ($res.state -eq "ok") "uv update outcome ok"
  Check ((Health) -match "^0\.9\.2") "uv install healthy at 0.9.2 ($(Health))"
  & $H version 2>&1 | ForEach-Object { "   $_" }
  StopPrivate
  & uv tool uninstall edp8 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
}

if ($Phase -eq "clean") {
  "== $(Stamp) clean: stop, uninstall the spike product"
  StopPrivate
  foreach ($row in (Installed) -split ",") {
    if ($row) { $code = ($row -split "=")[0]
      $p = Start-Process msiexec -ArgumentList @("/x", $code, "/qb", "/norestart", "/l*v", "`"$T\msiexec-clean.log`"") -Wait -PassThru
      "   msiexec /x $code exit $($p.ExitCode)" }
  }
  Check (-not (Installed)) "no spike product installed"
  $left = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.CommandLine -and $_.CommandLine.IndexOf($T, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
  Check ($left.Count -eq 0) "no process runs from the private folders ($($left.Count))"
}

$Fleet1 = FleetSnap
"   fleet after:  $Fleet1"
if ($Fleet1 -ne $Fleet0) { "FAIL  FLEET CHANGED during $Phase; stop and report to the architect"; exit 3 }
"PASS  fleet pids unchanged"
"elapsed $([math]::Round($sw.Elapsed.TotalSeconds))s"
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
