"""S16 (s-24f886a064): the root fleet ops script `edp.ps1`, brought to the S3 contract (s-870e401942).

Since S3 the fleet services (board, broker, pool, mcp, bridge, supervisor) go through the one launcher,
`heronry` (v8\\.venv python -m edp8.cli): process identity, stop/start and the supervisor's control port
live there and are tested in test_launcher_identity.py, test_cli_launcher.py, test_control_port.py and
edp-contracts' test_proc.py. What stays edp.ps1's own is tested here: static invariants (no image kill,
no tree kill, PowerShell 5.1 syntax, UTF-8 BOM), the heronry calls it plans (-WhatIf), the pool guard,
`update` (dirty tree, ff-only model, restart order, restoring the supervisor it paused), `.env` parsing
and the tailnet verbs. Real runs use a throwaway checkout whose venv python is a copy of this venv's
launcher and whose cwd holds a fake `edp8.cli` (python -m puts the cwd first on sys.path), so "heronry"
answers without touching any service. Nothing here touches the fleet's board/pool/mcp: every port is
overridden through the environment and the seat's EDP_HOME is dropped (else a copied edp.ps1 reads the
fleet's v8\\.env).
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
    for var in ("EDP_HOME", "EDP8_HOME"):  # the -RepoRoot checkout is the home, never the seat's fleet home
        env.pop(var, None)
    for var in ("EDP8_PORT", "EDP_BROKER_PORT", "EDP_POOL_PORT", "EDP8_MCP_PORT", "EDP_CODE_PORT"):
        env[var] = str(ports.get(var) or _free_port())  # nothing listens unless a fake does
    return env


def _run(args: list[str], env: dict[str, str], script: Path = SCRIPT, repo: Path | None = None, cwd: Path | None = None):
    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    if repo is not None:
        cmd += ["-RepoRoot", str(repo)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120, cwd=cwd)


def _fake(port: int, needle: str, body: dict | list | None = None, *extra: str) -> subprocess.Popen:
    env = dict(os.environ)
    if body is not None:
        env["FAKE_BODY"] = json.dumps(body)
    p = subprocess.Popen([sys.executable, "-c", FAKE_SERVER, str(port), needle, *extra], env=env)
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
    for p in procs:  # the venv python is a launcher + interpreter pair: kill the test's own fake tree
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)


# ── a throwaway checkout whose "heronry" is a fake ──────────────────────────────────────────────

# Prints what it was asked (and the board port it sees), fails on request: FAKE_HERONRY_RC for every
# call, FAKE_FAIL="<verb> <svc>" for one call (its message on stderr, like heronry's own errors).
# `status --json` answers FAKE_STATUS_JSON, else every service down.
FAKE_CLI = r"""
import json, os, sys
args = sys.argv[1:]
said = " ".join(args)
if args[:1] == ["status"] and "--json" in args:
    rows = [{"service": s, "state": "down"} for s in ("board", "broker", "pool", "mcp", "bridge", "supervisor")]
    print(os.environ.get("FAKE_STATUS_JSON") or json.dumps(rows))
    sys.exit(0)
print("fake heronry %s port=%s" % (said, os.environ.get("EDP8_PORT")))
fail = os.environ.get("FAKE_FAIL")
if fail and said.startswith(fail):
    sys.stderr.write("fake heronry: boom-on-stderr\n")
    sys.exit(3)
sys.exit(int(os.environ.get("FAKE_HERONRY_RC", "0")))
"""


def _fake_heronry(repo: Path, cwd: Path) -> None:
    """repo\\v8\\.venv holds a copy of this venv's launcher; cwd holds the fake edp8.cli."""
    venv = repo / "v8" / ".venv"
    (venv / "Scripts").mkdir(parents=True)
    real_venv = Path(sys.executable).resolve().parents[1]
    shutil.copy2(sys.executable, venv / "Scripts" / "python.exe")
    shutil.copy2(real_venv / "pyvenv.cfg", venv / "pyvenv.cfg")
    (cwd / "edp8").mkdir(parents=True)
    (cwd / "edp8" / "__init__.py").write_text("")
    (cwd / "edp8" / "cli.py").write_text(FAKE_CLI)


def _run_piped(args: list[str], env: dict[str, str], repo: Path, cwd: Path | None = None, timeout: float = 90):
    """Like _run, but stdout/stderr are pipes read by threads and we wait on the PROCESS, so a
    descendant that inherited the pipe shows up as 'hung' instead of hanging pytest (subprocess.run's
    communicate() waits for pipe EOF even after its timeout kill)."""
    import threading

    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args, "-RepoRoot", str(repo)]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    bufs: dict[str, list[str]] = {"out": [], "err": []}
    readers = [threading.Thread(target=lambda s=s, k=k: bufs[k].extend(s), daemon=True)
               for s, k in ((p.stdout, "out"), (p.stderr, "err"))]
    for t in readers:
        t.start()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        pytest.fail("edp.ps1 did not exit (hung): " + "".join(bufs["out"]))
    for t in readers:
        t.join(5)
    if any(t.is_alive() for t in readers):
        pytest.fail("edp.ps1 exited but its stdout pipe stayed open: a started service inherited the "
                    "caller's pipe, so a caller that reads to EOF hangs (m-0c1e43e1c3)")
    return subprocess.CompletedProcess(cmd, p.returncode, "".join(bufs["out"]), "".join(bufs["err"]))


@pytest.fixture
def checkout(tmp_path):
    """(repo, cwd, env): a checkout with only v8\\ and its fake heronry."""
    repo, cwd = tmp_path / "repo", tmp_path / "cwd"
    _fake_heronry(repo, cwd)
    return repo, cwd, _hermetic_env(tmp_path)


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
    assert not re.search(r"Get-Process\s+-Name|Get-Process\s+['\"]?[a-z]", code, re.I), "never select by image"
    # the kill goes through a handle opened by pid and checked against the discovered creation time
    assert re.search(r"Get-Process -Id", code) and "$h.Kill()" in code and "StartTime - $c.CreationDate" in code
    for form in ("&&", "||", "??"):
        assert form not in code, f"PS7-only operator {form}"


def test_a_dead_supervisor_record_is_not_a_running_supervisor(tmp_path, monkeypatch):
    """qa S16 (adversary #8), now heronry's: a crashed supervisor leaves supervisor.json behind; the
    launcher checks the recorded process is alive before calling it running (else `start supervisor`
    says 'already running' and nothing supervises)."""
    from edp8 import launcher, run_state

    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path))
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    run_state.write("supervisor", pid=dead.pid, port=None, git_rev="t")
    assert (tmp_path / "supervisor.json").exists()
    assert launcher.supervisor_running() is False


def test_heronry_load_dotenv_last_line_wins_and_the_environment_beats_the_file(tmp_path, monkeypatch):
    """start.ps1's .env block moved into heronry (cli.load_dotenv): a key set twice takes the last line,
    and a value already in the real environment still beats the file."""
    from edp8 import cli

    (tmp_path / ".env").write_text("EDP8_PORT=1111\nEDP_POOL_PORT=2222\nEDP8_PORT=3333   # override\nEDP_POOL_PORT=4444\n")
    monkeypatch.setenv("EDP_HOME", str(tmp_path))
    monkeypatch.delenv("EDP8_HOME", raising=False)
    monkeypatch.delenv("EDP8_PORT", raising=False)
    monkeypatch.setenv("EDP_POOL_PORT", "5555")
    cli.load_dotenv()
    assert os.environ["EDP8_PORT"] == "3333" and os.environ["EDP_POOL_PORT"] == "5555"


# ── -WhatIf: the heronry calls edp.ps1 plans ────────────────────────────────────────────────────

def test_status_lists_every_service(tmp_path):
    r = _run(["status"], _hermetic_env(tmp_path))
    assert r.returncode == 0, r.stderr
    for svc in ("board", "broker", "pool", "mcp", "bridge", "supervisor"):
        assert re.search(rf"^{svc}\s+down\b", r.stdout, re.M), r.stdout
    assert "started_at" in r.stdout and "rev" in r.stdout


def test_restart_board_whatif_plans_one_heronry_restart_and_changes_nothing(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True, "git_rev": "abc1234"}))
    r = _run(["restart", "board", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port))
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"^WHATIF: heronry restart board\s*$", r.stdout, re.M), r.stdout
    assert "heronry restart mcp" not in r.stdout and "supervisor" not in r.stdout, "board by name touches only the board"
    assert "-> " not in r.stdout, "a -WhatIf run must not execute any step"
    assert fakes[0].poll() is None, "the fake board must survive a -WhatIf restart"
    socket.create_connection(("127.0.0.1", port), timeout=1).close()


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
    assert "heronry" not in r.stdout

    r = _run(["restart", "pool", "-WhatIf", "-Force"], env)
    assert r.returncode == 0, r.stderr
    assert re.search(r"^WHATIF: heronry restart pool --force\s*$", r.stdout, re.M), r.stdout
    assert fakes[0].poll() is None

    r = _run(["stop", "all", "-WhatIf"], env)  # 'all' includes the pool, so it needs -Force too
    assert r.returncode == 3
    r = _run(["stop", "pool", "-WhatIf", "-Force"], env)  # a pool stop keeps its seats (re-adopted)
    assert re.search(r"^WHATIF: heronry stop pool --keep-seats --force\s*$", r.stdout, re.M), r.stdout


def test_force_passes_through_to_heronry_stop_whatif(tmp_path):
    """-Force past heronry's own refusals (e.g. a service another home started) is the owner's call."""
    r = _run(["stop", "board", "-Force", "-WhatIf"], _hermetic_env(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert re.search(r"^WHATIF: heronry stop board --force\s*$", r.stdout, re.M), r.stdout


# ── update against a throwaway repo ─────────────────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


def _repo_with_upstream_change(tmp_path: Path, changes: tuple[str, ...] = ("v8/web/app.ts", "edp-pool/svc.py")) -> Path:
    bare, work, other = tmp_path / "bare.git", tmp_path / "work", tmp_path / "other"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True, capture_output=True)
    _git(work, "config", "user.email", "t@t"); _git(work, "config", "user.name", "t")
    for f in ("v8/web/app.ts", "edp-pool/svc.py", "edp-broker/svc.py"):
        (work / f).parent.mkdir(parents=True, exist_ok=True)
        (work / f).write_text("1\n")
    (work / ".gitignore").write_text(".venv/\n")  # a fake heronry's venv copy is not a dirty tree
    _git(work, "add", "."); _git(work, "commit", "-qm", "base"); _git(work, "push", "-q", "origin", "HEAD")
    subprocess.run(["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "t@t"); _git(other, "config", "user.name", "t")
    for f in changes:
        (other / f).write_text("2\n")
    _git(other, "commit", "-qam", "upstream change"); _git(other, "push", "-q", "origin", "HEAD")
    _git(work, "fetch", "-q")
    return work


def test_update_whatif_plans_pull_spa_build_and_restart_order(tmp_path):
    """The order (consult finding 9, S3): the supervisor stops first, every consumer of an environment
    stops before it changes, the SPA builds before the board starts, the supervisor starts last."""
    work = _repo_with_upstream_change(tmp_path)
    head = _git(work, "rev-parse", "HEAD")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    assert "WHATIF: git pull --ff-only" in out
    assert "edp-pool changed; the pool is NOT restarted without -Force" in out
    assert "restart plan: supervisor(stop) -> stop board -> sync/build -> start board -> supervisor(start)" in out
    marks = ["WHATIF: heronry stop supervisor", "WHATIF: heronry stop board", "WHATIF: npm --prefix v8\\web run build (SPA)",
             "WHATIF: heronry start board --no-supervisor", "WHATIF: heronry start supervisor"]
    idx = [out.index(m) if m in out else -1 for m in marks]
    assert -1 not in idx and idx == sorted(idx), out
    assert out.rindex(marks[-1]) == idx[-1], "the supervisor starts last"
    assert "heronry stop pool" not in out and "heronry start pool" not in out
    assert not re.search(r"^-> ", out, re.M), "a -WhatIf run must not execute any step"
    assert _git(work, "rev-parse", "HEAD") == head, "-WhatIf must not pull"


def test_update_whatif_models_ff_only_when_local_is_ahead_and_flags_down_services(tmp_path):
    """Upstream behind HEAD = `git pull --ff-only` is a no-op; with services down (heronry status says
    so) the re-run must fail loudly, not report "up to date" (consult finding 6)."""
    work = _repo_with_upstream_change(tmp_path)
    _fake_heronry(work, tmp_path / "cwd")
    _git(work, "pull", "-q", "--ff-only")
    (work / "local.txt").write_text("x\n")
    _git(work, "add", "local.txt"); _git(work, "commit", "-qm", "local ahead")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work, cwd=tmp_path / "cwd")
    assert "0 commit(s) to pull" in r.stdout, r.stdout
    assert r.returncode == 9 and "DOWN: board, broker, pool, mcp, supervisor" in r.stderr, r.stdout + r.stderr


def test_update_counts_untracked_files_as_dirty(tmp_path):
    work = _repo_with_upstream_change(tmp_path)
    (work / "v8" / "web" / "stray.ts").write_text("untracked\n")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work)
    assert r.returncode == 2 and "?? v8/web/stray.ts" in r.stdout, r.stdout + r.stderr


def test_update_dirty_check_ignores_status_showuntrackedfiles_config(tmp_path):
    """qa S16 (adversary #4): `git status --porcelain` honours status.showUntrackedFiles=no, which
    would hide untracked files from the dirty check; the script asks for them explicitly."""
    work = _repo_with_upstream_change(tmp_path)
    _git(work, "config", "status.showUntrackedFiles", "no")
    (work / "v8" / "web" / "stray.ts").write_text("untracked\n")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work)
    assert r.returncode == 2 and "?? v8/web/stray.ts" in r.stdout, r.stdout + r.stderr


def test_update_refuses_a_dirty_tree_unless_forced(tmp_path):
    work = _repo_with_upstream_change(tmp_path)
    (work / "v8" / "web" / "app.ts").write_text("local edit\n")
    env = _hermetic_env(tmp_path)
    r = _run(["update", "-WhatIf"], env, repo=work)
    assert r.returncode == 2 and "refusing to update a dirty tree" in r.stderr, r.stdout + r.stderr
    r = _run(["update", "-WhatIf", "-Force"], env, repo=work)
    assert r.returncode == 0 and "WHATIF: git pull --ff-only" in r.stdout, r.stdout + r.stderr


def test_failed_update_keeps_stderr_and_restores_the_supervisor_it_paused(tmp_path):
    """Architect's second live run (m-49fbff3f84): a step failed with its message on stderr and the
    supervisor the run had paused stayed down. Here heronry fails to stop the broker after the
    supervisor was paused: its stderr is shown, the supervisor is started again and only what is
    really still down is named."""
    work = _repo_with_upstream_change(tmp_path, ("edp-broker/svc.py",))
    cwd = tmp_path / "cwd"
    _fake_heronry(work, cwd)
    r = _run_piped(["update"], {**_hermetic_env(tmp_path), "FAKE_FAIL": "stop broker"}, work, cwd=cwd)
    assert r.returncode == 1, r.stdout + r.stderr
    out = r.stdout
    idx = [out.index(m) if m in out else -1 for m in
           ("fake heronry stop supervisor", "fake heronry stop broker", "restoring the supervisor", "fake heronry start supervisor")]
    assert -1 not in idx and idx == sorted(idx), out
    assert "boom-on-stderr" in out, "heronry's stderr must be shown: " + out
    assert "heronry stop broker exited 3" in r.stderr, r.stderr
    assert "STILL DOWN:" not in r.stderr or "supervisor" not in r.stderr.split("STILL DOWN:")[1], \
        "a supervisor the restore brought back is not still down: " + r.stderr


def test_unexpected_exception_still_restores_the_paused_supervisor(tmp_path):
    """qa S16 (adversary #5): restoration lived only in explicit FailDown calls; a thrown exception
    (here: `uv` is not on PATH, so `uv sync` throws after the supervisor was paused and the broker
    stopped) skipped it. A script-level trap routes every exception through FailDown.

    The reduced PATH holds no git of its own (qa m-d125eafce3: Git for Windows' mingw64 git.exe cannot
    pull without its sibling dirs on PATH): a `git.cmd` shim runs the resolved git under this process's
    full PATH, so only edp.ps1 itself, not git, misses uv."""
    git = shutil.which("git")
    if not git:
        pytest.skip("needs git (the upstream repo fixture is built with it)")
    shim = tmp_path / "gitshim"
    shim.mkdir()
    (shim / "git.cmd").write_text(f'@echo off\r\nsetlocal\r\nset "PATH={os.environ["PATH"]}"\r\n'
                                  f'"{git}" %*\r\nexit /b %ERRORLEVEL%\r\n', encoding="utf-8", newline="")
    sysroot = os.environ.get("SystemRoot") or r"C:\Windows"
    path = os.pathsep.join([str(shim), rf"{sysroot}\System32", rf"{sysroot}\System32\WindowsPowerShell\v1.0"])
    if shutil.which("uv", path=path):
        pytest.skip("needs a PATH without uv")
    work = _repo_with_upstream_change(tmp_path, ("edp-broker/svc.py",))
    cwd = tmp_path / "cwd"
    _fake_heronry(work, cwd)
    r = _run_piped(["update"], {**_hermetic_env(tmp_path), "PATH": path}, work, cwd=cwd)
    assert r.returncode == 1 and "unexpected error" in r.stderr and "uv" in r.stderr, r.stdout + r.stderr
    assert "restoring the supervisor" in r.stdout and "fake heronry start supervisor" in r.stdout, \
        "the trap must reach FailDown's restore: " + r.stdout
    assert "STILL DOWN: broker" in r.stderr, r.stderr


# ── real runs through a pipe: heronry's exit code is edp.ps1's verdict ─────────────────────────

def test_a_failed_start_is_reported_as_a_failure(tmp_path, checkout):
    """Consult finding 5: a launcher exit code != 0 is exit 4, and a run whose stdout is a pipe returns."""
    repo, cwd, env = checkout
    r = _run_piped(["start", "board"], {**env, "FAKE_HERONRY_RC": "3"}, repo, cwd=cwd)
    assert r.returncode == 4 and "heronry start board exited 3" in r.stderr, r.stdout + r.stderr
    assert "fake heronry start board --no-supervisor" in r.stdout, r.stdout
    ok = _run_piped(["start", "board"], env, repo, cwd=cwd)
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_a_failed_restart_shows_heronrys_stderr_and_exits_4(tmp_path, checkout):
    repo, cwd, env = checkout
    r = _run_piped(["restart", "board"], {**env, "FAKE_FAIL": "restart board"}, repo, cwd=cwd)
    assert r.returncode == 4 and "heronry restart board exited 3" in r.stderr, r.stdout + r.stderr
    assert "boom-on-stderr" in r.stdout, "heronry's stderr must be shown: " + r.stdout


# ── start.ps1 on a running service leaves its run_state alone (architect m-91f66a7aac) ─────────

def test_run_state_adopt_keeps_an_accurate_record_and_fixes_a_stale_one(tmp_path, monkeypatch):
    from edp8 import run_state

    monkeypatch.setenv("EDP8_RUN_DIR", str(tmp_path))
    monkeypatch.setattr(run_state, "listener_pid", lambda port: os.getpid())
    run_state.write("mcp", pid=os.getpid(), port=9402, git_rev="c9f635f")
    before = (tmp_path / "mcp.json").read_bytes()
    run_state.adopt("mcp", port=9402)
    assert (tmp_path / "mcp.json").read_bytes() == before, "an accurate record is left untouched"

    run_state.write("mcp", pid=1, port=9402, git_rev="c9f635f")  # stale pid
    rec = run_state.adopt("mcp", port=9402)
    assert rec["pid"] == os.getpid() and rec["git_rev"] == "unknown"
    import psutil
    from datetime import datetime
    own_start = datetime.fromtimestamp(psutil.Process().create_time()).astimezone().isoformat(timespec="seconds")
    assert rec["started_at"] == own_start, "started_at is the listener's real process start, not now"


# ── the home's .env (m-17c32d9ed9: an appended override was ignored silently) ──────────────────

def test_a_key_set_twice_in_env_takes_the_last_value_and_warns(tmp_path, checkout):
    repo, cwd, env = checkout
    first, last = _free_port(), _free_port()
    (repo / "v8" / ".env").write_text(f"EDP8_PORT={first}\nEDP8_OWNER=owner\nEDP8_PORT={last}   # test override\n")
    del env["EDP8_PORT"]  # the real environment wins; here only the .env decides
    r = _run(["start", "board"], env, repo=repo, cwd=cwd)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"fake heronry start board --no-supervisor port={last}" in r.stdout, r.stdout + r.stderr
    assert re.search(r"warning: .*\.env sets EDP8_PORT more than once; using the last one \(line 3\)", r.stdout), r.stdout
    assert f"port={first}" not in r.stdout and "EDP8_OWNER more than once" not in r.stdout


# ---------------------------------------------------------------- tailnet verbs (C8 s-a4fd5df319)

TAILNET_BLOCK = ("# >>> edp tailnet (written by .\\edp.ps1 tailnet apply; undo with .\\edp.ps1 tailnet remove)\r\n"
                 "EDP8_HOST=127.0.0.1\r\nEDP8_PUBLIC_URL=https://h.example.ts.net\r\nEDP8_ADMIN_TOKEN=not-a-real-one\r\n"
                 "# <<< edp tailnet\r\n")


def _tailnet_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "v8").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "edp.ps1")
    (repo / "v8" / ".env").write_bytes(("﻿# keep me\r\nEDP8_RSI=1\r\n" + TAILNET_BLOCK).encode("utf-8"))
    return repo


def test_tailnet_apply_refuses_when_the_block_is_already_there(tmp_path):
    repo = _tailnet_repo(tmp_path)
    before = (repo / "v8" / ".env").read_bytes()
    r = _run(["tailnet", "apply"], _hermetic_env(tmp_path), script=repo / "edp.ps1", repo=repo)
    assert r.returncode == 6 and "already carries the tailnet block" in r.stderr, r.stdout + r.stderr
    assert (repo / "v8" / ".env").read_bytes() == before


def test_tailnet_remove_whatif_names_the_keys_changes_nothing_and_hides_the_token(tmp_path):
    repo = _tailnet_repo(tmp_path)
    before = (repo / "v8" / ".env").read_bytes()
    r = _run(["tailnet", "remove", "-WhatIf"], _hermetic_env(tmp_path), script=repo / "edp.ps1", repo=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WHATIF: tailscale serve reset" in r.stdout
    assert "EDP8_HOST, EDP8_PUBLIC_URL, EDP8_ADMIN_TOKEN" in r.stdout
    assert "WHATIF: heronry restart board" in r.stdout and "WHATIF: heronry restart mcp" in r.stdout
    assert "not-a-real-one" not in r.stdout + r.stderr
    assert (repo / "v8" / ".env").read_bytes() == before


def test_tailnet_needs_a_subverb(tmp_path):
    r = _run(["tailnet"], _hermetic_env(tmp_path))
    assert r.returncode == 5 and "check|apply|remove" in r.stderr
