"""s26 item 1 (pool half) — close-on-terminal-status.

The claude half (edp-claude/tests/test_s26_shell_lifecycle.py) proves that a
worker which ends its turn with a report ARMS its own reap. This half proves the
pool actually REAPS it — including, in the last test, a REAL OS process that is
killed with no human intervention.

Why the split: `edp_pool` is not importable from the claude venv, and each half
is tested where it lives.

R10 SAFETY. Every process signalled here is a disposable child THIS TEST
spawned. Nothing scans, nothing enumerates, nothing kills by name or by
"missing pool row" — the neuron's foreground shell and the user's terminal are
also claude.exe with no pool row, and a heuristic like that would kill them.
The kill path is `release` → `_kill_session` → `_proc_kill_allowed`, fail-closed
on a pid+create_time mismatch.
"""
import asyncio
import subprocess
import sys
import time

import pytest
from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


async def test_arming_an_idle_session_reaps_it_without_human_intervention(svc):
    """THE REPRODUCTION. The worker reported a terminal status and ended its
    turn — it never called pool_close_self. The pool reaps it anyway."""
    sid = svc.spawn("worker", "p:a1", None)
    assert svc.sessions[sid]["state"] == "active"

    res = svc.arm_close_when_idle(sid, idle_secs=0.05,
                                  reason="action a1 reached 'done'")
    assert res["armed"] is True
    await asyncio.sleep(0.25)   # let the one-shot timer fire

    assert svc.sessions[sid]["state"] == "done", (
        "a shell whose action reached a terminal status idled forever — this "
        "is the leak: it holds RAM until a human closes it")
    assert "p:a1" not in svc.locks, "the action lock was never released"


async def test_a_shell_that_closes_itself_first_is_a_noop(svc):
    """The healthy path (a1/a2/a3 took it) must not double-reap. `release` is
    idempotent, and the timer finds the session already gone."""
    sid = svc.spawn("worker", "p:a1", None)
    svc.arm_close_when_idle(sid, idle_secs=0.05)
    svc.release(sid)                     # the well-behaved worker closes itself
    await asyncio.sleep(0.25)
    assert svc.sessions[sid]["state"] == "done"


async def test_a_busy_shell_is_rechecked_never_killed_mid_flush(svc):
    """IDLE IS A SECOND GATE, NOT THE TRIGGER. A worker that reports and THEN
    runs its close sequence (CronDelete → stop Monitor → pool_close_self) is
    busy, not leaked. R5: silence != death, and output != leak.

    Here the shell keeps emitting output for the whole window, so every check
    re-arms and it is never signalled.
    """
    sid = svc.spawn("worker", "p:a1", None)
    svc.arm_close_when_idle(sid, idle_secs=0.05, max_checks=2)
    for _ in range(8):                   # keep the drain log growing
        svc.spawner.set_output_ts(sid, time.time())
        await asyncio.sleep(0.03)

    assert svc.sessions[sid]["state"] == "active", (
        "a shell still producing output was reaped mid-flush")


async def test_a_shell_that_falls_idle_after_being_busy_is_reaped(svc):
    """...and once the output stops, the re-check reaps it. Otherwise the busy
    guard above would be an escape hatch that never closes."""
    sid = svc.spawn("worker", "p:a1", None)
    svc.spawner.set_output_ts(sid, time.time())
    svc.arm_close_when_idle(sid, idle_secs=0.05, max_checks=5)
    await asyncio.sleep(0.5)             # no further output → falls idle
    assert svc.sessions[sid]["state"] == "done"


async def test_arming_an_unknown_or_released_session_is_not_an_error(svc):
    """`armed=False` is the HEALTHY answer, not a failure: the shell is already
    gone. A terminal status must never fail because the reap could not be armed.
    """
    assert svc.arm_close_when_idle("no-such-session")["armed"] is False
    sid = svc.spawn("worker", "p:a1", None)
    svc.release(sid)
    assert svc.arm_close_when_idle(sid)["armed"] is False


async def test_arming_is_idempotent(svc):
    sid = svc.spawn("worker", "p:a1", None)
    assert svc.arm_close_when_idle(sid, idle_secs=5)["armed"] is True
    assert svc.arm_close_when_idle(sid, idle_secs=5)["reason"] == "already armed"
    assert len(svc._close_timers) == 1


async def test_a_real_child_process_is_actually_killed(svc):
    """THE END-TO-END PROOF, against a real OS process rather than a fake.

    A worker shell that reports and stops is, to the OS, a live process sitting
    at a prompt. This spawns a disposable child that sleeps (the idling shell),
    registers it in the pool the way a spawn does, arms the reap, and asserts
    the process is GONE — with nothing but the terminal status to trigger it.

    R10: the only pid signalled is this child's, matched by pid+create_time.
    """
    import psutil

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # A pool restart destroys PTY handles, so `release` falls back to the
        # persisted fingerprint — the same path an orphaned shell takes. Use it,
        # because it is the one gated by _proc_kill_allowed.
        sid = "sess-real-child"
        svc.sessions[sid] = {
            "state": "active", "handle": "p:a1", "role": "worker",
            "proc": {"pid": proc.pid,
                     "create_time": psutil.Process(proc.pid).create_time()},
        }
        svc.locks["p:a1"] = sid
        assert proc.poll() is None, "child died before the test began"

        svc.arm_close_when_idle(sid, idle_secs=0.05, reason="terminal status")
        await asyncio.sleep(0.4)

        assert svc.sessions[sid]["state"] == "done"
        proc.wait(timeout=5)             # raises TimeoutExpired if still alive
        assert proc.poll() is not None, "the leaked shell was never killed"
    finally:
        if proc.poll() is None:          # teardown own pid on failure (R10)
            proc.kill()
            proc.wait(timeout=5)


async def test_a_session_with_no_fingerprint_is_refused_not_guessed(svc, monkeypatch):
    """FAIL-CLOSED. `_proc_kill_allowed` refuses without a stored create_time —
    pids are recycled, and killing a recycled pid is how a blanket kill took
    down the broker and the pool (2026-05-31). The arm must not weaken that.

    Asserting only that the session flips to `done` would prove BOOKKEEPING, not
    restraint: `release` marks the row done either way. So spy on the actual
    kill syscall and assert it is NEVER reached.
    """
    from edp_pool import proctree
    signalled: list[int] = []
    monkeypatch.setattr(proctree, "kill_process_tree",
                        lambda pid, *a, **k: signalled.append(pid))

    sid = "sess-no-fingerprint"
    svc.sessions[sid] = {"state": "active", "handle": "p:a1", "role": "worker",
                         "proc": {"pid": 999999}}     # no create_time
    svc.locks["p:a1"] = sid
    svc.arm_close_when_idle(sid, idle_secs=0.05)
    await asyncio.sleep(0.25)

    assert signalled == [], (
        "a pid with no stored create_time was SIGNALLED — pid reuse means this "
        "can kill an unrelated process, e.g. the user's own terminal")
    # The bookkeeping still releases the lock; nothing was signalled.
    assert svc.sessions[sid]["state"] == "done"


async def test_a_failing_reap_task_is_logged_not_swallowed(svc, monkeypatch):
    """asyncio only surfaces a task exception when the task is GC'd, as "Task
    exception was never retrieved". A bare pop in the done-callback would hide a
    broken reap behind a successful arm — the leak this mechanism closes,
    reintroduced one level down. (This is not hypothetical: the first draft of
    `_close_when_idle` raised TypeError on a logging call and silently never
    reaped. The suite caught it only because the reap was asserted, not the arm.)
    """
    errors: list[tuple] = []
    from edp_pool import service as service_mod
    monkeypatch.setattr(service_mod._log, "error",
                        lambda kind, detail, **f: errors.append((kind, f)))
    monkeypatch.setattr(
        svc, "release",
        lambda _sid: (_ for _ in ()).throw(RuntimeError("boom")))

    sid = svc.spawn("worker", "p:a1", None)
    svc.arm_close_when_idle(sid, idle_secs=0.05)
    await asyncio.sleep(0.25)

    assert errors and errors[0][0] == "close_when_idle_failed", (
        "a reap task died silently; the arm still reported success")


def test_the_endpoint_arms(client_and_spawner=None):
    """The HTTP surface the claude MCP calls."""
    from edp_pool.service import create_app
    from fastapi.testclient import TestClient

    spawner = FakeSpawner()
    app = create_app(spawner)
    with TestClient(app) as client:
        sid = client.post("/v1/spawn",
                          json={"role": "worker", "handle": "p:a1"}).json()[
                              "session_id"]
        r = client.post(f"/v1/close_when_idle/{sid}",
                        json={"idle_secs": 30, "reason": "done"})
        assert r.status_code == 200
        assert r.json()["armed"] is True
        assert r.json()["session_id"] == sid
