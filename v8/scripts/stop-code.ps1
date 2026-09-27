# Stop the `code` service: a thin wrapper over `heronry stop code` (S21 s-0cfebd3862, edp8.code_service).
#
#   scripts\stop-code.ps1
#
# Stops only what this home recorded in <run>\code.json: the code-server and its guard, each by its
# recorded (pid, create time), with their whole process trees; a record written by the old script
# (pid + creation_date) is matched the same way. Never by image name; a listener on the port that is not
# this home's code server is left alone. Exit 0 stopped or not running, 1 something survived.
param([int]$TimeoutSec = 20)
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot

$PY = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { [Console]::Error.WriteLine("stop-code: the edp8 venv python is missing ($PY)"); exit 4 }
if (-not $env:EDP_HOME -and -not $env:EDP8_HOME) { $env:EDP_HOME = $v8 }
& $PY -m edp8.cli stop code
exit $LASTEXITCODE
