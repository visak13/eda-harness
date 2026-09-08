#!/usr/bin/env sh
# Build the Folio SPA bundle into src/edp8/webapp/dist (gitignored, hatch force-included into the wheel).
# Resolves v8/ itself and uses `npm --prefix web` so the lockfile and scripts stay anchored in web/
# (never cd into web/, per web/README.md). Pass --ci for a lockfile-exact `npm ci` instead of install.
# EDP8_WEB_BASE selects the SPA mount base: default /ui/ (post-cutover, EDP8_UI=folio); set /app/ only
# to build the legacy-mode SPA that mounts at /app. Example: EDP8_WEB_BASE=/app/ scripts/build-web.sh
set -eu
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [ "${1:-}" = "--ci" ]; then
  npm --prefix web ci
else
  npm --prefix web install
fi
npm --prefix web run build
