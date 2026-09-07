# Thin wrapper (S17): the fleet launcher owns startup. Delegates to v8\start.ps1 -Only mcp.
# One .env, one run-state (v8\.run), one supervisor. See v8\README.md.
& (Join-Path (Split-Path -Parent $PSScriptRoot) "start.ps1") -Only mcp @args
