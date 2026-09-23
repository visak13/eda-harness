"""S16 (s-24f886a064): the root fleet ops script `edp.ps1`.

Static invariants of the safe-restart contract (no image kill, no tree kill, PowerShell 5.1 syntax,
UTF-8 BOM) plus `-WhatIf` runs against FAKE services: throwaway listeners on free ports whose
command line carries the service's needle, and throwaway git repos for `update`. Nothing here
touches the fleet's real board/pool/mcp — every port is overridden through the environment.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "edp.ps1"
PS = shutil.which("powershell.exe") or shutil.which("powershell")

pytestmark = pytest.mark.skipif(PS is None or sys.platform != "win32", reason="Windows PowerShell 5.1 only")

# A tiny HTTP server: answers every GET with FAKE_BODY. The trailing argv word is the service
# needle, so edp.ps1's command-line match sees this process as that service.
FAKE_SERVER = r"""
import http.server, os, sys
body = os.environ.get("FAKE_BODY", '{"status":"ready"}').encode()
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _hermetic_env(tmp_path: Path, **ports: int) -> dict[str, str]:
    env = dict(os.environ)
    env["EDP8_RUN_DIR"] = str(tmp_path / "run")  # never read the fleet's .run
    for var in ("EDP8_PORT", "EDP_BROKER_PORT", "EDP_POOL_PORT", "EDP8_MCP_PORT"):
        env[var] = str(ports.get(var) or _free_port())  # nothing listens unless a fake does
    return env


def _run(args: list[str], env: dict[str, str], script: Path = SCRIPT, repo: Path | None = None):
    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    if repo is not None:
        cmd += ["-RepoRoot", str(repo)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)


def _fake(port: int, needle: str, body: dict | list | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    if body is not None:
        env["FAKE_BODY"] = json.dumps(body)
    p = subprocess.Popen([sys.executable, "-c", FAKE_SERVER, str(port), needle], env=env)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.05)
    p.kill()
    raise RuntimeError("fake service never listened")


@pytest.fixture
def fakes():
    procs: list[subprocess.Popen] = []
    yield procs
    for p in procs:
        p.kill()


# ── static invariants ───────────────────────────────────────────────────────────────────────────

def test_script_is_bom_utf8_and_parses_under_windows_powershell_51():
    raw = SCRIPT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "PowerShell 5.1 misreads BOM-less UTF-8 (memory start-ps1-needs-utf8-bom)"
    # The 5.1 parser itself rejects PS7-only syntax (&&, ||, ??, ?:), so 0 parse errors is the proof.
    probe = (
        "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$null, [ref]$e); \"$($PSVersionTable.PSVersion.Major).$($PSVersionTable.PSVersion.Minor) $($e.Count)\""
    )
    out = subprocess.run([PS, "-NoProfile", "-Command", probe], capture_output=True, text=True, timeout=60).stdout.split()
    assert out == ["5.1", "0"]


def test_script_never_kills_by_image_or_by_tree():
    code = "\n".join(
        line.split("#", 1)[0] for line in SCRIPT.read_text(encoding="utf-8-sig").splitlines()
    )  # comments may *name* the forbidden forms; code may not use them
    assert not re.search(r"taskkill", code, re.I), "stop by Stop-Process -Id only"
    assert not re.search(r"/IM\b", code, re.I)
    assert not re.search(r"(?<![\w-])/T\b", code), "no tree kill: seat shells are pool children"
    assert not re.search(r"Stop-Process\b[^\n]*-Name", code, re.I)
    assert re.search(r"Stop-Process -Id", code)
    for form in ("&&", "||", "??"):
        assert form not in code, f"PS7-only operator {form}"


# ── -WhatIf against fake services ───────────────────────────────────────────────────────────────

def test_status_lists_every_service(tmp_path):
    r = _run(["status"], _hermetic_env(tmp_path))
    assert r.returncode == 0, r.stderr
    for svc in ("board", "broker", "pool", "mcp", "bridge", "supervisor"):
        assert re.search(rf"^{svc}\s+down\b", r.stdout, re.M), r.stdout
    assert "started_at" in r.stdout and "rev" in r.stdout


def test_restart_board_whatif_names_the_pid_and_changes_nothing(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True, "git_rev": "abc1234"}))
    env = _hermetic_env(tmp_path, EDP8_PORT=port)
    status = _run(["status"], env)
    assert re.search(r"^board\s+up\s+%d\s+\S*%d\S*\s+abc1234" % (port, fakes[0].pid), status.stdout, re.M), status.stdout

    r = _run(["restart", "board", "-WhatIf"], env)
    assert r.returncode == 0, r.stderr
    m = re.search(r"WHATIF: stop board: Stop-Process -Id ([\d,]+) -Force", r.stdout)
    assert m and str(fakes[0].pid) in m.group(1).split(","), r.stdout
    assert "WHATIF: start board: powershell -File v8\\start.ps1 -Only board" in r.stdout
    assert "-> " not in r.stdout, "a -WhatIf run must not execute any step"
    assert fakes[0].poll() is None, "the fake board must survive a -WhatIf restart"
    socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_foreign_listener_on_a_service_port_is_left_alone(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "something-else"))
    r = _run(["restart", "board", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port))
    assert "Stop-Process" not in r.stdout and "leaving it alone" in r.stderr, r.stdout + r.stderr


def test_restart_pool_lists_seats_and_refuses_without_force(tmp_path, fakes):
    port = _free_port()
    sessions = [
        {"handle": "architect.epic-x", "state": "active", "proc": {"pid": 111}},
        {"handle": "engineer.s-old", "state": "done", "proc": {"pid": 222}},
    ]
    fakes.append(_fake(port, "edp_pool.main", sessions))
    env = _hermetic_env(tmp_path, EDP_POOL_PORT=port)

    r = _run(["restart", "pool", "-WhatIf"], env)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "architect.epic-x (pid 111)" in r.stdout and "engineer.s-old" not in r.stdout
    assert "refusing to restart the pool without -Force" in r.stderr
    assert "Stop-Process" not in r.stdout

    r = _run(["restart", "pool", "-WhatIf", "-Force"], env)
    assert r.returncode == 0, r.stderr
    assert re.search(r"WHATIF: stop pool: Stop-Process -Id [\d,]*%d" % fakes[0].pid, r.stdout), r.stdout
    assert fakes[0].poll() is None

    r = _run(["stop", "all", "-WhatIf"], env)  # 'all' includes the pool, so it needs -Force too
    assert r.returncode == 3


# ── update -WhatIf against a throwaway repo ────────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def _repo_with_upstream_change(tmp_path: Path) -> Path:
    bare, work, other = tmp_path / "bare.git", tmp_path / "work", tmp_path / "other"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    for repo in (work,):
        _git(repo, "config", "user.email", "t@t"); _git(repo, "config", "user.name", "t")
    (work / "v8" / "web").mkdir(parents=True)
    (work / "v8" / "web" / "app.ts").write_text("1\n")
    (work / "edp-pool").mkdir()
    (work / "edp-pool" / "svc.py").write_text("1\n")
    _git(work, "add", "."); _git(work, "commit", "-qm", "base"); _git(work, "push", "-q", "origin", "HEAD")
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "t@t"); _git(other, "config", "user.name", "t")
    (other / "v8" / "web" / "app.ts").write_text("2\n")
    (other / "edp-pool" / "svc.py").write_text("2\n")
    _git(other, "commit", "-qam", "upstream change"); _git(other, "push", "-q", "origin", "HEAD")
    _git(work, "fetch", "-q")
    return work


def test_update_whatif_plans_pull_spa_build_and_restart_order(tmp_path):
    work = _repo_with_upstream_change(tmp_path)
    head = _git(work, "rev-parse", "HEAD")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "WHATIF: git pull --ff-only" in out
    assert "WHATIF: npm --prefix v8\\web run build (SPA)" in out
    assert "edp-pool changed; the pool is NOT restarted without -Force" in out
    assert "restart plan: supervisor(stop) -> board -> supervisor(start)" in out
    assert out.index("npm --prefix v8\\web run build") < out.index("WHATIF: start board")
    assert "-> " not in out.replace("supervisor(stop) -> board -> supervisor(start)", "")
    assert _git(work, "rev-parse", "HEAD") == head, "-WhatIf must not pull"


def test_update_refuses_a_dirty_tree_unless_forced(tmp_path):
    work = _repo_with_upstream_change(tmp_path)
    (work / "v8" / "web" / "app.ts").write_text("local edit\n")
    env = _hermetic_env(tmp_path)
    r = _run(["update", "-WhatIf"], env, repo=work)
    assert r.returncode == 2 and "refusing to update a dirty tree" in r.stderr, r.stdout + r.stderr
    r = _run(["update", "-WhatIf", "-Force"], env, repo=work)
    assert r.returncode == 0 and "WHATIF: git pull --ff-only" in r.stdout, r.stdout + r.stderr
