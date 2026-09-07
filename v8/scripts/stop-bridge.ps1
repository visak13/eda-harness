# Thin wrapper (S17): delegates to v8\stop.ps1 -Only bridge.
& (Join-Path (Split-Path -Parent $PSScriptRoot) "stop.ps1") -Only bridge @args
