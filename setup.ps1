# One-time setup after cloning this repo anywhere: build each service's env and check prereqs.
# Run from the repo root (or via absolute path); everything is located relative to this file.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

foreach ($tool in @("uv", "claude")) {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
    throw "'$tool' is not on PATH. Install it first (uv: https://docs.astral.sh/uv/ ; claude: https://claude.com/claude-code)."
  }
}

foreach ($proj in @("edp-contracts", "edp-broker", "edp-pool", "v8")) {
  $dir = Join-Path $root $proj
  if (-not (Test-Path (Join-Path $dir "pyproject.toml"))) { throw "missing project: $dir" }
  Write-Host "== uv sync: $proj"
  Push-Location $dir
  # uv reports progress on stderr; under Windows PowerShell 5.1 with "Stop" that line is a terminating
  # NativeCommandError, so run it under "Continue" and judge it by its exit code.
  $ErrorActionPreference = "Continue"
  try {
    uv sync 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed in $dir (exit $LASTEXITCODE)" }
  } finally { $ErrorActionPreference = "Stop"; Pop-Location }
}

Write-Host ""
Write-Host "setup complete. Next: copy v8\.env.example v8\.env, then .\edp.ps1 start all"
Write-Host "board UI: http://127.0.0.1:9400/ui"
