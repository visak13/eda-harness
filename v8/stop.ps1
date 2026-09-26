# edp8 fleet - bring everything down: a thin wrapper over `heronry stop` (edp8.cli; S3 s-870e401942).
#   .\stop.ps1                  stop supervisor + bridge + mcp + pool + broker + board
#   .\stop.ps1 -Only mcp        stop just one
#   -Force                      needed when the pool has live seats (a pool stop takes them offline)
# heronry verifies every process is gone before it prints "stopped" and exits 1 naming any survivor.
[CmdletBinding()]
param([string]$Only, [switch]$Force)
$ErrorActionPreference = "Stop"
$v8 = $PSScriptRoot
if (-not $env:EDP_HOME -and -not $env:EDP8_HOME) { $env:EDP_HOME = $v8 }
$py = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { [Console]::Error.WriteLine("edp8: no venv at $py - run: uv sync --directory v8"); exit 2 }
$a = @("stop"); if ($Only) { $a += $Only }; if ($Force) { $a += "--force" }
& $py -m edp8.cli @a
exit $LASTEXITCODE
