# Start the `code` service (code-server behind its loopback host guard): a thin wrapper over
# `heronry start code` (S21 s-0cfebd3862, edp8.code_service), kept so `.\edp.ps1 start code` and old
# habits keep working. The service itself (guard on 127.0.0.1:<EDP_CODE_PORT>, code-server on a random
# inner loopback port with a per-start secret, the EDP_*/EDP8_* env strip, the foreign-listener refusal,
# idempotent start, code.json with the mint key) lives in Python and runs the same on every OS.
#
#   scripts\start-code.ps1                     install the pinned build if needed, then heronry start code
#   scripts\start-code.ps1 -SkipExtensions     leave the extensions dir as it is (tests)
#
# Exit codes are the CLI's: 0 up (or already up), 2 a refused setting (a non-loopback EDP_CODE_HOST),
# 3 the port is held by something that is not this home's code server (never killed), 4 no install or no
# venv, 1 anything else. Stop with scripts\stop-code.ps1 (heronry stop code).
param(
  [switch]$SkipExtensions,
  [int]$TimeoutSec = 30
)
$ErrorActionPreference = "Stop"
$v8 = Split-Path -Parent $PSScriptRoot

function Fail($code, $msg) { [Console]::Error.WriteLine("start-code: $msg"); exit $code }

# a checkout pins its code-server build (vscode-ext\code-server.lock.json); a no-op when it is installed
& (Join-Path $PSScriptRoot "install-code-server.ps1")
if ($LASTEXITCODE -ne 0) { Fail 4 "install-code-server.ps1 exited $LASTEXITCODE" }

$PY = Join-Path $v8 ".venv\Scripts\python.exe"
if (-not (Test-Path $PY)) { Fail 4 "the code service needs the edp8 venv python ($PY); run uv sync in v8" }
# this checkout is the home unless the caller named one (the CLI then reads v8\.env, as edp.ps1 does)
if (-not $env:EDP_HOME -and -not $env:EDP8_HOME) { $env:EDP_HOME = $v8 }
$cliArgs = @("-m", "edp8.cli", "start", "code", "--timeout", "$TimeoutSec")
if ($SkipExtensions) { $cliArgs += "--skip-extensions" }
& $PY @cliArgs
exit $LASTEXITCODE
