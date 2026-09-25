# Start the `code` service: code-server behind the host guard on 127.0.0.1:<EDP_CODE_PORT> (default 9410)
# (s-3c8c2512d6; design-449b628cdd section 4; strategyhl-e69dbbae06 + strategyhl-f300df15cb; S1 report-b90f1f63df).
#
#   scripts\start-code.ps1                     install if needed, seed settings, install missing pinned
#                                              extensions, launch, wait for /healthz, write .run\code.json
#   scripts\start-code.ps1 -SkipExtensions     leave the extensions dir as it is (tests)
#
# DNS-rebinding guard (s-03c7e9168b, design-628b968271, steer m-b7adc0f74f): edp8.code_guard (the
# edp8 venv python) holds 127.0.0.1:<port>. It refuses a Host other than 127.0.0.1/localhost:<port>
# (421) and a WebSocket Origin outside its allowlist (403), and relays the rest to code-server on a
# random free inner 127.0.0.1 port, adding the session cookie of a per-start secret. code-server runs
# --auth password with that secret as $HASHED_PASSWORD, so a page that reaches the inner port directly
# meets the login wall, and the owner never sees a login. The secret travels only by environment.
# .run\code.json records both pids and the inner port; stop-code.ps1 stops both by recorded pid.
#
# Idempotent: our own service already on the port is left running. A foreign listener on the
# port fails loudly and is never killed. Every bind is loopback only (anyone who reaches code-server
# owns the host through the terminal), so any other EDP_CODE_HOST is refused. Every EDP_* / EDP8_* variable is removed from the server's environment
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
$BOARDPORT = EnvOr "EDP8_PORT" "9400"
$BOARD = "http://127.0.0.1:$BOARDPORT"
# the guard's WebSocket Origin allowlist beyond its own two origins: the board, and the public board
# origin in public mode (s-03c7e9168b; code-server itself still refuses an Origin that is not its Host)
$ORIGINS = @($BOARD, "http://localhost:$BOARDPORT")
$PUBLIC = EnvOr "EDP8_PUBLIC_URL" ""
if ($PUBLIC) { try { $u = [Uri]$PUBLIC; $ORIGINS += $u.GetLeftPart([UriPartial]::Authority) } catch { } }
if (@("127.0.0.1", "localhost") -notcontains $BINDHOST.ToLower()) {
  Fail 2 "refusing EDP_CODE_HOST=${BINDHOST}: code-server (behind its guard) binds 127.0.0.1 only"
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
# DNS-rebinding guard (s-03c7e9168b, design-628b968271 + steer m-b7adc0f74f): the host-allowlist
# guard (edp8.code_guard, the edp8 venv's python) owns 127.0.0.1:$PORT; code-server sits on a random
# free inner 127.0.0.1 port with --auth password and a per-start secret only the guard holds, so a
# rebinding page that finds the inner port meets the login wall. (A named pipe kills every extension
# host on Windows: code-server hands sockets to it over IPC, ENOTSUP, m-9ef1667f16.)
$PY = Join-Path $v8 ".venv\Scripts\python.exe"
function FreePort {
  $l = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback, 0); $l.Start()
  try { $l.LocalEndpoint.Port } finally { $l.Stop() }
}
$INNER = FreePort
while ($INNER -eq $PORT) { $INNER = FreePort }
# the secret is code-server's $HASHED_PASSWORD value (a non-argon2 value is compared to the session
# cookie verbatim); it travels only by environment and is never written to disk or a command line
$rng = [Security.Cryptography.RandomNumberGenerator]::Create(); $sb = New-Object byte[] 32; $rng.GetBytes($sb)
$SECRET = -join ($sb | ForEach-Object { $_.ToString("x2") })
New-Item -ItemType Directory -Force $RUN, $DATA, $userDir, $extDir, (Join-Path $userDir "User") | Out-Null

function Proc($procId) { Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue }
function IsOurs($p) { $p -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($toolsNorm, [StringComparison]::OrdinalIgnoreCase) }
function ListenerPid { $c = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { [int]$c.OwningProcess } else { $null } }
function Healthy { try { (Invoke-WebRequest "http://127.0.0.1:$PORT/healthz" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch { $false } }
function GitRev { try { ("" + (& git -C $v8 rev-parse --short HEAD 2>$null)).Trim() } catch { "" } }
# this port's guard: edp8.code_guard for --port $PORT, tagged with this install (the venv launcher or
# the interpreter it runs; both carry the same arguments)
function IsGuard($p) {
  $p -and $p.CommandLine -and $p.CommandLine -match 'edp8\.code_guard' -and $p.CommandLine -match ('--port\s+' + $PORT + '(\s|$)') -and
    $p.CommandLine.IndexOf($toolsNorm, [StringComparison]::OrdinalIgnoreCase) -ge 0
}
# a code-server of THIS service: a server (--bind-addr) whose parsed --user-data-dir is exactly ours
function DataDirOf($p) {
  if (-not $p -or -not $p.CommandLine -or $p.CommandLine -notmatch '--user-data-dir[\s=]+(?:"([^"]+)"|(\S+))') { return $null }
  $d = if ($Matches[1]) { $Matches[1] } else { $Matches[2] }
  try { [IO.Path]::GetFullPath($d).TrimEnd("\") } catch { $null }
}
function IsOurServer($p) { (IsOurs $p) -and $p.CommandLine -match '--bind-addr\s' -and ((DataDirOf $p) -eq ([IO.Path]::GetFullPath($userDir)).TrimEnd("\")) }
function SameStart($p, $recorded) { $p -and $recorded -and ([math]::Abs(($p.CreationDate - [datetime]$recorded).TotalSeconds) -le 1) }
# the workbench answers through the guard without a login: proves the guard's session cookie is the
# one code-server expects (/healthz alone answers without auth)
function Workbench {
  try {
    $r = [Net.HttpWebRequest]::Create("http://127.0.0.1:$PORT/"); $r.AllowAutoRedirect = $false; $r.Timeout = 5000
    $resp = $r.GetResponse()
    try { $code = [int]$resp.StatusCode; $loc = "" + $resp.Headers["Location"] } finally { $resp.Close() }
    ($code -eq 200) -or ($code -eq 302 -and $loc -notmatch 'login')
  } catch { $false }
}
function WriteState($p, $g, $inner) {
  $state = [ordered]@{
    service = "code"; pid = [int]$p.ProcessId; port = $PORT; version = $lock.version; sha256 = $lock.sha256
    git_rev = (GitRev); started_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    creation_date = $p.CreationDate.ToString("o"); install_dir = $installDir
    inner_port = $inner; guard_pid = $(if ($g) { [int]$g.ProcessId } else { $null })
    guard_creation_date = $(if ($g) { $g.CreationDate.ToString("o") } else { $null })
    last_probe = $null; last_ok = $null; last_restart_reason = $null; restarts = 0
  }
  WriteUtf8 $stateFile ($state | ConvertTo-Json)
}

# -- one start at a time: a second start (a retry after an edp timeout) must not race the first's
# download/extract/extension install, or its listener check. The lock is an exclusively opened file,
# released on exit.
$startLock = $null
try { $startLock = [IO.File]::Open((Join-Path $RUN "code.start.lock"), "OpenOrCreate", "ReadWrite", "None") }
catch { Fail 7 "another start-code.ps1 is running (it holds $RUN\code.start.lock); wait for it" }

# -- already running? -----------------------------------------------------------------------------
$lp = ListenerPid
if ($lp) {
  $p = Proc $lp
  if (IsGuard $p) {
    $rec = $null; try { $rec = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { }
    $srv = $null; $grd = $null
    if ($rec -and $rec.pid -and [int]$rec.port -eq $PORT) { $srv = Proc ([int]$rec.pid); $grd = Proc ([int]$rec.guard_pid) }
    # the recorded pair, authenticated by start time, and the listener is that guard (or its child)
    $pairOk = (IsOurServer $srv) -and (SameStart $srv $rec.creation_date) -and (IsGuard $grd) -and (SameStart $grd $rec.guard_creation_date) -and
      (([int]$grd.ProcessId -eq $lp) -or ([int]$p.ParentProcessId -eq [int]$grd.ProcessId))
    if (-not ($pairOk -and (Healthy) -and (Workbench))) { Fail 3 "port $PORT is held by this service's guard (pid $lp) but the recorded code-server behind it is missing, unverified or not serving the workbench: restart it (.\edp.ps1 restart code)" }
    $pinned = ([IO.Path]::GetFullPath($installDir)).TrimEnd("\") + "\"
    if (-not $srv.ExecutablePath.StartsWith($pinned, [StringComparison]::OrdinalIgnoreCase)) {
      Write-Host "code     running on 127.0.0.1:$PORT from $($srv.ExecutablePath), NOT the pinned $($lock.version): restart it (.\edp.ps1 restart code)"
    } else { Write-Host "code     already running on 127.0.0.1:$PORT (guard pid $lp, code-server pid $($srv.ProcessId) on inner port $($rec.inner_port))" }
    exit 0
  }
  if (-not (IsOurs $p)) { Fail 3 "port $PORT is held by pid $lp ($($p.Name) $($p.ExecutablePath)), not this code-server; leaving it alone" }
  # code-server bound to the port itself: a start from before the guard (s-03c7e9168b); not a success
  Fail 3 "code-server is on 127.0.0.1:$PORT WITHOUT the host guard (pid $lp, a pre-guard start): restart it (.\edp.ps1 restart code)"
}

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
# the inner bind: the guard holds $PORT; the password comes by $HASHED_PASSWORD at launch, never from here
WriteUtf8 $config ("# written by scripts\start-code.ps1 on every start; edits are overwritten`nbind-addr: ${BINDHOST}:$INNER`nauth: password`ncert: false`n")

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
# v8 is a subfolder of the eda-base3 repo: the default ("prompt") left it with no repository, so
# source control was empty and tags carried commit null (@no-git)
$settings["git.openRepositoryInParentFolders"] = "always"
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
if (-not (Test-Path $PY)) { Fail 4 "the host guard needs the edp8 venv python ($PY); run uv sync in v8" }
$flags = @(
  # --log info outranks an inherited LOG_LEVEL: at trace VS Code logs its arguments, the password among them
  "`"$serverDir`"", "--bind-addr", "${BINDHOST}:$INNER", "--auth", "password", "--log", "info",
  "--disable-telemetry", "--disable-update-check", "--disable-proxy",
  "--config", "`"$config`"", "--user-data-dir", "`"$userDir`"", "--extensions-dir", "`"$extDir`""
)
$guardFlags = @("-m", "edp8.code_guard", "--port", "$PORT", "--upstream", "tcp:${BINDHOST}:$INNER")
foreach ($o in $ORIGINS) { $guardFlags += @("--allow-origin", $o) }
$guardFlags += @("--tag", "`"$installDir`"")
$log = Join-Path $RUN "code.log"; $err = Join-Path $RUN "code.err.log"
$glog = Join-Path $RUN "code.guard.log"; $gerr = Join-Path $RUN "code.guard.err.log"
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
  # the per-start secret: to code-server as $HASHED_PASSWORD (it deletes the variable after reading, so
  # terminals never inherit it), then to the guard as CODE_GUARD_SESSION; never on a command line
  '$s = $env:CODE_GUARD_HANDOFF; Remove-Item Env:CODE_GUARD_HANDOFF',
  # inherited settings that would change how code-server reads or logs the password: a cookie suffix
  # renames the cookie the guard injects, trace logging (LOG_LEVEL, VSCODE_OPTIONS) writes it out
  'foreach ($k in "LOG_LEVEL", "PASSWORD", "CODE_SERVER_COOKIE_SUFFIX", "VSCODE_OPTIONS", "CODE_SERVER_CONFIG") { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }',
  '$env:HASHED_PASSWORD = $s',
  # Keep the original app port in a URL-parseable path. The board sends the browser a loopback-only
  # redirect; it never proxies app traffic. {{port}} in a URL port is invalid before substitution.
  ('$env:VSCODE_PROXY_URI = {0}' -f (& $q "$BOARD/v1/code/external/{{port}}/")),
  ('$p =Start-Process -FilePath {0} -ArgumentList @({1}) -WorkingDirectory {2} -WindowStyle Hidden -PassThru -RedirectStandardOutput {3} -RedirectStandardError {4}' -f
    (& $q $node), (($flags | ForEach-Object { & $q $_ }) -join ", "), (& $q $v8), (& $q $log), (& $q $err)),
  # the server pid is recorded at once, so a failing guard launch never leaves an unrecorded server
  ('Set-Content -Path {0} -Value $p.Id -Encoding ascii' -f (& $q $pidFile)),
  'Remove-Item Env:HASHED_PASSWORD; $env:CODE_GUARD_SESSION = $s',
  ('try {{ $g =Start-Process -FilePath {0} -ArgumentList @({1}) -WorkingDirectory {2} -WindowStyle Hidden -PassThru -RedirectStandardOutput {3} -RedirectStandardError {4} }} catch {{ Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue; throw }}' -f
    (& $q $PY), (($guardFlags | ForEach-Object { & $q $_ }) -join ", "), (& $q $v8), (& $q $glog), (& $q $gerr)),
  ('Add-Content -Path {0} -Value $g.Id -Encoding ascii' -f (& $q $pidFile))
) -join "`r`n"
WriteUtf8 $wrap $body
WithoutFleetEnv {
  $env:CODE_GUARD_HANDOFF = $SECRET
  try {
    $w = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru `
      -ArgumentList @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$wrap`"")
  } finally { Remove-Item Env:CODE_GUARD_HANDOFF -ErrorAction SilentlyContinue }
  if (-not $w.WaitForExit(30000)) { Fail 6 "the launch wrapper did not exit within 30 s ($wrap)" }
}
Remove-Item $wrap -Force -ErrorAction SilentlyContinue
# a failed start rolls back what it launched: stop-code.ps1 finds the server by this service's
# user-data dir and the guard by its record or listener, and kills only those trees
function FailRollback($code, $msg) {
  & (Join-Path $PSScriptRoot "stop-code.ps1") *>&1 | ForEach-Object { Write-Host "   rollback | $_" }
  Fail $code "$msg (rolled back)"
}
if (-not (Test-Path $pidFile)) { FailRollback 6 "the launch wrapper recorded no server pid (see $err)" }
$pids = @(Get-Content $pidFile | ForEach-Object { ("" + $_).Trim() } | Where-Object { $_ }); Remove-Item $pidFile -Force
$serverPid = [int]$pids[0]
$root = Proc $serverPid
$guardPid = if ($pids.Count -ge 2) { [int]$pids[1] } else { 0 }
$groot = if ($guardPid) { Proc $guardPid } else { $null }
# the records are taken now, while they are alive: stop-code.ps1 finds either by them after a failure
if ($root) { WriteState $root $groot $INNER }
if ($pids.Count -lt 2) { FailRollback 6 "the launch wrapper recorded no guard pid (see $err / $gerr)" }
$script:proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
$script:gproc = Get-Process -Id $guardPid -ErrorAction SilentlyContinue
if (-not $script:proc) { FailRollback 6 "code-server pid $serverPid exited at once; see $err" }
if (-not $script:gproc) { FailRollback 6 "the guard pid $guardPid exited at once; see $gerr" }
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline -and -not (Healthy)) {
  if ($script:proc.HasExited) { FailRollback 6 "code-server exited ($($script:proc.ExitCode)) before /healthz answered; see $err" }
  if ($script:gproc.HasExited) { FailRollback 6 "the guard exited ($($script:gproc.ExitCode)) before /healthz answered; see $gerr" }
  Start-Sleep -Milliseconds 500
}
if (-not (Healthy)) { FailRollback 6 "code-server pid $serverPid behind guard pid $guardPid did not answer /healthz within $TimeoutSec s; see $log / $err / $gerr" }
# the inner port was free when chosen, but anything could have taken it before code-server bound it:
# the guard hands its secret to whatever listens there, so that must be this service's code-server
$ic = Get-NetTCPConnection -LocalPort $INNER -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$ip = if ($ic) { Proc ([int]$ic.OwningProcess) } else { $null }
# (the listener is code-server's forked child: node ...\out\node\entry, parent = the server we started)
if (-not ((IsOurs $ip) -and [int]$ip.ParentProcessId -eq $serverPid -and $ip.CreationDate -ge $root.CreationDate)) { FailRollback 6 "the inner port $INNER is held by pid $($ic.OwningProcess) ($($ip.Name)), not this code-server" }
if (-not (Workbench)) { FailRollback 6 "the workbench did not answer through the guard without a login (the session cookie was not accepted); see $log / $gerr" }
Write-Host "code     up   guard pid $guardPid http://127.0.0.1:$PORT -> code-server pid $serverPid on 127.0.0.1:$INNER (auth password, guard-held)  (code-server $($lock.version))"
exit 0
