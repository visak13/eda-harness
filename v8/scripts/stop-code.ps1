# Stop the `code` service (s-3c8c2512d6; strategyhl-e69dbbae06 "Stop").
#
#   scripts\stop-code.ps1
#
# Kills the pid recorded in .run\code.json (or, with no record, our own listener on EDP_CODE_PORT)
# plus its descendant tree, never by image name. Windows has no SIGTERM, so a pid-only kill would
# orphan the extension host, pty host, watcher and terminal shells. The tree walk is guarded against
# pid reuse (memory windows-stale-ppid-tree-walk): the root must run from .tools\code-server\ with the
# recorded creation time, and a child joins only when created at or after its parent. A last sweep
# stops processes whose EXECUTABLE lives under .tools\code-server\ (node.exe, OpenConsole.exe, rg.exe),
# which never matches another seat's node or the board. Then it verifies the port is closed and no
# process references the install dir, and removes .run\code.json. Other services are never touched.
param([int]$TimeoutSec = 20)
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot

function Fail($code, $msg) { [Console]::Error.WriteLine("stop-code: $msg"); exit $code }
function EnvOr($n, $d) { $v = [Environment]::GetEnvironmentVariable($n, "Process"); if ($v) { $v } else { $d } }

$HOMEDIR = EnvOr "EDP8_HOME" $v8
$RUN = EnvOr "EDP8_RUN_DIR" (Join-Path $HOMEDIR ".run")
$PORT = [int](EnvOr "EDP_CODE_PORT" "9410")
$stateFile = Join-Path $RUN "code.json"
$toolsNorm = ([IO.Path]::GetFullPath((Join-Path $v8 ".tools\code-server"))).TrimEnd("\") + "\"

function IsOurs($p) { $p -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($toolsNorm, [StringComparison]::OrdinalIgnoreCase) }
function ListenerPid { $c = Get-NetTCPConnection -LocalPort $PORT -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { [int]$c.OwningProcess } else { $null } }
# a process "references the install" when it runs from it, or is a node/console helper naming it; a
# shell whose command line merely mentions the path (this check, a seat's grep) is not a leftover
$Helpers = @("node.exe", "openconsole.exe", "conhost.exe", "rg.exe")
function References($all) {
  @($all | Where-Object { (IsOurs $_) -or ($_.CommandLine -and ($Helpers -contains $_.Name.ToLower()) -and $_.CommandLine.IndexOf($toolsNorm, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
}

$all = @(Get-CimInstance Win32_Process)
$byId = @{}; foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }

# -- the root: the recorded pid, authenticated; else our own listener ------------------------------
$root = $null
if (Test-Path $stateFile) {
  try { $rec = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { $rec = $null }
  if ($rec -and $rec.pid) {
    $p = $byId[[int]$rec.pid]
    $sameStart = $p -and $rec.creation_date -and ([math]::Abs(($p.CreationDate - [datetime]$rec.creation_date).TotalSeconds) -le 1)
    if ((IsOurs $p) -and $sameStart) { $root = $p }
    elseif ($p) { Write-Host "recorded pid $($rec.pid) is now $($p.Name) (not this code-server or a reused pid); not killing it" }
  }
}
if (-not $root) {
  $lp = ListenerPid
  if ($lp) {
    $p = $byId[$lp]
    if (-not (IsOurs $p)) { Fail 3 "port $PORT is held by pid $lp ($($p.Name)), not this code-server; leaving it alone" }
    # the listener may be the server's child: climb to the outermost ancestor that is also ours
    $root = $p
    for ($i = 0; $i -lt 3; $i++) {
      $pp = $byId[[int]$root.ParentProcessId]
      if ((IsOurs $pp) -and $pp.CreationDate -le $root.CreationDate) { $root = $pp } else { break }
    }
  }
}

# -- the tree: descendants created at or after their parent ---------------------------------------
$tree = @()
if ($root) {
  $tree = @($root); $frontier = @($root)
  while ($frontier.Count -gt 0) {
    $next = @()
    foreach ($f in $frontier) {
      $next += @($all | Where-Object { [int]$_.ParentProcessId -eq [int]$f.ProcessId -and $_.CreationDate -ge $f.CreationDate -and [int]$_.ProcessId -ne [int]$f.ProcessId })
    }
    $tree += $next; $frontier = $next
  }
}
# the sweep: leftovers running an executable from the install dir (orphans of an earlier crash)
$ids = @{}; foreach ($t in $tree) { $ids[[int]$t.ProcessId] = $t }
# ...but never while another code-server from this install serves a DIFFERENT port (a second instance,
# e.g. a test on a spare port): its processes are not orphans
# (the server's own helpers listen on ephemeral ports too; those are in the tree and do not count)
$others = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {
  $_.LocalPort -ne $PORT -and -not $ids.ContainsKey([int]$_.OwningProcess) -and (IsOurs $byId[[int]$_.OwningProcess]) })
if ($others.Count -gt 0) {
  Write-Host ("sweep skipped: this install also serves port(s) {0}" -f (($others | ForEach-Object { $_.LocalPort } | Sort-Object -Unique) -join ","))
} else {
  foreach ($p in $all) { if ((IsOurs $p) -and -not $ids.ContainsKey([int]$p.ProcessId)) { $ids[[int]$p.ProcessId] = $p } }
}

if ($ids.Count -eq 0) {
  Write-Host "code     not running"
} else {
  # leaves first (newest first), each kill bound to a handle checked against the discovered start time
  foreach ($p in @($ids.Values | Sort-Object CreationDate -Descending)) {
    $h = Get-Process -Id ([int]$p.ProcessId) -ErrorAction SilentlyContinue
    if (-not $h) { continue }
    try { if ([math]::Abs(($h.StartTime - $p.CreationDate).TotalSeconds) -gt 1) { continue } } catch { }
    try { $h.Kill() } catch { }
  }
  Write-Host ("code     stopping {0} process(es): {1}" -f $ids.Count, (($ids.Values | Sort-Object CreationDate | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ", "))
}

# -- verify: port closed, nothing references the install -------------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSec)
do {
  $now = @(Get-CimInstance Win32_Process | Where-Object { [int]$_.ProcessId -ne $PID })
  if ($others.Count -gt 0) { $left = @($now | Where-Object { $ids.ContainsKey([int]$_.ProcessId) -and $_.CreationDate -eq $ids[[int]$_.ProcessId].CreationDate }) }
  else { $left = References $now }
  $lp = ListenerPid
  if ($left.Count -eq 0 -and -not $lp) { break }
  Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if ($lp) { Fail 1 "port $PORT still has a listener (pid $lp) after the stop" }
if ($left.Count -gt 0) { Fail 1 ("processes still reference the install dir: " + (($left | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ", ")) }
if (Test-Path $stateFile) { Remove-Item -Force $stateFile }
Write-Host "code     stopped (port $PORT closed, 0 processes reference $toolsNorm)"
exit 0
