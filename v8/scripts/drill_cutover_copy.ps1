# S9 (s-9648fded35, design-e963c656f5 s4.13) evidence drill: the dogfood cutover runbook
# (docs/runbook-cutover.md), run on a COPY of this host's v8 state, never on the live fleet.
#   1. copy:    the v8 state into a temp folder (the DB by SQLite online backup, the rest by robocopy)
#   2. wheels:  the four wheels, built offline from this checkout
#   3. install: a private venv + a private EDP_HOME (not a source checkout); spare ports; env scrubbed
#   4. heronry init, import --from <copy> (dry run, then --apply), start, health, whoami with an
#      imported owner token, stop, nothing left, the copy unchanged
# Isolation from the fleet (what a copy of a live host would otherwise reach):
#   * pool-state.json is not copied: its seat and driver rows hold the live fleet's pids;
#   * slack_map.json is not copied: the bridge would relay the live Slack channel;
#   * EDP8_HOST / EDP8_PUBLIC_URL / EDP8_RSI / EDP_RESUME_WATCHDOG are pinned in env, which beats the
#     config.toml the import writes from the copy's .env (tailnet bind, RSI ticks, seat resumes);
#   * seats would run a stub harness; the embedder is off.
#
# -WebDist <dir> serves a private SPA build (EDP8_WEB_DIST); -Shots <dir> then screenshots the epic, ticket and topic
# chats on the imported copy in light and dark (scripts/chat_border_walk.mjs, t-6129a95a3d).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_cutover_copy.ps1 [-Keep] [-WebDist <dir> -Shots <dir>]
param([switch]$Keep, [string]$WebDist, [string]$Shots, [string]$Epic = "epic-7f3d64e6de", [string]$Ticket = "s-9648fded35",
  [string]$Topic = "topic-cd90a55e14")
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$srcPy = Join-Path $v8 ".venv\Scripts\python.exe"
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-cutover-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function Manifest($dir) {
  # path|size|mtime of every file; the extended-length form, since .data holds paths beyond MAX_PATH
  & $srcPy -c @"
import os, sys
root = '\\\\?\\' + os.path.abspath(sys.argv[1])
for d, _, fs in sorted(os.walk(root)):
    for f in sorted(fs):
        st = os.stat(os.path.join(d, f))
        print(os.path.join(d, f)[len(root):], st.st_size, st.st_mtime_ns, sep='|')
"@ $dir
}
$uvCache = (& uv cache dir --color never | Out-String).Trim()
$basePy = (& $srcPy -c "import sys; print(sys.base_prefix)").Trim() + "\python.exe"
"temp $T"

"== 1. copy the v8 state (the live checkout is only read)"
$C = Join-Path $T "v8-copy"
New-Item -ItemType Directory -Path "$C\.data" | Out-Null
foreach ($f in ".env", "tokens.json", "models.json", "ui-settings.json", "ui-avatars.json") {
  if (Test-Path "$v8\$f") { Copy-Item "$v8\$f" "$C\$f" }
}
robocopy "$v8\.data" "$C\.data" /E /R:0 /W:0 /NFL /NDL /NJH /NP `
  /XF edp8.db edp8.db-wal edp8.db-shm edp8.db.vec pool-state.json *.log *.err *.err.* *.pid *.lock `
  /XD logs | Select-Object -Last 4 | ForEach-Object { "   $_" }
if (Test-Path "$v8\uploads") { robocopy "$v8\uploads" "$C\uploads" /E /R:0 /W:0 /NFL /NDL /NJH /NJS /NP | Out-Null }
& $srcPy -c @"
import shutil, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
ro = sqlite3.connect(f'file:{src}?mode=ro', uri=True)
out = sqlite3.connect(dst)
ro.backup(out)
out.close(); ro.close()
shutil.copyfile(src + '.vec', dst + '.vec')
"@ "$v8\.data\edp8.db" "$C\.data\edp8.db"
Check (Test-Path "$C\.data\edp8.db") "the copy holds a DB snapshot"
Check (-not (Test-Path "$C\.data\pool-logs\pool-state.json")) "the copy carries no fleet pool state"
$before = Manifest $C
"   copy: $($before.Count) files"

"== 2. wheels, built offline from HEAD (git archive) with a private SPA build"
# The shared webapp/dist belongs to the architect's deploys, so it is neither used nor rebuilt: the SPA is built
# from this checkout's web/ straight into the archive's dist, and the wheels come from the committed tree.
$S = Join-Path $T "src"; New-Item -ItemType Directory -Path $S | Out-Null
& git -C $root archive --format=tar -o "$T\src.tar" HEAD edp-contracts edp-pool edp-broker v8 CHANGELOG.md LICENSE NOTICE
& tar -xf "$T\src.tar" -C $S
"   HEAD $(& git -C $root rev-parse --short HEAD)"
$env:EDP8_WEB_OUT = "$S\v8\src\edp8\webapp\dist"; $env:EDP8_WEB_BASE = "/ui/"
& npm --prefix "$v8\web" run build 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
Remove-Item Env:EDP8_WEB_OUT, Env:EDP8_WEB_BASE
Check (Select-String -Quiet -Path "$S\v8\src\edp8\webapp\dist\index.html" -Pattern "/ui/assets/") "the private SPA build has the /ui/ base"
$W = Join-Path $T "wheels"
$env:EDP8_WEB_AUTOBUILD = "0"
foreach ($p in "edp-contracts", "edp-pool", "edp-broker", "v8") {
  & uv build --offline --wheel --out-dir $W "$S\$p" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
}
Check (@(Get-ChildItem "$W\*.whl").Count -eq 4) "four wheels"

"== 3. private install: venv + EDP_HOME, spare ports, env scrubbed"
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or $_.Name -like "SLACK*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:UV_CACHE_DIR = $uvCache
& uv venv --offline --python $basePy "$T\venv" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
# uv cannot reach the network on this host and its offline resolver misses cached wheels (pywinpty), so the
# dependencies come from a wheelhouse repacked from the checkout's own venvs (scripts/repack_wheelhouse.py).
& $srcPy "$v8\scripts\repack_wheelhouse.py" "$T\wheelhouse" "$v8\.venv" "$root\edp-pool\.venv" "$root\edp-broker\.venv" `
  --skip edp8,edp-pool,edp-broker,edp-contracts | ForEach-Object { "   $_" }
& uv pip install --offline --no-index --find-links "$T\wheelhouse" --python "$T\venv\Scripts\python.exe" (Get-ChildItem "$W\*.whl").FullName 2>&1 |
  Select-Object -Last 2 | ForEach-Object { "   $_" }
$h = "$T\venv\Scripts\heronry.exe"
Check (Test-Path $h) "heronry.exe in the private venv"
$HomeDir = Join-Path $T "home"; New-Item -ItemType Directory -Path $HomeDir | Out-Null
$env:EDP_HOME = $HomeDir
$env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort; $env:EDP_CODE_PORT = FreePort
$env:EDP8_HOST = "127.0.0.1"; $env:EDP8_PUBLIC_URL = "http://127.0.0.1:$env:EDP8_PORT"
$env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
if ($WebDist) { $env:EDP8_WEB_DIST = $WebDist }
Copy-Item "$root\edp-pool\tests\fixtures\stub_harness.py" "$T\stub_harness.py"
Set-Content -Path "$T\claude-stub.cmd" -Value "@`"$T\venv\Scripts\python.exe`" `"$T\stub_harness.py`" %*" -Encoding ascii
$env:EDP_CLAUDE_BIN = "$T\claude-stub.cmd"; $env:EDP_SPAWN_MODE = "headless"; $env:EDP_SHADOW = "0"
Set-Location $T
"   ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT"
& $h version

"== 4a. heronry init"
& $h init --harness claude --yes 2>&1 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "init exit 0"

"== 4b. heronry import --from <copy> (dry run)"
& $h import --from $C 2>&1 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "dry run exit 0"
Check (-not (Test-Path "$HomeDir\.data\edp8.db") -or ((Get-Item "$HomeDir\.data\edp8.db").Length -lt 1MB)) "the dry run wrote no DB"

"== 4c. heronry import --from <copy> --apply"
& $h import --from $C --apply 2>&1 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "import exit 0"
$counts = & "$T\venv\Scripts\python.exe" -c @"
import json, sys
from pathlib import Path
from edp8.importer import db_counts
a, b = db_counts(Path(sys.argv[1])), db_counts(Path(sys.argv[2]))
print(json.dumps({'copy': a, 'imported': b, 'equal': a == b}))
"@ "$C\.data\edp8.db" "$HomeDir\.data\edp8.db" | ConvertFrom-Json
"   copy     $($counts.copy | ConvertTo-Json -Compress)"
"   imported $($counts.imported | ConvertTo-Json -Compress)"
Check $counts.equal "the imported DB holds the same rows as the copy"

try {
  "== 4d. heronry start"
  & $h start --no-browser 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "start exit 0"
  & $h status 2>&1 | ForEach-Object { "   $_" }
  $rows = & $h status --json | Out-String | ConvertFrom-Json
  foreach ($svc in "board", "mcp", "pool", "broker") {
    $r = @($rows | Where-Object { $_.service -eq $svc })[0]
    Check ($r.state -eq "up" -and $r.url -match "^http://127\.0\.0\.1:\d+$") "status: $svc up at $($r.url)"
  }
  $hl = $null; try { $hl = Invoke-RestMethod "http://127.0.0.1:$env:EDP8_PORT/v1/health" -TimeoutSec 10 } catch { }
  "   board /v1/health: $($hl | ConvertTo-Json -Compress -Depth 3)"
  Check ($hl -and ($hl | ConvertTo-Json -Depth 5) -match '"0\.9\.0"') "the board reports version 0.9.0"
  $ui = ""; try { $ui = (Invoke-WebRequest "http://127.0.0.1:$env:EDP8_PORT/ui/" -UseBasicParsing -TimeoutSec 10).Content } catch { }
  Check ($ui -match "<title>Heronry") "/ui serves the Heronry SPA"
  $tok = & "$T\venv\Scripts\python.exe" -c "import json,sys; print(json.load(open(sys.argv[1]))['owner'])" "$C\tokens.json"
  $who = $null; try { $who = Invoke-RestMethod "http://127.0.0.1:$env:EDP8_PORT/v1/whoami" -Headers @{ "X-Participant" = "owner"; "X-Token" = $tok } -TimeoutSec 20 } catch { "   whoami error: $($_.Exception.Message)" }
  $pid_ = $who.value.participant.id  # the board envelope is {ok, value, hint}
  "   whoami with the imported owner token: $pid_ ($(@($who.value.tickets).Count) tickets)"
  Check ([bool]$pid_) "an imported owner token signs in to the new board"
  if ($Shots) {
    "== chat-pane screenshots on the imported copy (t-6129a95a3d)"
    New-Item -ItemType Directory -Force -Path $Shots | Out-Null
    $env:WALK_OWNER_TOKEN = $tok
    & node "$v8\scripts\chat_border_walk.mjs" "http://127.0.0.1:$env:EDP8_PORT" $Shots $Epic $Ticket $Topic 2>&1 | ForEach-Object { "   $_" }
    Check ($LASTEXITCODE -eq 0) "every chat pane is framed in light and dark"
    Remove-Item Env:WALK_OWNER_TOKEN
  }
  $tok = $null
} finally {
  "== 4e. heronry stop"
  & $h stop --force 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "stop exit 0"
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process | Where-Object {
  ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase)) -or
  ($_.CommandLine -and $_.CommandLine.IndexOf($T, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
Check ($left.Count -eq 0) "stop leaves no process running from the private install ($($left.Count) found)"
foreach ($p in @($env:EDP8_PORT, $env:EDP8_MCP_PORT, $env:EDP_POOL_PORT, $env:EDP_BROKER_PORT)) {
  Check (-not (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue)) "port $p is free"
}
$after = Manifest $C
Check ((Compare-Object $before $after).Count -eq 0) "the import left the copy unchanged ($($after.Count) files)"
if (-not $Keep) {
  # extended-length paths and read-only git objects: Remove-Item leaves a copied .data behind
  Set-Location $env:TEMP
  & $srcPy -c "import os, shutil, stat, sys; shutil.rmtree(chr(92) * 2 + '?' + chr(92) + sys.argv[1], onexc=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))" $T
  Check (-not (Test-Path $T)) "the temp folder is removed"
}
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
