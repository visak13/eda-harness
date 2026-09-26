# edp8 fleet launcher (Windows) - a thin wrapper over the one launcher, `heronry start|restart`
# (edp8.cli; S3 s-870e401942, design-e963c656f5 4.4). Kept so every existing caller (edp.ps1,
# scripts\start-*.ps1, the supervisor of an older build) keeps working.
#
#   .\start.ps1                   bring the fleet up (skip what is already running) + the supervisor
#   .\start.ps1 -Only mcp         start just one service
#   .\start.ps1 -Restart board    restart ONE service (-Force for the pool: it takes the seats offline)
#   .\start.ps1 -NoSupervisor     do not leave the supervisor running
#
# This checkout is the home (dev mode: its .env, its .data, its .run) unless EDP_HOME says otherwise.
# Builds the web app first when dist is missing. Seats never start/stop shared services.
param([string]$Restart, [string]$Only, [switch]$NoSupervisor, [switch]$Force)
$ErrorActionPreference = "Stop"
$v8 = $PSScriptRoot
if (-not $env:EDP_HOME -and -not $env:EDP8_HOME) { $env:EDP_HOME = $v8 }
$py = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { [Console]::Error.WriteLine("edp8: no venv at $py - run: uv sync --directory v8"); exit 2 }

$dist = Join-Path $v8 "src\edp8\webapp\dist\index.html"
if (-not (Test-Path $dist)) {
  Write-Host "web/ dist missing - building the SPA (npm ci + build)..."
  & npm --prefix (Join-Path $v8 "web") ci
  & npm --prefix (Join-Path $v8 "web") run build
  if (-not (Test-Path $dist)) { [Console]::Error.WriteLine("edp8: web build did not produce dist/index.html"); exit 4 }
}

if ($Restart) {
  $a = @("restart", $Restart); if ($Force) { $a += "--force" }
} else {
  $a = @("start"); if ($Only) { $a += $Only }; if ($NoSupervisor) { $a += "--no-supervisor" }
}
& $py -m edp8.cli @a
exit $LASTEXITCODE
