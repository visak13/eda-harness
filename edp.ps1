# edp.ps1 - the ONE script for v8 fleet operations (status / start / stop / restart / update).
#
#   .\edp.ps1 status                       every service: state, pid pair, rev, started_at
#   .\edp.ps1 start   <svc|all>            start via v8\start.ps1 -Only <svc> (idempotent)
#   .\edp.ps1 stop    <svc|all>            safe stop: pid pair by command line, Stop-Process by id
#   .\edp.ps1 restart <svc|all>            safe stop + start + bounded health wait, prints new pid + rev
#   .\edp.ps1 update                       git pull --ff-only, uv sync, SPA rebuild, restart in order
#   add -WhatIf to print the plan and change nothing; -Force where a step needs it (see below)
#
#   services: board (:9400)  mcp (:9402)  pool (:9301)  broker (:9300)  bridge  supervisor  all
#
# SAFE RESTART CONTRACT (memories never-taskkill-board-by-image, pool-restart-tree-kill-takes-seats,
# start-ps1-restart-noop-kill-both-pids):
#   * every service is a chain of processes with one command line (uv / shim -> venv launcher ->
#     interpreter owning the port); the chain is found from the port's LISTEN owner plus its
#     same-service ancestors, never from an image name and never from run_state alone (it can hold
#     a null/stale pid).
#   * processes are stopped with Stop-Process -Id <pid>; there is NO tree kill: every seat shell is
#     a child of the pool, so a tree kill of the pool kills the fleet.
#   * the pool (stop/restart, or 'all') lists the seats it takes offline and refuses without -Force.
#   * `update` refuses on a dirty tree unless -Force.
# Seats never run this against the shared services (shared-host rules); the human/owner does.
param(
  [Parameter(Position = 0)][string]$Command = "help",
  [Parameter(Position = 1)][string]$Service = "all",
  [switch]$Force,
  [switch]$WhatIf,
  [int]$TimeoutSec = 60,
  [string]$RepoRoot = ""
)
$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path }
$V8 = Join-Path $RepoRoot "v8"
$StartPs1 = Join-Path $V8 "start.ps1"

# -- the same one .env as start.ps1 (real environment wins) -------------------------------------
$envFile = Join-Path $V8 ".env"
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("#")) { continue }
    $kv = $t -split "=", 2
    if ($kv.Count -eq 2) {
      $k = $kv[0].Trim(); $val = ($kv[1] -split "\s+#", 2)[0].Trim()
      if (-not [Environment]::GetEnvironmentVariable($k, "Process")) { Set-Item -Path "Env:$k" -Value $val }
    }
  }
}
function EnvOr($n, $d) { $v = [Environment]::GetEnvironmentVariable($n, "Process"); if ($v) { $v } else { $d } }
$RunDir = EnvOr "EDP8_RUN_DIR" (Join-Path (EnvOr "EDP8_HOME" $V8) ".run")

# name -> port, health path, command-line needle. bridge/supervisor are port-less (run_state pid).
$SVC = [ordered]@{
  board      = @{ port = [int](EnvOr "EDP8_PORT" "9400");       health = "/v1/health"; needle = "edp8-board" }
  broker     = @{ port = [int](EnvOr "EDP_BROKER_PORT" "9300"); health = "/v1/health"; needle = "edp_broker.main" }
  pool       = @{ port = [int](EnvOr "EDP_POOL_PORT" "9301");   health = "/v1/health"; needle = "edp_pool.main" }
  mcp        = @{ port = [int](EnvOr "EDP8_MCP_PORT" "9402");   health = "/healthz";   needle = "edp8.mcp_server" }
  bridge     = @{ port = 0; health = ""; needle = "edp8.slack_bridge" }
  supervisor = @{ port = 0; health = ""; needle = "edp8.supervisor" }
}
$ChainImages = @("python.exe", "pythonw.exe", "uv.exe", "edp8-board.exe")
$START_ORDER = @("board", "broker", "pool", "mcp", "bridge", "supervisor")
$STOP_ORDER  = @("supervisor", "bridge", "mcp", "pool", "broker", "board")

function Say($s) { Write-Host $s }
function Fail($code, $msg) { [Console]::Error.WriteLine("edp: $msg"); exit $code }
function Step($desc, [scriptblock]$action) {
  if ($WhatIf) { Say "WHATIF: $desc"; return }
  Say "-> $desc"
  & $action
}

# -- process discovery ----------------------------------------------------------------------------
function Proc($procId) {
  if (-not $procId) { return $null }
  Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
}
function ListenerPid($port) {
  if (-not $port) { return $null }
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($c) { [int]$c.OwningProcess } else { $null }
}
function RunStatePid($name) {
  $f = Join-Path $RunDir "$name.json"
  if (-not (Test-Path $f)) { return $null }
  try { $r = Get-Content $f -Raw | ConvertFrom-Json; if ($r.pid) { [int]$r.pid } else { $null } } catch { $null }
}
function RunStateRev($name) {
  $f = Join-Path $RunDir "$name.json"
  if (-not (Test-Path $f)) { return "" }
  try { "" + (Get-Content $f -Raw | ConvertFrom-Json).git_rev } catch { "" }
}
# The pid pair: the anchor process plus the ancestors and children that belong to the SAME service
# (the venv launcher + its interpreter; for a uv-started board also the uv.exe and edp8-board.exe
# shims above them). An ancestor must carry the service's needle AND be created no later than its
# child: Windows reuses pids, so a stale ParentProcessId can name an unrelated process (memory
# windows-stale-ppid-tree-walk). Children are only same-command-line copies, never seat shells.
function PidPair($anchorPid, $needle) {
  $a = Proc $anchorPid
  if (-not $a) { return @() }
  $pair = @($a)
  $cur = $a
  for ($i = 0; $i -lt 4; $i++) {
    $p = Proc $cur.ParentProcessId
    if (-not $p -or -not $p.CommandLine -or -not $p.CommandLine.Contains($needle) -or $p.CreationDate -gt $cur.CreationDate) { break }
    # only launcher images join the chain: a shell (powershell/bash/cmd/claude) whose command line
    # merely mentions the service must never be stopped
    if ($ChainImages -notcontains $p.Name.ToLower()) { break }
    $pair = @($p) + $pair
    $cur = $p
  }
  $kids = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$($a.ProcessId)" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -eq $a.CommandLine -and $_.CreationDate -ge $a.CreationDate })
  $pair + $kids
}
function Discover($name) {
  $s = $SVC[$name]
  $anchor = $null
  if ($s.port) { $anchor = ListenerPid $s.port }
  if (-not $anchor) {
    $rp = RunStatePid $name
    $rproc = Proc $rp
    if ($rproc -and $rproc.CommandLine -and $rproc.CommandLine.Contains($s.needle)) { $anchor = $rp }
  }
  if (-not $anchor) { return @() }
  # authenticate the ANCHOR before walking: a foreign listener (or a process that merely names the
  # service in an argument but is not a launcher image) is never acted on, nor are its ancestors
  $a = Proc $anchor
  if (-not $a -or -not $a.CommandLine -or -not $a.CommandLine.Contains($s.needle) -or ($ChainImages -notcontains $a.Name.ToLower())) {
    [Console]::Error.WriteLine("edp: $name port $($s.port) is held by pid $anchor, which is not a '$($s.needle)' launcher process; leaving it alone")
    return @()
  }
  @(PidPair $anchor $s.needle)
}
function Health($name) {
  $s = $SVC[$name]
  if (-not $s.port) { return $null }
  try { Invoke-RestMethod "http://127.0.0.1:$($s.port)$($s.health)" -TimeoutSec 3 } catch { $null }
}
function RevOf($name, $h) {
  if ($h -and $h.git_rev) { return "" + $h.git_rev }
  if ($name -eq "mcp" -and $h -and $h.version) { return "" + $h.version }
  $r = RunStateRev $name
  if ($r) { return "$r (run_state)" }
  "-"
}
function StartedOf($h, $pair) {
  if ($h -and $h.started_at) { return "" + $h.started_at }
  if ($pair.Count -gt 0) { return ($pair[0].CreationDate).ToString("yyyy-MM-ddTHH:mm:sszzz") + " (process)" }
  "-"
}
function ChainText($name, $pair) {
  # outermost first; the listener (the pid netstat and `edp8 status` name) is marked with *
  $lp = ListenerPid $SVC[$name].port
  (($pair | ForEach-Object { if ([int]$_.ProcessId -eq $lp) { "$($_.ProcessId)*" } else { "$($_.ProcessId)" } }) -join "/")
}

# -- pool seats: the shells a pool stop takes offline ------------------------------------------------
function PoolSeats {
  try {
    # /v1/sessions is the pool's plain ledger (fast); /v1/panel/shells measures every thread and can take >30 s
    $all = Invoke-RestMethod "http://127.0.0.1:$($SVC.pool.port)/v1/sessions" -TimeoutSec 10
    @($all | Where-Object { $_.state -eq "active" } | ForEach-Object { "$($_.handle) (pid $($_.proc.pid))" })
  } catch { @("<pool unreachable: seat list unknown>") }
}
function GuardPool($verb) {
  $seats = @(PoolSeats)
  Say "pool $verb takes these $($seats.Count) seat(s) offline while it is down (their shells are pool children; no tree kill, they are re-adopted):"
  foreach ($x in $seats) { Say "  - $x" }
  if (-not $Force) { Fail 3 "refusing to $verb the pool without -Force (owner's call)" }
  $script:PoolSeatsBefore = $seats
}

# -- stop / start / restart ---------------------------------------------------------------------
$script:Stopped = @()
function FailDown($code, $msg) {
  if ($script:Stopped.Count -gt 0) { $msg += "; STILL DOWN: $($script:Stopped -join ', ') - fix the cause, then .\edp.ps1 start all" }
  Fail $code $msg
}
function Stop-Svc($name) {
  $pair = @(Discover $name)
  if ($pair.Count -eq 0) { Say ("{0,-10} not running" -f $name); return }
  $ids = @($pair | ForEach-Object { [int]$_.ProcessId })
  Step ("stop {0}: Stop-Process -Id {1} -Force (service process chain by command line, no tree kill)" -f $name, ($ids -join ",")) {
    # Kill through a HANDLE opened now and checked against the discovered process's creation time:
    # a pid that exited and was reused since discovery is skipped, never killed (pid-reuse race).
    $handles = @()
    foreach ($c in $pair) {
      $h = Get-Process -Id ([int]$c.ProcessId) -ErrorAction SilentlyContinue
      if (-not $h) { continue }
      try { $null = $h.Handle } catch { continue }   # opens + caches the handle that Kill() then uses
      if ([math]::Abs(($h.StartTime - $c.CreationDate).TotalSeconds) -gt 1) { Say "  skip pid $($c.ProcessId): reused since discovery"; continue }
      $handles += $h
    }
    foreach ($h in $handles) { try { $h.Kill() } catch { } }   # Stop-Process -Id semantics, bound to the handle
    foreach ($h in $handles) { $null = $h.WaitForExit(15000) }
    $alive = @($handles | Where-Object { -not $_.HasExited } | ForEach-Object { $_.Id })
    if ($alive.Count -gt 0) { FailDown 1 "$name still running: pid $($alive -join ',')" }
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline -and (ListenerPid $SVC[$name].port)) { Start-Sleep -Milliseconds 250 }
    if (ListenerPid $SVC[$name].port) { FailDown 1 "$name port $($SVC[$name].port) still has a listener after the stop" }
    $rs = Join-Path $RunDir "$name.json"
    if (Test-Path $rs) { Remove-Item $rs -Force }
    $script:Stopped += $name
    Say ("{0,-10} stopped (pid {1})" -f $name, ($ids -join ","))
  }
}
function Invoke-StartPs1($label, $extra) {
  # start.ps1 Start-Process'es long-lived services that inherit its handles. Whatever pipe start.ps1
  # holds, the service then holds for its whole life: piping start.ps1 (or launching it with
  # redirection = CreateProcess with inherited handles) handed the CALLER's stdout pipe to the board,
  # and a caller that reads to EOF never returned (architect's live run, m-0c1e43e1c3). So start.ps1
  # runs through a ShellExecute launch (no redirection => no handle inheritance, our environment is
  # passed), inside a tiny wrapper that redirects start.ps1's streams to a log file and writes its
  # exit code to a file; we wait for the wrapper process only, not its descendants.
  $tag = "edp-start-{0}-{1}" -f $label, [guid]::NewGuid().ToString("N").Substring(0, 8)
  $log = Join-Path $env:TEMP "$tag.log"; $rc = Join-Path $env:TEMP "$tag.rc"; $wrap = Join-Path $env:TEMP "$tag.ps1"
  # parameter names stay bare (a quoted '-Only' would bind as a positional string); values are quoted
  $argText = ($extra | ForEach-Object { if ($_ -match '^-[A-Za-z]+$') { $_ } else { "'" + ($_ -replace "'", "''") + "'" } }) -join " "
  $body = @(
    '$ErrorActionPreference = "Continue"',
    ("try {{ & '{0}' {1} *> '{2}'; `$code = `$LASTEXITCODE }} catch {{ `$_ | Out-File -Append '{2}'; `$code = 1 }}" -f ($StartPs1 -replace "'", "''"), $argText, $log),
    'if ($null -eq $code) { $code = 0 }',
    ("Set-Content -Path '{0}' -Value `$code" -f $rc)
  ) -join "`r`n"
  [IO.File]::WriteAllText($wrap, $body, (New-Object Text.UTF8Encoding $true))
  $p = Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -PassThru `
    -ArgumentList @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$wrap`"")
  if (-not $p.WaitForExit($TimeoutSec * 3000)) { FailDown 4 "start.ps1 $($extra -join ' ') did not exit within $($TimeoutSec * 3) s (log $log)" }
  if (Test-Path $log) { Get-Content $log | ForEach-Object { Say "   | $_" } }
  $code = 1; if (Test-Path $rc) { $code = [int]("" + (Get-Content $rc -Raw)).Trim() }
  Remove-Item $wrap, $rc -Force -ErrorAction SilentlyContinue
  if ($code -ne 0) { FailDown 4 "start.ps1 $($extra -join ' ') exited $code (log $log)" }
  Remove-Item $log -Force -ErrorAction SilentlyContinue
}
function Wait-Up($name) {
  # a service is up when its health route answers (port services) or its process chain exists
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ($true) {
    $h = Health $name
    $pair = @(Discover $name)
    $ok = ($pair.Count -gt 0) -and ((-not $SVC[$name].port) -or $h)
    if ($ok -or (Get-Date) -gt $deadline) { break }
    Start-Sleep -Milliseconds 500
  }
  if (-not $ok) { FailDown 4 "$name is not up after $TimeoutSec s (health $($SVC[$name].health); see v8\.data\$name.err)" }
  $script:Stopped = @($script:Stopped | Where-Object { $_ -ne $name })
  Say ("{0,-10} up   pid {1}  rev {2}  started_at {3}" -f $name, (ChainText $name $pair), (RevOf $name $h), (StartedOf $h $pair))
}
function Start-Svc($name) {
  if ($name -eq "bridge" -and -not (Test-Path (Join-Path $V8 "slack_map.json"))) { Say "bridge     skipped (no v8\slack_map.json)"; return }
  # start.ps1 has no -Only for the supervisor; its plain run is idempotent and starts only what is down.
  $extra = @(); if ($name -ne "supervisor") { $extra = @("-Only", $name) }
  Step ("start {0}: powershell -File v8\start.ps1 {1}" -f $name, ($extra -join " ")) {
    Invoke-StartPs1 $name $extra
    Wait-Up $name
  }
}
function Report-PoolLiveness {
  if ($WhatIf -or -not $script:PoolSeatsBefore) { return }
  Say "pool liveness after restart:"
  foreach ($x in $script:PoolSeatsBefore) {
    $handle = ($x -split " ", 2)[0]
    if ($handle.StartsWith("<")) { continue }
    try { $l = Invoke-RestMethod "http://127.0.0.1:$($SVC.pool.port)/v1/liveness/$handle" -TimeoutSec 5; Say "  - $handle $($l.state)" }
    catch { Say "  - $handle <liveness unreachable>" }
  }
}
function Targets($svc, $order) {
  if ($svc -eq "all") { return $order }
  if (-not $SVC.Contains($svc)) { Fail 5 "unknown service '$svc' (board|mcp|pool|broker|bridge|supervisor|all)" }
  @($svc)
}
function WithSupervisorPaused($t) {
  # the supervisor restarts whatever it sees down (via start.ps1 -Restart); pause it around any
  # restart of another service so the two never race, and bring it back last
  if (($t -notcontains "supervisor") -and (@(Discover "supervisor").Count -gt 0)) { return @("supervisor") + $t }
  $t
}
function Restart-Set($t) {
  foreach ($n in $STOP_ORDER) { if ($t -contains $n) { Stop-Svc $n } }
  foreach ($n in $START_ORDER) { if ($t -contains $n) { Start-Svc $n } }
  Report-PoolLiveness
}

# -- status -----------------------------------------------------------------------------------
function Show-Status {
  $rows = foreach ($name in $START_ORDER) {
    $pair = @(Discover $name)
    $h = Health $name
    $state = "down"
    if ($pair.Count -gt 0) { $state = "up" }
    if ($pair.Count -gt 0 -and $SVC[$name].port -and -not $h) { $state = "unhealthy" }
    [pscustomobject]@{
      service    = $name
      state      = $state
      port       = $(if ($SVC[$name].port) { $SVC[$name].port } else { "-" })
      pid        = $(if ($pair.Count) { ChainText $name $pair } else { "-" })
      rev        = RevOf $name $h
      started_at = $(if ($pair.Count) { StartedOf $h $pair } else { "-" })
    }
  }
  $rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
  Say "pid = the service's process chain, outermost first, * = the port's listener; started_at from /healthz when the service reports it, else the process start."
  Say "HEAD $((& git --no-optional-locks -C $RepoRoot rev-parse --short HEAD 2>$null))"
}
function DownCore {
  @(@("board", "broker", "pool", "mcp") | Where-Object { -not (Health $_) }) + @(@("supervisor") | Where-Object { @(Discover $_).Count -eq 0 })
}

# -- update ------------------------------------------------------------------------------------
function Do-Update {
  # dirty = modified tracked files AND untracked non-ignored files (they could leak into a build);
  # --no-optional-locks: even this read must not refresh the index under -WhatIf
  $dirty = @(& git --no-optional-locks -C $RepoRoot status --porcelain)
  if ($dirty.Count -gt 0 -and -not $Force) {
    Say "working tree is dirty: $($dirty.Count) modified or untracked path(s), e.g.:"
    $dirty | Select-Object -First 10 | ForEach-Object { Say "  $_" }
    Fail 2 "refusing to update a dirty tree without -Force (commit or ask the seats that own these files)"
  }
  $old = (& git --no-optional-locks -C $RepoRoot rev-parse HEAD).Trim()
  if ($WhatIf) {
    # no fetch under -WhatIf: plan from the last-fetched upstream ref
    $new = (& git --no-optional-locks -C $RepoRoot rev-parse "@{u}" 2>$null)
    if (-not $new) { Fail 6 "no upstream branch configured for $(& git -C $RepoRoot rev-parse --abbrev-ref HEAD)" }
    $new = $new.Trim()
    # model --ff-only exactly: upstream behind/equal = no-op; both sides ahead = diverged = refused
    $lr = ("" + (& git --no-optional-locks -C $RepoRoot rev-list --left-right --count "HEAD...@{u}")).Trim() -split "\s+"
    $ahead = [int]$lr[0]; $behind = [int]$lr[1]
    if ($behind -gt 0 -and $ahead -gt 0) { Fail 6 "HEAD and upstream have diverged ($ahead ahead, $behind behind): git pull --ff-only would refuse" }
    if ($behind -eq 0) { $new = $old }
    Say "WHATIF: git pull --ff-only  (plan from last-fetched upstream $($new.Substring(0,7)): $behind commit(s) to pull; HEAD $($old.Substring(0,7)), $ahead local commit(s) ahead)"
  } else {
    Say "-> git pull --ff-only"
    & git -C $RepoRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) { Fail 6 "git pull --ff-only failed (diverged? resolve by hand); nothing restarted" }
    $new = (& git -C $RepoRoot rev-parse HEAD).Trim()
  }
  if ($old -eq $new) {
    # a re-run after a failed update lands here with services still down: say so, never "all fine"
    $down = @(DownCore)
    if ($down.Count -gt 0) { Fail 9 "already at $($old.Substring(0,7)) but DOWN: $($down -join ', ') (an earlier update failed?) - .\edp.ps1 start all" }
    Say "already up to date at $($old.Substring(0,7)); nothing to restart"; return
  }
  $changed = @(& git --no-optional-locks -C $RepoRoot diff --name-only $old $new)
  Say "$($changed.Count) file(s) change between $($old.Substring(0,7)) and $($new.Substring(0,7))"
  $v8Py   = @($changed | Where-Object { $_ -match '^v8/(src/|pyproject\.toml|uv\.lock|hatch_build\.py)' }).Count -gt 0
  $v8Deps = @($changed | Where-Object { $_ -match '^v8/(pyproject\.toml|uv\.lock|hatch_build\.py)' }).Count -gt 0
  $web    = @($changed | Where-Object { $_ -match '^v8/web/' }).Count -gt 0
  $webDep = @($changed | Where-Object { $_ -match '^v8/web/package(-lock)?\.json$' }).Count -gt 0
  $poolCh = @($changed | Where-Object { $_ -match '^edp-pool/' }).Count -gt 0
  $brkCh  = @($changed | Where-Object { $_ -match '^edp-broker/' }).Count -gt 0

  $restart = @()
  if ($v8Py -or $web) { $restart += "board" }
  if ($brkCh) { $restart += "broker" }
  if ($poolCh) {
    if ($Force) { $restart += "pool" } else { Say "NOTE: edp-pool changed; the pool is NOT restarted without -Force (it takes the seats offline): run .\edp.ps1 restart pool -Force" }
  }
  if ($v8Py) { $restart += @("mcp", "bridge") }
  if ($restart.Count -eq 0) { Say "no service code changed; nothing to restart"; return }
  if ($restart -contains "pool") { GuardPool "restart" }
  if ($restart -contains "mcp") { Say "NOTE: mcp restarts: every running seat keeps the old MCP code until it respawns (shared-host rules)." }
  $restart = @($START_ORDER | Where-Object { $restart -contains $_ })
  $stopList = @($STOP_ORDER | Where-Object { $restart -contains $_ })
  Say ("restart plan: supervisor(stop) -> stop {0} -> sync/build -> start {1} -> supervisor(start)" -f ($stopList -join ","), ($restart -join ","))

  # every consumer of an environment is stopped BEFORE that environment changes (Windows locks
  # loaded files: uv sync cannot replace a running edp8-board.exe or a loaded .pyd)
  Stop-Svc "supervisor"
  foreach ($n in $stopList) { Stop-Svc $n }
  if ($v8Deps -or $v8Py) { Step "uv sync --directory v8" { & uv sync --directory $V8; if ($LASTEXITCODE -ne 0) { FailDown 7 "uv sync (v8) failed" } } }
  if ($restart -contains "pool") { Step "uv sync --directory edp-pool" { & uv sync --directory (Join-Path $RepoRoot "edp-pool"); if ($LASTEXITCODE -ne 0) { FailDown 7 "uv sync (edp-pool) failed" } } }
  if ($brkCh) { Step "uv sync --directory edp-broker" { & uv sync --directory (Join-Path $RepoRoot "edp-broker"); if ($LASTEXITCODE -ne 0) { FailDown 7 "uv sync (edp-broker) failed" } } }
  if ($web) {
    if ($webDep) { Step "npm --prefix v8\web ci" { & npm --prefix (Join-Path $V8 "web") ci; if ($LASTEXITCODE -ne 0) { FailDown 8 "npm ci failed" } } }
    Step "npm --prefix v8\web run build (SPA)" { & npm --prefix (Join-Path $V8 "web") run build; if ($LASTEXITCODE -ne 0) { FailDown 8 "SPA build failed" } }
  }
  foreach ($n in $restart) { Start-Svc $n }
  Report-PoolLiveness
  Start-Svc "supervisor"
}

# -- dispatch --------------------------------------------------------------------------------------
switch ($Command.ToLower()) {
  "status" { Show-Status }
  "start" {
    if ($Service -eq "all") {
      Step "start all: powershell -File v8\start.ps1 (idempotent; supervisor included)" {
        Invoke-StartPs1 "all" @()
        foreach ($n in $START_ORDER) {
          if ($n -eq "bridge" -and -not (Test-Path (Join-Path $V8 "slack_map.json"))) { continue }
          Wait-Up $n
        }
      }
    }
    else { foreach ($n in (Targets $Service $START_ORDER)) { Start-Svc $n } }
  }
  "stop" {
    $t = @(Targets $Service $STOP_ORDER)
    if ($t -contains "pool") { GuardPool "stop" }
    if ($Service -ne "all" -and $Service -ne "supervisor" -and @(Discover "supervisor").Count -gt 0) {
      Say "NOTE: the supervisor is running and restarts a service after ~45 s of failed probes; stop it too (.\edp.ps1 stop supervisor) to keep $Service down."
    }
    foreach ($n in $t) { Stop-Svc $n }
  }
  "restart" {
    $t = @(Targets $Service $STOP_ORDER)
    if ($t -contains "pool") { GuardPool "restart" }
    if ($t -contains "mcp") { Say "NOTE: mcp restart: every running seat keeps the old MCP code until it respawns (shared-host rules)." }
    Restart-Set (WithSupervisorPaused $t)
  }
  "update" { Do-Update }
  default {
    $lines = @(Get-Content $PSCommandPath); $end = [Array]::IndexOf($lines, "param(")
    $lines[1..($end - 1)] | ForEach-Object { $_ -replace '^# ?', '' } | Write-Host
    if ($Command -ne "help") { exit 5 }
  }
}
exit 0
