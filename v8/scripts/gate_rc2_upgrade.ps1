# RC2 upgrade gate (c-300f4365a2, t-e338298d88; architect m-4812de0b3c): the owner's real data and config, copied
# read-only into a PRIVATE sandbox home, upgraded by the documented steps with zero manual edits, then checked.
#
#   powershell -NoProfile -File v8\scripts\gate_rc2_upgrade.ps1 -Phase build|hop1|hop2|hop2rm|hop3rm|refuse|manual010|hop2code|clean
#   powershell -NoProfile -File v8\scripts\gate_rc2_upgrade.ps1 -Phase build -Only 0.10.1 [-Ref <commit>] [-Version 0.10.2]
#
#   build  one MSI per version with the GATE identity (bundle io.github.visak13.rc2gate, "Heronry RC2 Gate": its own
#          UpgradeCode, install folder, Start-menu entry and HKCU key, no PATH component), from 0.9.1 = tag v0.9.1,
#          0.10.0 = 9f9f05a9 (the RC1 the owner runs) and 0.10.1 = main; each a release dir (MSI + SHA256SUMS).
#          -Reuse: a build that stopped before its MSI (the memory pause) keeps src-<V> and wheels-<V>; when their
#          src-<V>\.gate-ref is the ref's commit, the SPA, the wheels and the pins are reused, only the MSI step runs
#          -MinFreeMB (default 800): the MSI step waits up to 30 min for this much free RAM, then fails the check
#   hop1   0.9.1 -> 0.10.1 by the 0.9.x steps (CHANGELOG [0.10.1]): `heronry stop all --force`, msiexec /i the
#          new .msi, `heronry start`. The sandbox starts from the owner's 0.9.1-era files: config.toml.bak-code (no
#          [code_server] path pin), models.json.bak-effortcap (caps at medium), and pool settings with 0.9.1's
#          effortLevel pin and no template stamp. Then: the checks, `heronry start code` with a broken code-server
#          first on PATH, and a start interrupted mid-warm-up followed by a plain `heronry start`.
#   hop2   0.10.0 -> 0.10.1 via `heronry update --release-url`: the owner's restart path, from the owner's current
#          files as they are, with a live codex seat (`<install>\heronry.exe -m edp8.codex_seat.run` on the stub
#          codex) through the update: no "files in use" stall, and what became of the seat is recorded.
#   hop2code  hop2's last leg alone, on the running hop2 stack (its ports from <home>\gate\ports.json): the owner
#          removes the [code_server] path pin and runs `heronry start code` (the pinned download and unpack), then
#          the checks. Run every phase visibly, as a plain child of the caller's shell: never detached, hidden or with
#          -ExecutionPolicy Bypass (shared-host-rules a781bf99: the host antivirus quarantines those launches).
#   memlog every 10 s until the log's end marker: free MB and the working set of each gate process, into <log>.mem.txt
#          (its own file: a second writer on the leg's redirected log overwrites lines).
#   clean  stop the private stack by pid and uninstall the gate product.
#
# Never touches the installed fleet or the owner's home: the source is only read (the DB through SQLite's online
# backup), every EDP*/HERONRY*/SLACK* variable is wiped, the ports are free ones picked at run time, slack_map.json
# and the pool's state are never copied (no bridge, no adoption of fleet seats), seats run a stub harness, and every
# process is identified by an executable path or command line under the gate folder. Fleet pids are snapshotted
# before and after each phase; any change fails the gate.
param([ValidateSet("build", "hop1", "hop2", "hop2rm", "hop3rm", "refuse", "manual010", "hop2code", "memlog", "clean")][string]$Phase = "build",
      [string]$Gate = "", [string[]]$Only = @(), [switch]$Reuse, [int]$MinFreeMB = 800, [string]$Ref = "",
      [string]$Version = "", [switch]$Tail)
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$mainRoot = Split-Path -Parent (Resolve-Path (git -C $root rev-parse --git-common-dir)).Path
$mainV8 = Join-Path $mainRoot "v8"
if (-not $Gate) { $Gate = Join-Path (Split-Path -Parent $mainRoot) "heronry-rc\gate" }   # beside the checkout
$Py = "$mainV8\.venv\Scripts\python.exe"   # read only: the checks, the DB backup, the MSI queries
$Src = Join-Path $env:LOCALAPPDATA "heronry"  # the owner's home: READ ONLY
$Ev = Join-Path $Gate "evidence"
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function Stamp { (Get-Date).ToString("HH:mm:ss") }
$Builds = [ordered]@{ "0.9.1" = "v0.9.1"; "0.10.0" = "9f9f05a9"; "0.10.1" = "main" }
# -Ref: build the one -Only version from another commit (a branch's fix before it merges). -Version (architect
# m-0068de8988): stamp that build with a gate-only version, so the fixed 0.10.1's own helper runs an update (hop3rm,
# 0.10.1 -> 0.10.2). Gate identity only: the stamped MSI lands in <gate>\release-<Version> and nowhere else.
$StampFrom = ""
if ($Ref -or $Version) {
  if ($Only.Count -ne 1 -or -not $Builds.Contains($Only[0])) { "ABORT -Ref/-Version need exactly one -Only of $($Builds.Keys -join ', ')"; exit 3 }
  if ($Ref) { $Builds[$Only[0]] = $Ref }
  if ($Version) {
    if ($Builds.Contains($Version) -or $Version -notmatch '^\d+\.\d+\.\d+$') { "ABORT -Version $Version must be a new x.y.z, not a real release"; exit 3 }
    if ($Gate -match '\\\d+\.\d+\.\d+\\release') { "ABORT -Version builds only into the gate folder, never a release dir ($Gate)"; exit 3 }
    $StampFrom = $Only[0]
    $Builds = [ordered]@{ $Version = $Builds[$StampFrom] }
    $Only = @()
  }
}
New-Item -ItemType Directory -Force -Path $Gate, $Ev | Out-Null   # after the argument checks: an abort writes nothing
Set-Location $Gate   # a relative path can never land in the caller's folder
# the one version across the packages (S9), every place it is written: project versions, pins and __version__
$StampFiles = "edp-contracts\pyproject.toml", "edp-pool\pyproject.toml", "edp-broker\pyproject.toml", "v8\pyproject.toml",
  "v8\desktop\pyproject.toml", "edp-contracts\src\edp_contracts\__init__.py", "edp-pool\src\edp_pool\__init__.py",
  "edp-broker\src\edp_broker\__init__.py", "v8\src\edp8\__init__.py"
function Restamp($S, $from, $to) {
  $n = 0
  foreach ($f in $StampFiles) {
    $p = Join-Path $S $f
    $t = [IO.File]::ReadAllText($p)
    $re = [regex]('(version = "|==|__version__ = ")' + [regex]::Escape($from) + '(?=")')
    $n += $re.Matches($t).Count
    [IO.File]::WriteAllText($p, $re.Replace($t, '${1}' + $to))
  }
  "   restamped $from -> $to in $($StampFiles.Count) files ($n places)"
  $left = @($StampFiles | Where-Object { [IO.File]::ReadAllText((Join-Path $S $_)) -match ('(version = "|==|__version__ = ")' + [regex]::Escape($from) + '"') })
  Check (-not $left -and $n -ge 15) "every version stamp reads $to (left at $from`: $($left -join ', '))"
}

# ------------------------------------------------------------------------------------------ fleet safety
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$FleetRun = Join-Path $Src "run"
$FleetApp = Join-Path $env:LOCALAPPDATA "Programs\Heronry contributors\Heronry Desktop"
function FleetPids { foreach ($s in "board", "broker", "pool", "mcp", "bridge", "supervisor") {
  $f = Join-Path $FleetRun "$s.json"; if (Test-Path $f) { [int](Get-Content $f -Raw | ConvertFrom-Json).pid } } }
function FleetSnap { (@(FleetPids) | Sort-Object) -join "," }
function Under($pr, $dir) {
  ($pr.ExecutablePath -and $pr.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase)) -or
  ($pr.CommandLine -and $pr.CommandLine.IndexOf($dir, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}
function CodexSeats { @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*edp8.codex_seat.run*" -and (Under $_ $Gate) } | ForEach-Object { [int]$_.ProcessId }) }
# a Claude seat's stub harness (claude-stub.cmd -> seat_wrap.py), one python per seat shell
function ClaudeSeats { @(Get-CimInstance Win32_Process | Where-Object { $_.Name -ne "cmd.exe" -and $_.CommandLine -like "*seat_wrap.py*" -and (Under $_ $Gate) } | ForEach-Object { [int]$_.ProcessId }) }
# this shell and every process above it: the owner's .bat names the gate folder on its command line, and stopping it
# there ended the run after hop1's opening StopPrivate, so hop2 never started (run-hops-73aef932.bat, run-gate-63e1a4bb.bat)
function Callers {
  $parent = @{}; Get-CimInstance Win32_Process | ForEach-Object { $parent[[int]$_.ProcessId] = [int]$_.ParentProcessId }
  $chain = @(); $p = [int]$PID
  while ($parent.ContainsKey($p) -and $chain -notcontains $p) { $chain += $p; $p = $parent[$p] }
  $chain
}
function StopPrivate {
  $fleet = @(FleetPids)
  $callers = @(Callers)
  $ps = @(Get-CimInstance Win32_Process | Where-Object { $callers -notcontains [int]$_.ProcessId -and (Under $_ $Gate) -and $_.Name -ne "powershell.exe" })
  foreach ($pr in $ps) { if ($fleet -contains [int]$pr.ProcessId -or (Under $pr $FleetApp)) { "ABORT pid $($pr.ProcessId) is the fleet's"; exit 3 } }
  foreach ($pr in $ps) { Stop-Process -Id $pr.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  "   private pids stopped: $($ps.Count)"
}
$Fleet0 = FleetSnap
"   fleet before: $Fleet0"

# ------------------------------------------------------------------------------------------ build
if ($Phase -eq "build") {
  foreach ($V in @($Builds.Keys | Where-Object { -not $Only -or $Only -contains $_ })) {
    $ref = $Builds[$V]
    "== $(Stamp) build $V from $ref"
    $S = Join-Path $Gate "src-$V"
    $W = Join-Path $Gate "wheels-$V"
    $D = "$S\v8\desktop"
    $sha = (& git -C $mainRoot rev-parse "$ref^{commit}").Trim()
    $reused = $Reuse -and (Test-Path "$S\.gate-ref") -and ((Get-Content "$S\.gate-ref" -Raw).Trim() -eq $sha) -and
              (Test-Path "$S\v8\src\edp8\webapp\dist\index.html") -and @(Get-ChildItem "$W\*.whl" -ErrorAction SilentlyContinue).Count -ge 4 -and
              ([IO.File]::ReadAllText("$D\pyproject.toml") -match 'rc2gate') -and
              ([IO.File]::ReadAllText("$D\pyproject.toml") -match "edp8==$([regex]::Escape($V))`"")
    if ($reused) { "   -Reuse: src-$V and wheels-$V are $($sha.Substring(0, 8)); the SPA, wheels and pins are kept" }
    else {
      if (Test-Path $S) { cmd /c rmdir /s /q "$S" }
      New-Item -ItemType Directory -Path $S | Out-Null
      & git -C $mainRoot archive --format=tar -o "$Gate\src.tar" $ref edp-contracts edp-pool edp-broker v8 CHANGELOG.md LICENSE NOTICE
      & "$env:SystemRoot\System32\tar.exe" -xf "$Gate\src.tar" -C $S
      Remove-Item "$Gate\src.tar"
      if ($StampFrom) { Restamp $S $StampFrom $V }
      $env:EDP8_WEB_BASE = "/ui/"
      & npm --prefix "$S\v8\web" ci --no-audit --no-fund 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
      & npm --prefix "$S\v8\web" run build 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
      Remove-Item Env:EDP8_WEB_BASE
      Check (Test-Path "$S\v8\src\edp8\webapp\dist\index.html") "the SPA built at $V"
      if (Test-Path $W) { Remove-Item -Recurse -Force $W }
      $env:EDP8_WEB_AUTOBUILD = "0"
      foreach ($p in "edp-contracts", "edp-pool", "edp-broker", "v8") {
        & uv build --offline --wheel --out-dir $W "$S\$p" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" } }
      Check (@(Get-ChildItem "$W\*.whl").Count -eq 4) "four wheels at $V"
      Copy-Item "$mainV8\desktop\wheels\proxy_tools-0.1.0-py3-none-any.whl" $W -ErrorAction SilentlyContinue
      $D = "$S\v8\desktop"
      # the build machinery is main's for every version (0.9.1's script has no -Fresh/-NoCliPath/-BuildEnv, and a
      # PATH component would share the fleet's GUID and HKCU key); the app it packages is that version's own
      Copy-Item "$v8\desktop\scripts\*.ps1" "$D\scripts\" -Force   # build_windows.ps1 and the helpers it calls (patch_wxs.ps1)
      $txt = [IO.File]::ReadAllText("$D\pyproject.toml")
      $txt = $txt -replace 'bundle = "io\.github\.visak13"', 'bundle = "io.github.visak13.rc2gate"' `
                  -replace 'formal_name = "Heronry Desktop"', 'formal_name = "Heronry RC2 Gate"'
      [IO.File]::WriteAllText("$D\pyproject.toml", $txt)
      Check ($txt -match 'rc2gate' -and $txt -match "edp8==$([regex]::Escape($V))") "gate identity + $V pins in desktop\pyproject.toml"
      Set-Content -Path "$S\.gate-ref" -Value $sha -Encoding ascii
    }
    # pause the MSI build until -MinFreeMB is free, never risk a killed build. 800 by default: the release build
    # measured ~0.35 GB, and the owner ruled 2.5 GB too much (m-d135dff5c4, architect m-8a9d37e021)
    $free = { [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024) }
    $until = (Get-Date).AddMinutes(30)
    while ((& $free) -lt $MinFreeMB -and (Get-Date) -lt $until) { "   $(Stamp) paused: $(& $free) MB free, waiting for $MinFreeMB"; Start-Sleep -Seconds 30 }
    if ((& $free) -lt $MinFreeMB) { Check $false "$MinFreeMB MB free for the $V MSI build ($(& $free) MB after 30 min)"; break }
    "   $(& $free) MB free before the $V MSI build"
    $bt = [Diagnostics.Stopwatch]::StartNew()
    & powershell -NoProfile -File "$D\scripts\build_windows.ps1" -Wheels $W -Fresh -NoCliPath `
        -BuildEnv "$mainV8\desktop\.buildenv" 2>&1 |
      Tee-Object -FilePath "$Gate\build-$V.log" | Select-String -Pattern "^==|^MSI|error|fail|throw" | ForEach-Object { "   $_" }
    "   build took $([math]::Round($bt.Elapsed.TotalSeconds))s"
    $msi = Get-ChildItem "$D\dist\*.msi" -ErrorAction SilentlyContinue | Select-Object -First 1
    Check ([bool]$msi) "an MSI for $V"
    if ($msi) {
      $R = Join-Path $Gate "release-$V"
      if (Test-Path $R) { Remove-Item -Recurse -Force $R }
      New-Item -ItemType Directory -Path $R | Out-Null
      Copy-Item $msi.FullName $R
      $sha = (Get-FileHash (Join-Path $R $msi.Name) -Algorithm SHA256).Hash.ToLower()
      Set-Content -Path "$R\SHA256SUMS" -Value "$sha  $($msi.Name)" -Encoding ascii
      "   $($msi.Name) $([math]::Round($msi.Length/1MB,1)) MB"
    }
    # free the disk a build tree holds before the next one (only the release dir is kept)
    cmd /c rmdir /s /q "$S"
  }
}

# ------------------------------------------------------------------------------------------ the sandbox
# t-fd7cf3a6b5: a space in both, as in the owner's default `...\Heronry contributors\Heronry Desktop` (msiexec 1639)
$Inst = Join-Path $Gate "install dir"
$Exe = Join-Path $Inst "heronry.exe"
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function Msi($V) { (Get-ChildItem (Join-Path $Gate "release-$V\*.msi")).FullName }
function Products { if (-not (Test-Path (Join-Path $Gate "release-0.10.1"))) { return "" }
  & $Py -c "import sys; sys.path.insert(0, sys.argv[2]); from edp8.update_helper import msi_property, related_products; print(','.join(r['code'] + '=' + r['version'] for r in related_products(msi_property(sys.argv[1], 'UpgradeCode'))))" (Msi "0.10.1") "$mainV8\src" }

function CopyHome($H, [switch]$Era091) {
  # EDP_HOME layout: config.toml + secrets in the home, data in <home>\.data (edp_contracts.settings)
  if (Test-Path $H) { cmd /c rmdir /s /q "$H" }
  $D = Join-Path $H ".data"
  if (-not [IO.Path]::IsPathRooted($D) -or -not $D.StartsWith($Gate, [StringComparison]::OrdinalIgnoreCase)) { "ABORT sandbox data dir $D is not under $Gate"; exit 3 }
  New-Item -ItemType Directory -Force -Path $H, $D, (Join-Path $D "claude-pool") | Out-Null
  $cfg = if ($Era091) { "config.toml.bak-code" } else { "config.toml" }
  Copy-Item (Join-Path $Src "config\$cfg") (Join-Path $H "config.toml")
  Copy-Item (Join-Path $Src "config\desktop.json") $H -ErrorAction SilentlyContinue
  # the secrets keep their owner-only ACL: the board refuses a tokens file others can read. The source files take
  # it from their (protected) folder, so each copy gets the source's effective ACL, inherited entries made explicit
  Get-ChildItem (Join-Path $Src "config\secrets") -File | ForEach-Object {
    $dst = Join-Path $H $_.Name
    Copy-Item $_.FullName $dst
    $acl = Get-Acl $_.FullName
    $acl.SetAccessRuleProtection($true, $true)
    Set-Acl -Path $dst -AclObject $acl }
  & $Py -c "import sqlite3, sys; s = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" `
      (Join-Path $Src "data\edp8.db") (Join-Path $D "edp8.db")
  foreach ($f in "edp8.db.vec", "edp8.db.cursor-key", "setup.json") { Copy-Item (Join-Path $Src "data\$f") $D -ErrorAction SilentlyContinue }
  $models = if ($Era091) { "models.json.bak-effortcap" } else { "models.json" }
  Copy-Item (Join-Path $Src "data\$models") (Join-Path $D "models.json")
  # the agent home sits beside config.toml under an EDP_HOME (edp_contracts.settings.agent_home), not in .data: the
  # refresh (and its .new files) must run on the owner's own agent home, not on a fresh one
  robocopy (Join-Path $Src "data\agent-home") (Join-Path $H "agent-home") /E /NFL /NDL /NJH /NJS /NP | Out-Null
  foreach ($sub in "uploads", "tools") {   # not $d: PowerShell names ignore case ($D)
    robocopy (Join-Path $Src "data\$sub") (Join-Path $D $sub) /E /NFL /NDL /NJH /NJS /NP | Out-Null }
  $pool = Get-Content (Join-Path $Src "data\claude-pool\settings.json") -Raw | ConvertFrom-Json
  if ($Era091) {   # 0.9.1's template pinned effortLevel and had no compact hook stamp: the pre-merge state
    $pool | Add-Member -NotePropertyName effortLevel -NotePropertyValue "medium" -Force
  } else { Copy-Item (Join-Path $Src "data\claude-pool\.settings-template.sha256") (Join-Path $D "claude-pool") }
  ($pool | ConvertTo-Json -Depth 20) | Set-Content -Path (Join-Path $D "claude-pool\settings.json") -Encoding utf8
  "   sandbox home $H from the owner's $(if ($Era091) { '0.9.1-era' } else { 'current' }) files ($([math]::Round(((Get-ChildItem $H -Recurse -File | Measure-Object Length -Sum).Sum)/1MB)) MB)"
}

function UseEnv($H, [hashtable]$Ports = $null) {
  Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "SLACK*" -or
    @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
  $fleet = 9400, 9402, 9301, 9300, 19400, 19402, 19301, 19300, 19410
  foreach ($k in "EDP8_PORT", "EDP8_MCP_PORT", "EDP_POOL_PORT", "EDP_BROKER_PORT", "EDP_CODE_PORT") {
    if ($Ports) { Set-Item "Env:$k" ([string]$Ports[$k]); continue }
    do { $p = FreePort } while ($fleet -contains $p); Set-Item "Env:$k" ([string]$p) }
  $env:EDP_HOME = $H
  $env:EDP8_HOST = "127.0.0.1"
  $env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
  $env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
  # seats: the stub harness, behind a wrapper that records the env and argv a seat is launched with
  Copy-Item "$mainRoot\edp-pool\tests\fixtures\stub_harness.py" "$Gate\stub_harness.py" -Force
  $env:GATE_EFFORT_LOG = Join-Path $H "gate\seat-env.jsonl"
  New-Item -ItemType Directory -Force (Split-Path $env:GATE_EFFORT_LOG) | Out-Null
  Set-Content -Path "$Gate\seat_wrap.py" -Encoding ascii -Value @'
import json, os, runpy, sys
with open(os.environ["GATE_EFFORT_LOG"], "a", encoding="utf-8") as f:
    f.write(json.dumps({"EDP_SEAT_EFFORT": os.environ.get("EDP_SEAT_EFFORT"), "argv": sys.argv[1:]}) + "\n")
sys.argv = [os.path.join(os.path.dirname(__file__), "stub_harness.py"), *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
'@
  Set-Content -Path "$Gate\claude-stub.cmd" -Value "@`"$Py`" `"$Gate\seat_wrap.py`" %*" -Encoding ascii
  $env:EDP_CLAUDE_BIN = "$Gate\claude-stub.cmd"; $env:EDP_SPAWN_MODE = "headless"; $env:EDP_SHADOW = "0"
  # codex seats too (the copied board auto-staffs qa on the owner's epics): never the real codex and its login
  # it stays up without answering (a live seat for hop2's update), under the gate folder so StopPrivate finds it
  Set-Content -Path "$Gate\codex_stub.py" -Encoding ascii -Value "import sys, time`r`nprint('RC2 gate: codex is stubbed in the sandbox', file=sys.stderr)`r`ntime.sleep(1800)"
  Set-Content -Path "$Gate\codex-stub.cmd" -Encoding ascii -Value "@`"$Py`" `"$Gate\codex_stub.py`" %*"
  $env:EDP_CODEX_BIN = "$Gate\codex-stub.cmd"
  # a broken code-server first on PATH (the owner's npm shim: MODULE_NOT_FOUND)
  New-Item -ItemType Directory -Force "$Gate\broken-path" | Out-Null
  Set-Content -Path "$Gate\broken-path\code-server.cmd" -Encoding ascii -Value "@echo Error: Cannot find module 'code-server/out/node/entry' 1>&2`r`n@exit /b 1"
  $env:PATH = "$Gate\broken-path;$env:PATH"
  "   ports board=$env:EDP8_PORT pool=$env:EDP_POOL_PORT mcp=$env:EDP8_MCP_PORT broker=$env:EDP_BROKER_PORT code=$env:EDP_CODE_PORT"
  $pj = @{}; foreach ($k in "EDP8_PORT", "EDP8_MCP_PORT", "EDP_POOL_PORT", "EDP_BROKER_PORT", "EDP_CODE_PORT") { $pj[$k] = [int](Get-Item "Env:$k").Value }
  $pj | ConvertTo-Json | Set-Content (Join-Path $H "gate\ports.json") -Encoding ascii
}
function Health { try { $h = Invoke-RestMethod "http://127.0.0.1:$env:EDP8_PORT/v1/health" -TimeoutSec 5; "$($h.version)$($h.value.version)" } catch { $null } }
function Install($V, $log) {   # /qn: no progress window on the owner's desktop (architect m-986725fc4f)
  $u = [Diagnostics.Stopwatch]::StartNew()
  $p = Start-Process msiexec -ArgumentList @("/i", "`"$(Msi $V)`"", "/qn", "/norestart", "/l*v", "`"$Ev\$log`"",
    "MSIINSTALLPERUSER=1", "ALLUSERS=2", "INSTALLFOLDER=`"$Inst`"") -Wait -PassThru
  "   msiexec /i $V exit $($p.ExitCode) in $([math]::Round($u.Elapsed.TotalSeconds,1))s"
  $script:msiRc = $p.ExitCode
}
function Uninstall { foreach ($row in (Products) -split ",") { if ($row) { $code = $row.Split("=")[0]
  $p = Start-Process msiexec -ArgumentList @("/x", $code, "/qn", "/norestart") -Wait -PassThru
  "   msiexec /x $row exit $($p.ExitCode)" } } }
function Hx($what, [string[]]$a) {   # one sandbox CLI call, its output kept as evidence
  "   $(Stamp) heronry $($a -join ' ')"
  & $Exe @a 2>&1 | Tee-Object -FilePath "$Ev\$what.txt" | ForEach-Object { "   | $_" }
  $script:rc = $LASTEXITCODE
  "   exit $script:rc"
}
# the installed product's tool names (board tools + proxied browser tools), printed by its own interpreter; no double
# quotes in the code, so PowerShell 5.1 passes it to the native exe intact (gate_agent_home.py reads the file)
$ToolsCode = "import json,importlib,importlib.util as u; from edp8.bundles import ALL_TOOLS as A; n=set(A); " +
  "b=u.find_spec('edp8.browser_proxy'); n|=set(importlib.import_module('edp8.browser_proxy').TOOL_NAMES) if b else set(); " +
  "print(json.dumps(sorted(n)))"
function ToolRegistry($file) {
  $out = (& $Exe -c $ToolsCode 2> "$file.err" | Out-String).Trim()   # stdout only: the JSON; stderr kept beside it
  [IO.File]::WriteAllText($file, $out)
  $n = try { (ConvertFrom-Json $out).Count } catch { 0 }
  "   tool registry: $n names -> $(Split-Path -Leaf $file)"
}
function Checks($H, $kind) {
  & $Py "$PSScriptRoot\gate_rc2_checks.py" $H $kind --out $Ev 2>&1 | ForEach-Object { $_; if ($_ -like "FAIL*") { $script:fail++ } }
}
function Interrupted {
  "== $(Stamp) interrupted start: kill the CLI mid-start, then a plain start"
  Hx "interrupt-stop" @("stop", "all", "--keep-seats")
  $cli = Start-Process $Exe -ArgumentList @("start", "--no-browser") -PassThru -NoNewWindow -RedirectStandardOutput "$Ev\interrupt-first.txt" -RedirectStandardError "$Ev\interrupt-first.err"
  Start-Sleep -Seconds 4
  & taskkill /PID $cli.Id /T /F 2>&1 | Out-Null   # the CLI and what it was waiting on, as a closed terminal does
  "   killed the first start (pid $($cli.Id)) after 4 s"
  Hx "interrupt-second" @("start", "--no-browser")
  Check ($script:rc -eq 0) "the start after an interrupted start exits 0"
  Check (-not (Select-String -Path "$Ev\interrupt-second.txt" -Pattern "Traceback" -Quiet)) "no traceback"
  Check ([bool](Health)) "the board answers after the recovery"
}

# ------------------------------------------------------------------------------------------ hop 1: 0.9.1 -> 0.10.1
if ($Phase -eq "hop1") {
  $H = Join-Path $Gate "home hop1"
  StopPrivate
  Uninstall
  CopyHome $H -Era091
  UseEnv $H
  "== $(Stamp) 0.9.1 installed and running on the owner's 0.9.1-era files"
  Install "0.9.1" "msiexec-hop1-0.9.1.log"
  Check ($script:msiRc -eq 0) "0.9.1 (gate identity) installed"
  Hx "hop1-start-0.9.1" @("start", "--no-browser")
  Check ((Health) -match "^0\.9\.1") "the sandbox board runs 0.9.1 on the copied data ($(Health))"
  "== $(Stamp) the documented 0.9.x steps (CHANGELOG [0.10.1] Upgrading), nothing else"
  Hx "hop1-step1-stop" @("stop", "all", "--force")
  Install "0.10.1" "msiexec-hop1-0.10.1.log"
  Check ($script:msiRc -eq 0) "step 2: msiexec /i the 0.10.1 .msi (upgrade in place)"
  Hx "hop1-step3-start" @("start", "--no-browser")
  Check ($script:rc -eq 0 -and (Health) -match "^0\.10\.1") "step 3: heronry start; the board runs 0.10.1 ($(Health))"
  Check ((Products) -notmatch "0\.9\.1") "one gate product installed, at 0.10.1 ($(Products))"
  Hx "hop1-status" @("status")
  Hx "hop1-code" @("start", "code")
  Checks $H "hop1"
  Interrupted
}

# ------------------------------------------------------------------------------------------ hop 2: 0.10.0 -> 0.10.1
if ($Phase -eq "hop2") {
  $H = Join-Path $Gate "home hop2"
  StopPrivate
  Uninstall
  CopyHome $H
  UseEnv $H
  "== $(Stamp) 0.10.0 installed and running on the owner's current files"
  Install "0.10.0" "msiexec-hop2-0.10.0.log"
  Check ($script:msiRc -eq 0) "0.10.0 (gate identity) installed"
  Hx "hop2-start-0.10.0" @("start", "--no-browser")
  Check ((Health) -match "^0\.10\.0") "the sandbox board runs 0.10.0 ($(Health))"
  ToolRegistry "$Ev\hop2-tools-0.10.0.json"
  # a live codex seat through the update (architect m-0b95d8413e): the owner's fleet runs codex seats
  & $Py "$PSScriptRoot\gate_rc2_checks.py" $H "hop2-codex" --out $Ev --spawn-codex 2>&1 | ForEach-Object { "   | $_" }
  $deadline = (Get-Date).AddSeconds(60)
  do { Start-Sleep -Seconds 2; $seat0 = @(CodexSeats) } while (-not $seat0 -and (Get-Date) -lt $deadline)
  Check ($seat0.Count -ge 1) "a codex seat runs from the gate install before the update (pids $($seat0 -join ','))"
  "== $(Stamp) heronry update --release-url (the owner's restart path)"
  $result = Join-Path $H ".data\update\update-result.json"
  $t0 = Get-Date
  Hx "hop2-update" @("update", "--release-url", (Join-Path $Gate "release-0.10.1"), "--previous-url", (Join-Path $Gate "release-0.10.0"))
  $deadline = (Get-Date).AddMinutes(20)
  while ((Get-Date) -lt $deadline -and -not ((Get-ChildItem $H -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue) | Select-Object -First 1)) { Start-Sleep -Seconds 3 }
  $rf = Get-ChildItem $H -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($rf) { Copy-Item $rf.FullName "$Ev\hop2-update-result.json"; $res = Get-Content $rf.FullName -Raw | ConvertFrom-Json }
  Check ($res.state -eq "ok") "the update ends ok ($($res.state) $($res.reason))"
  $msi = @(Get-CimInstance Win32_Process -Filter "Name='msiexec.exe'" | Where-Object { $_.CommandLine -like "*$Gate*" })
  Check ($rf -and -not $msi) "the update finished in $([int]((Get-Date) - $t0).TotalSeconds) s with no msiexec left waiting (no files-in-use stall, no click)"
  $seat1 = @(CodexSeats)
  $kept = @($seat0 | Where-Object { $seat1 -contains $_ })
  "   codex seat after the update: before $($seat0 -join ','), now $($seat1 -join ','), kept $($kept -join ',')"
  "   codex seat outcome: $(if ($kept) { 'kept running' } elseif ($seat1) { 'stopped and re-adopted (new pid)' } else { 'stopped, not running now' })"
  Check ((Health) -match "^0\.10\.1") "the board runs 0.10.1 after the update ($(Health))"
  Hx "hop2-status" @("status")
  Hx "hop2-code" @("start", "code")
  ToolRegistry "$Ev\hop2-tools-0.10.1.json"   # gate_rc2_checks.py hop2 #7: the agent home names no tool outside it
  Checks $H "hop2"
  "== $(Stamp) the owner removes the [code_server] path pin (the one documented edit after the restart), restarts code"
  $cfg = Join-Path $H "config.toml"
  $sec = ""
  $kept = foreach ($l in (Get-Content $cfg)) {
    if ($l -match '^\s*\[(.+)\]') { $sec = $Matches[1] }
    if ($sec -eq "code_server" -and $l -match '^\s*path\s*=') { Write-Host "   removed: $l" } else { $l } }
  [IO.File]::WriteAllLines($cfg, [string[]]$kept)   # UTF-8 without a BOM, as TOML wants
  Hx "hop2-code-stop" @("stop", "code")
  Hx "hop2-code-unpinned" @("start", "code")
  Checks $H "hop2-unpinned"
}

# ------------------------------------------------------------------------------------------ hop 2's last leg, alone
if ($Phase -eq "hop2code") {
  $H = Join-Path $Gate "home hop2"
  $pj = Get-Content (Join-Path $H "gate\ports.json") -Raw | ConvertFrom-Json
  $ports = @{}; $pj.PSObject.Properties | ForEach-Object { $ports[$_.Name] = $_.Value }
  UseEnv $H $ports
  Check ((Health) -match "^0\.10\.1") "the hop2 stack is up on 0.10.1 ($(Health))"
  "== $(Stamp) the owner removes the [code_server] path pin (the one documented edit after the restart), restarts code"
  $cfg = Join-Path $H "config.toml"
  $sec = ""
  $kept = foreach ($l in (Get-Content $cfg)) {
    if ($l -match '^\s*\[(.+)\]') { $sec = $Matches[1] }
    if ($sec -eq "code_server" -and $l -match '^\s*path\s*=') { Write-Host "   removed: $l" } else { $l } }
  [IO.File]::WriteAllLines($cfg, [string[]]$kept)
  Hx "hop2-code-stop" @("stop", "code")
  Hx "hop2-code-unpinned" @("start", "code")
  Checks $H "hop2-unpinned"
}

# ------------------------------------------------------------------------------------------ the owner's fleet shape
# t-fb8b63874e (architect m-7831c5104a, m-0068de8988): the owner's real update rolled back with `holders: None`. The
# owner's fleet had two kinds of process from the install folder that `stop --force` never ends: the opt-in code server
# (code-guard) and the seats' feed monitors (`heronry.exe -m edp8.feed_driver`). Each leg starts both from the installed
# exe, logs every Restart Manager rc on the install folder through the update (gate_rm_probe.py, read-only), and records
# what the update did. The probe and the feed monitor are plain children of this shell, stopped by pid at the end.
#   hop2rm  0.10.0 -> 0.10.1 on 0.10.0's helper (a hop only ever runs the installed version's helper), two legs:
#           a  as the owner ran it: expected to reproduce the rollback, the rcs logged by the probe
#           b  the owner's one-time workaround first (`heronry stop code`, then each feed monitor stopped by pid):
#              0.10.0's helper then reaches msiexec, which refuses the spaced install folder with 1639
#              (t-fd7cf3a6b5): this hop cannot be done by `heronry update`; the manual phase does it
#   hop3rm  0.10.1 -> 0.10.2 (the gate-stamped build of the same commit, -Version): the fixed helper ends both itself,
#           logs every rc, and starts the code server again
# architect m-e489ec9159: the owner's 0.10.0 runs the checkout's code-server (its guard's --tag is the release dir
# under <checkout>\v8\.tools\code-server). 0.10.0 would otherwise take PATH, where the broken shim sits first;
# the shim stays, so the pin is what starts it. The dir is found at run time, never written into this script.
function PinCode($H) {
  $cs = Get-ChildItem (Join-Path $mainV8 ".tools\code-server") -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending |
    ForEach-Object { Get-ChildItem $_.FullName -Directory -Filter "code-server-*-windows-amd64" } | Select-Object -First 1
  Check ([bool]$cs -and (Test-Path (Join-Path $cs.FullName "lib\node.exe"))) "the checkout's code-server release dir is there to pin ($(if ($cs) { $cs.Name }))"
  if ($cs) {
    $cfg = Join-Path $H "config.toml"
    $lines = [Collections.Generic.List[string]](Get-Content $cfg)
    $at = $lines.IndexOf("[code_server]")
    if ($at -lt 0) { $lines.Add(""); $lines.Add("[code_server]"); $at = $lines.Count - 1 }
    $lines.Insert($at + 1, "path = '$($cs.FullName)'")   # a TOML literal string: backslashes stay as they are
    [IO.File]::WriteAllLines($cfg, [string[]]$lines)
    "   [code_server] path pinned to the checkout's $($cs.Name)"
  }
}
# an orphaned feed monitor (architect m-6648604844): its seat is gone, so its parent pid is dead. The gate runs as a
# seat's background process, and a monitor started straight from it descends from that seat's claude.exe, which the
# update rightly refuses as an untracked seat window. So it starts under a cmd.exe the gate then stops by pid (no detach,
# no tree kill): the monitor lives on with a dead parent, as an orphan does.
function OrphanFeed($seat, $tag) {
  $a = "-m edp8.feed_driver --participant $seat --board http://127.0.0.1:$env:EDP8_PORT --broker http://127.0.0.1:$env:EDP_BROKER_PORT"
  $c = Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -NoNewWindow -PassThru -ArgumentList "/s /c `"`"$Exe`" $a 1>`"$Ev\$tag-feed.out`" 2>`"$Ev\$tag-feed.err`"`""
  $deadline = (Get-Date).AddSeconds(20)
  do { Start-Sleep -Milliseconds 500
       $f = Get-CimInstance Win32_Process -Filter "ParentProcessId=$($c.Id)" | Where-Object { $_.CommandLine -like "*edp8.feed_driver*" } | Select-Object -First 1
  } while (-not $f -and (Get-Date) -lt $deadline)
  Stop-Process -Id $c.Id -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  "   feed monitor $(if ($f) { $f.ProcessId }) started under cmd.exe $($c.Id), which is stopped by pid"
  Check ([bool]$f -and -not (Get-Process -Id $c.Id -ErrorAction SilentlyContinue)) "the feed monitor's parent (pid $($c.Id)) is no longer alive: an orphan, no live claude.exe above it"
  $script:orphan = if ($f) { Get-Process -Id $f.ProcessId -ErrorAction SilentlyContinue }   # its lines stay in the log
}
function RmLeg($leg, $from, $to, [switch]$Workaround, [switch]$PinCode, [switch]$ClaudeSeat) {
  $H = Join-Path $Gate "home $leg"
  StopPrivate
  Uninstall
  CopyHome $H
  UseEnv $H
  if ($PinCode) { PinCode $H }
  "== $(Stamp) $leg`: $from installed and running on the owner's current files, with the code server and a feed monitor"
  Install $from "msiexec-$leg-$from.log"
  Check ($script:msiRc -eq 0) "$from (gate identity) installed"
  Hx "$leg-start-$from" @("start", "--no-browser")
  Check ((Health) -match "^$([regex]::Escape($from))") "the sandbox board runs $from ($(Health))"
  # a live seat through the update (as hop2): after it, the seat must run exactly one shell (architect m-4e2fe95fac).
  # -ClaudeSeat (architect m-6f9232f522): the stub codex never answers `codex mcp list`, so a codex seat refuses to
  # start about 30 s in and is gone before the update; a Claude seat in monitor mode outlives `stop --force` as the
  # owner's windows do. It opens a visible stub console window on the desktop, and its resumed shell another.
  if ($ClaudeSeat) {
    & $Py "$PSScriptRoot\gate_rc2_checks.py" $H "$leg-claude" --out $Ev --spawn-claude-monitor 2>&1 | ForEach-Object { "   | $_" }
    $seats = { ClaudeSeats }; $kind = "Claude"
  } else {
    & $Py "$PSScriptRoot\gate_rc2_checks.py" $H "$leg-codex" --out $Ev --spawn-codex 2>&1 | ForEach-Object { "   | $_" }
    $seats = { CodexSeats }; $kind = "codex"
  }
  $deadline = (Get-Date).AddSeconds(60)
  do { Start-Sleep -Seconds 2; $seat0 = @(& $seats) } while (-not $seat0 -and (Get-Date) -lt $deadline)
  Check ($seat0.Count -ge 1) "$kind seat shells run from the gate install before the update (pids $($seat0 -join ','))"
  if ($ClaudeSeat) {
    # architect m-5af39714ab: the owner's windows predated the pool that ran at their update (5980 was spawned by a pool
    # replaced a day earlier), so `stop --force` reached them neither as descendants nor through the pool's job. The pool
    # restarts once with its seats kept, so the update meets a seat outside the running pool's tree, as the owner's was.
    $rows = @(try { Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10 } catch { })
    $row0 = $rows | Where-Object { $_.mode -eq "monitor" -and $_.handle -like "engineer.*" -and $_.proc } | Select-Object -First 1
    Check ([bool]$row0) "the pool tracks the Claude seat ($($row0.handle): $($row0.state), proc $($row0.proc.pid) $($row0.proc.name))"
    $shell0 = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$row0.proc.pid)"
    "   the seat's shell $($row0.proc.pid) runs under parent $($shell0.ParentProcessId) (the pool that spawned it)"
    Hx "$leg-stop-pool" @("stop", "pool", "--keep-seats")
    Hx "$leg-restart" @("start", "--no-browser")
    $deadline = (Get-Date).AddSeconds(60)
    do {
      Start-Sleep -Seconds 3
      $rowR = @(try { Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10 } catch { }) | Where-Object { $_.handle -eq $row0.handle } | Select-Object -First 1
    } while ($rowR.state -ne "active" -and (Get-Date) -lt $deadline)
    $seatR = @(& $seats)
    Check ($seatR.Count -eq $seat0.Count -and -not (Compare-Object @($seat0) @($seatR))) "the Claude seat outlives the pool restart with --keep-seats (before $($seat0 -join ','), after $($seatR -join ','))"
    $shellR = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$row0.proc.pid)"
    $par = if ($shellR) { Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$shellR.ParentProcessId)" }
    Check ($shellR -and -not ($par -and $par.CommandLine -like "*--heronry-service pool*")) "the seat's shell (pid $($row0.proc.pid)) is no longer a live pool's child (parent $($shellR.ParentProcessId): $(if ($par) { $par.Name } else { 'gone' }))"
    Check ($rowR.state -eq "active" -and [int]$rowR.proc.pid -eq [int]$row0.proc.pid -and [double]$rowR.proc.create_time -eq [double]$row0.proc.create_time) "the restarted pool tracks the seat as active with the same proc ($($rowR.state), pid $($rowR.proc.pid), create_time $($rowR.proc.create_time))"
  }
  Hx "$leg-code" @("start", "code")
  $guard = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*--heronry-service code-guard*" -and (Under $_ $Inst) })
  Check ($guard.Count -ge 1) "the code server's guard runs from the gate install (pids $(($guard | ForEach-Object ProcessId) -join ','))"
  $seat = (Get-Content (Join-Path $H "tokens.json") -Raw | ConvertFrom-Json).PSObject.Properties.Name | Where-Object { $_ -ne "owner" } | Select-Object -First 1
  OrphanFeed $seat $leg
  $feed = $script:orphan
  Start-Sleep -Seconds 5
  Check ($feed -and -not $feed.HasExited) "a seat's feed monitor runs from the gate install (pid $($feed.Id))"
  $stop = Join-Path $Ev "$leg-probe.stop"
  Remove-Item $stop, "$Ev\$leg-rm.jsonl" -ErrorAction SilentlyContinue
  $probe = Start-Process -FilePath $Py -NoNewWindow -PassThru -RedirectStandardError "$Ev\$leg-probe.err" `
    -ArgumentList @("$PSScriptRoot\gate_rm_probe.py", "`"$Inst`"", "`"$Ev\$leg-rm.jsonl`"", "`"$stop`"")
  if ($Workaround) {
    "== $(Stamp) the owner's one-time workaround: stop the code server, then each feed monitor by pid"
    Hx "$leg-stop-code" @("stop", "code")
    $said = Get-Content "$Ev\$leg-stop-code.txt" -Raw
    Check ($script:rc -eq 0 -and $said -notmatch "not running") "heronry stop code stopped a running code server (exit $script:rc)"
    $feeds = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*edp8.feed_driver*" -and (Under $_ $Inst) })
    foreach ($f in $feeds) { "   taskkill /PID $($f.ProcessId) /F   (feed monitor)"; & taskkill /PID $f.ProcessId /F 2>&1 | ForEach-Object { "   | $_" } }
    Start-Sleep -Seconds 2
    $left = @(Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like "*edp8.feed_driver*" -or $_.CommandLine -like "*--heronry-service code-guard*") -and (Under $_ $Inst) })
    Check (-not $left) "no code server or feed monitor runs from the install after the workaround (left: $(($left | ForEach-Object ProcessId) -join ','))"
  }
  "== $(Stamp) heronry update --release-url (the owner's restart path)$(if (-not $Workaround) { ', with both alive' })"
  $t0 = Get-Date
  Hx "$leg-update" @("update", "--release-url", (Join-Path $Gate "release-$to"), "--previous-url", (Join-Path $Gate "release-$from"))
  $deadline = (Get-Date).AddMinutes(20)
  while ((Get-Date) -lt $deadline -and -not ((Get-ChildItem $H -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue) | Select-Object -First 1)) { Start-Sleep -Seconds 3 }
  New-Item -ItemType File -Force $stop | Out-Null
  $script:res = $null
  $rf = Get-ChildItem $H -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($rf) { Copy-Item $rf.FullName "$Ev\$leg-update-result.json"; $script:res = Get-Content $rf.FullName -Raw | ConvertFrom-Json }
  $ul = Get-ChildItem $H -Recurse -Filter "update.log" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($ul) { Copy-Item $ul.FullName "$Ev\$leg-update.log"; Get-Content $ul.FullName | ForEach-Object { "   | $_" } }
  # item 6: the rollback's `start` said board FAILED; keep the board's own log beside the update's
  Get-ChildItem $H -Recurse -Filter "board*.log" -ErrorAction SilentlyContinue | ForEach-Object { Copy-Item $_.FullName "$Ev\$leg-$($_.Name)" }
  # the pool resumes an updater-parked seat a few seconds after its start: give it 90 s, then count the shells
  $deadline = (Get-Date).AddSeconds(90)
  do { Start-Sleep -Seconds 5; $seat1 = @(& $seats) } while ($seat1.Count -lt $seat0.Count -and (Get-Date) -lt $deadline)
  Start-Sleep -Seconds 10
  $script:seat0 = $seat0; $script:seat1 = @(& $seats)
  "   seat shells: before $($seat0 -join ','), after $($script:seat1 -join ',') ($(if ($script:seat1 | Where-Object { $seat0 -contains $_ }) { 'the old shell lives on' } else { 'no old shell' }))"
  "   update: $($script:res.state) in $([int]((Get-Date) - $t0).TotalSeconds) s: $($script:res.reason)"
  Start-Sleep -Seconds 2
  $script:feedAfter = -not $feed.HasExited
  foreach ($p in @($feed, $probe)) { if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
  "   stopped by pid: feed monitor $($feed.Id) (alive after the update: $script:feedAfter), probe $($probe.Id)"
  if ($ClaudeSeat) {   # the resumed seat's console window and its tree (the stub's sleeping grandchild is not under the gate)
    $shells = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "cmd.exe" -and $_.CommandLine -like "*claude-stub.cmd*" -and (Under $_ $Gate) })
    foreach ($s in $shells) { "   taskkill /PID $($s.ProcessId) /T /F   (Claude seat shell)"; & taskkill /PID $s.ProcessId /T /F 2>&1 | ForEach-Object { "   | $_" } }
  }
  & $Py -c "import json,sys,collections; rows=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]; c=collections.Counter((r.get('start_rc'),tuple(r.get('register_rcs') or ()),r.get('list1_rc'),r.get('list2_rc')) for r in rows); print('   probe looks:',len(rows)); [print('   rcs (start, register, list1, list2)',k,'x',n) for k,n in c.most_common()]" "$Ev\$leg-rm.jsonl"
}

if ($Phase -eq "hop2rm") {
  # t-fd7cf3a6b5: 0.10.0's helper on a spaced folder ends at msiexec 1639, and msiexec answers 1639 with its usage
  # dialog on the desktop even under /qn (the owner saw it: m-905f81e190). Recorded once (hop2rm-spaces.log); never again
  "ABORT hop2rm runs 0.10.0's helper, which pops msiexec's 1639 dialog on the desktop in a spaced folder ($Inst)"; exit 3
  RmLeg "hop2rm-a" "0.10.0" "0.10.1" -PinCode
  Check ($res.state -eq "rolled_back" -and $res.reason -match "Restart Manager|held") "a: 0.10.0's helper reproduces the owner's rollback ($($res.state) $($res.reason))"
  Check ((Health) -match "^0\.10\.0") "a: the board is back on 0.10.0 ($(Health))"
  RmLeg "hop2rm-b" "0.10.0" "0.10.1" -Workaround -PinCode
  Check ($res.state -eq "rolled_back" -and $res.reason -match "msiexec exit 1639") "b: with the workaround 0.10.0's helper reaches msiexec, which refuses the spaced install folder with 1639 ($($res.state) $($res.reason))"
  Check ((Health) -match "^0\.10\.0") "b: the board is back on 0.10.0 ($(Health))"
}

if ($Phase -eq "hop3rm") {
  RmLeg "hop3rm" "0.10.1" "0.10.2" -ClaudeSeat -PinCode   # the pin skips a 207 MB fetch (architect m-08bbc021ae)
  Check ($res.state -eq "ok") "the fixed helper's update ends ok with the code server and a feed monitor alive ($($res.state) $($res.reason))"
  Check ((Health) -match "^0\.10\.2") "the board runs 0.10.2 after the update ($(Health))"
  Check ($seat1.Count -eq $seat0.Count -and -not ($seat1 | Where-Object { $seat0 -contains $_ })) "each seat runs exactly one fresh shell after the update (before $($seat0 -join ','), after $($seat1 -join ','))"
  $log = if (Test-Path "$Ev\hop3rm-update.log") { Get-Content "$Ev\hop3rm-update.log" -Raw } else { "" }
  Check ($log -match "ending parked seat " -and $log -notmatch "its shell is already gone") "the parked seat outlived the stop and the update ended its shell with its tree, named in update.log"
  Check ($log -match "(?m)^.*stop code: .* stop code") "the update stopped the code server through ``heronry stop code``"
  # the gate's own feed monitor is an orphan (a child of this shell, no seat): the by-pid backstop's case
  Check ($log -match "stopping .*edp8\.feed_driver.*runs from the install folder" -and -not $feedAfter) "the update stopped the orphaned feed monitor by its pid, named in update.log"
  Check ($log -match "restart manager look 1/\d+ \(images\): \{") "update.log carries the Restart Manager return codes"
  $guard = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*--heronry-service code-guard*" -and (Under $_ $Inst) })
  Check ($guard.Count -ge 1) "the code server runs again after the update (pids $(($guard | ForEach-Object ProcessId) -join ','))"
}

# ------------------------------------------------------------------------------------------ the up-front refusal
# t-fb8b63874e (architect m-bdbb53ca17): a live seat the pool does not track, with its feed monitor running from the
# install folder, makes `heronry update` refuse before it downloads, parks or stops anything, naming the seat. The
# fixed 0.10.1 (from the run-rm .bat's build) runs on its own home; a hand-started seat-like process (the installed
# exe, its command line marked `edp8.codex_seat.run` as a codex seat's is) starts a feed monitor child. Both are
# plain children of this shell, stopped by pid at the end. Needs release-0.10.1 (fixed) and release-0.10.2.
if ($Phase -eq "refuse") {
  $H = Join-Path $Gate "home refuse"
  StopPrivate
  Uninstall
  CopyHome $H
  UseEnv $H
  "== $(Stamp) refuse: the fixed 0.10.1 running, with a live seat outside the pool and its feed monitor"
  Install "0.10.1" "msiexec-refuse-0.10.1.log"
  Check ($script:msiRc -eq 0) "0.10.1 (gate identity) installed"
  Hx "refuse-start" @("start", "--no-browser")
  Check ((Health) -match "^0\.10\.1") "the sandbox board runs 0.10.1 ($(Health))"
  Set-Content -Path "$Gate\fakeseat.py" -Encoding ascii -Value @'
import subprocess, sys, time
# a seat-like shell outside the pool: argv = <marker> <participant> <board> <broker>; its child is the feed monitor
subprocess.Popen([sys.executable, "-m", "edp8.feed_driver", "--participant", sys.argv[2], "--board", sys.argv[3],
                  "--broker", sys.argv[4]])
time.sleep(900)
'@
  $seat = (Get-Content (Join-Path $H "tokens.json") -Raw | ConvertFrom-Json).PSObject.Properties.Name | Where-Object { $_ -ne "owner" } | Select-Object -First 1
  $code = "import runpy,sys; sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"
  $fake = Start-Process -FilePath $Exe -NoNewWindow -PassThru -RedirectStandardOutput "$Ev\refuse-seat.out" -RedirectStandardError "$Ev\refuse-seat.err" `
    -ArgumentList "-c `"$code`" `"$Gate\fakeseat.py`" edp8.codex_seat.run $seat http://127.0.0.1:$env:EDP8_PORT http://127.0.0.1:$env:EDP_BROKER_PORT"
  Start-Sleep -Seconds 8
  $feed = @(Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $fake.Id -and $_.CommandLine -like "*edp8.feed_driver*" })
  Check (-not $fake.HasExited -and $feed.Count -eq 1) "a seat outside the pool (pid $($fake.Id)) runs a feed monitor from the install (pid $(($feed | ForEach-Object ProcessId) -join ','))"
  Remove-Item (Join-Path $H ".data\update\update-result.json") -ErrorAction SilentlyContinue
  Hx "refuse-update" @("update", "--release-url", (Join-Path $Gate "release-0.10.2"), "--previous-url", (Join-Path $Gate "release-0.10.1"))
  # Tee-Object writes UTF-16, and PowerShell 5.1 wraps the stderr ErrorRecord at console width: collapse it (m-6f9232f522)
  $out = (Get-Content "$Ev\refuse-update.txt" -Raw -Encoding Unicode) -replace '\s+', ' '
  Check ($script:rc -eq 2) "heronry update exits 2 (exit $script:rc)"
  Check ($out -match "update refused: seat\(s\) running outside the pool's tracking" -and $out -match "\(pid $($fake.Id)\): " -and
         $out -match "Close this window, or resume the seat through the board, then run update again" -and $out -match "Nothing changed") "the refusal names the seat (pid $($fake.Id)) and the remedy"
  $rows = @(try { Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10 } catch { })
  $parked = @($rows | Where-Object { $_.state -eq "parked" -or $_.park_for_update })
  Check (-not $parked) "nothing was parked ($(($parked | ForEach-Object handle) -join ','))"
  Check (-not (Get-ChildItem $H -Recurse -Filter "update-result.json" -ErrorAction SilentlyContinue) -and -not (Test-Path (Join-Path $H ".data\update\update-plan.json"))) "no update was staged"
  Check (-not $fake.HasExited -and (Get-Process -Id $feed[0].ProcessId -ErrorAction SilentlyContinue)) "the seat and its feed monitor still run (nothing was stopped)"
  Check ((Health) -match "^0\.10\.1") "the board still runs 0.10.1 ($(Health))"
  foreach ($p in @($feed | ForEach-Object ProcessId) + @($fake.Id)) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
  "   stopped by pid: feed monitor $(($feed | ForEach-Object ProcessId) -join ','), seat $($fake.Id)"
}

# ------------------------------------------------------------------------------------------ 0.10.0 -> 0.10.1 by hand
# t-fd7cf3a6b5 (architect m-9600222f25): 0.10.0's helper always hits msiexec 1639 in a folder with a space, so the owner
# updates this one hop by hand, by the steps in the owner guide (note-5f00be90f6), the 0.9.x path hop1 proves plus the
# code server and the feed monitors. A live 0.10.0 in the spaced folder with the code server, a feed monitor and a
# Claude seat in monitor mode (a visible stub console window, closed by pid as the owner closes it), then exactly
# those steps.
# -Tail runs steps 7-8 on the sandbox steps 1-6 left running, as a foreground call (architect m-3db0224041: the harness
# reaps a background shell under memory pressure, which is what killed hop3rm's first download)
$H010 = Join-Path $Gate "home manual010"
if ($Phase -eq "manual010" -and $Tail) {
  $H = $H010
  $st = Get-Content (Join-Path $H "gate\manual010.json") -Raw | ConvertFrom-Json
  $pj = Get-Content (Join-Path $H "gate\ports.json") -Raw | ConvertFrom-Json
  $ports = @{}; foreach ($k in $pj.PSObject.Properties.Name) { $ports[$k] = $pj.$k }
  UseEnv $H $ports
  $row0 = [pscustomobject]@{ handle = $st.handle }; $seat0 = @($st.seat0); $feed = $null
  Check ((Health) -match "^0\.10\.1") "steps 1-6 left the sandbox board on 0.10.1 ($(Health))"
}
if ($Phase -eq "manual010" -and -not $Tail) {
  $H = $H010
  StopPrivate
  Uninstall
  CopyHome $H
  UseEnv $H
  PinCode $H
  "== $(Stamp) manual010: 0.10.0 installed and running in the spaced folder, with the code server, a feed monitor and a seat"
  Install "0.10.0" "msiexec-manual010-0.10.0.log"
  Check ($script:msiRc -eq 0) "0.10.0 (gate identity) installed in '$Inst'"
  Hx "manual010-start-0.10.0" @("start", "--no-browser")
  Check ((Health) -match "^0\.10\.0") "the sandbox board runs 0.10.0 ($(Health))"
  & $Py "$PSScriptRoot\gate_rc2_checks.py" $H "manual010-claude" --out $Ev --spawn-claude-monitor 2>&1 | ForEach-Object { "   | $_" }
  $deadline = (Get-Date).AddSeconds(60)
  do { Start-Sleep -Seconds 2; $seat0 = @(ClaudeSeats) } while (-not $seat0 -and (Get-Date) -lt $deadline)
  $row0 = @(try { Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10 } catch { }) |
    Where-Object { $_.mode -eq "monitor" -and $_.handle -like "engineer.*" -and $_.proc } | Select-Object -First 1
  Check ($seat0.Count -ge 1 -and $row0) "a Claude seat window runs ($($row0.handle), shell $($row0.proc.pid), stub pids $($seat0 -join ','))"
  Hx "manual010-code" @("start", "code")
  $guard = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*--heronry-service code-guard*" -and (Under $_ $Inst) })
  Check ($guard.Count -ge 1) "the code server's guard runs from the install (pids $(($guard | ForEach-Object ProcessId) -join ','))"
  $seat = (Get-Content (Join-Path $H "tokens.json") -Raw | ConvertFrom-Json).PSObject.Properties.Name | Where-Object { $_ -ne "owner" } | Select-Object -First 1
  OrphanFeed $seat "manual010"
  $feed = $script:orphan
  Start-Sleep -Seconds 5
  Check ($feed -and -not $feed.HasExited) "a feed monitor runs from the install (pid $($feed.Id))"

  "== $(Stamp) the owner's steps (note-5f00be90f6)"
  "   1. close every seat window (closing a console window ends its tree)"
  & taskkill /PID ([int]$row0.proc.pid) /T /F 2>&1 | ForEach-Object { "   | $_" }
  Start-Sleep -Seconds 2
  Check (-not @(ClaudeSeats)) "no seat window is left ($((@(ClaudeSeats)) -join ','))"
  "   2. heronry stop code"
  Hx "manual010-stop-code" @("stop", "code")
  $said = Get-Content "$Ev\manual010-stop-code.txt" -Raw
  Check ($script:rc -eq 0 -and $said -notmatch "not running") "heronry stop code stopped a running code server (exit $script:rc)"
  "   3. each feed monitor by its pid, /F without /T"
  $feeds = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*edp8.feed_driver*" -and (Under $_ $Inst) })
  foreach ($f in $feeds) { "   taskkill /PID $($f.ProcessId) /F"; & taskkill /PID $f.ProcessId /F 2>&1 | ForEach-Object { "   | $_" } }
  Start-Sleep -Seconds 2
  $left = @(Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like "*edp8.feed_driver*" -or $_.CommandLine -like "*--heronry-service code-guard*") -and (Under $_ $Inst) })
  Check (-not $left) "no code server or feed monitor runs from the install (left: $(($left | ForEach-Object ProcessId) -join ','))"
  "   4. heronry stop all --force"
  Hx "manual010-stop-all" @("stop", "all", "--force")
  Check ($script:rc -eq 0) "heronry stop all --force exits 0"
  $held = @(Get-CimInstance Win32_Process | Where-Object { (Under $_ $Inst) })
  Check (-not $held) "nothing runs from the install folder (left: $(($held | ForEach-Object { "$($_.Name) $($_.ProcessId)" }) -join ', '))"
  # the owner's install has no pin (architect m-08bbc021ae): the pin only gave 0.10.0 a running code server to stop, so
  # it goes before 0.10.1, whose `start code` then takes the download path on the spaced install
  $cfg = Join-Path $H "config.toml"
  [IO.File]::WriteAllLines($cfg, [string[]]@(Get-Content $cfg | Where-Object { $_ -notmatch "^path = '.*code-server" }))
  Check (-not (Select-String -Path $cfg -Pattern "^path = '" -Quiet)) "the code-server pin is gone before 0.10.1"
  "   5. run the 0.10.1 installer (msiexec /i, INSTALLFOLDER=`"<the spaced folder>`")"
  Install "0.10.1" "msiexec-manual010-0.10.1.log"
  Check ($script:msiRc -eq 0) "msiexec /i 0.10.1 exits 0 into '$Inst' (exit $script:msiRc)"
  "   6. heronry start"
  Hx "manual010-start-0.10.1" @("start", "--no-browser")
  Check ($script:rc -eq 0 -and (Health) -match "^0\.10\.1") "the board runs 0.10.1 after the manual install ($(Health))"
  @{ handle = $row0.handle; seat0 = $seat0 } | ConvertTo-Json | Set-Content (Join-Path $H "gate\manual010.json") -Encoding ascii
  "== $(Stamp) steps 1-6 done; the sandbox stays up for -Tail (steps 7-8)"
}
if ($Phase -eq "manual010" -and $Tail) {
  "   7. heronry start code"
  $free = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
  if ($free -lt 1) {   # the code-server download and unpack (owner m-783ec47f35: 400 MB is headroom; architect m-3db0224041)
    "ABORT $free GB free before step 7's code-server download: below 1 GB, stopping the sandbox"
    StopPrivate; exit 4 }
  "   $free GB free"
  Hx "manual010-code-after" @("start", "code")
  $guard = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*--heronry-service code-guard*" -and (Under $_ $Inst) })
  Check ($guard.Count -ge 1) "the code server runs again (pids $(($guard | ForEach-Object ProcessId) -join ','))"
  "   8. resume the seat from the board, then check one live window per seat"
  & $Py "$PSScriptRoot\gate_rc2_checks.py" $H "manual010-resume" --out $Ev --resume $row0.handle 2>&1 | ForEach-Object { "   | $_"; if ($_ -like "*FAIL*") { $script:fail++ } }
  $deadline = (Get-Date).AddSeconds(90)
  do { Start-Sleep -Seconds 5; $seat1 = @(ClaudeSeats) } while ($seat1.Count -lt $seat0.Count -and (Get-Date) -lt $deadline)
  Start-Sleep -Seconds 10
  $seat1 = @(ClaudeSeats)
  Check ($seat1.Count -eq $seat0.Count -and -not ($seat1 | Where-Object { $seat0 -contains $_ })) "the seat runs exactly one fresh window (before $($seat0 -join ','), after $($seat1 -join ','))"
  if ($feed -and -not $feed.HasExited) { Stop-Process -Id $feed.Id -Force -ErrorAction SilentlyContinue }
  $shells = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -eq "cmd.exe" -and $_.CommandLine -like "*claude-stub.cmd*" -and (Under $_ $Gate) })
  foreach ($s in $shells) { "   taskkill /PID $($s.ProcessId) /T /F   (the resumed seat's window)"; & taskkill /PID $s.ProcessId /T /F 2>&1 | ForEach-Object { "   | $_" } }
}

# ------------------------------------------------------------------------------------------ memory log for a long leg
if ($Phase -eq "memlog") {
  $log = $Only[0]
  while (-not (Select-String -Path $log -Pattern "^== .* done: " -Quiet -ErrorAction SilentlyContinue)) {
    $free = [int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1KB)
    $top = @(Get-CimInstance Win32_Process | Where-Object { (Under $_ $Gate) -and $_.ProcessId -ne $PID } |
      Sort-Object WorkingSetSize -Descending | Select-Object -First 6 |
      ForEach-Object { "$($_.Name):$($_.ProcessId):$([int]($_.WorkingSetSize / 1MB))MB" }) -join " "
    Add-Content -Path "$log.mem.txt" -Value "   [mem $(Stamp)] free MB $free | $top"
    Start-Sleep -Seconds 10
  }
  exit 0
}

if ($Phase -eq "clean") { StopPrivate; Uninstall }

$Fleet1 = FleetSnap
Check ($Fleet1 -eq $Fleet0) "the fleet's service pids are unchanged ($Fleet0)"
"== $(Stamp) $Phase done: $fail failure(s)"
exit [int]($fail -gt 0)
