"""W12 — token-free pause via process suspension.

WHAT THESE TESTS ARE FOR, in one line each:

  F1  the verdict "frozen" comes from THREAD SUSPEND COUNTS, and would be wrong
      if it came from `psutil.status()` — so one test forces `status()` to lie
      and shows the verdict is unmoved.
  F0  the reported paused-state is MEASURED at read time. Suspend a process
      behind the pool's back and the pool reports frozen; resume it behind the
      pool's back and the pool reports running. Nothing is stored, so nothing
      can go stale.
  R10 a pid is signalled only when it still carries the create_time recorded
      for it. No create_time ⇒ refusal, not best-effort.
  F2  no freeze without a live out-of-tree watchdog.

Every process suspended here is a `python -c "time.sleep(…)"` THIS TEST
spawned. Nothing resolves a pid by image name; nothing is ever swept. Every
suspend is undone in a `finally`, and the tree is killed after.
"""

import subprocess
import sys
import time

import psutil
import pytest

from edp_pool import proctree
from edp_pool.proctree import (
    fingerprint_matches,
    observe_tree_state,
    process_freeze_state,
    resume_tree,
    suspend_tree,
    tree_pids,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="suspend/resume verification is Windows thread-level (NtSuspendProcess)",
)

_IDLE = "import time; time.sleep(120)"


def _settle_tree(pid: int, timeout: float = 5.0) -> list[int]:
    """Wait until the tree stops growing.

    `python -c …` acquires a child python.exe a beat after launch. A test that
    snapshots the tree before it settles suspends the root, watches the child
    appear, and reads `mixed` — a race that looks exactly like a real bug in the
    instrument. Settle first, and the test measures what it means to measure."""
    deadline = time.time() + timeout
    last, stable = [], 0
    while time.time() < deadline:
        now = tree_pids(pid)
        stable = stable + 1 if now == last and now else 0
        if stable >= 3:
            return now
        last = now
        time.sleep(0.15)
    return tree_pids(pid)


@pytest.fixture
def idle_proc():
    """A process that is ALIVE and doing nothing — the exact case
    `cpu_times()` deltas cannot distinguish from a frozen one."""
    p = subprocess.Popen([sys.executable, "-c", _IDLE])
    ct = psutil.Process(p.pid).create_time()
    _settle_tree(p.pid)
    try:
        yield p.pid, ct
    finally:
        for q in tree_pids(p.pid):              # never leave a frozen orphan
            try:
                psutil.Process(q).resume()
            except psutil.Error:
                pass
        proctree.kill_process_tree(p.pid)


def _ok_launch(seen):
    """A watchdog launcher that records instead of spawning. Keeps the unit
    tests off WMI; `test_w12_watchdog.py` exercises the real launch."""
    def _launch(cmdline, cwd):
        seen.append((cmdline, cwd))
        return 999_999_999          # a pid that is not ours and not alive
    return _launch


# ── F1: the instrument ───────────────────────────────────────────────────

def test_idle_process_reads_running_and_suspended_reads_frozen(idle_proc):
    """The discrimination `cpu_times()` cannot make. An idle process burns
    zero CPU exactly like a frozen one; only the thread suspend count differs."""
    pid, _ct = idle_proc
    assert process_freeze_state(pid) == "running"
    psutil.Process(pid).suspend()
    try:
        assert process_freeze_state(pid) == "frozen"
    finally:
        psutil.Process(pid).resume()
    assert process_freeze_state(pid) == "running"


def test_the_verdict_does_not_come_from_psutil_status(idle_proc, monkeypatch):
    """F1, pinned. `psutil.status()` reported `running` for 4 of 16 pids whose
    every thread was suspended, and flipped mid-freeze on the root. If the
    verdict were derived from it, this test would fail: we make `status()` lie
    in BOTH directions and the measured verdict is unmoved."""
    pid, _ct = idle_proc

    monkeypatch.setattr(psutil.Process, "status", lambda self: "stopped")
    assert process_freeze_state(pid) == "running", (
        "a lying status() must not be able to manufacture a 'frozen' verdict")

    psutil.Process(pid).suspend()
    try:
        monkeypatch.setattr(psutil.Process, "status", lambda self: "running")
        assert process_freeze_state(pid) == "frozen", (
            "a lying status() must not be able to hide a real freeze")
    finally:
        psutil.Process(pid).resume()


def test_probe_leaves_the_suspend_count_exactly_as_it_found_it(idle_proc):
    """The probe suspends to read, then resumes. Ten reads of a running process
    must not accumulate into a suspended one."""
    pid, _ct = idle_proc
    for _ in range(10):
        assert process_freeze_state(pid) == "running"
    assert psutil.Process(pid).is_running()


def test_gone_pid_reads_gone_not_running():
    assert process_freeze_state(2_000_000_000) in ("gone", "unknown")


# ── F0: measured at read time, never stored ──────────────────────────────

def _signal_all(pid, action):
    """Signal the tree as it stands RIGHT NOW — not a list captured earlier."""
    for p in tree_pids(pid):
        try:
            getattr(psutil.Process(p), action)()
        except psutil.Error:
            pass


def test_observe_tree_state_tracks_the_world_not_a_flag(idle_proc):
    """Nothing wrote a `paused` boolean anywhere in this test. The pool's answer
    changes because the WORLD changed — the suspend and the resume both happen
    behind its back, through psutil directly."""
    pid, ct = idle_proc
    assert observe_tree_state(pid, ct)["state"] == "running"

    _signal_all(pid, "suspend")
    try:
        obs = observe_tree_state(pid, ct)
        assert obs["state"] == "frozen" and obs["frozen"] is True
        assert obs["instrument"] == "thread-suspend-count"
        assert obs["measured_at"]
    finally:
        _signal_all(pid, "resume")

    obs = observe_tree_state(pid, ct)
    assert obs["state"] == "running" and obs["frozen"] is False


def test_a_partially_frozen_tree_never_reads_frozen(idle_proc):
    """A tree is `frozen` only when EVERY probeable process in it is. Freezing
    the root while a child still runs is `mixed` — the shell can still execute.

    Not hypothetical: a `claude.exe` root drags conhost, uv, bash and several
    python MCP servers along, and a1's 12-minute freeze had to suspend all 16.
    Reporting the root's state as the tree's state is how "paused" gets shown
    over a shell that is still working."""
    pid, ct = idle_proc
    pids = tree_pids(pid)
    if len(pids) < 2:
        pytest.skip("this host gave the fixture no child process to desync")

    psutil.Process(pid).suspend()          # root only
    try:
        obs = observe_tree_state(pid, ct)
        assert obs["state"] == "mixed"
        assert obs["frozen"] is False
    finally:
        psutil.Process(pid).resume()


def test_observe_refuses_a_fingerprint_mismatch(idle_proc):
    pid, ct = idle_proc
    obs = observe_tree_state(pid, ct + 500.0)
    assert obs["fingerprint_ok"] is False
    assert obs["frozen"] is None and obs["state"] == "unknown"


# ── R10: the fingerprint gate ────────────────────────────────────────────

def test_fingerprint_refuses_without_a_recorded_create_time(idle_proc):
    pid, ct = idle_proc
    ok, why = fingerprint_matches(pid, None)
    assert not ok and "create_time" in why
    ok, why = fingerprint_matches(pid, ct + 999.0)
    assert not ok and "reused" in why
    assert fingerprint_matches(pid, ct)[0] is True


def test_suspend_refuses_a_pid_it_cannot_fingerprint(idle_proc):
    """The 2026-06-02 guard, at the suspend seam: no create_time, no signal."""
    pid, _ct = idle_proc
    res = suspend_tree(pid, None, token_dir=None, arm_watchdog=False)
    assert res["ok"] is False and "create_time" in res["refused"]
    assert process_freeze_state(pid) == "running"   # untouched


# ── F2: no freeze without a watchdog ─────────────────────────────────────

def test_suspend_refuses_entirely_when_the_watchdog_will_not_launch(
        idle_proc, tmp_path):
    """An unresumable freeze holds the shell's pool lock forever and R5 forbids
    force-failing it. So a watchdog that will not launch REFUSES THE SUSPEND —
    it does not degrade to an unwatched freeze."""
    pid, ct = idle_proc

    def _boom(cmdline, cwd):
        raise OSError("WMI unavailable")

    res = suspend_tree(pid, ct, token_dir=tmp_path, launch_fn=_boom)
    assert res["ok"] is False
    assert "watchdog" in res["refused"]
    assert process_freeze_state(pid) == "running", "must not freeze unwatched"
    assert not list(tmp_path.glob("*.owner")), "token must not outlive the refusal"


def test_suspend_then_resume_roundtrip(idle_proc, tmp_path):
    pid, ct = idle_proc
    seen = []
    res = suspend_tree(pid, ct, token_dir=tmp_path, launch_fn=_ok_launch(seen))
    try:
        assert res["ok"] is True and res["observed"]["state"] == "frozen"
        assert seen, "the watchdog must be armed before the freeze"
        assert (tmp_path / f"pause-{pid}.owner").exists()
        # measured independently of suspend_tree's own return value
        assert process_freeze_state(pid) == "frozen"
    finally:
        out = resume_tree(pid, ct, token_dir=tmp_path, runid=res["runid"])

    assert out["ok"] is True and out["observed"]["state"] == "running"
    assert out["token_released"] is True
    assert not (tmp_path / f"pause-{pid}.owner").exists(), (
        "the run token is released LAST — after the resume — but it IS released")


def test_suspend_is_idempotent_and_arms_no_second_watchdog(idle_proc, tmp_path):
    pid, ct = idle_proc
    seen = []
    first = suspend_tree(pid, ct, token_dir=tmp_path, launch_fn=_ok_launch(seen))
    try:
        again = suspend_tree(pid, ct, token_dir=tmp_path,
                             launch_fn=_ok_launch(seen))
        assert again["ok"] is True and again["idempotent"] is True
        assert len(seen) == 1, "a second watchdog would race the first"
    finally:
        resume_tree(pid, ct, token_dir=tmp_path, runid=first["runid"])


def test_an_already_frozen_but_UNWATCHED_tree_is_adopted_not_blessed(
        idle_proc, tmp_path):
    """IDEMPOTENCE IS WHERE SAFETY INVARIANTS GO TO DIE.

    A tree frozen out-of-band (an earlier pool process, a crashed observer, a
    human with a debugger) has NO run token and nothing watching it. The
    "already frozen → return ok, nothing to do" branch would report it as paused
    while no watchdog exists to ever resume it — the unresumable freeze that
    holds the shell's pool lock forever, reached through the one path written to
    be a harmless no-op.

    This is F0 one altitude up: a no-op that REPORTS SUCCESS is a stored
    boolean. The observed fact is "is there a watchdog under this freeze", and
    the code has to look."""
    pid, ct = idle_proc
    _signal_all(pid, "suspend")               # frozen by someone else entirely
    try:
        assert not (tmp_path / f"pause-{pid}.owner").exists()
        seen = []
        res = suspend_tree(pid, ct, token_dir=tmp_path,
                           launch_fn=_ok_launch(seen))
        assert res["ok"] is True and res["adopted"] is True
        assert len(seen) == 1, "an orphaned freeze must acquire a watchdog"
        assert (tmp_path / f"pause-{pid}.owner").read_text() == res["runid"]
    finally:
        _signal_all(pid, "resume")


def test_an_orphaned_freeze_that_cannot_be_watched_is_refused_not_reported_ok(
        idle_proc, tmp_path):
    """And if we cannot arm a watchdog for it, we say so. We do not return ok
    into an unwatched freeze, and we do not silently undo a freeze we did not
    create."""
    pid, ct = idle_proc
    _signal_all(pid, "suspend")
    try:
        def _boom(cmdline, cwd):
            raise OSError("WMI unavailable")

        res = suspend_tree(pid, ct, token_dir=tmp_path, launch_fn=_boom)
        assert res["ok"] is False
        assert "ALREADY FROZEN AND UNWATCHED" in res["refused"]
        assert res["observed"]["state"] == "frozen"   # reported honestly
    finally:
        _signal_all(pid, "resume")


def test_resume_of_a_running_process_is_a_safe_noop(idle_proc, tmp_path):
    """Firing late is always safe; refusing to fire is not. This is the property
    that licenses the watchdog to fire on a freeze that already ended."""
    pid, ct = idle_proc
    out = resume_tree(pid, ct, token_dir=tmp_path)
    assert out["ok"] is True and out["observed"]["state"] == "running"
    assert psutil.Process(pid).is_running()


def test_a_freeze_that_does_not_verify_is_rolled_back(idle_proc, tmp_path,
                                                      monkeypatch):
    """We never return 'paused' on faith. If the post-condition does not measure
    as frozen, the suspension is undone and the token released — a partially
    frozen shell is the worst state to leave behind."""
    pid, ct = idle_proc
    monkeypatch.setattr(proctree, "_signal_tree", lambda pids, action: [])
    seen = []
    res = suspend_tree(pid, ct, token_dir=tmp_path, launch_fn=_ok_launch(seen))
    assert res["ok"] is False and "rolled back" in res["refused"]
    assert not (tmp_path / f"pause-{pid}.owner").exists()
    assert process_freeze_state(pid) == "running"


# ── a1 §6.3: the freeze must be legible AT THE SHELL ─────────────────────

def test_the_pause_marks_and_restores_a_real_console_window_title(tmp_path):
    """The user force-closed a1's fixture because a suspended monitor-mode shell
    looks EXACTLY like a hung one. The pool writes its own child's window title
    from outside — no code enters the Claude Code shell, no in-shell affordance.

    Uses a real `CREATE_NEW_CONSOLE` process, which is what `ConsoleLaunch`
    creates for a monitor-mode shell. Also pins the ORDER: the title is written
    before the freeze, because `WM_SETTEXT` to a suspended window blocks (probed:
    >6 s, no return) — marking after the suspend would hang the pool."""
    import ctypes

    from edp_pool.proctree import _tree_windows

    proc = subprocess.Popen(["cmd.exe", "/c", "ping -n 30 127.0.0.1 >nul"],
                            creationflags=subprocess.CREATE_NEW_CONSOLE)
    u32 = ctypes.WinDLL("user32")

    def title(h):
        b = ctypes.create_unicode_buffer(512)
        u32.GetWindowTextW(ctypes.c_void_p(h), b, 512)
        return b.value

    try:
        _settle_tree(proc.pid)
        ct = psutil.Process(proc.pid).create_time()
        wins = _tree_windows(tree_pids(proc.pid))
        if not wins:
            pytest.skip("no visible console window on this host")
        # the invisible MSCTFIME UI / Default IME helper windows are filtered out
        assert len(wins) == 1, [title(h) for h, _ in wins]
        hwnd = wins[0][0]
        original = title(hwnd)

        seen = []
        res = suspend_tree(proc.pid, ct, token_dir=tmp_path,
                           launch_fn=_ok_launch(seen))
        try:
            assert res["ok"] is True
            assert res["window_title"]["marked"] == 1
            assert title(hwnd).startswith("[EDP PAUSED] ")
        finally:
            out = resume_tree(proc.pid, ct, token_dir=tmp_path,
                              runid=res.get("runid"))
        assert out["ok"] is True
        assert title(hwnd) == original, "the title must be restored exactly"
    finally:
        for q in tree_pids(proc.pid):
            try:
                psutil.Process(q).resume()
            except psutil.Error:
                pass
        proctree.kill_process_tree(proc.pid)


def test_a_headless_tree_reports_an_honest_absence_of_a_window(idle_proc):
    """A ConPTY shell has no window. The pool says so; it does not pretend to
    have marked one."""
    pid, _ct = idle_proc
    out = proctree.mark_window_title(pid, tree_pids(pid))
    assert out["marked"] == 0
    assert "no visible window" in out["reason"]


def test_tree_pids_snapshots_root_first():
    parent = subprocess.Popen([sys.executable, "-c", (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "time.sleep(30)")])
    try:
        for _ in range(50):
            pids = tree_pids(parent.pid)
            if len(pids) >= 2:
                break
            time.sleep(0.1)
        assert pids[0] == parent.pid and len(pids) >= 2
    finally:
        proctree.kill_process_tree(parent.pid)
