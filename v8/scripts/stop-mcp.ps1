# Thin wrapper (S17): delegates to v8\stop.ps1 -Only mcp.
& (Join-Path (Split-Path -Parent $PSScriptRoot) "stop.ps1") -Only mcp @args
