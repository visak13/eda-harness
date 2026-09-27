# v0.9.1 (s-dbe96f11cd) evidence drill: an INSTALLED Heronry spawns a fresh claude seat and resumes an imported,
# closed claude seat, both with the REAL claude harness, on a private install that never touches the live fleet.
# Sibling of drill_cutover_copy.ps1 (which runs seats on a stub harness).
#   1. source: a copy of the board DB + tokens + models catalogs, a pool-state.json holding ONE closed seat row,
#      and an "old" pool claude store beside it (<T>\edp-pool\.claude-pool) holding that seat's transcript under
#      the copy's cwd key, written by a real `claude -p` turn (the shape the owner's checkout had)
#   2. wheels from HEAD (git archive, uv build --offline), a private venv, a private EDP_HOME, spare ports
#   3. heronry init, import --apply: the transcript must land under the installed agent home's key
#   4. heronry start; fresh spawn through the board (POST /v1/sessions/spawn): the seat must call whoami() and
#      stay alive; resume the imported closed seat through the board (POST /v1/sessions/resume): same
#   5. heronry stop, no survivors; the temp folder (it holds a copy of the claude sign-in) is removed
# The folder lives under v8\.data (git-ignored), not %TEMP%: claude's trust walk needs the agent home there
# (memory private-pool-seat-home-needs-trust). Seats are stopped as soon as their whoami() is seen.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_installed_seats.ps1 [-Keep]
param([switch]$Keep, [string]$SpawnTicket = "t-8713b03b24", [string]$ResumeHandle = "engineer.t-e5fe207e39",
  [int]$SeatWait = 240, [switch]$OnlyResume)
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$srcPy = Join-Path $v8 ".venv\Scripts\python.exe"
$devStore = Join-Path $root "edp-pool\.claude-pool"
$T = Join-Path $v8 (".data\v091-drill-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function Key($p) { -join ([string]$p).ToCharArray().ForEach({ if ([char]::IsLetterOrDigit($_)) { $_ } else { '-' } }) }
function SeedStore($dir) {
  # the pool's claude store needs a sign-in and the first-run flags; the dev store has both
  New-Item -ItemType Directory -Force -Path $dir | Out-Null
  Copy-Item "$devStore\.credentials.json" "$dir\.credentials.json"
  Copy-Item "$devStore\.claude.json" "$dir\.claude.json"
}
# Seat check: a transcript in $proj written after $since whose whoami() tool call got a participant back.
function WaitWhoami($proj, $since, $handle) {
  $deadline = (Get-Date).AddSeconds($SeatWait)
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $hit = & $srcPy "$T\whoami_probe.py" $proj $since $handle
    if ($hit) { return $hit }
  }
  return $null
}
"temp $T"
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
            if c.get('type') == 'tool_use' and c.get('name', '').endswith('__whoami'): ids[c['id']] = c['name']
            if c.get('type') == 'tool_result' and c.get('tool_use_id') in ids:
                body = c.get('content')
                text = body if isinstance(body, str) else ''.join(x.get('text', '') for x in body or [] if isinstance(x, dict))
                try: env = json.loads(text)
                except ValueError: continue
                who = ((env.get('value') or {}).get('participant') or {}).get('id') if env.get('ok') else None
                if who == handle:  # the seat under test, not a sibling still writing
                    print(f'{f}|{ids[c["tool_use_id"]]} -> ok, participant {who}|{len(lines)} transcript lines'); sys.exit(0)
'@
try {
  "== 1. source: DB copy, tokens, catalogs, one closed seat row, an old claude store with its transcript"
  $C = Join-Path $T "v8"
  New-Item -ItemType Directory -Path "$C\.data\pool-logs" | Out-Null
  Copy-Item "$v8\tokens.json" "$C\tokens.json"
  Copy-Item "$v8\models.json" "$C\models.json"
  Copy-Item "$v8\.data\models.json" "$C\.data\models.json"
  & $srcPy -c @"
import sqlite3, sys
ro = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True); out = sqlite3.connect(sys.argv[2]); ro.backup(out); out.close(); ro.close()
"@ "$v8\.data\edp8.db" "$C\.data\edp8.db"
  Check (Test-Path "$C\.data\edp8.db") "the copy holds a DB snapshot"
  $old = Join-Path $T "edp-pool\.claude-pool"
  SeedStore $old
  $S = [guid]::NewGuid().ToString()
  Push-Location $C
  $env:CLAUDE_CONFIG_DIR = $old; $env:DISABLE_AUTOUPDATER = "1"
  $said = & claude -p "reply with the single word ok" --session-id $S 2>&1 | Out-String
  Remove-Item Env:CLAUDE_CONFIG_DIR
  Pop-Location
  "   old-store turn said: $($said.Trim())"
  $oldT = Join-Path $old "projects\$(Key $C)\$S.jsonl"
  Check (Test-Path $oldT) "the old store holds the seat's transcript under the copy's key ($(Key $C))"
  & $srcPy -c @"
import json, sys
live, out, handle, sess = sys.argv[1:5]
rows = json.load(open(live, encoding='utf-8'))['sessions']
row = max((r for r in rows.values() if r.get('handle') == handle and r.get('state') == 'done'),
          key=lambda r: r.get('resumed_at') or r.get('spawned_at') or '')
row = dict(row, claude_session_id=sess, proc=None, mode='monitor')
row['spawn_settings'] = dict(row.get('spawn_settings') or {}, mode='monitor')
json.dump({'sessions': {row['session_id']: row}, 'locks': {}, 'neuron_drivers': {}, 'limit_overrides': {}},
          open(out, 'w', encoding='utf-8'))
print(row['session_id'])
"@ "$v8\.data\pool-logs\pool-state.json" "$C\.data\pool-logs\pool-state.json" $ResumeHandle $S | ForEach-Object { "   closed row: $_ (claude session $S)" }

  "== 2. wheels from HEAD, private venv"
  $Src = Join-Path $T "src"; New-Item -ItemType Directory -Path $Src | Out-Null
  & git -C $root archive --format=tar -o "$T\src.tar" HEAD edp-contracts edp-pool edp-broker v8 CHANGELOG.md LICENSE NOTICE
  & "$env:SystemRoot\System32\tar.exe" -xf "$T\src.tar" -C $Src   # Windows bsdtar: Git Bash's GNU tar reads "C:" as a host
  "   HEAD $(& git -C $root rev-parse --short HEAD)"
  # the edp8 wheel requires an SPA bundle; the seats never need a fresh one, so the served dist is copied (read only)
  $dist = "$Src\v8\src\edp8\webapp\dist"
  if (Test-Path "$v8\src\edp8\webapp\dist\index.html") { robocopy "$v8\src\edp8\webapp\dist" $dist /E /NFL /NDL /NJH /NJS /NP | Out-Null }
  else { $env:EDP8_WEB_OUT = $dist; $env:EDP8_WEB_BASE = "/ui/"; & npm --prefix "$v8\web" run build 2>&1 | Select-Object -Last 1; Remove-Item Env:EDP8_WEB_OUT, Env:EDP8_WEB_BASE }
  # the hook refuses a bundle older than web/src (the archive's files carry the commit time); seats never read it
  Get-ChildItem -Recurse -File $dist | ForEach-Object { $_.LastWriteTime = Get-Date }
  Check (Test-Path "$dist\index.html") "an SPA bundle for the edp8 wheel"
  $W = Join-Path $T "wheels"
  $env:EDP8_WEB_AUTOBUILD = "0"
  foreach ($p in "edp-contracts", "edp-pool", "edp-broker", "v8") {
    & uv build --offline --wheel --out-dir $W "$Src\$p" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
  }
  Check (@(Get-ChildItem "$W\*.whl").Count -eq 4) "four wheels"
  $uvCache = (& uv cache dir --color never | Out-String).Trim()
  $basePy = (& $srcPy -c "import sys; print(sys.base_prefix)").Trim() + "\python.exe"
  Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or $_.Name -like "SLACK*" -or
    @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
  $env:UV_CACHE_DIR = $uvCache
  & uv venv --offline --python $basePy "$T\venv" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
  & $srcPy "$v8\scripts\repack_wheelhouse.py" "$T\wheelhouse" "$v8\.venv" "$root\edp-pool\.venv" "$root\edp-broker\.venv" `
    --skip edp8,edp-pool,edp-broker,edp-contracts | Select-Object -Last 1 | ForEach-Object { "   $_" }
  & uv pip install --offline --no-index --find-links "$T\wheelhouse" --python "$T\venv\Scripts\python.exe" (Get-ChildItem "$W\*.whl").FullName 2>&1 |
    Select-Object -Last 1 | ForEach-Object { "   $_" }
  $h = "$T\venv\Scripts\heronry.exe"
  Check (Test-Path $h) "heronry.exe in the private venv"

  "== 3. private EDP_HOME, spare ports, the real claude harness"
  $HomeDir = Join-Path $T "home"; New-Item -ItemType Directory -Path $HomeDir | Out-Null
  $env:EDP_HOME = $HomeDir
  $env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort; $env:EDP_CODE_PORT = FreePort
  $env:EDP8_HOST = "127.0.0.1"; $env:EDP8_PUBLIC_URL = "http://127.0.0.1:$env:EDP8_PORT"
  $env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
  $env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
  $env:EDP_SPAWN_MODE = "monitor"; $env:EDP_SHADOW = "0"   # monitor is the owner's mode: the activation rides argv
  SeedStore (Join-Path $HomeDir ".data\claude-pool")
  Set-Location $T
  "   ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT"
  & $h version
  & $h init --harness claude --yes 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "init exit 0"
  & $h import --from $C --apply 2>&1 | Where-Object { $_ -notmatch "^\s+(new|merge|replace|same)\s+\.data/" } | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "import exit 0"
  $agentHome = Join-Path $HomeDir "agent-home"
  $proj = Join-Path $HomeDir ".data\claude-pool\projects\$(Key $agentHome)"
  Check (Test-Path "$proj\$S.jsonl") "import copied the transcript under the agent home's key ($(Key $agentHome))"
  Check ((Get-Content -Raw "$HomeDir\.data\models.json") -eq (Get-Content -Raw "$C\.data\models.json")) "the live .data/models.json won over the template"

  "== 4. start, fresh spawn, resume"
  & $h start --no-browser 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "start exit 0"
  $B = "http://127.0.0.1:$env:EDP8_PORT"
  $hl = $null; try { $hl = Invoke-RestMethod "$B/v1/health" -TimeoutSec 20 } catch { }
  "   board /v1/health version: $($hl.value.version)$($hl.version)"
  $r = $null; try { $r = Invoke-WebRequest "$B/" -MaximumRedirection 0 -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop } catch { $r = $_.Exception.Response }
  Check ($r -and [int]$r.StatusCode -eq 307) "GET / redirects to /ui/"
  $tok = & $srcPy -c "import json,sys; print(json.load(open(sys.argv[1]))['owner'])" "$C\tokens.json"
  $Hdr = @{ "X-Participant" = "owner"; "X-Token" = $tok; "Content-Type" = "application/json" }

  Start-Sleep -Seconds 3
  $rows = $null; try { $rows = Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/sessions" -TimeoutSec 10 } catch { }
  foreach ($row in @($rows.sessions) + @($rows | Where-Object { $_.handle })) {
    if ($row.handle -and $row.state -in @("active", "starting")) {
      "   reaping a seat the imported state started by itself: $($row.handle)"
      try { Invoke-RestMethod "$B/v1/sessions/reap" -Method Post -Headers $Hdr -TimeoutSec 60 -Body (@{ participant_id = $row.handle; reason = "drill: not ours" } | ConvertTo-Json) | Out-Null } catch { }
    }
  }
  $since = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $fresh = "engineer.$SpawnTicket"
  if (-not $OnlyResume) {
  $out = $null
  try { $out = Invoke-RestMethod "$B/v1/sessions/spawn" -Method Post -Headers $Hdr -TimeoutSec 120 `
      -Body (@{ role = "engineer"; participant_id = $fresh; ticket_id = $SpawnTicket } | ConvertTo-Json) } catch { "   spawn error: $($_.Exception.Message)" }
  "   spawn: ok=$($out.ok) $($out.value | ConvertTo-Json -Compress -Depth 3)"
  $hit = WaitWhoami $proj $since $fresh
  "   fresh seat transcript: $hit"
  Check ([bool]$hit) "a fresh claude seat called whoami() and got its participant back"
  Start-Sleep -Seconds 15
  $live = $null; try { $live = Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/liveness/$fresh" -TimeoutSec 10 } catch { }
  "   fresh liveness 15 s later: $($live | ConvertTo-Json -Compress)"
  Check (($live | ConvertTo-Json -Compress) -match "alive|active") "the fresh seat stays alive"
  try { Invoke-RestMethod "$B/v1/sessions/close" -Method Post -Headers $Hdr -TimeoutSec 60 -Body (@{ participant_id = $fresh; reason = "drill done" } | ConvertTo-Json) | Out-Null } catch { }

  }
  $since = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $out = $null
  try { $out = Invoke-RestMethod "$B/v1/sessions/resume" -Method Post -Headers $Hdr -TimeoutSec 120 `
      -Body (@{ participant_id = $ResumeHandle } | ConvertTo-Json) } catch { "   resume error: $($_.Exception.Message)" }
  "   resume: ok=$($out.ok) via=$($out.value.via) hint=$($out.hint)"
  Check ($out.ok -and $out.value.via -in @("resume-from-closed", "started-fresh")) "the imported closed seat resumed ($($out.value.via))"
  $hit = WaitWhoami $proj $since $ResumeHandle
  "   resumed seat transcript: $hit"
  Check ([bool]$hit) "the resumed claude seat called whoami() and got its participant back"
  Start-Sleep -Seconds 15
  $live = $null; try { $live = Invoke-RestMethod "http://127.0.0.1:$env:EDP_POOL_PORT/v1/liveness/$ResumeHandle" -TimeoutSec 10 } catch { }
  "   resumed liveness 15 s later: $($live | ConvertTo-Json -Compress)"
  Check (($live | ConvertTo-Json -Compress) -match "alive|active") "the resumed seat stays alive"
  $tok = $null; $Hdr = $null
  $logs = Join-Path $HomeDir ".data\pool-logs"
  Get-ChildItem "$logs\*.log" -ErrorAction SilentlyContinue | ForEach-Object { "   drain log $($_.Name): $($_.Length) bytes" }
} finally {
  "== 5. stop"
  if ($h -and (Test-Path $h)) { & $h stop --force 2>&1 | ForEach-Object { "   $_" } }
  Start-Sleep -Seconds 3
  $left = @(Get-CimInstance Win32_Process | Where-Object {
    ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase)) -or
    ($_.CommandLine -and $_.CommandLine.IndexOf($T, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
  Check ($left.Count -eq 0) "stop leaves no process running from the private install ($($left.Count) found)"
  $left | ForEach-Object { "   left: $($_.ProcessId) $($_.Name)" }
  if ($left.Count) {
    & $srcPy -c "import psutil, sys; ps = [psutil.Process(int(x)) for x in sys.argv[1:] if psutil.pid_exists(int(x))]; ks = [k for p in ps for k in p.children(recursive=True) if k.create_time() >= p.create_time()]; [q.kill() for q in ps + ks if q.is_running()]; print('   killed', len(ps + ks))" @($left | ForEach-Object { $_.ProcessId })
  }
  Set-Location $v8
  if (-not $Keep) {
    & $srcPy -c "import os, shutil, stat, sys; shutil.rmtree(chr(92) * 2 + '?' + chr(92) + sys.argv[1], onexc=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))" $T
    Check (-not (Test-Path $T)) "the temp folder (with its copied claude sign-in) is removed"
  }
}
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
