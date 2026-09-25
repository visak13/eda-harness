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

$HOMEDIR = EnvOr "EDP8_HOME" $v8
$RUN = EnvOr "EDP8_RUN_DIR" (Join-Path $HOMEDIR ".run")
$PORT = [int](EnvOr "EDP_CODE_PORT" "9410")
$stateFile = Join-Path $RUN "code.json"
$userDir = [IO.Path]::GetFullPath((Join-Path (EnvOr "EDP_CODE_DATA" (Join-Path $v8 ".data\code")) "user"))
$toolsNorm = ([IO.Path]::GetFullPath((Join-Path $v8 ".tools\code-server"))).TrimEnd("\") + "\"

function IsOurs($p) { $p -and $p.ExecutablePath -and $p.ExecutablePath.StartsWith($toolsNorm, [StringComparison]::OrdinalIgnoreCase) }
# the host guard in front of this port (s-03c7e9168b): edp8.code_guard --port $PORT tagged with this install
function IsGuard($p) {
  $p -and $p.CommandLine -and $p.CommandLine -match 'edp8\.code_guard' -and $p.CommandLine -match ('--port\s+' + $PORT + '(\s|$)') -and
    $p.CommandLine.IndexOf($toolsNorm, [StringComparison]::OrdinalIgnoreCase) -ge 0
}
function SameStart($p, $recorded) { $p -and $recorded -and ([math]::Abs(($p.CreationDate - [datetime]$recorded).TotalSeconds) -le 1) }
function Climb($p, [scriptblock]$same) {
  # the outermost ancestor of the same kind (a listener may be the child of a launcher)
  $r = $p
  for ($i = 0; $i -lt 3; $i++) {
    $pp = $byId[[int]$r.ParentProcessId]
    if ((& $same $pp) -and $pp.CreationDate -le $r.CreationDate) { $r = $pp } else { break }
  }
  $r
}
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
$root = $null; $groot = $null
if (Test-Path $stateFile) {
  try { $rec = Get-Content $stateFile -Raw | ConvertFrom-Json } catch { $rec = $null }
  if ($rec -and $rec.pid) {
    $p = $byId[[int]$rec.pid]
    if ((IsOurs $p) -and (SameStart $p $rec.creation_date)) { $root = $p }
    elseif ($p) { Write-Host "recorded pid $($rec.pid) is now $($p.Name) (not this code-server or a reused pid); not killing it" }
  }
  if ($rec -and $rec.guard_pid) {
    $p = $byId[[int]$rec.guard_pid]
    if ((IsGuard $p) -and (SameStart $p $rec.guard_creation_date)) { $groot = $p }
    elseif ($p) { Write-Host "recorded guard pid $($rec.guard_pid) is now $($p.Name) (not this guard or a reused pid); not killing it" }
  }
}
$lp = ListenerPid
if ($lp -and -not ($root -and $groot)) {
  $p = $byId[$lp]
  if (IsGuard $p) { if (-not $groot) { $groot = Climb $p { param($x) IsGuard $x } } }
  elseif (IsOurs $p) { if (-not $root) { $root = Climb $p { param($x) IsOurs $x } } }   # a pre-guard start bound to the port
  elseif (-not $root -and -not $groot) { Fail 3 "port $PORT is held by pid $lp ($($p.Name)), not this code-server; leaving it alone" }
}

# -- the tree: descendants created at or after their parent ---------------------------------------
$tree = @()
foreach ($r in @($root, $groot)) {
  if (-not $r) { continue }
  $tree += @($r); $frontier = @($r)
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
# ...but never while another code-server from this install is alive for a DIFFERENT port or runs its
# extension CLI (a second instance, e.g. a test on a spare port, possibly still starting): its
# processes are not orphans. It is recognised by its server root's --bind-addr, not by a listener
# (helpers listen on ephemeral ports; a starting server listens on nothing yet).
function OtherInstance($p) {
  if (-not (IsOurs $p) -or $ids.ContainsKey([int]$p.ProcessId) -or -not $p.CommandLine) { return $false }
  # a server is this service's when it runs on this service's user-data dir: behind the guard it binds a
  # random inner port, so the port no longer tells instances apart (a spare-port test uses its own dir)
  if ($p.CommandLine -match '--bind-addr\s') { return ($p.CommandLine.IndexOf($userDir, [StringComparison]::OrdinalIgnoreCase) -lt 0) }
  $p.CommandLine -match '--install-extension|--list-extensions|--uninstall-extension'
}
$others = @($all | Where-Object { OtherInstance $_ })
if ($others.Count -gt 0) {
  Write-Host ("sweep skipped: another instance of this install is alive (pid {0})" -f (($others | ForEach-Object { $_.ProcessId }) -join ","))
} else {
  foreach ($p in $all) { if ((IsOurs $p) -and -not $ids.ContainsKey([int]$p.ProcessId)) { $ids[[int]$p.ProcessId] = $p } }
}

# each kill is bound to a handle checked against the discovered start time (a reused pid is skipped)
function KillOne($p) {
  $h = Get-Process -Id ([int]$p.ProcessId) -ErrorAction SilentlyContinue
  if (-not $h) { return }
  try { if ([math]::Abs(($h.StartTime - $p.CreationDate).TotalSeconds) -gt 1) { return } } catch { return }
  try { $h.Kill() } catch { }
}
if ($ids.Count -eq 0) {
  Write-Host "code     not running"
} else {
  Write-Host ("code     stopping {0} process(es): {1}" -f $ids.Count, (($ids.Values | Sort-Object CreationDate | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ", "))
  # oldest first: the server goes before its helpers, so it cannot respawn a pty host we just killed
  foreach ($p in @($ids.Values | Sort-Object CreationDate)) { KillOne $p }
}

# -- verify: port closed, nothing references the install (late-spawned helpers are killed too) ------
$deadline = (Get-Date).AddSeconds($TimeoutSec)
do {
  $now = @(Get-CimInstance Win32_Process | Where-Object { [int]$_.ProcessId -ne $PID })
  if ($others.Count -gt 0) {
    # only our tree: what is left of it, plus children it spawned after the snapshot
    $live = @{}; foreach ($p in $now) { if ($ids.ContainsKey([int]$p.ProcessId) -and $p.CreationDate -eq $ids[[int]$p.ProcessId].CreationDate) { $live[[int]$p.ProcessId] = $p } }
    foreach ($p in $now) { if ($ids.ContainsKey([int]$p.ParentProcessId) -and -not $ids.ContainsKey([int]$p.ProcessId) -and $p.CreationDate -ge $ids[[int]$p.ParentProcessId].CreationDate) { $ids[[int]$p.ProcessId] = $p; $live[[int]$p.ProcessId] = $p } }
    $left = @($live.Values)
  } else {
    # the guard is the venv python, not an install executable: it is left over while it is alive
    $left = @(References $now) + @($now | Where-Object { $ids.ContainsKey([int]$_.ProcessId) -and -not (IsOurs $_) -and $_.CreationDate -eq $ids[[int]$_.ProcessId].CreationDate })
  }
  $lp = ListenerPid
  if ($left.Count -eq 0 -and -not $lp) { break }
  foreach ($p in $left) { if ((IsOurs $p) -or $ids.ContainsKey([int]$p.ProcessId)) { KillOne $p } }
  Start-Sleep -Milliseconds 500
} while ((Get-Date) -lt $deadline)
if ($lp) { Fail 1 "port $PORT still has a listener (pid $lp) after the stop" }
if ($left.Count -gt 0) { Fail 1 ("processes still reference the install dir: " + (($left | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ", ")) }
if (Test-Path $stateFile) { Remove-Item -Force $stateFile }
if ($others.Count -gt 0) { Write-Host "code     stopped (port $PORT closed, this instance's processes gone; the other instance was left running)" }
else { Write-Host "code     stopped (port $PORT closed, 0 processes reference $toolsNorm)" }
exit 0
