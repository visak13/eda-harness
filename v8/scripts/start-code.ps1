# Start the `code` service: code-server on 127.0.0.1:<EDP_CODE_PORT> (default 9410), auth none
# (s-3c8c2512d6; design-449b628cdd section 4; strategyhl-e69dbbae06 + strategyhl-f300df15cb; S1 report-b90f1f63df).
#
#   scripts\start-code.ps1                     install if needed, seed settings, install missing pinned
#                                              extensions, launch, wait for /healthz, write .run\code.json
#   scripts\start-code.ps1 -SkipExtensions     leave the extensions dir as it is (tests)
#
# Idempotent: our own server already listening on the port is left running. A foreign listener on the
# port fails loudly and is never killed. The bind is loopback only: with --auth none the socket is the
# only fence (anyone who reaches the port owns the host through the terminal), so any other
# EDP_CODE_HOST is refused. Every EDP_* / EDP8_* variable is removed from the server's environment
# (dec-ea925a2d30: terminals and extensions must not inherit seat or board secrets, DB or run dirs);
# the removal is scoped to the launch, so a seat shell that runs this script keeps its own env.
# Stop with scripts\stop-code.ps1. Seats start/stop ONLY this service (shared-host rules).
param(
  [switch]$SkipExtensions,
  [int]$TimeoutSec = 30
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$v8 = Split-Path -Parent $PSScriptRoot

function Fail($code, $msg) { [Console]::Error.WriteLine("start-code: $msg"); exit $code }
function EnvOr($n, $d) { $v = [Environment]::GetEnvironmentVariable($n, "Process"); if ($v) { $v } else { $d } }
function WriteUtf8($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }

# the same v8\.env as edp.ps1 (the real environment wins), so a direct run agrees with edp.ps1 on the port
function LoadDotEnv($file) {
  if (-not (Test-Path $file)) { return }
  $vals = [ordered]@{}
  foreach ($line in Get-Content $file) {
    $t = $line.Trim(); if (-not $t -or $t.StartsWith("#")) { continue }
    $kv = $t -split "=", 2
    if ($kv.Count -eq 2) { $vals[$kv[0].Trim()] = ($kv[1] -split "\s+#", 2)[0].Trim() }
  }
  foreach ($k in $vals.Keys) { if (-not [Environment]::GetEnvironmentVariable($k, "Process")) { [Environment]::SetEnvironmentVariable($k, $vals[$k], "Process") } }
}
LoadDotEnv (Join-Path $v8 ".env")

# -- configuration (read BEFORE the env strip) ------------------------------------------------------
$HOMEDIR = EnvOr "EDP8_HOME" $v8
$RUN = EnvOr "EDP8_RUN_DIR" (Join-Path $HOMEDIR ".run")
$DATA = EnvOr "EDP_CODE_DATA" (Join-Path $v8 ".data\code")
$PORT = [int](EnvOr "EDP_CODE_PORT" "9410")
$BINDHOST = EnvOr "EDP_CODE_HOST" "127.0.0.1"
$BOARD = "http://127.0.0.1:" + (EnvOr "EDP8_PORT" "9400")
if (@("127.0.0.1", "localhost") -notcontains $BINDHOST.ToLower()) {
  Fail 2 "refusing EDP_CODE_HOST=${BINDHOST}: code-server runs with --auth none, so it binds 127.0.0.1 only"
}
$BINDHOST = "127.0.0.1"

$lock = Get-Content (Join-Path $v8 "vscode-ext\code-server.lock.json") -Raw | ConvertFrom-Json
$toolsRoot = Join-Path $v8 ".tools\code-server"
$installDir = Join-Path $toolsRoot $lock.version
$serverDir = Join-Path $installDir $lock.server_dir
$node = Join-Path $serverDir $lock.node
$toolsNorm = ([IO.Path]::GetFullPath($toolsRoot)).TrimEnd("\") + "\"
$userDir = Join-Path $DATA "user"
$extDir = Join-Path $DATA "extensions"
$config = Join-Path $DATA "config.yaml"
$stateFile = Join-Path $RUN "code.json"
New-Item -ItemType Directory -Force $RUN, $DATA, $userDir, $extDir, (Join-Path $userDir "User") | Out-Null

function Proc($procId) { Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue }
function IsOurs($p) { $p -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($toolsNorm, [StringComparison]::OrdinalIgnoreCase) }
function ListenerPid { $c = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { [int]$c.OwningProcess } else { $null } }
function Healthy { try { (Invoke-WebRequest "http://127.0.0.1:$PORT/healthz" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }
function GitRev { try { ("" + (& git -C $v8 rev-parse --short HEAD 2>$null)).Trim() } catch { "" } }
function WriteState($p) {
  $state = [ordered]@{
    service = "code"; pid = [int]$p.ProcessId; port = $PORT; version = $lock.version; sha256 = $lock.sha256
    git_rev = (GitRev); started_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    creation_date = $p.CreationDate.ToString("o"); install_dir = $installDir
    last_probe = $null; last_ok = $null; last_restart_reason = $null; restarts = 0
  }
  WriteUtf8 $stateFile ($state | ConvertTo-Json)
}

# -- already running? -----------------------------------------------------------------------------
$lp = ListenerPid
if ($lp) {
  $p = Proc $lp
  if (-not (IsOurs $p)) { Fail 3 "port $PORT is held by pid $lp ($($p.Name) $($p.ExecutablePath)), not this code-server; leaving it alone" }
  # the listener is the server's child: the record names the outermost ancestor that is also ours
  $root = $p
  for ($i = 0; $i -lt 3; $i++) {
    $pp = Proc $root.ParentProcessId
    if ((IsOurs $pp) -and $pp.CreationDate -le $root.CreationDate) { $root = $pp } else { break }
  }
  # adopt it when the record is missing or names another process (a stale record from an earlier run)
  $rec = $null; try { $rec = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { }
  if (-not $rec -or [int]$rec.pid -ne [int]$root.ProcessId) { WriteState $root }
  $pinned = ([IO.Path]::GetFullPath($installDir)).TrimEnd("\") + "\"
  if (-not $root.ExecutablePath.StartsWith($pinned, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "code     running on 127.0.0.1:$PORT from $($root.ExecutablePath), NOT the pinned $($lock.version): restart it (.\edp.ps1 restart code)"
  } else { Write-Host "code     already running on 127.0.0.1:$PORT (pid $($root.ProcessId))" }
  exit 0
}

# -- one start at a time: a second start (a retry after an edp timeout) must not race the first's
# download/extract/extension install. The lock is an exclusively opened file, released on exit.
$startLock = $null
try { $startLock = [IO.File]::Open((Join-Path $RUN "code.start.lock"), "OpenOrCreate", "ReadWrite", "None") }
catch { Fail 7 "another start-code.ps1 is running (it holds $RUN\code.start.lock); wait for it" }

# -- install (no-op when the pinned build is present and verified) -----------------------------------
& (Join-Path $PSScriptRoot "install-code-server.ps1")
if ($LASTEXITCODE -ne 0) { Fail 4 "install-code-server.ps1 exited $LASTEXITCODE" }

# -- the environment strip, scoped: run a block with every EDP_*/EDP8_* removed, then restore -----
function WithoutFleetEnv([scriptblock]$block) {
  $saved = @{}
  foreach ($k in @([Environment]::GetEnvironmentVariables("Process").Keys)) {
    if ($k -match '^EDP8?_') { $saved[$k] = [Environment]::GetEnvironmentVariable($k, "Process"); [Environment]::SetEnvironmentVariable($k, $null, "Process") }
  }
  try { & $block } finally { foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], "Process") } }
}

# -- config.yaml: our own, so a flag-less launch never falls back to :8080 with a password ---------
WriteUtf8 $config ("# written by scripts\start-code.ps1 on every start; edits are overwritten`nbind-addr: ${BINDHOST}:$PORT`nauth: none`ncert: false`n")

# -- pinned extension list ------------------------------------------------------------------------
$pins = @(Get-Content (Join-Path $v8 "vscode-ext\extensions.txt") | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("#") })
$extLock = (Get-Content (Join-Path $v8 "vscode-ext\extensions.lock.json") -Raw | ConvertFrom-Json).extensions

# -- user settings: merge the managed keys, keep everything else the user set ----------------------
$settingsPath = Join-Path $userDir "User\settings.json"
$settings = [ordered]@{}
if (Test-Path $settingsPath) {
  try {
    $cur = Get-Content $settingsPath -Raw | ConvertFrom-Json
    if ($cur) { foreach ($pr in $cur.PSObject.Properties) { $settings[$pr.Name] = $pr.Value } }
  } catch {
    $bak = "$settingsPath.bak-" + (Get-Date).ToString("yyyyMMddHHmmss")
    Copy-Item $settingsPath $bak
    Write-Host "settings.json did not parse as JSON; kept a copy at $bak and re-seeded"
  }
}
$exclude = [ordered]@{ "**/.venv/**" = $true; "**/node_modules/**" = $true; "**/.data/**" = $true; "**/.run/**" = $true; "**/.tools/**" = $true; "**/web/dist/**" = $true }
$gitExe = (Get-Command git -ErrorAction SilentlyContinue | Select-Object -First 1).Source
$bash = $null
# Git for Windows puts git.exe in <root>\cmd or <root>\mingw64\bin; Git Bash is <root>\bin\bash.exe
$d = if ($gitExe) { Split-Path -Parent $gitExe } else { $null }
for ($i = 0; $d -and $i -lt 3 -and -not $bash; $i++) {
  $b = Join-Path $d "bin\bash.exe"; if ((Test-Path $b) -and (Test-Path (Join-Path $d "git-bash.exe"))) { $bash = $b }
  $d = Split-Path -Parent $d
}
$profiles = [ordered]@{
  "PowerShell" = [ordered]@{ path = (Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"); icon = "terminal-powershell" }
  "Command Prompt" = [ordered]@{ path = (Join-Path $env:SystemRoot "System32\cmd.exe"); icon = "terminal-cmd" }
}
if ($bash) { $profiles["Git Bash"] = [ordered]@{ path = $bash; args = @("--login", "-i"); icon = "terminal-bash" } }
$autolinks = @(foreach ($pre in @("t-", "s-", "epic-", "m-")) {
  [ordered]@{ prefix = $pre; url = "$BOARD/ui/ticket/$pre<num>"; alphanumeric = $true; ignoreCase = $false; title = "Open $pre<num> on the board" }
})
$allowed = [ordered]@{}
foreach ($pin in $pins) {
  $id, $ver = $pin -split "@", 2
  $tp = $extLock.$id.target_platform
  if ($tp -and $tp -ne "universal") { $ver = "$ver@$tp" }
  $allowed[$id] = @($ver)
}
# our own extension, installed from the local vsix below (not a pin): any version it is built at
$allowed["edp.edp-code"] = $true
$settings["extensions.autoUpdate"] = $false
$settings["extensions.autoCheckUpdates"] = $true
$settings["extensions.allowed"] = $allowed
$settings["files.watcherExclude"] = $exclude
$settings["search.exclude"] = $exclude
$settings["terminal.integrated.profiles.windows"] = $profiles
$settings["terminal.integrated.defaultProfile.windows"] = "PowerShell"
$settings["gitlens.autolinks"] = $autolinks
# the blame hover (commit + its ticket link) shows when hovering anywhere on the current line
$settings["gitlens.hovers.currentLine.over"] = "line"
$settings["telemetry.telemetryLevel"] = "off"
$settings["update.mode"] = "none"
# PS 5.1 escapes < > as < >: same JSON, but the autolink <num> placeholder should read as written
WriteUtf8 $settingsPath (($settings | ConvertTo-Json -Depth 10) -replace '\\u003c', '<' -replace '\\u003e', '>')

# -- extensions: install the missing pins from sha256-checked .vsix files ------------------------
function CodeCli($cliArgs) {
  # the server entry in CLI mode, with the fleet env stripped; returns stdout+stderr lines
  WithoutFleetEnv {
    # PS 5.1 turns a native stderr line (node's DeprecationWarning) into a terminating error under Stop
    $ErrorActionPreference = "Continue"
    # no gallery for CLI installs: with one configured, a vsix's extensionPack/extensionDependencies
    # (ms-python.python -> debugpy, envs) were fetched from Open VSX unchecked and replaced our files
    $galleryWas = $env:EXTENSIONS_GALLERY; $env:EXTENSIONS_GALLERY = "{}"
    try {
      $script:cliOut = @(& $node $serverDir --user-data-dir $userDir --extensions-dir $extDir @cliArgs 2>&1 |
        ForEach-Object { "$_" } | Where-Object { $_ -notmatch "DeprecationWarning|trace-deprecation" })
      $script:cliExit = $LASTEXITCODE
    } finally { $env:EXTENSIONS_GALLERY = $galleryWas }
  }
  $script:cliOut
}
function InstallVsix($files) {
  # ONE call for every file: ms-python.debugpy declares ms-python.python as a dependency and python's
  # pack names debugpy, so a file-by-file install fetched the missing one from the gallery unchecked
  $cliArgs = @(); foreach ($f in $files) { $cliArgs += @("--install-extension", $f) }
  CodeCli ($cliArgs + @("--force")) | ForEach-Object { Write-Host "   | $_" }
  if ($script:cliExit -ne 0) { Fail 5 "installing $($files -join ', ') failed ($script:cliExit)" }
}
if ($SkipExtensions) {
  Write-Host "extensions: skipped (-SkipExtensions)"
} else {
  $vsixCache = Join-Path $v8 ".tools\vsix"
  New-Item -ItemType Directory -Force $vsixCache | Out-Null
  $missing = @()
  foreach ($pin in $pins) {
    $id, $ver = $pin -split "@", 2
    $e = $extLock.$id
    if (-not $e -or $e.version -ne $ver) { Fail 5 "$pin has no matching entry in vscode-ext\extensions.lock.json" }
    $present = @(Get-ChildItem $extDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match ('^' + [regex]::Escape("$id-$ver") + '(-[a-z0-9]+(-[a-z0-9]+)?)?$') })   # 1.2.3 is not 1.2.30
    if ($present.Count -gt 0) { Write-Host "extension $pin present"; continue }
    $file = Join-Path $vsixCache ([IO.Path]::GetFileName(([Uri]$e.url).AbsolutePath))
    if (-not (Test-Path $file)) { Invoke-WebRequest -Uri $e.url -OutFile "$file.part" -UseBasicParsing; Move-Item -Force "$file.part" $file }
    $got = (Get-FileHash -Algorithm SHA256 $file).Hash.ToLower()
    if ($got -ne ("" + $e.sha256).ToLower()) { Remove-Item -Force $file; Fail 5 "sha256 mismatch for $pin (lock $($e.sha256), file $got); not installed" }
    Write-Host "extension $pin to install (sha256 ok)"
    $missing += $file
  }
  if ($missing.Count -gt 0) { InstallVsix $missing }
  # every pin must now be installed at exactly its pinned version (a gallery fallback would show here)
  $have = @{}
  foreach ($line in (CodeCli @("--list-extensions", "--show-versions"))) { if ($line -match '^([\w.-]+)@(\S+)$') { $have[$Matches[1].ToLower()] = $Matches[2] } }
  $wrong = @(foreach ($pin in $pins) { $id, $ver = $pin -split "@", 2; if ($have[$id.ToLower()] -ne $ver) { "$pin (installed: $($have[$id.ToLower()]))" } })
  if ($wrong.Count -gt 0) { Fail 5 "extensions not at their pins: $($wrong -join '; ')" }
  Write-Host "extensions: all $($pins.Count) pins installed at their pinned versions"
  # EDP extension hook (S5 builds v8\vscode-ext\edp-code\*.vsix); a no-op until that vsix exists
  $edp = @(Get-ChildItem (Join-Path $v8 "vscode-ext\edp-code") -Filter *.vsix -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1)
  if ($edp.Count -gt 0) { Write-Host "extension edp-code installing from $($edp[0].Name)"; InstallVsix @($edp[0].FullName) }
  else { Write-Host "extension edp-code: no vsix yet (S5); skipped" }
}

# -- launch ---------------------------------------------------------------------------------------
$flags = @(
  "`"$serverDir`"", "--bind-addr", "${BINDHOST}:$PORT", "--auth", "none",
  "--disable-telemetry", "--disable-update-check", "--disable-proxy",
  "--config", "`"$config`"", "--user-data-dir", "`"$userDir`"", "--extensions-dir", "`"$extDir`""
)
$log = Join-Path $RUN "code.log"; $err = Join-Path $RUN "code.err.log"
# Start-Process -Redirect* creates the child with handle inheritance on, so a server started from
# here would inherit THIS shell's stdout/stderr: a caller reading our output to EOF (a pipe, pytest, a
# seat's tool) would then wait for the server to exit. So the server is started by a tiny wrapper
# that is itself launched through ShellExecute (no redirection = no inherited handles; our stripped
# environment is passed); the wrapper records the server pid and exits (the edp.ps1 start pattern).
$q = { param($x) "'" + ($x -replace "'", "''") + "'" }
$pidFile = Join-Path $RUN "code.launch.pid"; $wrap = Join-Path $RUN "code.launch.ps1"
Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
$body = @(
  '$ErrorActionPreference = "Stop"',
  ('$p = Start-Process -FilePath {0} -ArgumentList @({1}) -WorkingDirectory {2} -WindowStyle Hidden -PassThru -RedirectStandardOutput {3} -RedirectStandardError {4}' -f
    (& $q $node), (($flags | ForEach-Object { & $q $_ }) -join ", "), (& $q $v8), (& $q $log), (& $q $err)),
  ('Set-Content -Path {0} -Value $p.Id -Encoding ascii' -f (& $q $pidFile))
) -join "`r`n"
WriteUtf8 $wrap $body
WithoutFleetEnv {
  $w = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru `
    -ArgumentList @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$wrap`"")
  if (-not $w.WaitForExit(30000)) { Fail 6 "the launch wrapper did not exit within 30 s ($wrap)" }
}
Remove-Item $wrap -Force -ErrorAction SilentlyContinue
if (-not (Test-Path $pidFile)) { Fail 6 "the launch wrapper recorded no server pid (see $err)" }
$serverPid = [int]("" + (Get-Content $pidFile -Raw)).Trim(); Remove-Item $pidFile -Force
$script:proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
if (-not $script:proc) { Fail 6 "code-server pid $serverPid exited at once; see $err" }
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline -and -not (Healthy)) {
  if ($script:proc.HasExited) { Fail 6 "code-server exited ($($script:proc.ExitCode)) before /healthz answered; see $err" }
  Start-Sleep -Milliseconds 500
}
if (-not (Healthy)) { Fail 6 "code-server pid $($script:proc.Id) did not answer /healthz within $TimeoutSec s; see $log / $err (stop it with scripts\stop-code.ps1)" }
$root = Proc $script:proc.Id
WriteState $root
Write-Host "code     up   pid $($script:proc.Id)  http://127.0.0.1:$PORT  (code-server $($lock.version))"
exit 0
