# Co-launch the eda-base3 stack — broker + pool + RuleSupervisor — as
# persistent services in ONE window, with tracked-PID teardown on Ctrl-C.
#
# This replaces the old three-terminal manual run-order
# (docs/design/components/integration/integration-HITL.md): the
# RuleSupervisor now comes up ALONGSIDE the broker and pool, so the event
# plane's registered rules (e.g. the 6th-sense advisory watcher) survive a
# restart instead of dying with whatever shell created them.
#
# It is a thin wrapper over `python -m edp_claude.stack_launcher`, which owns
# the real lifecycle: dependency-ordered health-gated startup, a tracked Popen
# per service, and graceful->hard teardown of ONLY those tracked PIDs on exit
# AND failure (never a name/image-wide python|node kill). Ctrl-C here stops all
# three cleanly.
#
# Usage (from the claude repo dir):
#   .\scripts\start-stack.ps1                  # broker + pool + supervisor
#   .\scripts\start-stack.ps1 --no-supervisor  # broker + pool only
#   .\scripts\start-stack.ps1 --max-runtime 30 # bring up, hold 30s, tear down
#
# All args pass through to the launcher CLI.

$ErrorActionPreference = "Stop"

# this script lives in <claude>/scripts; the launcher runs from <claude>.
$ClaudeDir = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $ClaudeDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }   # fall back to PATH python

Push-Location $ClaudeDir
try {
    & $Py -m edp_claude.stack_launcher @args
}
finally {
    Pop-Location
}
