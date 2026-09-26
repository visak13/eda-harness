"""t-86f4ae3569: `edp.ps1 start|stop|restart all` includes code-server, and status names a reason for
every service that is not up (owner m-03b329ede2; m-40bcc074d1: "I started everything but it is
showing down").

-WhatIf runs prove the order (code starts LAST, stops FIRST) against a hermetic environment. The real
runs use a throwaway checkout: its venv python is a copy of this venv's launcher, and the run's cwd
holds a fake `edp8.cli` (python -m puts the cwd first on sys.path), so "heronry" answers without
touching any service; its start-code.ps1 / stop-code.ps1 are fakes that fail on request. Nothing here
touches the fleet's board/pool/mcp/code: every port is a free one.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "edp.ps1"
PS = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(PS is None or sys.platform != "win32", reason="Windows PowerShell 5.1 only")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _env(tmp_path: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["EDP8_RUN_DIR"] = str(tmp_path / "run")  # never read or write the fleet's .run
    for var in ("EDP8_PORT", "EDP_BROKER_PORT", "EDP_POOL_PORT", "EDP8_MCP_PORT", "EDP_CODE_PORT"):
        env[var] = str(_free_port())  # nothing listens
    env.update(extra)
    return env


def _run(args: list[str], env: dict[str, str], repo: Path | None = None, cwd: Path | None = None):
    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args]
    if repo is not None:
        cmd += ["-RepoRoot", str(repo)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180, cwd=cwd)


def _order(out: str, *marks: str) -> list[int]:
    idx = []
    for m in marks:
        assert m in out, f"missing {m!r} in:\n{out}"
        idx.append(out.index(m))
    return idx


# ── -WhatIf: the order ──────────────────────────────────────────────────────────────────────────

def test_start_all_whatif_starts_code_last_after_the_fleet(tmp_path):
    r = _run(["start", "all", "-WhatIf"], _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    idx = _order(r.stdout, "WHATIF: heronry start all", "WHATIF: start code on :")
    assert idx == sorted(idx), r.stdout
    assert not re.search(r"^-> ", r.stdout, re.M), "a -WhatIf run must not execute any step"


def test_stop_all_whatif_stops_code_first(tmp_path):
    r = _run(["stop", "all", "-WhatIf", "-Force"], _env(tmp_path))  # 'all' has the pool: -Force
    assert r.returncode == 0, r.stdout + r.stderr
    idx = _order(r.stdout, "WHATIF: stop code", "WHATIF: heronry stop supervisor", "WHATIF: heronry stop board")
    assert idx == sorted(idx), r.stdout
    assert not re.search(r"^-> ", r.stdout, re.M)


def test_restart_all_whatif_stops_code_first_and_starts_it_last(tmp_path):
    r = _run(["restart", "all", "-WhatIf", "-Force"], _env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    idx = _order(r.stdout, "WHATIF: stop code", "WHATIF: heronry restart board",
                 "WHATIF: heronry restart supervisor", "WHATIF: start code on :")
    assert idx == sorted(idx), r.stdout


def test_code_by_name_touches_no_other_service(tmp_path):
    for verb in ("start", "stop", "restart"):
        r = _run([verb, "code", "-WhatIf"], _env(tmp_path))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "heronry" not in r.stdout and "code" in r.stdout, r.stdout


# ── status: a reason for every service that is not up ───────────────────────────────────────────

def test_status_names_a_reason_for_every_down_service(tmp_path):
    env = _env(tmp_path)
    r = _run(["status"], env)
    assert r.returncode == 0, r.stderr
    for svc in ("board", "broker", "pool", "mcp", "supervisor"):
        assert re.search(rf"^{svc}\s+down\b.*not running: no run record", r.stdout, re.M), r.stdout
    assert re.search(r"^bridge\s+down\b.*(no Slack map|no run record)", r.stdout, re.M), r.stdout
    assert re.search(r"^code\s+down\b.*not started", r.stdout, re.M), r.stdout
    assert "Cannot find path" not in r.stdout + r.stderr, "a missing run record is a reason, not an error"


def test_status_says_code_crashed_with_its_log_path(tmp_path):
    env = _env(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (run / "code.json").write_text('{"pid": %d, "port": %s}' % (dead.pid, env["EDP_CODE_PORT"]))
    out = _run(["status"], env).stdout
    assert re.search(r"^code\s+down\b.*exited: recorded pid %d is gone" % dead.pid, out, re.M), out
    assert "code.err.log" in out, out


def test_status_says_a_failed_code_start(tmp_path):
    env = _env(tmp_path)
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "code.last-error.txt").write_text("2026-09-27T00:00:00+00:00 start failed: boom (logs kept: X.log)")
    out = _run(["status"], env).stdout
    assert re.search(r"^code\s+down\b.*start failed: boom", out, re.M), out


# ── real runs in a throwaway checkout: a code failure never hides the fleet ─────────────────────

FAKE_CLI = r"""
import os, sys
args = sys.argv[1:]
print("fake heronry " + " ".join(args))
if args[:1] == ["status"]:
    if "--json" in args:
        print("[]")
    else:
        print("board  up  1  9400")
    sys.exit(0)
sys.exit(int(os.environ.get("FAKE_HERONRY_RC", "0")))
"""

FAKE_START_CODE = r"""
if ($env:FAKE_CODE_START_FAIL) { [Console]::Error.WriteLine("start-code: download failed (fake)"); exit 4 }
Write-Host "fake start-code ok"
exit 0
"""

FAKE_STOP_CODE = r"""
if ($env:FAKE_CODE_STOP_FAIL) { [Console]::Error.WriteLine("stop-code: cannot stop (fake)"); exit 3 }
Write-Host "fake stop-code ok"
exit 0
"""


@pytest.fixture
def checkout(tmp_path):
    """(repo, cwd): repo\\v8\\.venv holds a copy of this venv's launcher; cwd holds the fake edp8.cli."""
    repo = tmp_path / "repo"
    scripts = repo / "v8" / "scripts"
    venv = repo / "v8" / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    scripts.mkdir(parents=True)
    real_venv = Path(sys.executable).resolve().parents[1]
    shutil.copy2(sys.executable, venv / "Scripts" / "python.exe")
    shutil.copy2(real_venv / "pyvenv.cfg", venv / "pyvenv.cfg")
    (scripts / "start-code.ps1").write_text("﻿" + FAKE_START_CODE, encoding="utf-8")
    (scripts / "stop-code.ps1").write_text("﻿" + FAKE_STOP_CODE, encoding="utf-8")
    cwd = tmp_path / "cwd"
    (cwd / "edp8").mkdir(parents=True)
    (cwd / "edp8" / "__init__.py").write_text("")
    (cwd / "edp8" / "cli.py").write_text(FAKE_CLI)
    return repo, cwd


def test_start_all_code_failure_is_named_and_the_fleet_result_stands(tmp_path, checkout):
    repo, cwd = checkout
    env = _env(tmp_path, FAKE_CODE_START_FAIL="1", EDP_HOME=str(repo / "v8"))
    r = _run(["start", "all", "-TimeoutSec", "5"], env, repo=repo, cwd=cwd)
    assert r.returncode == 10, r.stdout + r.stderr
    assert "fake heronry start all" in r.stdout, r.stdout
    assert "download failed (fake)" in r.stdout, "code's own failure line is shown: " + r.stdout
    assert re.search(r"only code failed to start: .*start-code\.ps1 exited 4 \(logs kept: \S+\.log", r.stderr), r.stderr
    assert "The fleet services are up" in r.stderr, r.stderr
    assert "fake heronry status" in r.stdout, "the status table is printed before the verdict: " + r.stdout
    err = (tmp_path / "run" / "code.last-error.txt").read_text()
    assert "start failed" in err and "exited 4" in err, err
    status = _run(["status"], env, repo=repo, cwd=cwd).stdout
    assert re.search(r"^code\s+down\b.*start failed: .*exited 4", status, re.M), status


def test_start_all_names_both_when_fleet_and_code_fail(tmp_path, checkout):
    repo, cwd = checkout
    env = _env(tmp_path, FAKE_CODE_START_FAIL="1", FAKE_HERONRY_RC="3", EDP_HOME=str(repo / "v8"))
    r = _run(["start", "all", "-TimeoutSec", "5"], env, repo=repo, cwd=cwd)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "heronry start all exited 3" in r.stderr and "code also failed" in r.stderr, r.stderr
    idx = _order(r.stdout, "fake heronry start all", "download failed (fake)")  # code is still attempted
    assert idx == sorted(idx), r.stdout


def test_stop_all_code_failure_does_not_stop_the_fleet_stop(tmp_path, checkout):
    repo, cwd = checkout
    env = _env(tmp_path, FAKE_CODE_STOP_FAIL="1", EDP_HOME=str(repo / "v8"))
    r = _run(["stop", "all", "-Force"], env, repo=repo, cwd=cwd)
    assert r.returncode == 10, r.stdout + r.stderr
    idx = _order(r.stdout, "cannot stop (fake)", "code       stop FAILED", "fake heronry stop supervisor", "fake heronry stop board")
    assert idx == sorted(idx), r.stdout
    assert "only code failed: it did not stop" in r.stderr and "the fleet services stopped" in r.stderr, r.stderr


def test_stop_all_clears_a_stale_code_start_error(tmp_path, checkout):
    repo, cwd = checkout
    env = _env(tmp_path, EDP_HOME=str(repo / "v8"))
    (tmp_path / "run").mkdir()
    last = tmp_path / "run" / "code.last-error.txt"
    last.write_text("old start failed")
    r = _run(["stop", "all", "-Force"], env, repo=repo, cwd=cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not last.exists(), "a clean stop clears the old start failure"
