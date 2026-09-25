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
    for var in ("EDP8_PORT", "EDP_BROKER_PORT", "EDP_POOL_PORT", "EDP8_MCP_PORT", "EDP_CODE_PORT"):
        env[var] = str(ports.get(var) or _free_port())  # nothing listens unless a fake does
    return env


def _run(args: list[str], env: dict[str, str], script: Path = SCRIPT, repo: Path | None = None):
    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args]
    if repo is not None:
        cmd += ["-RepoRoot", str(repo)]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)


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


def _fake_proc(needle: str, *extra: str) -> subprocess.Popen:
    """A port-less fake (bridge/supervisor): sleeps, with the needle in its command line. An extra
    argument naming a checkout path makes the fake that checkout's own service."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)", needle, *extra])


def _record(tmp_path: Path, service: str, pid: int) -> None:
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    (run / f"{service}.json").write_text(json.dumps({"service": service, "pid": pid, "git_rev": "t"}))


@pytest.fixture
def fakes():
    procs: list[subprocess.Popen] = []
    yield procs
    for p in procs:  # the venv python is a launcher + interpreter pair: kill the test's own fake tree
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)


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


def test_start_ps1_stop_one_has_no_tree_kill():
    """The supervisor restarts through start.ps1 -Restart (Stop-One): a /T there kills every seat
    with a pool restart (consult finding 4 on c7aa5b7)."""
    src = (ROOT / "v8" / "start.ps1").read_text(encoding="utf-8-sig")
    body = src[src.index("function Stop-One"):src.index("function Restart-One")]
    code = "\n".join(line.split("#", 1)[0] for line in body.splitlines())
    assert "taskkill" in code and not re.search(r"(?<![\w-])/T\b", code)
    # qa S16 (adversary #7): inside a double-quoted string `$o.pid` expands to "@{pid=..}.pid", so the
    # supervisor's stop was a malformed taskkill that never stopped anything; the pid must be $( )-wrapped
    assert "/PID $o.pid" not in code and "/PID $_.OwningProcess" not in code, code
    assert "/PID $($o.pid)" in code and "/PID $($_.OwningProcess)" in code, code


def test_start_ps1_supervisor_record_alone_is_not_a_running_supervisor():
    """qa S16 (adversary #8): a crashed supervisor leaves supervisor.json behind; start.ps1 must check
    the recorded pid is alive before saying 'already running' (else edp.ps1 start supervisor fails 4)."""
    src = (ROOT / "v8" / "start.ps1").read_text(encoding="utf-8-sig")
    body = src[src.index("function Start-Supervisor"):src.index("function Stop-One")]
    assert re.search(r"\$st -and \(Get-Process -Id", body), body


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
    assert "WHATIF: start board on :%d: powershell -File v8\\start.ps1 -Only board" % port in r.stdout
    assert "-> " not in r.stdout, "a -WhatIf run must not execute any step"
    assert fakes[0].poll() is None, "the fake board must survive a -WhatIf restart"
    socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_foreign_listener_on_a_service_port_is_left_alone(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "something-else"))
    r = _run(["restart", "board", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port))
    assert "Stop-Process" not in r.stdout and "leaving it alone" in r.stderr, r.stdout + r.stderr


def test_a_shell_parent_that_mentions_the_service_is_not_in_the_chain(tmp_path):
    """The ancestor walk takes only launcher images (python/uv/edp8-board): the shell that started a
    service - here a powershell whose own command line names edp8-board - is never stopped."""
    port = _free_port()
    srv = tmp_path / "fake.py"
    srv.write_text(FAKE_SERVER)
    shell = subprocess.Popen([PS, "-NoProfile", "-Command", f"& '{sys.executable}' '{srv}' {port} edp8-board"])
    try:
        for _ in range(200):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.05)
        r = _run(["restart", "board", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port))
        m = re.search(r"WHATIF: stop board: Stop-Process -Id ([\d,]+) -Force", r.stdout)
        assert m, r.stdout + r.stderr
        assert str(shell.pid) not in m.group(1).split(","), "the launching shell must not join the chain"
    finally:
        subprocess.run(["taskkill", "/PID", str(shell.pid), "/T", "/F"], capture_output=True)  # the test's own tree


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
    assert "restart plan: supervisor(stop) -> stop board -> sync/build -> start board -> supervisor(start)" in out
    assert out.index("npm --prefix v8\\web run build") < out.index("WHATIF: start board")
    assert not re.search(r"^-> ", out, re.M), "a -WhatIf run must not execute any step"
    assert _git(work, "rev-parse", "HEAD") == head, "-WhatIf must not pull"


def test_update_whatif_stops_a_running_supervisor_first_and_restarts_it_last(tmp_path, fakes):
    """Consult finding 9: the order test must see a REAL supervisor process, not a plan string."""
    work = _repo_with_upstream_change(tmp_path)
    sup = _fake_proc("edp8.supervisor", str(work / "v8"))  # the throwaway checkout's own supervisor
    fakes.append(sup)
    env = _hermetic_env(tmp_path)
    _record(tmp_path, "supervisor", sup.pid)
    out = _run(["update", "-WhatIf"], env, repo=work).stdout
    stop = re.search(r"WHATIF: stop supervisor: Stop-Process -Id [\d,]*\b%d\b" % sup.pid, out)
    assert stop, out
    assert stop.start() < out.index("WHATIF: npm --prefix v8\\web run build") < out.index("WHATIF: start board")
    assert out.rindex("WHATIF: start supervisor") > out.index("WHATIF: start board")
    assert sup.poll() is None


def test_update_whatif_models_ff_only_when_local_is_ahead_and_flags_down_services(tmp_path):
    """Upstream behind HEAD = `git pull --ff-only` is a no-op; with services down (every hermetic
    port is empty) the re-run must fail loudly, not report "up to date" (consult finding 6)."""
    work = _repo_with_upstream_change(tmp_path)
    _git(work, "pull", "-q", "--ff-only")
    (work / "local.txt").write_text("x\n")
    _git(work, "add", "local.txt"); _git(work, "commit", "-qm", "local ahead")
    r = _run(["update", "-WhatIf"], _hermetic_env(tmp_path), repo=work)
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


# ── real (non -WhatIf) start/restart against a fake start.ps1 ──────────────────────────────────

FAKE_START = r"""param([string]$Only, [string]$Restart, [switch]$NoSupervisor)
if ($env:FAKE_START_EXIT) { Write-Host "fake start.ps1 failing"; exit ([int]$env:FAKE_START_EXIT) }
if ($env:FAKE_FAIL_ONLY -and $Only -eq $env:FAKE_FAIL_ONLY) {
  # like the real start.ps1's "unknown service" / missing-tool path: console stderr, then exit 5
  [Console]::Error.WriteLine("fake start.ps1: boom-on-stderr"); exit 5
}
if (-not $Only -and -not $Restart) {
  # a plain run starts the supervisor and records its pid, as the real launcher does
  $log = Join-Path $env:FAKE_LOGDIR ("sup-" + [guid]::NewGuid().ToString("N") + ".log")
  $p = Start-Process -FilePath $env:FAKE_PY -ArgumentList @($env:FAKE_SLEEP, "edp8.supervisor") -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
  New-Item -ItemType Directory -Force $env:EDP8_RUN_DIR | Out-Null
  Set-Content -Path (Join-Path $env:EDP8_RUN_DIR "supervisor.json") -Value ('{"service": "supervisor", "pid": ' + $p.Id + '}')
}
if ($Only -eq "board") {
  # exactly like the real launcher (StartProc): redirected Start-Process = CreateProcess with
  # inherited handles, so the long-lived child also holds whatever pipe this process was given
  $log = Join-Path $env:FAKE_LOGDIR ("board-" + [guid]::NewGuid().ToString("N") + ".log")
  Start-Process -FilePath $env:FAKE_PY -ArgumentList @($env:FAKE_SRV, $env:EDP8_PORT, "edp8-board") -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err"
}
Write-Host "fake start.ps1 -Only $Only done"
exit 0
"""


def _run_piped(args: list[str], env: dict[str, str], repo: Path, timeout: float = 90):
    """Like _run, but stdout/stderr are pipes read by threads and we wait on the PROCESS, so a
    descendant that inherited the pipe shows up as 'hung' instead of hanging pytest (subprocess.run's
    communicate() waits for pipe EOF even after its timeout kill)."""
    import threading

    cmd = [PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT), *args, "-RepoRoot", str(repo)]
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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


def _fake_repo(tmp_path: Path) -> tuple[Path, dict[str, str], int]:
    repo = tmp_path / "repo"
    (repo / "v8").mkdir(parents=True)
    (repo / "v8" / "start.ps1").write_text("﻿" + FAKE_START, encoding="utf-8")
    srv = repo / "fake_board.py"  # inside the checkout: its services are its own
    srv.write_text(FAKE_SERVER)
    port = _free_port()
    env = _hermetic_env(tmp_path, EDP8_PORT=port)
    sleeper = repo / "fake_sleep.py"
    sleeper.write_text("import time\ntime.sleep(600)\n")
    env.update(FAKE_PY=sys.executable, FAKE_SRV=str(srv), FAKE_SLEEP=str(sleeper), FAKE_LOGDIR=str(tmp_path),
               FAKE_BODY=json.dumps({"ok": True, "git_rev": "f00d123"}))
    return repo, env, port


def test_failed_restart_keeps_stderr_and_restores_the_supervisor_it_paused(tmp_path, fakes):
    """Architect's second live run (m-49fbff3f84): start.ps1 exited 5 with its message on console
    stderr, no log survived, and the supervisor the restart had paused stayed down."""
    repo, env, port = _fake_repo(tmp_path)
    fakes.append(_fake(port, "edp8-board", {"ok": True}, str(repo / "v8")))
    sup = _fake_proc("edp8.supervisor", str(repo / "v8"))
    fakes.append(sup)
    _record(tmp_path, "supervisor", sup.pid)
    r = _run_piped(["restart", "board", "-TimeoutSec", "10"], {**env, "FAKE_FAIL_ONLY": "board"}, repo)
    new_sup = None
    try:
        assert r.returncode == 4, r.stdout + r.stderr
        assert "boom-on-stderr" in r.stdout, "start.ps1's console stderr must be shown: " + r.stdout
        m = re.search(r"logs kept: (\S+\.log), (\S+\.err)\)", r.stderr)
        assert m and "boom-on-stderr" in Path(m.group(2)).read_text(), r.stderr
        assert "restoring the supervisor" in r.stdout, r.stdout
        rec = json.loads((tmp_path / "run" / "supervisor.json").read_text())
        new_sup = int(rec["pid"])
        assert new_sup != sup.pid and sup.poll() is not None, "the paused supervisor is replaced, not left down"
        assert re.search(r"^supervisor\s+up\s+pid \S*%d" % new_sup, r.stdout, re.M), r.stdout
        assert "STILL DOWN: board" in r.stderr and "supervisor" not in r.stderr.split("STILL DOWN:")[1], r.stderr
    finally:
        if new_sup:
            subprocess.run(["taskkill", "/PID", str(new_sup), "/T", "/F"], capture_output=True)  # the test's own fake


def test_unexpected_exception_still_restores_the_paused_supervisor(tmp_path, fakes):
    """qa S16 (adversary #5): restoration lived only in explicit FailDown calls; a thrown exception
    (here: the wrapper file cannot be written because TEMP does not exist) skipped it and left the
    supervisor this run paused down. A script-level trap now routes every exception through FailDown."""
    repo, env, port = _fake_repo(tmp_path)
    fakes.append(_fake(port, "edp8-board", {"ok": True}, str(repo / "v8")))
    sup = _fake_proc("edp8.supervisor", str(repo / "v8"))
    fakes.append(sup)
    _record(tmp_path, "supervisor", sup.pid)
    bad_tmp = tmp_path / "temp-is-a-file"   # a nonexistent TEMP gets created; a FILE cannot be a directory
    bad_tmp.write_text("not a directory")
    bad_tmp = str(bad_tmp)
    r = _run_piped(["restart", "board", "-TimeoutSec", "10"], {**env, "TEMP": bad_tmp, "TMP": bad_tmp}, repo)
    assert r.returncode == 1 and "unexpected error" in r.stderr, r.stdout + r.stderr
    assert "restoring the supervisor" in r.stdout, "the trap must reach FailDown's restore: " + r.stdout
    assert sup.poll() is not None, "the supervisor was paused (stopped) before the exception"
    assert "STILL DOWN:" in r.stderr and "supervisor" in r.stderr.split("STILL DOWN:")[1], r.stderr


def _listener_pid(port: int) -> int | None:
    out = subprocess.run([PS, "-NoProfile", "-Command",
                          f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"],
                         capture_output=True, text=True, timeout=30).stdout.strip()
    return int(out) if out else None


def test_real_restart_returns_through_a_pipe_and_replaces_the_chain(tmp_path):
    """The architect's live run hung (m-0c1e43e1c3): start.ps1's Start-Process child inherited the
    caller's stdout pipe. Here stdout IS a pipe (capture_output) and the call must return, stop the
    old chain by pid, and print the new chain with the listener marked."""
    repo, env, port = _fake_repo(tmp_path)
    env["EDP8_PORT"] = str(port)
    first = _run_piped(["start", "board", "-TimeoutSec", "20"], env, repo)
    try:
        assert first.returncode == 0, first.stdout + first.stderr
        old = _listener_pid(port)
        assert old and re.search(r"^board\s+up\s+pid \S*%d\*\s+rev f00d123" % old, first.stdout, re.M), first.stdout

        r = _run_piped(["restart", "board", "-TimeoutSec", "20"], env, repo)  # would time out (120 s) if it hung
        assert r.returncode == 0, r.stdout + r.stderr
        new = _listener_pid(port)
        assert new and new != old, (old, new)
        assert re.search(r"^board\s+stopped \(pid [\d,]*\b%d\b" % old, r.stdout, re.M), r.stdout
        assert re.search(r"^board\s+up\s+pid \S*%d\*" % new, r.stdout, re.M), r.stdout
        assert subprocess.run([PS, "-NoProfile", "-Command", f"Get-Process -Id {old} -ErrorAction SilentlyContinue"],
                              capture_output=True, text=True).stdout.strip() == ""
    finally:
        pid = _listener_pid(port)
        if pid:
            subprocess.run([PS, "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"], capture_output=True)


def test_a_failed_start_is_reported_as_a_failure(tmp_path):
    """Consult finding 5: a launcher exit code != 0, or a service that never comes up, is exit 4."""
    repo, env, port = _fake_repo(tmp_path)
    r = _run_piped(["start", "board", "-TimeoutSec", "3"], {**env, "FAKE_START_EXIT": "3"}, repo)
    assert r.returncode == 4 and "exited 3" in r.stderr and " up " not in r.stdout, r.stdout + r.stderr
    (repo / "v8" / "slack_map.json").write_text("{}")  # so the bridge is not skipped
    r = _run_piped(["start", "bridge", "-TimeoutSec", "3"], env, repo)  # launcher ok, no bridge process
    assert r.returncode == 4 and "bridge is not up" in r.stderr, r.stdout + r.stderr


def test_restart_pauses_a_running_supervisor(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True}))
    sup = _fake_proc("edp8.supervisor")
    fakes.append(sup)
    _record(tmp_path, "supervisor", sup.pid)
    out = _run(["restart", "board", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port)).stdout
    order = [out.index(s) for s in ("WHATIF: stop supervisor", "WHATIF: stop board", "WHATIF: start board", "WHATIF: start supervisor")]
    assert order == sorted(order), out


def test_update_refuses_a_dirty_tree_unless_forced(tmp_path):
    work = _repo_with_upstream_change(tmp_path)
    (work / "v8" / "web" / "app.ts").write_text("local edit\n")
    env = _hermetic_env(tmp_path)
    r = _run(["update", "-WhatIf"], env, repo=work)
    assert r.returncode == 2 and "refusing to update a dirty tree" in r.stderr, r.stdout + r.stderr
    r = _run(["update", "-WhatIf", "-Force"], env, repo=work)
    assert r.returncode == 0 and "WHATIF: git pull --ff-only" in r.stdout, r.stdout + r.stderr


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


def test_real_start_ps1_on_a_running_service_changes_no_run_state_file(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True}))
    lp = _listener_pid(port)
    run = tmp_path / "run"
    run.mkdir()
    rec = {"service": "board", "pid": lp, "port": port, "git_rev": "0ld0ld0", "started_at": "2026-09-23T04:18:28+05:30",
           "last_probe": None, "last_ok": None, "last_restart_reason": None, "restarts": 0}
    (run / "board.json").write_text(json.dumps(rec, indent=2))
    before = (run / "board.json").read_bytes()
    env = _hermetic_env(tmp_path, EDP8_PORT=port)
    env["EDP8_DATA"] = str(tmp_path / "data")  # belt and braces: nothing here may touch the fleet DB
    r = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "v8" / "start.ps1"), "-Only", "board"],
                       env=env, capture_output=True, text=True, timeout=120)
    assert "already running" in r.stdout, r.stdout + r.stderr
    assert (run / "board.json").read_bytes() == before, (run / "board.json").read_text()


# ── two checkouts on one host (m-17c32d9ed9: a clone's stop took the fleet board) ──────────────

def _checkout(tmp_path: Path, env_text: str | None = None) -> Path:
    """A second checkout: edp.ps1 only needs <root>/v8 (and its .env) to plan start/stop."""
    root = tmp_path / "other-checkout"
    (root / "v8").mkdir(parents=True)
    if env_text is not None:
        (root / "v8" / ".env").write_text(env_text)
    return root


def test_a_key_set_twice_in_env_takes_the_last_value_and_warns(tmp_path):
    first, last = _free_port(), _free_port()
    root = _checkout(tmp_path, f"EDP8_PORT={first}\nEDP8_OWNER=owner\nEDP8_PORT={last}   # test override\n")
    env = _hermetic_env(tmp_path)
    del env["EDP8_PORT"]  # the real environment wins; here only the .env decides
    r = _run(["start", "board", "-WhatIf"], env, repo=root)
    assert f"WHATIF: start board on :{last}:" in r.stdout, r.stdout + r.stderr
    assert re.search(r"warning: .*\.env sets EDP8_PORT more than once; using the last one \(line 3\)", r.stdout), r.stdout
    assert str(first) not in r.stdout and "EDP8_OWNER more than once" not in r.stdout


def test_start_ps1_parses_env_the_same_way(tmp_path):
    """start.ps1's .env block, run alone against a .env with a duplicated key: last wins, warns,
    and a value already in the real environment still beats the file."""
    text = (ROOT / "v8" / "start.ps1").read_text(encoding="utf-8-sig")
    block = text[text.index('$envFile = Join-Path $v8 ".env"'):text.index("function Env(")]
    (tmp_path / ".env").write_text("EDP8_PORT=1111\nEDP_POOL_PORT=2222\nEDP8_PORT=3333\nEDP_POOL_PORT=4444\n")
    probe = tmp_path / "probe.ps1"
    probe.write_text(f"$v8 = '{tmp_path}'\n{block}\nWrite-Host \"PORT=$env:EDP8_PORT POOL=$env:EDP_POOL_PORT\"\n",
                     encoding="utf-8-sig")
    env = {k: v for k, v in os.environ.items() if not k.startswith("EDP")}
    env["EDP_POOL_PORT"] = "5555"
    out = subprocess.run([PS, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(probe)], env=env,
                         capture_output=True, text=True, timeout=60).stdout
    assert "PORT=3333 POOL=5555" in out, out
    assert "sets EDP8_PORT more than once; using the last one (line 3)" in out, out


def test_stop_refuses_a_service_another_checkout_started_and_stops_its_own(tmp_path, fakes):
    """The fake board runs from THIS checkout's v8 venv. From a second checkout configured on the
    same port, `stop board` must refuse (exit 4, naming the foreign path) and leave it running;
    from this checkout the same stop takes it down."""
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True}))
    other = _checkout(tmp_path)
    env = _hermetic_env(tmp_path, EDP8_PORT=port)
    r = _run(["stop", "board"], env, repo=other)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "refusing to stop board" in r.stderr and "not started from this checkout" in r.stderr, r.stderr
    assert str(ROOT / "v8" / ".venv").lower() in r.stderr.lower(), r.stderr  # names the foreign path
    assert fakes[0].poll() is None
    socket.create_connection(("127.0.0.1", port), timeout=1).close()

    w = _run(["restart", "board", "-WhatIf"], env, repo=other)
    assert w.returncode == 4 and "Stop-Process" not in w.stdout, w.stdout + w.stderr

    own = _run(["stop", "board"], env)  # this checkout (the default -RepoRoot) owns it
    assert own.returncode == 0 and re.search(r"^board\s+stopped", own.stdout, re.M), own.stdout + own.stderr
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_force_stops_a_service_from_another_checkout_whatif(tmp_path, fakes):
    port = _free_port()
    fakes.append(_fake(port, "edp8-board", {"ok": True}))
    r = _run(["stop", "board", "-Force", "-WhatIf"], _hermetic_env(tmp_path, EDP8_PORT=port), repo=_checkout(tmp_path))
    assert r.returncode == 0 and "-Force: stopping board, which runs from another checkout" in r.stdout, r.stdout + r.stderr
    assert re.search(r"WHATIF: stop board: Stop-Process -Id [\d,]*%d" % fakes[0].pid, r.stdout), r.stdout
    assert fakes[0].poll() is None


def test_start_ps1_status_report_is_never_fatal():
    """Fresh-clone run (S21): `edp.ps1 start board` brought the board up, then start.ps1 exited 1
    because `edp8.cli status` wrote "down: bridge" to stderr under "Stop" with redirected streams."""
    src = (ROOT / "v8" / "start.ps1").read_text(encoding="utf-8-sig")
    body = src[src.index('Write-Host "fleet state (edp8 status):"'):]
    call = body.index("& $py -m edp8.cli status")
    assert body.rindex('$ErrorActionPreference = "Continue"', 0, call) >= 0
    assert body.index('$ErrorActionPreference = "Stop"', call) > call
