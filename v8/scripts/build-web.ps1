# Build the Folio SPA bundle into src/edp8/webapp/dist (gitignored, hatch force-included into the wheel).
# Run from anywhere; this resolves v8/ itself and uses `npm --prefix web` so the lockfile and scripts
# stay anchored in web/ (never cd into web/, per web/README.md).
#   -Ci   use `npm ci` (lockfile-exact, for a clean/CI build) instead of `npm install`.
# EDP8_WEB_BASE selects the SPA mount base: default /ui/ (post-cutover, EDP8_UI=folio); set /app/ only
# to build the legacy-mode SPA that mounts at /app. Example: $env:EDP8_WEB_BASE='/app/'; scripts\build-web.ps1
param([switch]$Ci)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
  if ($Ci) { npm --prefix web ci } else { npm --prefix web install }
  npm --prefix web run build
} finally { Pop-Location }
