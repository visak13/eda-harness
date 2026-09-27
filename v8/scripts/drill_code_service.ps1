# S21 (s-0cfebd3862, c-0b7b0506e6): the code service from an INSTALLED wheel on a private home, cold.
#   1. wheels:  the four wheels, built offline from HEAD (git archive), with a private SPA build
#   2. install: a private venv + a private EDP_HOME (not a checkout: no pinned build, no vendored extensions); spare ports
#   3. not_installed: no code-server anywhere -> `heronry start code` exits 1 with the install hint; status says so
#   4. opt-in: `heronry start` brings up the fleet and leaves code down (code_server.autostart is off)
#   5. start: code_server.path names a real code-server -> guard + code-server listen on loopback only; a second
#      start is idempotent; the board's Code tab status is running; the owner's minted session signs a browser in
#      through the guard and the workbench loads (what the tab's iframe does); an unsigned request gets 401
#   6. stop: `heronry stop code` leaves none of the recorded processes and frees the port; `heronry stop`; no survivors
# Never touches the fleet: every port is a free one, the fleet's :9410 is checked unchanged at the end.
#   -Shots <dir>: then scripts/s21_code_walk.mjs drives the private board as its admin (c-b73a4537db): light/dark shots
# Usage: scripts\drill_code_service.ps1 [-CodeServer <dir>] [-Shots <dir>] [-Keep]   (default: v8\.tools\code-server\<pinned>)
param([string]$CodeServer = "", [string]$Shots = "", [switch]$Keep)
$ErrorActionPreference = "Continue"
$v8 = Split-Path -Parent $PSScriptRoot
$root = Split-Path -Parent $v8
$srcPy = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not $CodeServer) {
  $pin = (Get-Content "$v8\vscode-ext\code-server.lock.json" -Raw | ConvertFrom-Json).version
  # the pinned archive unpacks into one release dir (lib\node.exe + the server) under the version dir
  $CodeServer = @(Get-ChildItem -Directory (Join-Path $v8 ".tools\code-server\$pin") | Where-Object { Test-Path "$($_.FullName)\lib\node.exe" })[0].FullName
}
$T = Join-Path ([IO.Path]::GetTempPath()) ("heronry-code-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Path $T | Out-Null
$fail = 0
function Check($ok, $what) { if ($ok) { "PASS  $what" } else { "FAIL  $what"; $script:fail++ } }
function FreePort { $l = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0); $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); $p }
function CodeRow { $all = & $h status --json | Out-String | ConvertFrom-Json; @($all | Where-Object { $_.service -eq "code" })[0] }
function Fleet9410 { @(Get-NetTCPConnection -LocalPort 9410 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { $_.OwningProcess }) -join "," }
$uvCache = (& uv cache dir --color never | Out-String).Trim()
$basePy = (& $srcPy -c "import sys; print(sys.base_prefix)").Trim() + "\python.exe"
$fleetBefore = Fleet9410
"temp $T"
"code-server under test: $CodeServer"
"fleet :9410 listener pid(s): '$fleetBefore' (must be the same at the end)"

"== 1. wheels, built offline from HEAD (git archive) with a private SPA build"
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

"== 2. private install: venv + EDP_HOME, spare ports, env scrubbed"
Get-ChildItem Env: | Where-Object { $_.Name -like "EDP*" -or $_.Name -like "HERONRY*" -or $_.Name -like "UV_*" -or $_.Name -like "SLACK*" -or
  @("CLAUDE_CONFIG_DIR", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONHOME") -contains $_.Name } | ForEach-Object { Remove-Item "Env:$($_.Name)" }
$env:UV_CACHE_DIR = $uvCache
& uv venv --offline --python $basePy "$T\venv" 2>&1 | Select-Object -Last 1 | ForEach-Object { "   $_" }
& $srcPy "$v8\scripts\repack_wheelhouse.py" "$T\wheelhouse" "$v8\.venv" "$root\edp-pool\.venv" "$root\edp-broker\.venv" `
  --skip edp8,edp-pool,edp-broker,edp-contracts | Select-Object -Last 1 | ForEach-Object { "   $_" }
& uv pip install --offline --no-index --find-links "$T\wheelhouse" --python "$T\venv\Scripts\python.exe" (Get-ChildItem "$W\*.whl").FullName 2>&1 |
  Select-Object -Last 1 | ForEach-Object { "   $_" }
$h = "$T\venv\Scripts\heronry.exe"
$py = "$T\venv\Scripts\python.exe"
Check (Test-Path $h) "heronry.exe in the private venv"
$HomeDir = Join-Path $T "home"; New-Item -ItemType Directory -Path $HomeDir | Out-Null
$env:EDP_HOME = $HomeDir
$env:EDP8_PORT = FreePort; $env:EDP8_MCP_PORT = FreePort; $env:EDP_POOL_PORT = FreePort; $env:EDP_BROKER_PORT = FreePort
$env:EDP_CODE_PORT = FreePort
$env:EDP8_HOST = "127.0.0.1"   # no EDP8_PUBLIC_URL: a fresh local install is not in public mode
$env:EDP8_RSI = "0"; $env:EDP_RESUME_WATCHDOG = "0"; $env:EDP8_EMBEDDER = "none"
$env:HERONRY_NO_UPDATE_CHECK = "1"; $env:PYTHONIOENCODING = "utf-8"
Copy-Item "$root\edp-pool\tests\fixtures\stub_harness.py" "$T\stub_harness.py"
Set-Content -Path "$T\claude-stub.cmd" -Value "@`"$py`" `"$T\stub_harness.py`" %*" -Encoding ascii
$env:EDP_CLAUDE_BIN = "$T\claude-stub.cmd"; $env:EDP_SPAWN_MODE = "headless"; $env:EDP_SHADOW = "0"
# no code-server anywhere on PATH (npm's global bin is where `npm install -g code-server` would put it)
$env:PATH = (($env:PATH -split ";") | Where-Object { $_ -and -not (Test-Path (Join-Path $_ "code-server*")) }) -join ";"
Set-Location $T
"   ports board=$env:EDP8_PORT mcp=$env:EDP8_MCP_PORT pool=$env:EDP_POOL_PORT broker=$env:EDP_BROKER_PORT code=$env:EDP_CODE_PORT"
& $h version
& $h init --harness claude --yes 2>&1 | Select-Object -Last 2 | ForEach-Object { "   $_" }
Check ($LASTEXITCODE -eq 0) "init exit 0"

"== 3. without code-server: not_installed with the install hint"
$out = & $h start code 2>&1 | Out-String
$code3 = $LASTEXITCODE
$out.TrimEnd() -split "`n" | ForEach-Object { "   $_" }
Check ($code3 -eq 1) "heronry start code exits 1 (got $code3)"
Check ($out -match "not installed" -and $out -match "npm install -g code-server") "it names the install command for this OS"
$row = CodeRow
"   status code row: $($row | ConvertTo-Json -Compress)"
Check ($row.state -eq "not_installed" -and $row.install_hint -match "code-server") "status shows code not_installed with the hint"
Check (-not (Get-NetTCPConnection -LocalPort $env:EDP_CODE_PORT -State Listen -ErrorAction SilentlyContinue)) "nothing listens on the code port"

try {
  "== 4. opt-in: heronry start leaves code alone while code_server.autostart is off"
  & $h start --no-browser 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "start exit 0"
  $rows = & $h status --json | Out-String | ConvertFrom-Json
  foreach ($svc in "board", "mcp", "pool", "broker") {
    Check ((@($rows | Where-Object { $_.service -eq $svc })[0]).state -eq "up") "status: $svc up"
  }
  $crow = @($rows | Where-Object { $_.service -eq "code" })[0]
  Check ($crow.state -ne "up" -and -not $crow.autostart) "code is not started by heronry start (state $($crow.state), autostart $($crow.autostart))"

  "== 5. start code with code_server.path set: guard + code-server, loopback only, embedded by the board"
  # in config.toml, where an admin sets it: the running board and supervisor read it too (env would reach the CLI only)
  Set-Content -Path "$T\setpath.py" -Encoding utf8 -Value @'
import sys
from edp_contracts import settings
f = settings.config_file()
text = f.read_text(encoding="utf-8") if f.is_file() else ""
line = "path = '" + sys.argv[1] + "'"  # a TOML literal string: no escaping of the backslashes
lines = text.splitlines()
if "[code_server]" in (x.strip() for x in lines):
    i = [x.strip() for x in lines].index("[code_server]")
    lines.insert(i + 1, line)
else:
    lines += ["", "[code_server]", line]
f.write_text("\n".join(lines) + "\n", encoding="utf-8")
settings.config_values()  # parses: a broken file would read as empty
print(f"   {f}: [code_server] {line}")
'@
  & $py "$T\setpath.py" $CodeServer
  $t0 = Get-Date
  & $h start code --timeout 120 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "heronry start code exit 0 ($([int]((Get-Date) - $t0).TotalSeconds) s)"
  & $h start code 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "a second start is idempotent"
  & $h status 2>&1 | ForEach-Object { "   $_" }
  # PowerShell 5.1 drops the double quotes of a native argument, so the probe runs from a file
  Set-Content -Path "$T\probe.py" -Value @'
import json, os, sys, urllib.request, urllib.error
import psutil
from edp_contracts import settings
from edp8 import code_service
rec = code_service.record()
board = f"http://127.0.0.1:{os.environ['EDP8_PORT']}"
guard = f"http://127.0.0.1:{os.environ['EDP_CODE_PORT']}"
out = {'record_keys': sorted(k for k in rec if k != 'mint_key'), 'source': rec.get('source'), 'version': rec.get('version')}
def tree(pid):
    try:
        p = psutil.Process(pid); return [p, *p.children(recursive=True)]
    except psutil.Error:
        return []
procs = tree(rec['pid']) + tree(rec['guard_pid'])
out['pids'] = sorted({p.pid for p in procs})
listens = []
for p in procs:
    try:
        listens += [f'{c.laddr.ip}:{c.laddr.port}' for c in p.net_connections(kind='inet') if c.status == psutil.CONN_LISTEN]
    except psutil.Error:
        pass
out['listens'] = sorted(set(listens))
out['loopback_only'] = bool(listens) and all(x.startswith('127.0.0.1:') for x in listens)
out['guard_port'] = any(x == f"127.0.0.1:{os.environ['EDP_CODE_PORT']}" for x in listens)
out['inner_port'] = any(x == f"127.0.0.1:{rec['inner_port']}" for x in listens)
env_leak = []
for p in procs:
    try:
        env_leak += [k for k in p.environ() if k.startswith(('EDP_', 'EDP8_'))]
    except psutil.Error:
        pass
out['server_env_edp_keys'] = sorted(set(env_leak) - {'EDP_HOME', 'EDP8_HOME', 'EDP8_DATA', 'EDP8_RUN_DIR', 'EDP_CONFIG_DIR'})
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
op = urllib.request.build_opener(NoRedirect)
def get(url, headers=None, method='GET', data=None):
    try:
        r = op.open(urllib.request.Request(url, headers=headers or {}, method=method, data=data), timeout=30)
        return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
tok = json.loads((settings.secrets_dir() / 'tokens.json').read_text(encoding='utf-8'))['owner']
auth = {'X-Participant': 'owner', 'X-Token': tok}
s, _, b = get(board + '/v1/code', auth)
st = json.loads(b); st = st.get('value', st)
out['board_code_status'] = {k: st.get(k) for k in ('running', 'url', 'version', 'installed', 'start_command')}
s, _, b = get(board + '/ui/code')
out['ui_code'] = s
out['unsigned_guard'] = get(guard + '/')[0]
out['wrong_host'] = get(guard + '/', {'Host': 'evil.example:80'})[0]
s, _, b = get(board + '/v1/code/session', {**auth, 'Content-Type': 'application/json'}, 'POST', b'{}')
out['session_mint'] = s
t = json.loads(b)['value']['token']
s, hd, _ = get(guard + '/__edp/login?t=' + t + '&next=/')
out['login'] = s
cookie = '; '.join(v.split(';', 1)[0] for k, v in hd.items() if k.lower() == 'set-cookie')
s, hd2, b = get(guard + '/', {'Cookie': cookie})
loc = next((v for k, v in hd2.items() if k.lower() == 'location'), '')
if s == 302 and 'folder=' in loc and '//' not in loc:
    # code-server sends / on to the last folder (./?folder=...): same origin, the iframe follows it
    out['workbench_redirect'] = loc
    s, _, b = get(guard + '/' + loc.lstrip('./'), {'Cookie': cookie})
out['workbench'] = s
out['workbench_is_vscode'] = b'vscode' in b.lower() or b'workbench' in b.lower()
out['replayed_token'] = get(guard + '/__edp/login?t=' + t + '&next=/')[0]
print(json.dumps(out))
'@ -Encoding utf8
  $probe = & $py "$T\probe.py" | Out-String
  "   $($probe.Trim())"
  $pr = $probe | ConvertFrom-Json
  Check ($pr.source -eq "setting") "located through code_server.path (source=$($pr.source), version $($pr.version))"
  Check ($pr.loopback_only -and $pr.guard_port -and $pr.inner_port) "guard and code-server listen on 127.0.0.1 only ($($pr.listens -join ', '))"
  Check (@($pr.server_env_edp_keys).Count -eq 0) "no EDP_*/EDP8_* in the service processes beyond the guard's home keys"
  Check ($pr.board_code_status.running -and $pr.board_code_status.start_command -eq "heronry start code") "the board's Code tab status: running, start_command heronry start code"
  Check ($pr.ui_code -eq 200) "/ui/code serves the Code tab"
  Check ($pr.unsigned_guard -eq 401 -and $pr.wrong_host -eq 421) "the guard refuses an unsigned browser (401) and a foreign Host (421)"
  Check ($pr.session_mint -eq 200 -and $pr.login -eq 302 -and $pr.workbench -eq 200 -and $pr.workbench_is_vscode) "the owner's minted session signs in through the guard and the workbench loads"
  Check ($pr.replayed_token -ne 302) "a used login token does not sign in again ($($pr.replayed_token))"
  $pids = @($pr.pids)

  "== 6. heronry stop code: no process left, the port is free"
  & $h stop code 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "heronry stop code exit 0"
  $alive = @($pids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue })
  Check ($alive.Count -eq 0) "none of the $($pids.Count) recorded service processes survives ($($alive -join ','))"
  Check (-not (Get-NetTCPConnection -LocalPort $env:EDP_CODE_PORT -State Listen -ErrorAction SilentlyContinue)) "the code port is free"
  $row = CodeRow
  Check ($row.state -eq "down") "status: code down"
  if ($Shots) {
    "== 6b. the admin walk: Services and the Code tab, no shell (scripts/s21_code_walk.mjs)"
    New-Item -ItemType Directory -Force -Path $Shots | Out-Null
    $env:WALK_OWNER_TOKEN = (& $py -c "import json; from edp_contracts import settings; print(json.loads((settings.secrets_dir() / 'tokens.json').read_text(encoding='utf-8'))['owner'])").Trim()
    & node "$v8\scripts\s21_code_walk.mjs" "http://127.0.0.1:$env:EDP8_PORT" $Shots 2>&1 | ForEach-Object { "   $_" }
    Check ($LASTEXITCODE -eq 0) "the admin walk passed"
    Remove-Item Env:WALK_OWNER_TOKEN
    Check (-not (Get-NetTCPConnection -LocalPort $env:EDP_CODE_PORT -State Listen -ErrorAction SilentlyContinue)) "the walk left the code server stopped"
  }
} finally {
  "== 7. heronry stop"
  & $h stop --force 2>&1 | ForEach-Object { "   $_" }
  Check ($LASTEXITCODE -eq 0) "stop exit 0"
}
Start-Sleep -Seconds 2
$left = @(Get-CimInstance Win32_Process | Where-Object {
  ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($T, [StringComparison]::OrdinalIgnoreCase)) -or
  ($_.CommandLine -and $_.CommandLine.IndexOf($T, [StringComparison]::OrdinalIgnoreCase) -ge 0) })
Check ($left.Count -eq 0) "no process runs from the private install ($($left.Count) found)"
$fleetAfter = Fleet9410
Check ($fleetAfter -eq $fleetBefore) "the fleet's :9410 listener is untouched ('$fleetAfter')"
if (-not $Keep) {
  Set-Location $env:TEMP
  & $srcPy -c "import os, shutil, stat, sys; shutil.rmtree(sys.argv[1], onexc=lambda f, p, e: (os.chmod(p, stat.S_IWRITE), f(p)))" $T
  Check (-not (Test-Path $T)) "the temp folder is removed"
}
if ($fail) { "RESULT: $fail check(s) FAILED"; exit 1 }
"RESULT: all checks passed"
