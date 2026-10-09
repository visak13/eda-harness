# S11 (s-9277bcebc9, c-23e2510a2e) installed-app drill on a PRIVATE install that never touches the live fleet:
#   A. a fresh engineer seat spawned through the board calls whoami() and stays alive (real claude harness)
#   B. a Help (doctor) seat idle on an open topic is NOT restarted by a board restart (m-9982d31ded): same pid, no new row
#   C. the same seat, closed (an idle topic with no live seat), is NOT started again by a board restart
#   D. ... nor by a restart of the whole private stack
# Wheels come from HEAD of this worktree (S14's 0c86407a is an ancestor); deps are repacked from the main checkout's
# dev venvs (no network). Fleet pids are snapshotted before and after; the private stack is only ever stopped by pid
# under the private folder. The claude sign-in copy is deleted at the end of every run.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_s11_installed.ps1 [-Step build|run|clean]
param([ValidateSet("build", "run", "clean")][string]$Step = "run", [int]$SeatWait = 240, [string]$Log = "",
  [string]$Rev = "HEAD", [string]$Tag = "")   # -Rev <commit> -Tag -control: the same drill on another commit, in its own folder (a control run)
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$T = Join-Path $v8 (".data\s11-drill" + $Tag)
$mainV8 = Join-Path (Split-Path -Parent (Resolve-Path (git -C $root rev-parse --git-common-dir)).Path) "v8"
$mainRoot = Split-Path -Parent $mainV8
$srcPy = Join-Path $mainV8 ".venv\Scripts\python.exe"
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function Stamp { (Get-Date).ToString("HH:mm:ss") }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function Key($p) { -join ([string]$p).ToCharArray().ForEach({ if ([char]::IsLetterOrDigit($_)) { $_ } else { '-' } }) }

# ---------------------------------------------------------------------------------------------- fleet safety
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or $_.Name -like "SLACK*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$FleetRun = Join-Path $env:LOCALAPPDATA "heronry\run"
$FleetApp = Join-Path $env:LOCALAPPDATA "Programs\Heronry contributors"
$Names = "board", "broker", "pool", "mcp", "bridge", "supervisor"
function FleetPids { foreach ($s in $Names) { $f = Join-Path $FleetRun "$s.json"; if (Test-Path $f) { [int](Get-Content $f -Raw | ConvertFrom-Json).pid } } }
function FleetSnap {
  ($Names | ForEach-Object {
    $f = Join-Path $FleetRun "$_.json"
    $p = if (Test-Path $f) { (Get-Content $f -Raw | ConvertFrom-Json).pid } else { "none" }
    $alive = if ($p -ne "none" -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { "up" } else { "down" }
    "$_=$p/$alive" }) -join " "
}
function Under($pr, $dir) {
  ($pr.ExecutablePath -and $pr.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase)) -or
  ($pr.CommandLine -and $pr.CommandLine.IndexOf($dir, [StringComparison]::OrdinalIgnoreCase) -ge 0)
}
function PrivatePids { @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and (Under $_ $T) }) }
function StopPrivate {
  $fleet = @(FleetPids)
  $ps = PrivatePids
  foreach ($pr in $ps) { if ($fleet -contains [int]$pr.ProcessId -or (Under $pr $FleetApp)) { "ABORT pid $($pr.ProcessId) is the fleet's"; exit 3 } }
  foreach ($pr in $ps) { Stop-Process -Id $pr.ProcessId -Force -ErrorAction SilentlyContinue }
  Start-Sleep -Seconds 2
  "   private pids stopped: $($ps.Count); left: $((PrivatePids).Count)"
}
function PreCheck($homeDir) {
  $fleet = @(FleetPids)
  foreach ($f in Get-ChildItem (Join-Path $homeDir ".run") -Filter "*.json" -ErrorAction SilentlyContinue) {
    $rec = Get-Content $f.FullName -Raw | ConvertFrom-Json
    foreach ($p in @($rec.pid, $rec.root.pid) | Where-Object { $_ }) {
      if ($fleet -contains [int]$p) { "ABORT $($f.Name) names fleet pid $p"; exit 3 }
      $pr = Get-CimInstance Win32_Process -Filter "ProcessId=$p" -ErrorAction SilentlyContinue
      if ($pr -and -not (Under $pr $T)) { "ABORT $($f.Name) names pid $p ($($pr.ExecutablePath)) outside $T"; exit 3 }
    }
  }
  "   pre-check ok: every record in $homeDir\.run names a private (or dead) pid"
}
function RmTree($p) {
  if (Test-Path $p) { & $srcPy -c "import os, shutil, stat, sys; shutil.rmtree(chr(92) * 2 + '?' + chr(92) + sys.argv[1], onexc=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))" $p }
}
if ($Step -eq "clean") { StopPrivate; RmTree $T; Check (-not (Test-Path $T)) "private folder removed"; exit 0 }
if ($Log) { Start-Transcript -Path $Log -Force | Out-Null }
New-Item -ItemType Directory -Force -Path $T | Out-Null
$Fleet0 = FleetSnap
"fleet before: $Fleet0"
$freeGb = [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2)
"free RAM $freeGb GB"
if ($freeGb -lt 0.6) { "ABORT free RAM below 0.6 GB (host rule: 400 MB is the spawn threshold)"; exit 4 }

# ---------------------------------------------------------------------------------------------- build
$h = "$T\venv\Scripts\heronry.exe"
if ($Step -eq "build") {
  "== $(Stamp) wheels from $Rev $(& git -C $root rev-parse --short $Rev), private venv"
  $Src = Join-Path $T "src"; RmTree $Src; New-Item -ItemType Directory -Path $Src | Out-Null
  & git -C $root archive --format=tar -o "$T\src.tar" $Rev edp-contracts edp-pool edp-broker v8 CHANGELOG.md LICENSE NOTICE
  & "$env:SystemRoot\System32\tar.exe" -xf "$T\src.tar" -C $Src
  $dist = "$Src\v8\src\edp8\webapp\dist"   # the wheel needs an SPA bundle; the seats never read it, so the main checkout's is copied
  robocopy "$mainV8\src\edp8\webapp\dist" $dist /E /NFL /NDL /NJH /NJS /NP | Out-Null
  Get-ChildItem -Recurse -File $dist | ForEach-Object { $_.LastWriteTime = Get-Date }
  Check (Test-Path "$dist\index.html") "an SPA bundle for the edp8 wheel"
  $W = Join-Path $T "wheels"; RmTree $W
  $env:EDP8_WEB_AUTOBUILD = "0"
  foreach ($p in "edp-contracts", "edp-pool", "edp-broker", "v8") {
    & uv build --offline --wheel --out-dir $W "$Src\$p" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
  }
  Check (@(Get-ChildItem "$W\*.whl").Count -eq 4) "four wheels"
  $uvCache = (& uv cache dir --color never | Out-String).Trim()
  $env:UV_CACHE_DIR = $uvCache
  $basePy = (& $srcPy -c "import sys; print(sys.base_prefix)").Trim() + "\python.exe"
  RmTree "$T\venv"; RmTree "$T\wheelhouse"
  & uv venv --offline --python $basePy "$T\venv" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
  & $srcPy "$mainV8\scripts\repack_wheelhouse.py" "$T\wheelhouse" "$mainV8\.venv" "$mainRoot\edp-pool\.venv" "$mainRoot\edp-broker\.venv" `
    --skip edp8,edp-pool,edp-broker,edp-contracts | Select-Object -Last 1 | ForEach-Object { "   $_" }
  & uv pip install --offline --no-index --find-links "$T\wheelhouse" --python "$T\venv\Scripts\python.exe" (Get-ChildItem "$W\*.whl").FullName 2>&1 |
    Select-Object -Last 1 | ForEach-Object { "   $_" }
  Check (Test-Path $h) "heronry.exe in the private venv"
  "fleet after: $(FleetSnap)"
  Check ((FleetSnap) -eq $Fleet0) "fleet pids unchanged"
  if ($fail) { "RESULT: $fail FAILED"; exit 1 }; "RESULT: build ok"; exit 0
}

# ---------------------------------------------------------------------------------------------- run
if (-not (Test-Path $h)) { "ABORT no private install: run -Step build first"; exit 2 }
$HomeDir = Join-Path $T "home"
$store = Join-Path $HomeDir ".data\claude-pool"
try {
  StopPrivate
  RmTree $HomeDir; New-Item -ItemType Directory -Path $HomeDir | Out-Null
  $env:EDP_HOME = $HomeDir
  $env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort; $env:EDP_CODE_PORT = FreePort
  $env:EDP8_HOST = "127.0.0.1"   # loopback, like the installed app (a public URL would need seeded agent credentials)
  $env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
  $env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
  $env:EDP_SPAWN_MODE = "monitor"; $env:EDP_SHADOW = "0"
  New-Item -ItemType Directory -Force -Path $store | Out-Null
  $fleetStore = Join-Path $env:LOCALAPPDATA "heronry\data\claude-pool"
  Copy-Item "$fleetStore\.credentials.json" "$store\.credentials.json"
  Copy-Item "$fleetStore\.claude.json" "$store\.claude.json"
  Set-Location $T
  "ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT"
  & $h version
  & $h init --harness claude --yes 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "init exit 0"
  & $h start --no-browser 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "start exit 0"
  PreCheck $HomeDir
  $B = "http://127.0.0.1:$env:EDP8_PORT"; $PoolB = "http://127.0.0.1:$env:EDP_POOL_PORT"
  $tokFile = Get-ChildItem $HomeDir -Recurse -Filter tokens.json | Select-Object -First 1
  $tj = Get-Content $tokFile.FullName -Raw | ConvertFrom-Json
  $ownerName = ($tj.PSObject.Properties | Where-Object { $_.Value -is [string] } | Select-Object -First 1).Name
  $Hdr = @{ "X-Participant" = $ownerName; "X-Token" = $tj.$ownerName; "Content-Type" = "application/json" }
  $tj = $null
  function Api($method, $path, $body) {
    try { Invoke-RestMethod "$B$path" -Method $method -Headers $Hdr -TimeoutSec 120 -Body ($(if ($body) { $body | ConvertTo-Json -Depth 5 } else { $null })) }
    catch { [pscustomobject]@{ ok = $false; error = $_.Exception.Message } }
  }
  function Rows { $r = $null; try { $r = Invoke-RestMethod "$PoolB/v1/sessions" -TimeoutSec 10 } catch { return @() }
    @($r | ForEach-Object { $_ }) }   # the pool answers a bare JSON list of session rows
  function SeatRows($handle) { @(Rows | Where-Object { $_.handle -eq $handle }) }
  function BoardAsks($topic) { $pg = Api GET "/v1/topics/$topic" $null; @($pg.value.thread | ForEach-Object { $_ } | Where-Object { $_.created_by -eq 'board' }) }
  function SeatLine($handle) { (SeatRows $handle | ForEach-Object { "$($_.session_id) state=$($_.state) pid=$($_.proc.pid)" }) -join "; " }
  $agentHome = Join-Path $HomeDir "agent-home"
  $proj = Join-Path $store "projects\$(Key $agentHome)"

  Set-Content -Path "$T\whoami_probe.py" -Encoding ascii -Value @'
import json, os, sys
proj, since, handle = sys.argv[1], float(sys.argv[2]), sys.argv[3]
if not os.path.isdir(proj): sys.exit(0)
for f in sorted(os.listdir(proj)):
    p = os.path.join(proj, f)
    if not f.endswith('.jsonl') or os.path.getmtime(p) < since: continue
    ids, lines = {}, open(p, encoding='utf-8', errors='replace').read().splitlines()
    for ln in lines:
        try: o = json.loads(ln)
        except ValueError: continue
        for c in (o.get('message') or {}).get('content') or []:
            if not isinstance(c, dict): continue
            if c.get('type') == 'tool_use' and c.get('name', '').endswith(('__whoami', '__resume_self')): ids[c['id']] = c['name']
            if c.get('type') == 'tool_result' and c.get('tool_use_id') in ids:
                body = c.get('content')
                text = body if isinstance(body, str) else ''.join(x.get('text', '') for x in body or [] if isinstance(x, dict))
                try: env = json.loads(text)
                except ValueError: continue
                v = env.get('value') or {} if env.get('ok') else {}
                who = (v.get('participant') or (v.get('identity') or {}).get('participant') or {}).get('id')
                if who == handle:
                    print(f'{f}|{ids[c["tool_use_id"]]} -> ok, participant {who}|{len(lines)} transcript lines'); sys.exit(0)
'@
  function WaitWhoami($since, $handle) {
    $deadline = (Get-Date).AddSeconds($SeatWait)
    while ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 5; $hit = & $srcPy "$T\whoami_probe.py" $proj $since $handle; if ($hit) { return $hit } }
    $null
  }

  "== $(Stamp) A. fresh engineer spawn calls whoami()"
  $epic = Api POST "/v1/tickets" @{ kind = "epic"; work_type = "chore"; title = "S11 drill epic"; words = "S11 drill: prove a fresh seat calls whoami" }
  "   epic: $($epic | ConvertTo-Json -Compress -Depth 3)"
  $epicId = $epic.value.id
  $story = Api POST "/v1/tickets" @{ kind = "story"; work_type = "chore"; title = "S11 drill story"; parent_id = $epicId; description = "drill" }
  $storyId = $story.value.id
  "   story: $storyId"
  $fresh = "engineer.$storyId"
  $since = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $out = Api POST "/v1/sessions/spawn" @{ role = "engineer"; participant_id = $fresh; ticket_id = $storyId }
  "   spawn: ok=$($out.ok) $($out | ConvertTo-Json -Compress -Depth 3)"
  $hit = WaitWhoami $since $fresh
  "   fresh seat transcript: $hit"
  Check ([bool]$hit) "a fresh claude seat called whoami() and got its participant back"
  Start-Sleep -Seconds 10
  "   fresh seat row 10 s later: $(SeatLine $fresh)"
  Check (@(SeatRows $fresh | Where-Object { $_.state -notin @('done', 'closed', 'dead', 'crashed') }).Count -ge 1) "the fresh seat stays alive"
  [void](Api POST "/v1/sessions/close" @{ participant_id = $fresh; reason = "drill: whoami seen" })

  "== $(Stamp) B. an idle Help seat survives a board restart without a second start"
  $r = & $h doctor --agent "Drill ping: answer with the single word ok, calling no tool." 2>&1 | Out-String
  "   doctor --agent: $($r.Trim())"
  $topic = [regex]::Match($r, "topic-[0-9a-f]+").Value
  Check ([bool]$topic) "a help topic was opened ($topic)"
  $seat = "doctor.$topic"
  $deadline = (Get-Date).AddSeconds($SeatWait); $reply = $false
  while ((Get-Date) -lt $deadline -and -not $reply) {
    Start-Sleep -Seconds 4
    $page = Api GET "/v1/topics/$topic" $null
    $msgs = @($page.value.thread | ForEach-Object { $_ })   # the topic page's thread is a bare list of messages
    $reply = [bool]($msgs | Where-Object { $_.created_by -eq $seat })
  }
  Check $reply "the Help seat answered on its topic (it is now idle)"
  $before = SeatLine $seat
  "   BEFORE board restart: $before  (rows=$(@(SeatRows $seat).Count))"
  $alive = @(SeatRows $seat | Where-Object { $_.state -notin @('done', 'closed', 'dead', 'crashed') })
  Check ($alive.Count -eq 1) "exactly one live Help seat row before the restart"
  PreCheck $HomeDir
  & $h restart board 2>&1 | ForEach-Object { "   $_" }
  Start-Sleep -Seconds 20
  $after = SeatLine $seat
  "   AFTER  board restart: $after  (rows=$(@(SeatRows $seat).Count))"
  Check ($before -eq $after) "the board restart left the idle Help seat's row and pid unchanged (no second start)"
  $asksB = @(BoardAsks $topic).Count
  "   board-authored messages on the topic after the restart: $asksB"
  Check ($asksB -eq 0) "the restart posted no pending-pairing ask on the Help topic (S14 0c86407a)"

  "== $(Stamp) C. a Help topic that OWES an answer (an ask newer than its last shell, no live seat) is not started by a restart"
  # S14's trigger (topics.help_seat_owed): the owner's ask arrives while no seat can take it, then the board boots.
  [void](Api POST "/v1/sessions/close" @{ participant_id = $seat; reason = "drill: the seat is gone" })
  Start-Sleep -Seconds 6
  PreCheck $HomeDir
  & $h stop pool 2>&1 | ForEach-Object { "   $_" }
  Start-Sleep -Seconds 3
  $ask = Api POST "/v1/messages" @{ ticket_id = $topic; to = $seat; kind = "question"; text = "Drill: a second question, sent while the pool is down." }
  "   second ask posted while the pool is down: ok=$($ask.ok)"
  $rowsC0 = @(SeatRows $seat).Count   # the pool is down: read after it is back
  PreCheck $HomeDir
  & $h restart all 2>&1 | ForEach-Object { "   $_" }
  Start-Sleep -Seconds 45
  $pg = Api GET "/v1/topics/$topic" $null
  $thr = @($pg.value.thread | ForEach-Object { $_ })
  "   thread: $((($thr | ForEach-Object { "$($_.created_by):$($_.kind)" }) -join ' > '))"
  $owed = ($thr | Where-Object { $_.created_by -ne 'board' } | Select-Object -Last 1).created_by -ne $seat
  Check $owed "the topic's newest ask is unanswered and no seat shell is newer (the seat is owed: S14's trigger)"
  $liveC1 = @(SeatRows $seat | Where-Object { $_.state -notin @('done', 'closed', 'dead', 'crashed') }).Count
  "   AFTER stack restart: $(SeatLine $seat)  (rows=$(@(SeatRows $seat).Count) live=$liveC1)"
  Check ($liveC1 -eq 0 -and @(SeatRows $seat).Count -eq 1) "the stack restart did not start the owed Help seat (no live row, no new row; m-9982d31ded)"
  $asksC = @(BoardAsks $topic).Count
  "   board-authored messages on the topic after the restart: $asksC"
  Check ($asksC -eq 0) "the restart posted no pending-pairing ask on the Help topic (S14 0c86407a)"
  $liveProcs = @(Rows | Where-Object { $_.proc.pid -and $_.state -notin @('done', 'closed', 'dead', 'crashed') -and (Get-Process -Id $_.proc.pid -ErrorAction SilentlyContinue) })
  "   private pool rows with a live shell: $($liveProcs.Count)"
  Check ($liveProcs.Count -eq 0) "no seat shell runs from the private install"

  "== $(Stamp) D. the held topic stays held across another board restart"
  PreCheck $HomeDir
  & $h restart board 2>&1 | ForEach-Object { "   $_" }
  Start-Sleep -Seconds 25
  $liveD = @(SeatRows $seat | Where-Object { $_.state -notin @('done', 'closed', 'dead', 'crashed') }).Count
  $asksD = @(BoardAsks $topic).Count
  "   AFTER : $(SeatLine $seat)  (rows=$(@(SeatRows $seat).Count) live=$liveD) board-authored messages: $asksD"
  Check ($liveD -eq 0 -and @(SeatRows $seat).Count -eq 1 -and $asksD -eq 0) "a further board restart starts nothing and asks nothing"
} finally {
  "== $(Stamp) stop and clean"
  $Hdr = $null
  # seat shells outlive their pool (a restart leaves them running) and carry no private path in their command line:
  # take their pids from the PRIVATE pool's own session list before it goes
  $seatPids = @(Rows | Where-Object { $_.proc.pid -and $_.state -notin @('done', 'closed', 'dead', 'crashed') } | ForEach-Object { [int]$_.proc.pid })
  $fleetNow = @(FleetPids)
  foreach ($sp in $seatPids) { if ($fleetNow -notcontains $sp) { Stop-Process -Id $sp -Force -ErrorAction SilentlyContinue } }
  "   seat shells of the private pool stopped: $($seatPids.Count)"
  StopPrivate
  if (Test-Path "$store\.credentials.json") { Remove-Item "$store\.credentials.json", "$store\.claude.json" -Force -ErrorAction SilentlyContinue }
  Check (-not (Test-Path "$store\.credentials.json")) "the copied claude sign-in is deleted"
  Set-Location $v8
  "fleet after: $(FleetSnap)"
  Check ((FleetSnap) -eq $Fleet0) "fleet pids unchanged (before: $Fleet0)"
  if ($Log) { Stop-Transcript | Out-Null }
}
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
