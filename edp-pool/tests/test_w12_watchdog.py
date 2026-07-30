"""W12 — the out-of-tree auto-resume watchdog (F2).

THE DEFECT THIS EXISTS TO PREVENT, and it is the reason the token is a token
and not a timer: in a1's POC a watchdog left over from an earlier 70-second
probe reached its deadline 43 SECONDS INTO A LIVE 12-MINUTE FREEZE and silently
resumed the target — while the sampler kept printing `frozen`. The panel would
have shown a paused recipe that was burning tokens.

So the decisive test here is the NEGATIVE one: a stale watchdog, pointed at a
real suspended process, holding a runid that a later freeze has superseded,
MUST NOT RESUME IT. `test_a_stale_watchdog_cannot_resume_a_freeze_it_was_not_
armed_for` runs the watchdog's real entry point against a really-suspended
process and asserts the process is STILL FROZEN afterwards.
"""

import os
import shutil
import subprocess
import sys
import time

import psutil
import pytest

from edp_pool import proctree
from edp_pool.pause_watchdog import (
    arm,
    disarm,
    main,
    read_token,
    should_fire,
    write_token,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows suspend semantics")

_IDLE = "import time; time.sleep(120)"


@pytest.fixture
def idle_proc():
    p = subprocess.Popen([sys.executable, "-c", _IDLE])
    ct = psutil.Process(p.pid).create_time()
    try:
        yield p.pid, ct
    finally:
        try:
            psutil.Process(p.pid).resume()
        except psutil.Error:
            pass
        proctree.kill_process_tree(p.pid)


# ── the decision, as a pure function of the token ────────────────────────

def test_should_fire_is_a_function_of_the_token_only(tmp_path):
    pid = 4242
    fire, why = should_fire(tmp_path, pid, "run-A")
    assert fire is False and "gone" in why          # MISSING → stand down

    write_token(tmp_path, pid, "run-B")
    fire, why = should_fire(tmp_path, pid, "run-A")
    assert fire is False and "different freeze" in why   # SUPERSEDED

    write_token(tmp_path, pid, "run-A")
    fire, why = should_fire(tmp_path, pid, "run-A")
    assert fire is True and "still mine" in why     # MINE → the observer died


def test_disarm_never_removes_a_later_freezes_token(tmp_path):
    """Deleting another freeze's token would disarm the net under a LIVE
    freeze — the same class of harm as firing into one."""
    pid = 77
    write_token(tmp_path, pid, "run-B")
    assert disarm(tmp_path, pid, "run-A") is False
    assert read_token(tmp_path, pid) == "run-B"
    assert disarm(tmp_path, pid, "run-B") is True
    assert read_token(tmp_path, pid) is None


# ── THE MUTATION-PROOF NEGATIVE: a stale watchdog fires into nothing ──────

def test_a_stale_watchdog_cannot_resume_a_freeze_it_was_not_armed_for(
        idle_proc, tmp_path):
    """Real process. Really suspended. Real watchdog entry point. It stands
    down because the token names a LATER freeze, and the process stays frozen.

    Reintroducing the 43-second incident means making `should_fire` ignore the
    runid — do that, and this test goes RED at exactly this assertion."""
    pid, ct = idle_proc
    psutil.Process(pid).suspend()
    try:
        assert proctree.process_freeze_state(pid) == "frozen"

        # A LATER freeze took ownership of this target.
        write_token(tmp_path, pid, "the-current-freeze")

        # The stale watchdog wakes at its deadline holding the OLD runid.
        rc = main(["--token-dir", str(tmp_path), "--pid", str(pid),
                   "--create-time", repr(ct), "--runid", "a-long-dead-freeze",
                   "--deadline-epoch", repr(time.time() - 1)])

        assert rc == 0
        assert proctree.process_freeze_state(pid) == "frozen", (
            "THE STALE WATCHDOG RESUMED A LIVE FREEZE — this is the 43-second "
            "incident: the panel would report 'paused' while tokens burn")
        assert read_token(tmp_path, pid) == "the-current-freeze", (
            "and it must not have released the live freeze's token either")
    finally:
        psutil.Process(pid).resume()


def test_the_watchdog_fires_when_the_token_is_still_its_own(idle_proc, tmp_path):
    """The positive control for the test above. Same process, same entry point,
    same deadline — only the runid differs, and now it resumes."""
    pid, ct = idle_proc
    psutil.Process(pid).suspend()
    resumed = False
    try:
        write_token(tmp_path, pid, "my-freeze")
        rc = main(["--token-dir", str(tmp_path), "--pid", str(pid),
                   "--create-time", repr(ct), "--runid", "my-freeze",
                   "--deadline-epoch", repr(time.time() - 1)])
        assert rc == 0
        assert proctree.process_freeze_state(pid) == "running"
        resumed = True
        assert read_token(tmp_path, pid) is None, (
            "the token is released LAST, after the resume — but it is released")
    finally:
        if not resumed:
            psutil.Process(pid).resume()


def test_watchdog_stands_down_early_when_the_token_is_released(idle_proc, tmp_path):
    """No token at all: the freeze ended cleanly. Nothing is signalled."""
    pid, ct = idle_proc
    psutil.Process(pid).suspend()
    try:
        rc = main(["--token-dir", str(tmp_path), "--pid", str(pid),
                   "--create-time", repr(ct), "--runid", "orphan",
                   "--deadline-epoch", repr(time.time() - 1)])
        assert rc == 0
        assert proctree.process_freeze_state(pid) == "frozen"
    finally:
        psutil.Process(pid).resume()


# ── F2a: out of tree, VERIFIED — never assumed ───────────────────────────

def test_arm_refuses_a_watchdog_that_lands_inside_our_own_tree(tmp_path):
    """`DETACHED_PROCESS` is not enough: a detached child is still a DESCENDANT,
    so `kill_process_tree` and `TaskStop` take it down at exactly the moment it
    is needed. `arm` VERIFIES the launched pid is not ours — here we hand it one
    that is, and it refuses (and kills the doomed watchdog)."""
    child = subprocess.Popen([sys.executable, "-c", _IDLE])
    try:
        res = arm(token_dir=tmp_path, pid=4242, create_time=1.0,
                  runid="r1", launch_fn=lambda cmd, cwd: child.pid)
        assert res["ok"] is False
        assert res["out_of_tree"] is False
        assert "INSIDE the pool's process tree" in res["error"]
        assert not (tmp_path / "pause-4242.owner").exists()
        # it killed the watchdog it refused to trust
        for _ in range(50):
            if not psutil.pid_exists(child.pid):
                break
            time.sleep(0.1)
        assert not psutil.pid_exists(child.pid) or not psutil.Process(
            child.pid).is_running()
    finally:
        proctree.kill_process_tree(child.pid)


@pytest.mark.skipif(shutil.which("powershell") is None,
                    reason="WMI launch needs powershell")
def test_wmi_launch_really_lands_outside_this_process_tree(tmp_path):
    """The real launcher, once. WMI `Win32_Process.Create` reparents the child
    to `WmiPrvSE`, which is the whole point — a pool-child watchdog would die
    with the pool restart it exists to survive.

    Armed with a long deadline so it just sits there; we assert the parentage
    and then tear it down. (Its FIRE path is proven in-process above.)"""
    res = arm(token_dir=tmp_path, pid=os.getpid(), create_time=None,
              runid="probe", deadline_secs=300.0)
    wd = res.get("watchdog_pid")
    try:
        assert res["ok"] is True, res
        assert res["out_of_tree"] is True
        mine = {p.pid for p in psutil.Process(os.getpid()).children(recursive=True)}
        assert wd not in mine
        assert psutil.Process(wd).ppid() != os.getpid()
    finally:
        if wd:
            try:
                proctree.kill_process_tree(wd)
            except psutil.Error:
                pass
        disarm(tmp_path, os.getpid(), "probe")
