# Thin wrapper (S17): the fleet launcher owns startup. Delegates to v8\start.ps1 -Only board.
# One .env, one run-state (v8\.run), one supervisor. See v8\README.md.
#
# EDP8_UI (S12 cutover, design 4.1) selects which renderer owns /ui at board boot:
#   folio  (default) - Folio SPA at /ui, legacy server-rendered UI kept at /ui-legacy (rollback)
#   legacy           - legacy UI back at /ui, SPA at /app (the pre-cutover mapping)
# /ui/poll and every /v1 route are identical under both. Rollback the SPA in one flag:
#   $env:EDP8_UI = 'legacy'; scripts\start-board.ps1 -Restart     (the launcher restarts the board)
# The SPA must be built with a matching base (EDP8_WEB_BASE, default /ui/): npm --prefix web run build.
& (Join-Path (Split-Path -Parent $PSScriptRoot) "start.ps1") -Only board @args
