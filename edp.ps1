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
  $pair = @(PidPair $anchor $s.needle)
  # never act on a listener that is not the expected service (e.g. a foreign process on the port)
  $ok = @($pair | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($s.needle) })
  if ($ok.Count -eq 0) {
    [Console]::Error.WriteLine("edp: $name port $($s.port) is held by pid $anchor, whose command line lacks '$($s.needle)'; leaving it alone")
    return @()
  }
  $ok
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
function Stop-Svc($name) {
  $pair = @(Discover $name)
  if ($pair.Count -eq 0) { Say ("{0,-10} not running" -f $name); return }
  $ids = @($pair | ForEach-Object { [int]$_.ProcessId })
  Step ("stop {0}: Stop-Process -Id {1} -Force (service process chain by command line, no tree kill)" -f $name, ($ids -join ",")) {
    foreach ($i in $ids) { Stop-Process -Id $i -Force -ErrorAction SilentlyContinue }
    $deadline = (Get-Date).AddSeconds(15)
    while ((Get-Date) -lt $deadline) {
      $alive = @($ids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
      $port = $SVC[$name].port
      if ($alive.Count -eq 0 -and -not (ListenerPid $port)) { break }
      Start-Sleep -Milliseconds 250
    }
    $alive = @($ids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
    if ($alive.Count -gt 0) { Fail 1 "$name still running: pid $($alive -join ',')" }
    $rs = Join-Path $RunDir "$name.json"
    if (Test-Path $rs) { Remove-Item $rs -Force }
    Say ("{0,-10} stopped (pid {1})" -f $name, ($ids -join ","))
  }
}
function Start-Svc($name) {
  # start.ps1 has no -Only for the supervisor; its plain run is idempotent and starts only what is down.
  $argsList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $StartPs1)
  if ($name -ne "supervisor") { $argsList += @("-Only", $name) }
  Step ("start {0}: powershell -File v8\start.ps1 {1}" -f $name, ($(if ($name -ne "supervisor") { "-Only $name" } else { "" }))) {
    & powershell.exe @argsList | Out-Host
    if ($SVC[$name].port) {
      $deadline = (Get-Date).AddSeconds($TimeoutSec)
      while ((Get-Date) -lt $deadline -and -not (Health $name)) { Start-Sleep -Milliseconds 500 }
      $h = Health $name
      if (-not $h) { Fail 4 "$name did not answer $($SVC[$name].health) within $TimeoutSec s (see v8\.data\$name.err)" }
    } else { $h = $null }
    $pair = @(Discover $name)
    Say ("{0,-10} up   pid {1}  rev {2}  started_at {3}" -f $name, (($pair | ForEach-Object { $_.ProcessId }) -join "/"), (RevOf $name $h), (StartedOf $h $pair))
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
      pid        = $(if ($pair.Count) { ($pair | ForEach-Object { $_.ProcessId }) -join "/" } else { "-" })
      rev        = RevOf $name $h
      started_at = $(if ($pair.Count) { StartedOf $h $pair } else { "-" })
    }
  }
  $rows | Format-Table -AutoSize | Out-String -Width 200 | Write-Host
  Say "pid = the service's process chain, outermost first; started_at from /healthz when the service reports it, else the process start."
  Say "HEAD $((& git -C $RepoRoot rev-parse --short HEAD 2>$null))"
}

# -- update ------------------------------------------------------------------------------------
function Do-Update {
  $dirty = @(& git -C $RepoRoot status --porcelain --untracked-files=no)
  if ($dirty.Count -gt 0 -and -not $Force) {
    Say "working tree has $($dirty.Count) modified tracked file(s), e.g.:"
    $dirty | Select-Object -First 10 | ForEach-Object { Say "  $_" }
    Fail 2 "refusing to update a dirty tree without -Force (commit or ask the seats that own these files)"
  }
  $old = (& git -C $RepoRoot rev-parse HEAD).Trim()
  if ($WhatIf) {
    # no fetch under -WhatIf: plan from the last-fetched upstream ref
    $new = (& git -C $RepoRoot rev-parse "@{u}" 2>$null)
    if (-not $new) { Fail 6 "no upstream branch configured for $(& git -C $RepoRoot rev-parse --abbrev-ref HEAD)" }
    $new = $new.Trim()
    Say "WHATIF: git pull --ff-only  (plan from last-fetched upstream $($new.Substring(0,7)); HEAD $($old.Substring(0,7)))"
  } else {
    Say "-> git pull --ff-only"
    & git -C $RepoRoot pull --ff-only
    if ($LASTEXITCODE -ne 0) { Fail 6 "git pull --ff-only failed (diverged? resolve by hand); nothing restarted" }
    $new = (& git -C $RepoRoot rev-parse HEAD).Trim()
  }
  if ($old -eq $new) { Say "already up to date at $($old.Substring(0,7)); nothing to restart"; return }
  $changed = @(& git -C $RepoRoot diff --name-only $old $new)
  Say "$($changed.Count) file(s) change between $($old.Substring(0,7)) and $($new.Substring(0,7))"
  $v8Py   = @($changed | Where-Object { $_ -match '^v8/(src/|pyproject\.toml|uv\.lock|hatch_build\.py)' }).Count -gt 0
  $v8Deps = @($changed | Where-Object { $_ -match '^v8/(pyproject\.toml|uv\.lock|hatch_build\.py)' }).Count -gt 0
  $web    = @($changed | Where-Object { $_ -match '^v8/web/' }).Count -gt 0
  $webDep = @($changed | Where-Object { $_ -match '^v8/web/package(-lock)?\.json$' }).Count -gt 0
  $poolCh = @($changed | Where-Object { $_ -match '^edp-pool/' }).Count -gt 0
  $brkCh  = @($changed | Where-Object { $_ -match '^edp-broker/' }).Count -gt 0

  # restart order: supervisor off first (it would restart what we stop), board (the SPA + deps
  # need it down: uv sync cannot replace a running edp8-board.exe), broker, pool, mcp, bridge,
  # supervisor back last.
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
  Say ("restart plan: supervisor(stop) -> {0} -> supervisor(start)" -f ($restart -join " -> "))

  Stop-Svc "supervisor"
  if ($restart -contains "board") { Stop-Svc "board" }
  if ($v8Deps -or $v8Py) { Step "uv sync --directory v8" { & uv sync --directory $V8; if ($LASTEXITCODE -ne 0) { Fail 7 "uv sync failed" } } }
  if ($poolCh -and ($restart -contains "pool")) { Step "uv sync --directory edp-pool" { & uv sync --directory (Join-Path $RepoRoot "edp-pool") } }
  if ($brkCh) { Step "uv sync --directory edp-broker" { & uv sync --directory (Join-Path $RepoRoot "edp-broker") } }
  if ($web) {
    if ($webDep) { Step "npm --prefix v8\web ci" { & npm --prefix (Join-Path $V8 "web") ci; if ($LASTEXITCODE -ne 0) { Fail 8 "npm ci failed" } } }
    Step "npm --prefix v8\web run build (SPA)" { & npm --prefix (Join-Path $V8 "web") run build; if ($LASTEXITCODE -ne 0) { Fail 8 "SPA build failed" } }
  }
  foreach ($name in $restart) {
    if ($name -ne "board") { Stop-Svc $name }
    Start-Svc $name
  }
  Report-PoolLiveness
  Start-Svc "supervisor"
}

# -- dispatch --------------------------------------------------------------------------------------
switch ($Command.ToLower()) {
  "status" { Show-Status }
  "start" {
    if ($Service -eq "all") { Step "start all: powershell -File v8\start.ps1 (idempotent; supervisor included)" { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartPs1 | Out-Host } }
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
    foreach ($n in $t) { Stop-Svc $n }
    $up = @($START_ORDER | Where-Object { $t -contains $_ })
    foreach ($n in $up) { Start-Svc $n }
    Report-PoolLiveness
  }
  "update" { Do-Update }
  default {
    $lines = @(Get-Content $PSCommandPath); $end = [Array]::IndexOf($lines, "param(")
    $lines[1..($end - 1)] | ForEach-Object { $_ -replace '^# ?', '' } | Write-Host
    if ($Command -ne "help") { exit 5 }
  }
}
exit 0
