"""s26: a pool restart must not permanently orphan its pre-restart shells —
and the fix must never kill a recycled pid.

A pool restart destroys every in-memory PTY handle, so `spawner.knows(sid)`
goes False for every pre-restart session and `spawner.kill(sid)` silently
no-ops. `release()`/`reap()` "succeeded" while the shell kept running; d2
mandates one restart per phase, so every phase boundary stranded its shells.

The fallback kills through the process fingerprint the registry persisted at
spawn — `{pid, create_time}` — and REFUSES unless the live process's
create_time still matches the stored one. That refusal is the load-bearing
half: pids are recycled, and killing a recycled pid is the R10 catastrophe
(a blanket kill took down broker + pool mid-run on 2026-05-31). A fix that
kills by bare pid is worse than the leak it closes.

R10 discipline in this file: every process signalled here is a disposable
child THIS test spawned. Nothing else is ever touched, and no pool is
restarted — the "restart" is a fresh Spawner that does not `knows()` the sid.
"""

import sys

import psutil
import pytest

from edp_pool.proctree import kill_process_tree
from edp_pool.service import (
    PoolService,
    _proc_alive,
    _proc_fingerprint,
    _proc_kill_allowed,
)
from edp_pool.spawner import FakeSpawner

_SLEEP = "import time; time.sleep(60)"


@pytest.fixture
def child():
    """A disposable child process, stand-in for a spawned claude shell.
    Torn down by pid — never by name, never by a sweep."""
    p = psutil.Popen([sys.executable, "-c", _SLEEP])
    try:
        yield p
    finally:
        kill_process_tree(p.pid)
        psutil.wait_procs([p], timeout=5)


def _dead_child_fingerprint() -> dict:
    """Fingerprint of a process that is genuinely gone (exited, not reused)."""
    p = psutil.Popen([sys.executable, "-c", _SLEEP])
    fp = _proc_fingerprint(p.pid)
    kill_process_tree(p.pid)
    psutil.wait_procs([p], timeout=5)
    return fp


def _strand(tmp_path, role: str, handle: str, proc: dict | None):
    """Spawn a session, stamp `proc` on its row, then simulate a pool restart:
    a fresh PoolService with a FRESH spawner that has no PTY handle for it.
    No real pool is restarted."""
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    sid = svc1.spawn(role, handle, None)
    assert isinstance(sid, str)
    svc1.sessions[sid]["proc"] = proc
    svc1._persist()

    svc2 = PoolService(FakeSpawner(), state_path=state)
    assert svc2.spawner.knows(sid) is False       # the strand: no PTY handle
    assert svc2.locks[handle] == sid              # lock survived the restart
    assert svc2.sessions[sid]["state"] == "active"
    return svc2, sid


# ── (i) the leak: a stranded shell must actually be killed ─────────────────

def test_reap_kills_a_session_stranded_across_a_spawner_reset(tmp_path, child):
    """RED without the kill_process_tree fallback: `spawner.kill` no-ops on a
    session this spawner never launched, so reap returned success while the
    shell kept running."""
    svc, sid = _strand(tmp_path, "worker", "p:a1", _proc_fingerprint(child.pid))
    assert child.is_running()

    out = svc.reap("p:a1")

    assert out["reaped"] == sid
    _gone, alive = psutil.wait_procs([child], timeout=10)
    assert not alive, "the stranded shell survived reap — it was orphaned"
    assert "p:a1" not in svc.locks
    assert svc.sessions[sid]["state"] == "done"


def test_release_also_kills_a_stranded_session(tmp_path, child):
    """release() strands identically — pool_close_self runs through it."""
    svc, sid = _strand(tmp_path, "worker", "p:a2", _proc_fingerprint(child.pid))

    svc.release(sid)

    _gone, alive = psutil.wait_procs([child], timeout=10)
    assert not alive, "release() left the stranded shell running"
    assert "p:a2" not in svc.locks


def test_reap_kills_the_whole_stranded_subtree(tmp_path):
    """A shell is the root of a tree (MCP servers, rx drivers). Reaping the
    orphan must close the subtree, not just the root pid."""
    src = ("import subprocess, sys, time; "
           "subprocess.Popen([sys.executable, '-c', 'import time; "
           "time.sleep(60)']); time.sleep(60)")
    parent = psutil.Popen([sys.executable, "-c", src])
    grandchild = None
    try:
        for _ in range(50):
            kids = psutil.Process(parent.pid).children(recursive=True)
            if kids:
                grandchild = kids[0]
                break
            psutil.wait_procs([parent], timeout=0.1)
        assert grandchild is not None, "child process never spawned"

        svc, _sid = _strand(tmp_path, "worker", "p:a3",
                            _proc_fingerprint(parent.pid))
        svc.reap("p:a3")

        _gone, alive = psutil.wait_procs([parent, grandchild], timeout=10)
        assert not alive, f"subtree survivors: {[p.pid for p in alive]}"
    finally:
        kill_process_tree(parent.pid)


# ── (ii) THE LOAD-BEARING ONE: refuse to signal an unverified pid ──────────

def test_reap_refuses_when_the_stored_create_time_does_not_match(tmp_path, child):
    """RED without the fingerprint check: the fallback would kill by bare pid.

    Same live pid, WRONG stored create_time — exactly what a recycled pid
    looks like. The process at that pid is an innocent bystander (it could be
    the broker, the pool, or the user's own shell). Reap must REFUSE."""
    real = _proc_fingerprint(child.pid)["create_time"]
    impostor = {"pid": child.pid, "create_time": real + 1000.0}
    svc, sid = _strand(tmp_path, "worker", "p:a1", impostor)

    out = svc.reap("p:a1")

    assert child.is_running(), (
        "reap SIGNALLED a process whose fingerprint did not match — this is "
        "the pid-reuse catastrophe (R10), worse than the leak it closes"
    )
    assert "NOT signalled" in out["note"]
    assert "create_time mismatch" in out["note"]
    assert "pid was reused" in out["note"]
    # The lock is still released (re-dispatch must not deadlock) — but the
    # refusal is VISIBLE in the note, so a released lock is never read as
    # proof the process died.
    assert "p:a1" not in svc.locks
    assert svc.sessions[sid]["state"] == "done"


def test_reap_refuses_when_no_create_time_was_persisted(tmp_path, child):
    """Fail-closed, and STRICTER than `_proc_alive` on the very same row.

    `_proc_alive` answers "is it alive?" and may fall back to pid-only when
    create_time is missing. Authorizing a KILL must never guess. This asserts
    the asymmetry directly: liveness says True, the kill guard says no."""
    fp = {"pid": child.pid, "create_time": None}
    assert _proc_alive(fp) is True          # best-effort: the pid does exist
    svc, _sid = _strand(tmp_path, "worker", "p:a1", fp)

    out = svc.reap("p:a1")

    assert child.is_running(), "reap killed by bare pid with no create_time"
    assert "no persisted create_time" in out["note"]


def test_reap_refuses_when_no_fingerprint_was_persisted(tmp_path):
    """A legacy row (proc=None) authorizes nothing."""
    svc, _sid = _strand(tmp_path, "worker", "p:a1", None)
    out = svc.reap("p:a1")
    assert "NOT signalled" in out["note"] and "no persisted pid" in out["note"]


def test_proc_kill_allowed_is_fail_closed(child):
    """The authorization predicate, directly. Only an exact live match passes."""
    fp = _proc_fingerprint(child.pid)
    assert fp["create_time"] is not None            # psutil present

    allowed, why = _proc_kill_allowed(fp)
    assert allowed is True and "fingerprint matched" in why

    for bad, expect in [
        (None, "no persisted pid"),
        ({}, "no persisted pid"),
        ({"pid": 0, "create_time": 1.0}, "no persisted pid"),
        ({"pid": child.pid, "create_time": None}, "no persisted create_time"),
        ({"pid": child.pid, "create_time": 1.0}, "create_time mismatch"),
        ({"pid": 2_000_000_000, "create_time": 1.0}, "already gone"),
    ]:
        allowed, why = _proc_kill_allowed(bad)
        assert allowed is False, f"{bad!r} was authorized for a kill"
        assert expect in why, f"{bad!r} → {why!r}"


# ── (iii) item 3: stale rows over dead processes, every role ───────────────

def test_reconcile_sweeps_a_dead_planner_row_not_just_workers(tmp_path):
    """The old sweep lived inside the worker count, so a dead PLANNER's row
    read 'active' indefinitely and held its lock. RED without
    reconcile_sessions()."""
    svc, sid = _strand(tmp_path, "planner", "r:s1", _dead_child_fingerprint())

    assert svc.reconcile_sessions() == 1

    assert svc.sessions[sid]["state"] == "done"
    assert "r:s1" not in svc.locks


def test_a_dead_worker_row_no_longer_holds_a_concurrency_slot(tmp_path):
    svc, sid = _strand(tmp_path, "worker", "p:a1", _dead_child_fingerprint())
    assert svc.active_workers() == 0
    assert svc.sessions[sid]["state"] == "done"


def test_a_live_orphan_keeps_its_slot_and_is_never_reconciled(tmp_path, child):
    """The other half of item 3, and the dangerous one. Before the shared
    resolver, `active_workers` asked `spawner.alive(sid)` — False for EVERY
    pre-restart shell — so it reconciled a LIVE worker to 'done' and freed the
    lock its action was still executing under. RED without _session_alive."""
    svc, sid = _strand(tmp_path, "worker", "p:a1", _proc_fingerprint(child.pid))

    assert svc.reconcile_sessions() == 0
    assert svc.active_workers() == 1, "a live orphan lost its concurrency slot"
    assert svc.sessions[sid]["state"] == "active"
    assert svc.locks["p:a1"] == sid, "a live worker's lock was stolen"
    assert svc.liveness("p:a1") == "alive"
    assert child.is_running()


def test_no_new_caller_of_spawner_alive(tmp_path):
    """CLASS GUARD over SOURCE (s26/a5), the shape s25 built for guide-instructed
    verbs, pointed at the code instead.

    `spawner.alive` answers False for every session THIS spawner did not launch,
    so a restart-orphaned but LIVE shell reads "dead" through it. Exactly ONE
    call may exist — the guarded one inside `_session_alive`, which falls back
    to the persisted fingerprint. Every other liveness question must go through
    `_session_alive`.

    This exists because the defect it guards hid for a whole step behind a
    docstring that ASSERTED the property instead of pinning it. A universal
    nobody tests is a promise; this test is what makes it a fact. If you are
    adding a legitimate new call, add it to the enumeration in
    `_session_alive`'s docstring and to `_ALLOWED` here — deliberately.

    Matched on the AST, not on the source text: the first draft of this guard
    grepped for the literal `spawner.alive(` and flagged the very docstring
    that documents it. Prose that MENTIONS a call is not a call.
    """
    import ast
    from pathlib import Path

    import edp_pool.service as svc_mod

    tree = ast.parse(Path(svc_mod.__file__).read_text(encoding="utf-8"))
    _ALLOWED = {"_session_alive"}       # the one guarded fallback-aware reader

    found: list[tuple[str, int]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (isinstance(f, ast.Attribute) and f.attr == "alive"
                    and isinstance(f.value, ast.Attribute)
                    and f.value.attr == "spawner"):
                found.append((fn.name, node.lineno))

    offenders = [(name, ln) for name, ln in found if name not in _ALLOWED]
    assert not offenders, (
        "a NEW caller of self.spawner.alive() appeared in service.py — it reads "
        "'dead' for every session orphaned across a pool restart, so it will "
        "free a LIVE worker's lock. Route the liveness question through "
        f"_session_alive instead. Offenders (function, line): {offenders}")
    assert len(found) == 1, (
        f"expected exactly 1 guarded self.spawner.alive() call, found {found}")


def test_spawn_never_steals_a_live_orphans_lock(tmp_path, child):
    """s26/a5 (reviewer): the SAME defect, in the path that actually dispatches.

    `reconcile_sessions` was taught the shared resolver, but `spawn`'s stale-
    lock reap still asked `spawner.alive(holder)` — False for EVERY pre-restart
    session. So the pool would answer "alive" to `liveness()`, count the orphan
    in `active_workers()`, and in the same breath free its lock and launch a
    SECOND worker on the same action. RED without the `_session_alive` read in
    `spawn`: the lock moves to a new sid while the orphan is still running.
    """
    svc, sid = _strand(tmp_path, "worker", "p:a1", _proc_fingerprint(child.pid))
    assert svc.liveness("p:a1") == "alive" and svc.active_workers() == 1

    res = svc.spawn("worker", "p:a1", None)

    assert not isinstance(res, str), "spawn launched a second shell on p:a1"
    assert res.code == "pool_unknown_handle"
    assert "already locked" in res.message
    assert svc.locks["p:a1"] == sid, "a live worker's lock was stolen"
    assert svc.sessions[sid]["state"] == "active"
    assert child.is_running()


def test_spawn_still_reaps_an_unprovable_holders_lock(tmp_path):
    """CHARACTERIZATION, not an endorsement — the residual edge a5 did NOT
    close, pinned so the next change to `spawn` is a deliberate one.

    An UNKNOWN holder (no persisted pid) still has its lock reaped, per the
    2026-05-26 ruling this path was written under and test_pool.py's
    test_pool_state_persists_and_reloads: a lost lock is recoverable, an
    infinite wait is not. Note the asymmetry with `reconcile_sessions`, which
    REFUSES to write "done" over exactly this row. Narrow in practice — a real
    SubprocessSpawner always persists a pid, so only legacy/pid-less rows probe
    unknown — but if a live shell ever lands here, its lock is still taken."""
    svc, sid = _strand(tmp_path, "worker", "p:a1", None)
    assert svc.liveness("p:a1") == "unknown"
    assert svc.reconcile_sessions() == 0     # reconcile will NOT judge this row

    sid2 = svc.spawn("worker", "p:a1", None)

    assert isinstance(sid2, str) and sid2 != sid   # ...but spawn still reaps it
    assert svc.locks["p:a1"] == sid2


def test_unknown_liveness_is_never_reconciled_and_never_counted(tmp_path):
    """Absence of evidence of life is not evidence of death. A fingerprint-less
    row cannot be judged: it is never written to 'done' (that would be a guess)
    and never counted (a lost lock is recoverable; an infinite wait is not).
    Pins test_w11_registry.py:169."""
    svc, sid = _strand(tmp_path, "worker", "p:a1", None)

    assert svc.liveness("p:a1") == "unknown"
    assert svc.reconcile_sessions() == 0
    assert svc.sessions[sid]["state"] == "active"   # never guessed dead
    assert svc.active_workers() == 0                # never held a slot


def test_reconcile_records_but_never_signals(tmp_path, child):
    """FENCE: reconcile_sessions is a STATE WRITE, not a kill. It must never
    signal any process — including the live planner/worker rows of the very
    plan driving it. On-demand only; no timer, no thread, no reaper."""
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    live = svc1.spawn("worker", "p:live", None)
    dead = svc1.spawn("planner", "r:dead", None)
    svc1.sessions[live]["proc"] = _proc_fingerprint(child.pid)
    svc1.sessions[dead]["proc"] = _dead_child_fingerprint()
    svc1._persist()

    svc2 = PoolService(FakeSpawner(), state_path=state)
    svc2._kill_session = lambda sid: pytest.fail(
        f"reconcile_sessions signalled a process for {sid}")

    assert svc2.reconcile_sessions() == 1          # only the dead row changed

    assert svc2.sessions[dead]["state"] == "done"
    assert svc2.sessions[live]["state"] == "active"
    assert child.is_running(), "reconcile killed a live process"


def test_a_transient_probe_failure_is_unknown_not_death(tmp_path, child,
                                                        monkeypatch):
    """FENCE: a liveness probe that FAILS is not a process that DIED.
    reconcile writes 'done' over any row reported False, so an AccessDenied
    (or any non-NoSuchProcess error) must degrade to unknown."""
    svc, sid = _strand(tmp_path, "worker", "p:a1", _proc_fingerprint(child.pid))

    def _boom(self):
        raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil.Process, "create_time", _boom)

    assert svc.liveness("p:a1") == "unknown"
    assert svc.reconcile_sessions() == 0
    assert svc.sessions[sid]["state"] == "active"
