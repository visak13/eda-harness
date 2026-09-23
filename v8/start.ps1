# edp8 fleet launcher (Windows). One command from one .env brings up board, broker, pool, MCP
# and the Slack bridge; idempotent (a running service is left alone); builds the web app when its
# dist is missing; leaves a supervisor watching the fleet. Design §15/§22 (S17).
#
#   .\start.ps1                 bring the fleet up (skip what is already running)
#   .\start.ps1 -Restart board  restart ONE service through the launcher (the only supported way
#                               to make a code change live), records a service_restarted event
#   .\start.ps1 -Only mcp       (re)start just one service
#   .\start.ps1 -NoSupervisor   do not leave the health supervisor running
#
# Seats never start/stop shared services (design §22) — that is the human's or this launcher's job.
[CmdletBinding()]
param([string]$Restart, [string]$Only, [switch]$NoSupervisor)
$ErrorActionPreference = "Stop"
$v8 = $PSScriptRoot

# ── one .env (real environment wins, so a caller can override a line) ───────────────────────────
$envFile = Join-Path $v8 ".env"
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith("#")) { continue }
    $kv = $t -split "=", 2
    if ($kv.Count -eq 2) {
      $k = $kv[0].Trim(); $val = ($kv[1] -split "\s+#", 2)[0].Trim()  # drop an inline comment
      if (-not [Environment]::GetEnvironmentVariable($k, "Process")) { Set-Item -Path "Env:$k" -Value $val }
    }
  }
}

function Env($n, $d) { $v = [Environment]::GetEnvironmentVariable($n, "Process"); if ($v) { $v } else { $d } }
$HOMEDIR = Env "EDP8_HOME" $v8
$DATA    = Env "EDP8_DATA" (Join-Path $HOMEDIR ".data")
$RUN     = Env "EDP8_RUN_DIR" (Join-Path $HOMEDIR ".run")
$BOARD_PORT  = [int](Env "EDP8_PORT" "9400")
$BROKER_PORT = [int](Env "EDP_BROKER_PORT" "9300")
$POOL_PORT   = [int](Env "EDP_POOL_PORT" "9301")
$MCP_PORT    = [int](Env "EDP8_MCP_PORT" "9402")
$ADMIN   = Env "EDP8_ADMIN_TOKEN" "dev"
$OWNER   = Env "EDP8_OWNER" "owner"
$PUBLIC  = Env "EDP8_PUBLIC_URL" ""
$BIND    = Env "EDP8_HOST" $(if ($PUBLIC) { "0.0.0.0" } else { "127.0.0.1" })
$py      = Join-Path $v8 ".venv\Scripts\python.exe"
New-Item -ItemType Directory -Force $DATA, $RUN | Out-Null
[Environment]::SetEnvironmentVariable("EDP8_HOME", $HOMEDIR, "Process")
[Environment]::SetEnvironmentVariable("EDP8_RUN_DIR", $RUN, "Process")

# ── prerequisites: a missing tool is a one-line plain message and a non-zero exit ───────────────
function Need($tool) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    [Console]::Error.WriteLine("edp8: '$tool' is not on PATH. Install it (see README) and re-run .\start.ps1")
    exit 3
  }
}
Need "uv"
Need "node"
Need "npm"

function GitRev { try { (& git -C $HOMEDIR rev-parse --short HEAD).Trim() } catch { "unknown" } }
function Probe($port, $path) {
  try { Invoke-RestMethod "http://127.0.0.1:$port$path" -TimeoutSec 2 | Out-Null; $true } catch { $false }
}
function WriteState($svc, $procId, $port) {
  # Record the REAL pid owning the listener (or, for the port-less bridge, the newest slack_bridge),
  # falling back to the passed pid — so `edp8 status` and pid-kills hit the right process even from
  # the already-running branch, and consistently with Git Bash (S17 c-c0f2ceea9b).
  $fb = if ($procId) { "$procId" } else { "0" }
  $pt = if ("$port") { "$port" } else { "" }
  & $py -c "from edp8 import run_state; p=('$pt' and int('$pt')) or None; pid=(run_state.listener_pid(p) if p else run_state.process_pid_matching('edp8.slack_bridge')) or int('$fb' or 0); run_state.write('$svc', pid=pid, port=p, git_rev=run_state.git_rev())" 2>$null
}
function StartProc($file, $argList, $log, $errlog) {
  Start-Process -FilePath $file -ArgumentList $argList -WorkingDirectory $HOMEDIR -WindowStyle Hidden `
    -PassThru -RedirectStandardOutput $log -RedirectStandardError $errlog
}

# ── the web app: build only when the served bundle is missing ────────────────────────────────────
function Build-Web {
  $dist = Join-Path $v8 "src\edp8\webapp\dist\index.html"
  if (Test-Path $dist) { return }
  Write-Host "web/ dist missing — building the SPA (npm ci + build)..."
  & npm --prefix (Join-Path $v8 "web") ci
  & npm --prefix (Join-Path $v8 "web") run build
  if (-not (Test-Path $dist)) { [Console]::Error.WriteLine("edp8: web build did not produce dist/index.html"); exit 4 }
}

# ── per-service launchers (each idempotent: probe first, skip if already up) ─────────────────────
$root = Split-Path -Parent $v8

function Start-Board {
  if (Probe $BOARD_PORT "/v1/health") { WriteState "board" $null $BOARD_PORT; Write-Host "board    already running on :$BOARD_PORT"; return }
  $env:EDP8_HOST = $BIND; $env:EDP8_PORT = "$BOARD_PORT"; $env:EDP8_ADMIN_TOKEN = $ADMIN
  # EDP8_DATA reaches the board too: uploads live under <EDP8_DATA>/uploads (uploads.py). Without
  # it the board wrote v8/uploads into the source tree (qa acceptance, 2026-09-10). An existing
  # v8/uploads must be MOVED to .data/uploads before the next restart or its artifacts 404.
  $env:EDP8_HOME = $HOMEDIR; $env:EDP8_DATA = $DATA; $env:EDP8_DB = Join-Path $DATA "edp8.db"
  $env:EDP_POOL_URL = "http://127.0.0.1:$POOL_PORT"; $env:EDP_BROKER_URL = "http://127.0.0.1:$BROKER_PORT"
  # With a synced .venv present, run WITHOUT re-syncing: `uv run` otherwise tries to replace
  # .venv\Scripts\edp8-board.exe, which fails (os error 32) while another board from this tree is
  # running — the launcher drill's board never listened (qa launcher drill, 2026-09-10).
  $uvArgs = @("run"); if (Test-Path (Join-Path $HOMEDIR ".venv\Scripts\edp8-board.exe")) { $uvArgs += "--no-sync" }
  $p = StartProc "uv" ($uvArgs + @("--directory",$HOMEDIR,"edp8-board")) (Join-Path $DATA "board.log") (Join-Path $DATA "board.err")
  for ($i=0; $i -lt 60 -and -not (Probe $BOARD_PORT "/v1/health"); $i++) { Start-Sleep -Milliseconds 250 }
  WriteState "board" $p.Id $BOARD_PORT
  try { & uv @uvArgs --directory $HOMEDIR python -m edp8.bootstrap --board "http://127.0.0.1:$BOARD_PORT" --admin $ADMIN --owner $OWNER | Out-Null } catch {}
  Write-Host "board    up   pid $($p.Id)  http://127.0.0.1:$BOARD_PORT  (SPA: /ui)"
}

function Start-Broker {
  if (Probe $BROKER_PORT "/v1/health") { WriteState "broker" $null $BROKER_PORT; Write-Host "broker   already running on :$BROKER_PORT"; return }
  $brokerDir = Join-Path $root "edp-broker"
  if (-not (Test-Path $brokerDir)) { Write-Host "broker   skipped (no $brokerDir)"; return }
  $env:EDP_BROKER_HOST = $BIND; $env:EDP_BROKER_PORT = "$BROKER_PORT"; $env:EDP_BROKER_DATA = Join-Path $DATA "broker-data"
  New-Item -ItemType Directory -Force $env:EDP_BROKER_DATA | Out-Null
  $p = StartProc "uv" @("run","--directory",$brokerDir,"python","-m","edp_broker.main") (Join-Path $DATA "broker.log") (Join-Path $DATA "broker.err")
  for ($i=0; $i -lt 40 -and -not (Probe $BROKER_PORT "/v1/health"); $i++) { Start-Sleep -Milliseconds 250 }
  WriteState "broker" $p.Id $BROKER_PORT
  Write-Host "broker   up   pid $($p.Id)  http://127.0.0.1:$BROKER_PORT"
}

function Start-Pool {
  if (Probe $POOL_PORT "/v1/health") { WriteState "pool" $null $POOL_PORT; Write-Host "pool     already running on :$POOL_PORT"; return }
  $poolDir = Join-Path $root "edp-pool"; $ppy = Join-Path $poolDir ".venv\Scripts\python.exe"
  if (-not (Test-Path $ppy)) { Write-Host "pool     skipped (no edp-pool venv: $ppy)"; return }
  $env:EDP_POOL_AGENT_HOME = $HOMEDIR; $env:EDP_POOL_HOST = "127.0.0.1"; $env:EDP_POOL_PORT = "$POOL_PORT"
  $env:EDP_POOL_LOG_DIR = Join-Path $DATA "pool-logs"; $env:EDP_POOL_STATE = Join-Path $DATA "pool-logs\pool-state.json"
  $env:EDP_SPAWN_MODE = "monitor"; $env:EDP_SKIP_PERMISSIONS = "1"; $env:CLAUDE_CODE_FORCE_SESSION_PERSISTENCE = "1"
  $env:EDP8_BOARD_URL = "http://127.0.0.1:$BOARD_PORT"; $env:EDP_POOL_URL = "http://127.0.0.1:$POOL_PORT"
  $env:EDP_BROKER_URL = "http://127.0.0.1:$BROKER_PORT"
  New-Item -ItemType Directory -Force $env:EDP_POOL_LOG_DIR | Out-Null
  $p = StartProc $ppy @("-m","edp_pool.main") (Join-Path $DATA "pool.log") (Join-Path $DATA "pool.err")
  for ($i=0; $i -lt 60 -and -not (Probe $POOL_PORT "/v1/health"); $i++) { Start-Sleep -Milliseconds 300 }
  WriteState "pool" $p.Id $POOL_PORT
  Write-Host "pool     up   pid $($p.Id)  http://127.0.0.1:$POOL_PORT"
}

function Start-Mcp {
  if (Probe $MCP_PORT "/healthz") { WriteState "mcp" $null $MCP_PORT; Write-Host "mcp      already running on :$MCP_PORT"; return }
  $env:EDP8_HOME = $HOMEDIR; $env:EDP8_BOARD_URL = "http://127.0.0.1:$BOARD_PORT"
  $env:EDP_POOL_URL = "http://127.0.0.1:$POOL_PORT"; $env:EDP_BROKER_URL = "http://127.0.0.1:$BROKER_PORT"
  $env:EDP8_MCP_PORT = "$MCP_PORT"; $env:EDP8_MCP_HOST = "127.0.0.1"; $env:PYTHONPATH = Join-Path $v8 "src"
  $p = StartProc $py @("-m","edp8.mcp_server") (Join-Path $DATA "mcp.log") (Join-Path $DATA "mcp.err")
  for ($i=0; $i -lt 40 -and -not (Probe $MCP_PORT "/healthz"); $i++) { Start-Sleep -Milliseconds 250 }
  WriteState "mcp" $p.Id $MCP_PORT
  Write-Host "mcp      up   pid $($p.Id)  http://127.0.0.1:$MCP_PORT/mcp/<role>"
}

function Start-Bridge {
  if (-not (Test-Path (Join-Path $v8 "slack_map.json"))) { Write-Host "bridge   skipped (no slack_map.json)"; return }
  # Scoped detection (c-c0f2ceea9b): adopt ONLY the bridge pid THIS fleet recorded, verified still a
  # live slack_bridge — never a machine-global Win32_Process scan, which let a private fleet adopt
  # (and stop.ps1 later taskkill) the LIVE Slack bridge.
  $recPid = & $py -c "from edp8 import run_state; r=run_state.read('bridge'); print((r or {}).get('pid') or '')" 2>$null
  if ($recPid) {
    $ok = & $py -c "from edp8 import run_state; print('1' if run_state.pid_cmdline_matches($recPid,'edp8.slack_bridge') else '')" 2>$null
    if ($ok) { Write-Host "bridge   already running pid $recPid"; return }
  }
  $env:EDP8_HOME = $HOMEDIR; $env:EDP_BROKER_URL = "http://127.0.0.1:$BROKER_PORT"; $env:PYTHONPATH = Join-Path $v8 "src"
  if ($PUBLIC) { $env:EDP8_PUBLIC_URL = $PUBLIC }
  $p = StartProc $py @("-m","edp8.slack_bridge") (Join-Path $DATA "bridge.log") (Join-Path $DATA "bridge.err")
  WriteState "bridge" $p.Id ""
  Write-Host "bridge   up   pid $($p.Id)  (Slack doorbell)"
}

$SERVICES = [ordered]@{ board = ${function:Start-Board}; broker = ${function:Start-Broker};
                        pool = ${function:Start-Pool}; mcp = ${function:Start-Mcp}; bridge = ${function:Start-Bridge} }

function Start-Supervisor {
  if ($NoSupervisor) { return }
  $st = & $py -c "from edp8 import run_state; r=run_state.read('supervisor'); print(r['pid'] if r else '')" 2>$null
  if ($st) { Write-Host "supervisor already running pid $st"; return }
  $env:EDP8_BOARD_URL = "http://127.0.0.1:$BOARD_PORT"; $env:EDP8_ADMIN_TOKEN = $ADMIN; $env:PYTHONPATH = Join-Path $v8 "src"
  $p = StartProc $py @("-m","edp8.supervisor") (Join-Path $DATA "supervisor.log") (Join-Path $DATA "supervisor.err")
  Write-Host "supervisor up pid $($p.Id)  (probes every 15s; restarts through this launcher)"
}

function Stop-One($svc) {
  # NO /T (S16): every seat shell is a child of the pool, and the supervisor restarts through this
  # function, so a tree kill here took the whole fleet down with a pool restart. Operators use
  # ..\edp.ps1 restart <svc>, which stops the service's own process chain by id.
  $rec = & $py -c "import json;from edp8 import run_state;r=run_state.read('$svc');print(json.dumps(r) if r else '')" 2>$null
  if ($rec) { $o = $rec | ConvertFrom-Json
    if ($o.pid) { if (Get-Process -Id $o.pid -ErrorAction SilentlyContinue) { & cmd /c "taskkill /PID $o.pid /F >nul 2>&1" } }
    if ($o.port) { Get-NetTCPConnection -LocalPort $o.port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { if (Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue) { & cmd /c "taskkill /PID $_.OwningProcess /F >nul 2>&1" } } }
  }
}

function Restart-One($svc, $by) {
  if (-not $SERVICES.Contains($svc)) { [Console]::Error.WriteLine("edp8: unknown service '$svc' (board|broker|pool|mcp|bridge)"); exit 5 }
  Write-Host "restarting $svc (by $by)..."
  Stop-One $svc; Start-Sleep -Milliseconds 500
  & $SERVICES[$svc]
  & $py -c "from edp8 import run_state; run_state.mark_restart('$svc','manual restart via start.ps1', git_rev=run_state.git_rev())" 2>$null
  try { Invoke-RestMethod "http://127.0.0.1:$BOARD_PORT/v1/service_event" -Method Post -Headers @{ "X-Admin" = $ADMIN } `
        -ContentType "application/json" -Body (@{ service=$svc; reason="manual restart via start.ps1 --restart"; by=$by; git_rev=(& $py -c "from edp8 import run_state;print(run_state.git_rev())") } | ConvertTo-Json) | Out-Null
        Write-Host "recorded service_restarted {$svc, by=$by}" } catch { Write-Host "note: could not record service_restarted ($($_.Exception.Message))" }
}

# ── dispatch ─────────────────────────────────────────────────────────────────────────────────────
if ($Restart) { $by = if ($env:USERNAME) { $env:USERNAME } else { "human" }; Restart-One $Restart $by; exit 0 }

Build-Web
if ($Only) {
  if (-not $SERVICES.Contains($Only)) { [Console]::Error.WriteLine("edp8: unknown service '$Only'"); exit 5 }
  & $SERVICES[$Only]
} else {
  foreach ($name in $SERVICES.Keys) { & $SERVICES[$name] }
  Start-Supervisor
}

Write-Host ""
Write-Host "fleet state (edp8 status):"
$env:PYTHONPATH = Join-Path $v8 "src"; $env:EDP8_RUN_DIR = $RUN
& $py -m edp8.cli status
if ($PUBLIC) { Write-Host "`npublic reach: $PUBLIC  (board bound $BIND; TLS at your reverse proxy — see README)" }
