"""W14 (DESIGN-v6) — ACCEPTANCE: run-and-PROVE the four criteria END-TO-END
through the REAL pool spawn route, not a standalone harness.

The three spawn-side criteria are driven through PoolService.spawn ->
SubprocessSpawner.launch — the exact code path the live `/v1/spawn` HTTP
route calls (service.py:196). Only the un-runnable boundary is isolated: the
winpty `PtyProcess.spawn` OS-process-creation call is replaced by a fake that
CAPTURES the actual argv + env it is handed. That capture is the INDEPENDENT
read-back source — we assert against the real environment/argv the process
would have been launched with, not against a builder's return value. We never
launch a real interactive claude and NEVER touch the real claude.exe (every
binary is a fabricated npm layout under tmp_path).

The four provocations (each ACTIVELY provoked, then read back independently):
  1. Truncated claude.exe stub on the real spawn route -> auto-repair FIRES
     (stub grows on disk) and the spawn SUCCEEDS (PtyProcess.spawn is reached
     with the repaired bin), with ZERO neuron Bash — repair runs entirely
     inside the pool (pure-python shutil.copy2; pty_launcher imports no
     subprocess/shell at all).
  2. Repair sabotaged (versions-cache source removed) -> the spawn REFUSES
     with ClaudeInstallError naming the fix, and NO doomed shell is launched
     (PtyProcess.spawn is never reached; the stub is left untouched).
  3. A normal healthy spawn -> the shell's ACTUAL environment (as handed to
     process creation) carries DISABLE_AUTOUPDATER=1.
  4. `python -m edp_pool.doctor` run as a REAL subprocess against the LIVE
     stack finishes < 10s AND degrades gracefully with Phoenix :6006 down
     (phoenix = warn, overall healthy, exit 0).

Per d7 every test that touches role-scoped env clears/pins EDP_ROLE /
EDP_HANDLE so it is robust inside a spawned pytest subprocess.
"""
import json
import subprocess
import sys
import time
import types
from pathlib import Path

import httpx
import pytest

from edp_pool import pty_launcher as pl
from edp_pool.service import PoolService
from edp_pool.spawner import SubprocessSpawner

_HEALTHY = pl._MIN_HEALTHY_BIN_BYTES + 10
_STUB = 500

_LIVE_BROKER = "http://127.0.0.1:9300"
_LIVE_POOL = "http://127.0.0.1:9301"
# A port nothing listens on — a connection-refused is instant, so the
# Phoenix-down degrade path is deterministic regardless of whether a real
# Phoenix happens to be up in the ambient environment.
_DEAD_PORT_URL = "http://127.0.0.1:1"


def _make_install(root, *, bin_bytes, source_bytes=None, temp_shim=False):
    """Fabricate an npm claude-code layout under `root` (mirrors the W14
    launcher/doctor fixtures). Returns the resolved bin path (str). The real
    claude.exe is never involved."""
    adir = root / "node_modules" / "@anthropic-ai"
    binp = adir / "claude-code" / "bin" / "claude.exe"
    binp.parent.mkdir(parents=True, exist_ok=True)
    binp.write_bytes(b"\0" * bin_bytes)
    if source_bytes is not None:
        src = (adir / "claude-code" / "node_modules" / "@anthropic-ai"
               / "claude-code-win32-x64" / "claude.exe")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"\0" * source_bytes)
    if temp_shim:
        (adir / ".claude-code-ABCD1234-TEMP").mkdir(parents=True,
                                                    exist_ok=True)
    return str(binp)


class _CapturingProc:
    """Stand-in for winpty.PtyProcess — the ONLY isolated boundary. Emits a
    `❯` so PtyLaunch's readiness gate fires immediately; records writes so
    the activation is observable; stays alive until terminated."""

    def __init__(self):
        self._alive = True
        self._reads = ["booting...\n", "ready ❯ \n"]
        self.written: list[str] = []
        self.pid = 4242

    def read(self, _n):
        return self._reads.pop(0) if self._reads else ""

    def isalive(self):
        return self._alive

    def write(self, s):
        self.written.append(s)

    def terminate(self, force=False):
        self._alive = False


@pytest.fixture
def capturing_winpty(monkeypatch):
    """Install a fake `winpty` whose PtyProcess.spawn RECORDS the argv + env
    it is handed (the real process-creation boundary) and returns a live
    _CapturingProc. `calls` stays empty when the spawn is REFUSED pre-launch
    — that is how criterion 2 proves no doomed shell was started.

    Also pins the platform to win32 and clears EDP_ROLE/EDP_HANDLE (d7) so
    the spawned env is proven STAMPED by build_env, not inherited from this
    pytest subprocess."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)

    calls: list[dict] = []

    def _spawn(argv, cwd=None, dimensions=None, env=None):
        proc = _CapturingProc()
        calls.append({"argv": list(argv), "env": dict(env or {}),
                      "cwd": cwd, "proc": proc})
        return proc

    mod = types.ModuleType("winpty")
    mod.PtyProcess = types.SimpleNamespace(spawn=_spawn)
    monkeypatch.setitem(sys.modules, "winpty", mod)
    return calls


def _pool_route(claude_bin, log_dir):
    """The REAL pool spawn route object: PoolService wrapping a real
    SubprocessSpawner pinned at the fabricated bin. svc.spawn(...) is exactly
    what the /v1/spawn HTTP handler invokes (service.py:196)."""
    spawner = SubprocessSpawner(
        broker_url=_LIVE_BROKER, cwd=str(log_dir), log_dir=log_dir,
        claude_bin=claude_bin, pool_url=_LIVE_POOL,
    )
    return PoolService(spawner), spawner


# ── CRITERION 1: stub -> auto-repair fires -> spawn succeeds, zero Bash ─────
def test_c1_stub_autorepairs_on_real_spawn_route_no_neuron_bash(
        capturing_winpty, tmp_path):
    """PROVOKE: a truncated (500B) claude.exe stub with a versions-cache
    source. Drive the LIVE pool spawn route. READ BACK independently:
      - the stub file grew to healthy size on disk (repair FIRED, inside the
        pool — no external tool),
      - PtyProcess.spawn WAS reached with the repaired bin as argv[0]
        (the spawn SUCCEEDED past the gate),
      - the session is alive and the /worker activation was written.
    ZERO neuron Bash: the repair is pure-python (shutil.copy2) reached
    synchronously from svc.spawn; pty_launcher imports no subprocess/shell."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=_HEALTHY,
                         temp_shim=True)
    assert pl.claude_bin_needs_repair(binp) is True   # precondition: broken
    log_dir = tmp_path / "pool-logs"
    svc, spawner = _pool_route(binp, log_dir)

    sid = svc.spawn("worker", "recipe-x-eaa75d-s4:a_probe", parent=None,
                    mode="headless")  # this test drives the PTY route

    # spawn SUCCEEDED (a session id string, not a ToolError envelope)
    assert isinstance(sid, str), f"spawn refused unexpectedly: {sid!r}"
    # repair FIRED — independent filesystem read-back
    assert pl.claude_bin_needs_repair(binp) is False
    assert Path(binp).stat().st_size >= pl._MIN_HEALTHY_BIN_BYTES
    # no interrupted-update residue left to re-trip the guard
    adir = tmp_path / "node_modules" / "@anthropic-ai"
    assert not list(adir.glob(".claude*-TEMP"))
    # the OS-boundary was actually reached with the repaired bin
    assert len(capturing_winpty) == 1, "spawn never reached PtyProcess.spawn"
    assert capturing_winpty[0]["argv"][0] == binp
    # the shell is live and the role activation was submitted
    assert spawner.alive(sid) is True
    time.sleep(0.2)  # let the readiness-gated activation write land
    assert capturing_winpty[0]["proc"].written[:1] == ["/worker"]
    # ZERO neuron Bash, proven structurally: the launcher module never
    # imports a shell/subprocess facility — repair cannot shell out.
    src = Path(pl.__file__).read_text(encoding="utf-8")
    assert "import subprocess" not in src
    assert "os.system" not in src
    spawner.kill(sid)


# ── CRITERION 2: repair sabotaged -> refuse, no doomed shell ────────────────
def test_c2_sabotaged_repair_refuses_on_real_route_no_shell_launched(
        capturing_winpty, tmp_path):
    """PROVOKE: the same stub but with the versions-cache source REMOVED
    (repair cannot restore). Drive the LIVE pool spawn route. READ BACK:
      - it REFUSES with ClaudeInstallError naming the fix,
      - PtyProcess.spawn is NEVER reached (no doomed shell launched),
      - the stub is left untouched (refused, not half-repaired)."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=None)
    assert pl.claude_bin_needs_repair(binp) is True
    log_dir = tmp_path / "pool-logs"
    svc, _ = _pool_route(binp, log_dir)

    with pytest.raises(pl.ClaudeInstallError) as ei:
        svc.spawn("worker", "recipe-x-eaa75d-s4:a_probe2", parent=None)

    msg = str(ei.value)
    assert "python -m edp_pool.doctor" in msg        # names the fix
    assert "auto-repair failed" in msg
    assert "must NOT run Bash repair" in msg         # neuron only relays
    # NO doomed shell was launched — the OS boundary was never reached
    assert capturing_winpty == []
    # refused, not repaired: the stub is byte-for-byte unchanged
    assert Path(binp).stat().st_size == _STUB


# ── CRITERION 3: spawned shell's ACTUAL env carries DISABLE_AUTOUPDATER=1 ────
def test_c3_spawned_shell_actual_env_has_disable_autoupdater(
        capturing_winpty, tmp_path, monkeypatch):
    """PROVOKE: a normal HEALTHY spawn on the real route. READ BACK the
    ACTUAL environment handed to process creation (not build_env's return
    value): it carries DISABLE_AUTOUPDATER=1. The runner's own value is
    cleared first, so a present flag proves build_env STAMPED it, not that
    it leaked from this pytest subprocess."""
    monkeypatch.delenv("DISABLE_AUTOUPDATER", raising=False)
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)   # no repair needed
    assert pl.claude_bin_needs_repair(binp) is False
    log_dir = tmp_path / "pool-logs"
    svc, spawner = _pool_route(binp, log_dir)

    sid = svc.spawn("worker", "recipe-x-eaa75d-s4:a_probe3", parent=None,
                    mode="headless")  # PTY route: capturing_winpty sees it

    assert isinstance(sid, str)
    assert len(capturing_winpty) == 1
    launched_env = capturing_winpty[0]["env"]
    # the headline assertion: the REAL process env carries the stamp
    assert launched_env["DISABLE_AUTOUPDATER"] == "1"
    # sanity: role/handle were stamped from the spawn args (not inherited)
    assert launched_env["EDP_ROLE"] == "worker"
    assert launched_env["EDP_HANDLE"] == "recipe-x-eaa75d-s4:a_probe3"
    spawner.kill(sid)


# ── CRITERION 4: real doctor subprocess <10s + Phoenix-down graceful ────────
def _live_stack_up() -> bool:
    for url in (_LIVE_BROKER, _LIVE_POOL):
        try:
            r = httpx.get(url + "/v1/health", timeout=2.0)
            if r.status_code != 200:
                return False
        except Exception:
            return False
    return True


def test_c4_real_doctor_subprocess_under_10s_and_phoenix_down_graceful():
    """RUN-AND-PROVE: invoke `python -m edp_pool.doctor` as a REAL subprocess
    against the LIVE stack (broker:9300 + pool:9301 up). Phoenix is forced
    down via EDP_PHOENIX_URL at a dead port so the graceful-degrade is
    deterministic. READ BACK from the process's own JSON report + exit code:
      - finishes < 10s (both wall-clock and the doctor's self-timed budget),
      - broker + pool = ok, phoenix = warn (degraded, not error),
      - overall healthy, exit 0.
    A live-proof requires the live stack; if it is down that is a real
    precondition failure, not something to silently skip."""
    if not _live_stack_up():
        pytest.fail(
            "W14 acceptance criterion 4 requires the live stack (broker "
            ":9300 + pool :9301). Bring the stack up, then re-run.")

    env = {
        **_child_env(),
        "EDP_BROKER_URL": _LIVE_BROKER,
        "EDP_POOL_URL": _LIVE_POOL,
        "EDP_PHOENIX_URL": _DEAD_PORT_URL,   # force Phoenix-down deterministically
    }
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-m", "edp_pool.doctor", "--json"],
        capture_output=True, text=True, env=env, timeout=20,
    )
    wall_s = time.monotonic() - t0

    assert proc.returncode == 0, (
        f"doctor exited {proc.returncode} (expected healthy=0)\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
    report = json.loads(proc.stdout)
    by_name = {c["name"]: c for c in report["checks"]}
    # <10s on the healthy stack — both the wall clock and the self-timed run
    assert wall_s < 10.0, f"doctor took {wall_s:.2f}s wall (budget 10s)"
    assert report["elapsed_ms"] < 10_000
    # required services reachable
    assert by_name["broker"]["status"] == "ok"
    assert by_name["pool"]["status"] == "ok"
    # Phoenix down DEGRADES to warn, never error, and stays healthy overall
    assert by_name["phoenix"]["status"] == "warn"
    assert "degraded" in by_name["phoenix"]["detail"]
    assert report["ok"] is True


def _child_env() -> dict:
    """A minimal env for the doctor subprocess that still lets Python find
    the interpreter/venv (inherit the parent) but is safe to extend. Kept a
    helper so criterion 4's intent (which vars are FORCED) reads clearly."""
    import os
    return dict(os.environ)
