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
  try { uv sync } finally { Pop-Location }
}

Write-Host ""
Write-Host "setup complete. Start the stack with start-v8.bat, or your shell with owner.bat."
Write-Host "board UI: http://127.0.0.1:9400/ui"
