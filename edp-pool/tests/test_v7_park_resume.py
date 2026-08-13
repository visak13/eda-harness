"""DESIGN-v7 1.5.2-1.5.4 — park / fork-resume, pool half.

OPERATOR RULING 2026-07-25 RESTRUCTURED THIS FILE. Park previously KILLED the
shell and these tests pinned that. It no longer does:

    `CronCreate` (the heartbeat) and `Monitor` (the rx subscription reader)
    are CLAUDE CODE TOOLS THAT LIVE INSIDE A SESSION. The framework cannot
    re-arm them. Killing the shell destroys both permanently from the
    framework's side — the observe() subscription survives server-side and
    NOBODY IS LISTENING TO IT.

So a parked shell is now an ALIVE process with a row marked `parked`: the lock
stays held (no cold spawn can steal the handle), the claude_session_id stays on
the row, and a broker-inbox watermark records where it stopped consuming.
`parked` remains a third liveness answer — not active (no capacity slot, the
FSM must not treat it as terminal) and not dead (reconcile must not reap it).

WHAT THAT CHANGES FOR RESUME, and it is the main structural point of this file:
resume no longer forks a parked shell that is still alive — it restores the row
to `active` and returns a no-op, because the shell kept its own cron and
subscriptions and needs no reconstruction. Forking one would put a SECOND shell
on the handle: two heartbeats, two monitors, two dispatchers.

FORK-RESUME IS THEREFORE THE CRASH PATH ONLY. Tests that exercise forking must
park AND THEN KILL — see `_parked_planner(crash=True)`.

Broker access is faked by monkeypatching `svc._inbox_depth` — the pool half
needs the WATERMARK ARITHMETIC proven, not HTTP plumbing (one sync GET).
"""

import asyncio
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from edp_pool.resume_watchdog import ResumeWatchdog
from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


@pytest.fixture
def svc():
    return PoolService(FakeSpawner())


def _parked_planner(svc, monkeypatch, *, depth=7, crash=False,
                    handle="rec-x:s1", claude_session="base-uuid-1"):
    """Spawn a planner and park it with a faked broker inbox depth.

    The shell is LEFT ALIVE, which is the ruling — park is a state
    transition, not a teardown.

    `crash=True` additionally kills the shell AFTER parking, simulating a
    parked shell that died on its own. That is the ONLY situation in which
    fork-resume is now the correct act, so every fork test uses it.
    """
    sid = svc.spawn("planner", handle, None, claude_session=claude_session)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: depth)
    out = svc.park_session(sid, flush_timeout=0.05, flush_quiesce=0.01)
    assert out["parked"] is True
    assert svc.spawner.alive(sid) is True, (
        "park must LEAVE THE SHELL ALIVE — killing it destroys the in-session "
        "cron and Monitor tools, which the framework cannot re-arm")
    if crash:
        svc._kill_session(sid)
        assert svc.spawner.alive(sid) is not True
    return sid


# ── park semantics ─────────────────────────────────────────────────────────

def test_park_keeps_lock_watermark_and_resume_token(svc, monkeypatch):
    sid = _parked_planner(svc, monkeypatch, depth=7)
    row = svc.sessions[sid]
    assert row["state"] == "parked"
    assert svc.locks["rec-x:s1"] == sid, (
        "the handle lock must KEEP pointing at the parked row — releasing "
        "it would let a concurrent cold spawn double-dispatch the step")
    assert row["parked"]["inbox_watermark"] == 7
    assert row["parked"]["parked_at"]
    assert row["claude_session_id"] == "base-uuid-1"   # the resume token
    assert svc.spawner.alive(sid) is True, (
        "OPERATOR RULING 2026-07-25: the parked process must be LEFT ALIVE. "
        "This assertion was previously its exact inverse. Cron and Monitor "
        "are in-session Claude tools; the framework cannot re-arm them, so "
        "killing the shell strands the role with a live subscription nobody "
        "is listening to.")


def test_park_with_broker_down_stores_none_watermark(svc, monkeypatch):
    # fail-open: broker unobservable at park time must not block the park.
    sid = _parked_planner(svc, monkeypatch, depth=None)
    assert svc.sessions[sid]["state"] == "parked"
    assert svc.sessions[sid]["parked"]["inbox_watermark"] is None


def test_park_of_a_non_active_session_is_refused_not_raised(svc):
    assert svc.park_session("no-such")["parked"] is False
    sid = svc.spawn("worker", "p:a1", None)
    svc.release(sid)
    out = svc.park_session(sid)
    assert out["parked"] is False and "not active" in out["reason"]


def test_park_by_handle_and_release_park_flag(svc, monkeypatch):
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    sid = svc.spawn("planner", "rec-x:s1", None, claude_session="c1")
    out = svc.park("rec-x:s1", flush_timeout=0.05, flush_quiesce=0.01)
    assert out["parked"] is True and out["session_id"] == sid
    assert svc.park("never:held")["parked"] is False
    # release(park=True) is the close-path spelling of the same act. No
    # claude_session here → the flush-wait short-circuits (nothing to await),
    # keeping the test off the 20s default window.
    sid2 = svc.spawn("planner", "rec-y:s1", None)
    svc.release(sid2, park=True)
    assert svc.sessions[sid2]["state"] == "parked"


# ── parked is neither alive nor dead ──────────────────────────────────────

def test_parked_rows_are_not_reaped_by_reconcile(svc, monkeypatch):
    sid = _parked_planner(svc, monkeypatch)
    changed = svc.reconcile_sessions()
    assert changed == 0
    assert svc.sessions[sid]["state"] == "parked", (
        "reconcile wrote over a parked row — a parked process is dead BY "
        "DESIGN; 'done' here would strand the plan's resume token")
    assert svc.locks["rec-x:s1"] == sid


def test_parked_rows_do_not_count_toward_capacity(svc, monkeypatch):
    # fill the planner cap, park one → a new planner spawns in its place.
    for i in range(4):
        svc.spawn("planner", f"rec-{i}:s1", None, claude_session=f"c{i}")
    assert not isinstance(svc.spawn("planner", "rec-4:s1", None), str)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    svc.park_session(svc.locks["rec-0:s1"],
                     flush_timeout=0.05, flush_quiesce=0.01)
    assert svc._active_count("planner") == 3
    assert isinstance(svc.spawn("planner", "rec-4:s1", None), str)


def test_liveness_reports_parked_by_name(svc, monkeypatch):
    _parked_planner(svc, monkeypatch)
    assert svc.liveness("rec-x:s1") == "parked", (
        "'dead' trips the FSM's crash-recovery reincarnation; 'alive' makes "
        "it wait on a shell that cannot answer — parked is its own answer")


def test_cold_spawn_on_a_parked_handle_is_refused_naming_resume(svc,
                                                                monkeypatch):
    _parked_planner(svc, monkeypatch)
    res = svc.spawn("planner", "rec-x:s1", None)
    assert not isinstance(res, str)
    assert "parked" in res.message and "resume" in res.message


# ── resume: fork-resume, double-caller no-op, fail-open fallback ──────────

def test_resume_of_a_LIVE_parked_shell_restores_it_without_forking(
        svc, monkeypatch):
    """The ruling's central consequence. A parked shell that is still alive
    kept its own heartbeat and subscriptions, so there is nothing to
    reconstruct — forking would put a SECOND shell on the handle."""
    sid = _parked_planner(svc, monkeypatch)
    launches_before = len(svc.spawner.launched)

    out = svc.resume("rec-x:s1")

    assert out["resumed"] is False and out["no_op"] is True
    assert out["shell_alive"] is True
    assert len(svc.spawner.launched) == launches_before, (
        "no fork may occur — two shells on one handle means two heartbeats, "
        "two monitors and two dispatchers")
    assert svc.sessions[sid]["state"] == "active", (
        "the row must come back to active so capacity and the FSM see it "
        "working again")
    assert svc.locks["rec-x:s1"] == sid
    assert svc.spawner.alive(sid) is True


def test_resume_forks_the_parked_session(svc, monkeypatch):
    """FORK-RESUME IS NOW THE CRASH PATH: the shell died while parked, so
    there is no live cron or Monitor to preserve and reconstruction is the
    only option."""
    sid = _parked_planner(svc, monkeypatch, crash=True,
                          claude_session="base-uuid-1")
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is True and out["via"] == "fork-resume"

    rec = svc.spawner.launched[-1]
    assert rec["session_id"] == sid                    # same row, same lock
    assert rec["resume_session"] == "base-uuid-1"      # forks the base
    assert rec["claude_session"] == out["claude_session_id"]
    assert rec["claude_session"] != "base-uuid-1"      # fresh fork id
    uuid.UUID(rec["claude_session"])                   # a real uuid4
    # the resumed shell regrounds instead of re-running its role activator
    assert rec["activation"] == PoolService.PARK_RESUME_ACTIVATION
    assert "reconcile(reground=true)" in rec["activation"]

    row = svc.sessions[sid]
    assert row["state"] == "active"
    assert row["claude_session_id"] == rec["claude_session"]
    assert "parked" not in row
    assert svc.locks["rec-x:s1"] == sid
    assert svc.liveness("rec-x:s1") == "alive"


def test_double_resume_no_ops(svc, monkeypatch):
    """Watchdog + MCP backstop firing together must yield ONE spawn.
    Uses the CRASH path, since a live parked shell no-ops both callers."""
    _parked_planner(svc, monkeypatch, crash=True)
    launches_before = len(svc.spawner.launched)
    first = svc.resume("rec-x:s1")
    second = svc.resume("rec-x:s1")
    assert first["resumed"] is True
    assert second["resumed"] is False and second["no_op"] is True
    assert len(svc.spawner.launched) == launches_before + 1


def test_resume_of_a_dead_but_active_row_fork_resumes(svc, monkeypatch):
    """2026-08-13 hardening run, live repro: the pool died and restarted;
    session rows loaded back as "active" while every process had died with
    the old pool. resume() no-opped on the stale row FOREVER ("session is
    already active"), and the operator had to reap + fresh-spawn by hand.
    A probed-DEAD active session is a crash — fork-resume it."""
    sid = svc.spawn("planner", "rec-x:s1", None, claude_session="base-uuid-1")
    svc._kill_session(sid)
    assert svc.spawner.alive(sid) is not True
    assert svc.sessions[sid]["state"] == "active"       # the stale row
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is True and out["via"] == "fork-resume", (
        "an active row whose process is provably dead must resume, not "
        f"no-op: {out}")
    rec = svc.spawner.launched[-1]
    assert rec["session_id"] == sid                     # same row, same lock
    assert rec["resume_session"] == "base-uuid-1"       # forks the base
    assert svc.sessions[sid]["state"] == "active"
    assert svc.locks["rec-x:s1"] == sid
    assert svc.liveness("rec-x:s1") == "alive"


def test_resume_of_a_mid_resume_session_no_ops(svc, monkeypatch):
    _parked_planner(svc, monkeypatch)
    sid = svc.locks["rec-x:s1"]
    svc.sessions[sid]["state"] = "resuming"   # a racing caller got here first
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is False and out["no_op"] is True


def test_resume_of_unparked_or_unknown_handle_is_refused(svc):
    assert svc.resume("never:held")["resumed"] is False
    svc.spawn("planner", "rec-x:s1", None)
    out = svc.resume("rec-x:s1")                 # active, never parked
    assert out["resumed"] is False and out.get("no_op") is True


def test_resume_fail_open_falls_back_to_fresh_spawn(svc, monkeypatch):
    """A failed fork-resume must not strand the handle: fresh spawn on the
    SAME handle, default role activation (cold reground path)."""
    sid = _parked_planner(svc, monkeypatch, crash=True,
                          claude_session="base-uuid-1")
    real_launch = svc.spawner.launch

    def _fork_fails(*a, **k):
        if k.get("resume_session"):
            raise RuntimeError("claude --resume exploded")
        return real_launch(*a, **k)

    monkeypatch.setattr(svc.spawner, "launch", _fork_fails)
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is True and out["via"] == "fresh-fallback"
    rec = svc.spawner.launched[-1]
    assert rec["resume_session"] is None
    assert "replay=true" in (rec["activation"] or ""), (
        "cold fallback must tell the fresh shell to check_inbox with "
        "replay - the dead predecessor may have consumed its dispatch "
        "mail (the missing-launch-context incident)")
    assert svc.sessions[sid]["state"] == "active"
    assert svc.sessions[sid]["claude_session_id"] == rec["claude_session"]


def test_resume_total_failure_leaves_the_row_parked(svc, monkeypatch):
    sid = _parked_planner(svc, monkeypatch, crash=True)

    def _always_fails(*a, **k):
        raise RuntimeError("no spawns today")

    monkeypatch.setattr(svc.spawner, "launch", _always_fails)
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is False
    assert svc.sessions[sid]["state"] == "parked"   # still resumable later
    assert svc.locks["rec-x:s1"] == sid


def test_park_resume_state_survives_a_pool_restart(tmp_path, monkeypatch):
    state = tmp_path / "pool-state.json"
    svc1 = PoolService(FakeSpawner(), state_path=state)
    monkeypatch.setattr(svc1, "_inbox_depth", lambda h: 3)
    sid = svc1.spawn("planner", "rec-x:s1", None, claude_session="base-1")
    svc1.park_session(sid, flush_timeout=0.05, flush_quiesce=0.01)

    svc2 = PoolService(FakeSpawner(), state_path=state)   # "restart"
    row = svc2.sessions[sid]
    assert row["state"] == "parked"
    assert row["parked"]["inbox_watermark"] == 3
    assert row["claude_session_id"] == "base-1"
    assert svc2.locks["rec-x:s1"] == sid
    # ...and the restarted pool can resume it (the whole point of parking
    # being persisted state rather than an in-memory promise).
    out = svc2.resume("rec-x:s1")
    assert out["resumed"] is True
    assert svc2.spawner.launched[-1]["resume_session"] == "base-1"


# ── flush-before-kill (verified live finding) ─────────────────────────────

def test_park_waits_for_a_quiescent_transcript(svc, monkeypatch, tmp_path):
    """The transcript must exist AND settle before the tree is killed —
    killing mid-write truncates the very context the resume preserves."""
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path / "agent"))
    sid = svc.spawn("planner", "rec-x:s1", None, claude_session="sess-t1")
    path = svc._transcript_path("sess-t1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    t0 = time.monotonic()
    ok = svc._wait_transcript_flush(sid, "sess-t1",
                                    timeout=5.0, quiesce=0.1, poll=0.02)
    assert ok is True
    assert time.monotonic() - t0 >= 0.1   # it actually awaited quiescence


def test_park_no_longer_waits_on_the_transcript_at_all(
        svc, monkeypatch, tmp_path):
    """The flush-before-kill is GONE with the kill it protected.

    This test previously asserted that a missing transcript produced a
    `park_flush_timeout` warning and parked anyway. There is now nothing to
    flush against: the transcript mattered only because the process was about
    to be killed mid-write. A park that leaves the shell running cannot
    truncate anything, so it must not spend the flush window either."""
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", str(tmp_path))
    warned: list = []
    from edp_pool import service as service_mod
    monkeypatch.setattr(
        service_mod._log, "warning",
        lambda kind, detail, **f: warned.append(kind))
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)

    sid = svc.spawn("planner", "rec-x:s1", None, claude_session="sess-gone")
    t0 = time.monotonic()
    out = svc.park_session(sid, flush_timeout=5.0, flush_quiesce=1.0)
    elapsed = time.monotonic() - t0

    assert out["parked"] is True
    assert svc.sessions[sid]["state"] == "parked"
    assert svc.spawner.alive(sid) is True
    assert "park_flush_timeout" not in warned, (
        "no flush is attempted any more — the shell is not being killed")
    assert elapsed < 1.0, (
        f"park must not burn the flush window ({elapsed:.2f}s); the generous "
        "timeouts passed here would have cost seconds under the old path")


def test_transcript_path_uses_claude_codes_cwd_key_scheme(svc, monkeypatch):
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", r"D:\cfg")
    monkeypatch.setenv("EDP_AGENT_HOME",
                       r"C:\Projects\Learning\eda-base3\claude")
    p = svc._transcript_path("abc-123")
    assert p.name == "abc-123.jsonl"
    # every non-alphanumeric char of the cwd becomes '-' (observed scheme)
    assert p.parent.name == "C--Projects-Learning-eda-base3-claude"
    assert p.parent.parent.name == "projects"


# ── HTTP surface ───────────────────────────────────────────────────────────

def test_park_and_resume_endpoints():
    sp = FakeSpawner()
    app = create_app(sp)
    svc = app.state.svc
    svc._inbox_depth = lambda h: 2                       # fake the broker GET
    # the endpoint has no flush knobs (by design); stub the wait so the test
    # doesn't sit in the 20s transcript window for a shell that never wrote
    svc._wait_transcript_flush = lambda *a, **k: True
    c = TestClient(app)
    sid = c.post("/v1/spawn", json={"role": "planner",
                                    "handle": "rec-x:s1",
                                    "claude_session": "base-h1"}).json()[
                                        "session_id"]
    r = c.post("/v1/park/rec-x:s1")
    assert r.status_code == 200 and r.json()["parked"] is True
    rows = c.get("/v1/sessions").json()
    assert rows[0]["state"] == "parked"                  # exposed to readers
    assert c.get("/v1/liveness/rec-x:s1").json()["state"] == "parked"

    # The shell is still ALIVE (park no longer kills), so resume restores the
    # row without forking. The endpoint still returns 200 and the handle still
    # ends up alive — the difference is that no second shell was launched.
    launches_before = len(sp.launched)
    r2 = c.post("/v1/resume/rec-x:s1")
    assert r2.status_code == 200
    assert r2.json()["no_op"] is True and r2.json()["shell_alive"] is True
    assert len(sp.launched) == launches_before, "no fork for a live shell"
    assert c.get("/v1/liveness/rec-x:s1").json()["state"] == "alive"
    assert c.get("/v1/sessions").json()[0]["session_id"] == sid

    # ...and the CRASH path still forks over the same endpoint.
    svc._inbox_depth = lambda h: 2
    c.post("/v1/park/rec-x:s1")
    svc._kill_session(sid)
    r3 = c.post("/v1/resume/rec-x:s1")
    assert r3.status_code == 200 and r3.json()["resumed"] is True
    assert sp.launched[-1]["resume_session"] == "base-h1"


async def test_close_when_idle_with_park_parks_instead_of_releasing(svc,
                                                                    monkeypatch):
    """The shell-callable park trigger: a planner arms it and ends its turn;
    the pool parks the quiesced shell instead of closing it for good."""
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 5)
    # no claude_session → the park's flush-wait short-circuits; the deferred
    # trigger itself is what this test proves.
    sid = svc.spawn("planner", "rec-x:s1", None)
    res = svc.arm_close_when_idle(sid, idle_secs=0.05, park=True,
                                  reason="pacing says child_in_progress")
    assert res["armed"] is True
    await asyncio.sleep(0.4)
    row = svc.sessions[sid]
    assert row["state"] == "parked", "park=True must park, not release"
    assert row["parked"]["inbox_watermark"] == 5
    assert svc.locks["rec-x:s1"] == sid                  # lock kept


def test_close_when_idle_endpoint_accepts_park():
    from edp_pool.service import create_app as mk
    sp = FakeSpawner()
    app = mk(sp)
    app.state.svc._inbox_depth = lambda h: 0
    with TestClient(app) as c:
        sid = c.post("/v1/spawn", json={"role": "planner",
                                        "handle": "rec-x:s1"}).json()[
                                            "session_id"]
        r = c.post(f"/v1/close_when_idle/{sid}",
                   json={"idle_secs": 30, "park": True})
        assert r.status_code == 200 and r.json()["armed"] is True


# ── resume watchdog ────────────────────────────────────────────────────────

def test_watchdog_resumes_when_depth_exceeds_watermark(svc, monkeypatch):
    """CRASH path: the shell died while parked, so the watchdog forks it."""
    sid = _parked_planner(svc, monkeypatch, depth=7, crash=True)
    wd = ResumeWatchdog(svc, interval=999)               # tick() driven

    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)  # nothing new
    assert wd.tick() == []
    assert svc.sessions[sid]["state"] == "parked"

    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 8)  # a message landed
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"
    assert svc.spawner.launched[-1]["resume_session"] == "base-uuid-1"
    assert wd.tick() == []                                 # no re-fire


def test_watchdog_wakes_a_LIVE_parked_shell_without_forking(svc, monkeypatch):
    """The ordinary path under the ruling. Mail lands for a parked shell that
    is still running: the row returns to active, the shell hears the message
    through its OWN Monitor subscription, and no second shell is launched."""
    sid = _parked_planner(svc, monkeypatch, depth=7)
    wd = ResumeWatchdog(svc, interval=999)
    launches_before = len(svc.spawner.launched)

    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 8)
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"
    assert len(svc.spawner.launched) == launches_before
    assert svc.spawner.alive(sid) is True


def test_watchdog_is_robust_to_broker_downtime(svc, monkeypatch):
    sid = _parked_planner(svc, monkeypatch, depth=3)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: None)  # broker down
    assert wd.tick() == []                                 # no crash, no fire
    assert svc.sessions[sid]["state"] == "parked"
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 4)  # broker back
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"


def test_watchdog_with_no_watermark_fires_on_any_traffic(svc, monkeypatch):
    # broker was down AT PARK TIME → watermark None. Firing on any
    # observable depth is over-eager but recoverable; never firing strands
    # the plan (the same asymmetry ruling as the pause watchdog).
    sid = _parked_planner(svc, monkeypatch, depth=None)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    assert wd.tick() == []                                 # empty inbox: wait
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 1)
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"


def test_watchdog_survives_a_tick_that_raises(svc, monkeypatch):
    _parked_planner(svc, monkeypatch)
    wd = ResumeWatchdog(svc, interval=0.01)
    calls = {"n": 0}

    def _boom():
        calls["n"] += 1
        raise RuntimeError("bad tick")

    monkeypatch.setattr(wd, "tick", _boom)
    wd.start()
    try:
        deadline = time.monotonic() + 2.0
        while calls["n"] < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        wd.stop()
    assert calls["n"] >= 2, "one bad tick must not kill the watchdog thread"


def test_service_lifecycle_starts_and_stops_the_watchdog(monkeypatch):
    # mount() wires startup/shutdown; TestClient's context manager runs them.
    app = create_app(FakeSpawner())
    with TestClient(app):
        wd = app.state.svc._resume_watchdog
        assert wd is not None and wd._thread.is_alive()
    assert app.state.svc._resume_watchdog is None


def test_watchdog_can_be_disabled_by_env(monkeypatch):
    monkeypatch.setenv("EDP_RESUME_WATCHDOG", "0")
    app = create_app(FakeSpawner())
    with TestClient(app):
        assert app.state.svc._resume_watchdog is None


def test_watchdog_heartbeat_resumes_a_long_parked_row(svc, monkeypatch):
    # 1:1 cron parity (2026-07-19): a row parked past the band is resumed
    # with ZERO inbox traffic; a fresh park is left alone. The BAND ARITHMETIC
    # is what this test pins, and it is unchanged by the 2026-07-25 ruling.
    #
    # What the ruling changes is the ACT the band triggers. The original
    # rationale was that a parked shell has no in-shell cron, so the watchdog
    # must supply the tick. A parked CLAUDE shell now keeps its own
    # CronCreate — so crossing the band restores the row to active WITHOUT a
    # fork, and the shell's own heartbeat carries on. The crash case below
    # still forks, because there is no shell left to tick.
    sid = _parked_planner(svc, monkeypatch, depth=7)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)   # never traffic
    launches_before = len(svc.spawner.launched)

    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "1800")
    assert wd.tick() == []                       # fresh park: inside band
    assert svc.sessions[sid]["state"] == "parked"

    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "0.000001")
    time.sleep(0.01)                             # let the park age past it
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"
    assert len(svc.spawner.launched) == launches_before, (
        "a LIVE parked shell keeps its own cron — the band must not fork it")
    assert svc.spawner.alive(sid) is True


def test_watchdog_heartbeat_forks_a_long_parked_row_that_DIED(svc, monkeypatch):
    """Same band, crashed shell: here the watchdog genuinely must rebuild it,
    because nothing is left to tick."""
    sid = _parked_planner(svc, monkeypatch, depth=7, crash=True)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)   # never traffic

    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "0.000001")
    time.sleep(0.01)
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"
    assert svc.spawner.launched[-1]["resume_session"] == "base-uuid-1"


def test_watchdog_heartbeat_disabled_by_zero_band(svc, monkeypatch):
    sid = _parked_planner(svc, monkeypatch, depth=7)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)
    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "0")
    time.sleep(0.01)
    assert wd.tick() == []
    assert svc.sessions[sid]["state"] == "parked"


def test_watchdog_executes_the_shells_own_rx_subscription(
        svc, monkeypatch, tmp_path):
    # 1:1 rx parity (operator ruling 2026-07-19): the AGENT arms its
    # reactive stream with observe() — same protocol act as a Claude
    # shell — persisting .reactive/<sub>.spec + .bindings.json. A parked
    # shell has no Monitor to run the subscription, so the WATCHDOG is
    # the executor: growth in a spec's file-plane source (recipe
    # events.jsonl here) resumes the shell.
    home = tmp_path / "claude"
    rx = home / ".reactive"; rx.mkdir(parents=True)
    recipes = home / ".recipes" / "rec-x"; recipes.mkdir(parents=True)
    events = recipes / "events.jsonl"
    events.write_text('{"kind":"old"}\n', encoding="utf-8")
    (rx / "sub-abc.bindings.json").write_text(
        '{"me": "rec-x:s1"}', encoding="utf-8")
    (rx / "sub-abc.spec").write_text(
        "rx.recipe_events(me, kinds=['learning','blocker'])",
        encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))

    sid = _parked_planner(svc, monkeypatch, depth=7)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)  # broker quiet
    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "1800")

    assert wd.tick() == [], "baseline tick must not fire"
    with events.open("a", encoding="utf-8") as f:
        f.write('{"kind":"learning"}\n')          # flowback lands
    assert wd.tick() == ["rec-x:s1"], (
        "growth in the shell's OWN rx source must resume it")
    assert svc.sessions[sid]["state"] == "active"


def test_rx_file_plane_honors_the_spec_kind_filter(
        svc, monkeypatch, tmp_path):
    # A mundane recipe_saved line must NOT wake the shell (observed live
    # as a console popup per store save); the spec's kinds do.
    home = tmp_path / "claude"
    rx = home / ".reactive"; rx.mkdir(parents=True)
    recipes = home / ".recipes" / "rec-x"; recipes.mkdir(parents=True)
    events = recipes / "events.jsonl"
    events.write_text("", encoding="utf-8")
    (rx / "sub-k.bindings.json").write_text(
        '{"me": "rec-x:s1"}', encoding="utf-8")
    (rx / "sub-k.spec").write_text(
        "rx.recipe_events(me, kinds=['learning', 'blocker'])",
        encoding="utf-8")
    monkeypatch.setenv("EDP_AGENT_HOME", str(home))

    sid = _parked_planner(svc, monkeypatch, depth=7)
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 7)
    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "1800")
    assert wd.tick() == []

    with events.open("a", encoding="utf-8") as f:
        f.write('{"kind":"recipe_saved"}\n')      # noise
    assert wd.tick() == [], "non-matching kind must be consumed silently"
    assert svc.sessions[sid]["state"] == "parked"

    with events.open("a", encoding="utf-8") as f:
        f.write('{"kind":"blocker"}\n')           # subscribed kind
    assert wd.tick() == ["rec-x:s1"]
    assert svc.sessions[sid]["state"] == "active"


def test_crashed_child_wakes_the_parked_parent(svc, monkeypatch):
    # Crash flowback (operator finding 2026-07-19): a child dying NONZERO
    # must publish CORE kind `crashed` to its PARENT handle and mark the
    # row dead — the parent's inbox growth then wakes it.
    parent_sid = _parked_planner(svc, monkeypatch, depth=7,
                                 handle="rec-x:s1")
    wsid = svc.spawn("worker", "rec-x-s1:a1", None)
    monkeypatch.setattr(svc.spawner, "exit_code",
                        lambda s: 1 if s == wsid else None, raising=False)
    svc.broker_url = "http://test-broker"
    crashed = svc.sweep_crashed()
    assert [c["session_id"] for c in crashed] == [wsid]
    assert svc.sessions[wsid]["state"] == "dead"
    assert crashed[0]["parent"] == "rec-x-s1", (
        "the crash must be addressed to the PARENT plan's inbox")
    assert crashed[0]["exit_code"] == 1

    # idempotent: a dead row is never re-detected
    assert svc.sweep_crashed() == []

    # the watchdog announces it over the broker
    published = []
    import httpx as _httpx
    class _R:
        status_code = 200
    monkeypatch.setattr(_httpx, "post",
        lambda url, json=None, timeout=None: published.append(json) or _R())
    wd0 = ResumeWatchdog(svc, interval=999)
    wd0._publish_crashed(crashed[0])
    assert published and published[0]["kind"] == "crashed"
    assert published[0]["to"] == "rec-x-s1"

    # the parent parked on watermark 7; the crash message makes depth 8 —
    # the SAME watchdog tick then delivers the wake.
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 8)
    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "1800")
    assert "rec-x:s1" in wd.tick()
    assert svc.sessions[parent_sid]["state"] == "active"


def test_normal_exit_and_close_armed_rows_are_not_crashes(svc, monkeypatch):
    sid0 = svc.spawn("worker", "rec-x-s1:a2", None)      # exit 0 = done
    sid_armed = svc.spawn("worker", "rec-x-s1:a3", None)  # reap in grace
    svc._close_timers[sid_armed] = object()
    codes = {sid0: 0, sid_armed: 1}
    monkeypatch.setattr(svc.spawner, "exit_code",
                        lambda s: codes.get(s), raising=False)
    assert svc.sweep_crashed() == []


def test_turn_timeout_kills_and_crash_plane_announces(svc, monkeypatch):
    # A turn stuck past EDP_TURN_TIMEOUT_SECS (provider retrying silently
    # forever) is killed; the kill's nonzero exit becomes a `crashed`
    # event on the next sweep — bounded, visible, never a 3-hour stall.
    sid = svc.spawn("worker", "rec-x-s1:a9", None)
    killed = []
    monkeypatch.setattr(svc.spawner, "turn_runtime",
                        lambda s: 99999 if s == sid else None, raising=False)
    monkeypatch.setattr(svc.spawner, "kill",
                        lambda s: killed.append(s), raising=False)
    monkeypatch.setattr(svc.spawner, "exit_code",
                        lambda s: 1 if s in killed else None, raising=False)
    monkeypatch.setenv("EDP_TURN_TIMEOUT_SECS", "2400")
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    wd = ResumeWatchdog(svc, interval=999)
    wd.tick()          # kills the stuck turn AND sweeps it, same pass
    assert killed == [sid]
    assert svc.sessions[sid]["state"] == "dead"
    assert "exited 1" in svc.sessions[sid]["dead_reason"]

    monkeypatch.setenv("EDP_TURN_TIMEOUT_SECS", "0")   # disabled = no kill
    sid2 = svc.spawn("worker", "rec-x-s1:a10", None)
    monkeypatch.setattr(svc.spawner, "turn_runtime",
                        lambda s: 99999, raising=False)
    killed.clear()
    wd.tick()
    assert killed == []


def test_terminal_release_closes_viewport_park_does_not(svc, monkeypatch):
    closed = []
    monkeypatch.setattr(svc.spawner, "close_viewport",
                        lambda s: closed.append(s), raising=False)
    parked_sid = _parked_planner(svc, monkeypatch, depth=1,
                                 handle="rec-vp:s1")
    assert closed == [], "a PARK must keep the window (session resumes)"
    sid = svc.spawn("worker", "rec-vp-s1:a1", None)
    svc.release(sid)
    assert closed == [sid], (
        "a TERMINAL release must close the shell's viewport window")


def test_operator_window_close_is_a_kill_even_when_parked(svc, monkeypatch):
    # 1:1 with killing a Claude monitor console: the operator closing a
    # shell's window ENDS the shell — dead row + `crashed` to the parent
    # within one sweep, crash recovery replaces it. A parked row dies
    # ONLY this way (its old exit code 0 must not kill it).
    sid = _parked_planner(svc, monkeypatch, depth=1, handle="rec-ok:s1")
    monkeypatch.setattr(svc.spawner, "viewport_died",
                        lambda s: s == sid, raising=False)
    monkeypatch.setattr(svc.spawner, "exit_code",
                        lambda s: 0, raising=False)
    crashed = svc.sweep_crashed()
    assert [c["session_id"] for c in crashed] == [sid]
    assert svc.sessions[sid]["state"] == "dead"
    assert "operator closed" in svc.sessions[sid]["dead_reason"]
    assert crashed[0]["parent"] == "rec-ok"


def test_pool_closed_viewport_is_never_a_crash(svc, monkeypatch):
    sid = svc.spawn("worker", "rec-ok-s1:a1", None)
    # pool-initiated viewport close (terminal release) → dismissed flag,
    # viewport_died False → no crash from the sweep.
    monkeypatch.setattr(svc.spawner, "viewport_died",
                        lambda s: False, raising=False)
    monkeypatch.setattr(svc.spawner, "exit_code",
                        lambda s: None, raising=False)
    assert svc.sweep_crashed() == []


def _wire_channels(monkeypatch, wd, channels, msgs_by_channel):
    monkeypatch.setattr(wd, "_channels", lambda: channels)
    monkeypatch.setattr(wd, "_channel_msgs",
                        lambda name: msgs_by_channel.get(name, []))


def test_channel_member_wake_on_addressed_mail(svc, monkeypatch):
    # CHANNELS: a steer addressed to a parked member resumes it; other
    # members' traffic never wakes it.
    sid = _parked_planner(svc, monkeypatch, depth=1, handle="rec-c:s1")
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 1)  # no inbox growth
    monkeypatch.setenv("EDP_PARKED_HEARTBEAT_SECS", "1800")
    ch = [{"channel": "rec-c-s1",
           "members": ["rec-c:s1", "rec-c-s1:a1"]}]
    msgs = {"rec-c-s1": [
        {"body": {"for": "rec-c-s1:a1"}, "kind": "steer"},   # not for us
    ]}
    _wire_channels(monkeypatch, wd, ch, msgs)
    wd.tick()          # baseline pass — history is never a wake
    assert svc.sessions[sid]["state"] == "parked"
    msgs["rec-c-s1"].append({"body": {"for": "rec-c:s1"}, "kind": "steer"})
    wd.tick()
    assert svc.sessions[sid]["state"] == "active", (
        "mail addressed to the parked member must resume it")


def test_mentions_never_spawn_only_agents_do(svc, monkeypatch):
    # OPERATOR RULING (2026-07-21): "only an agent can spawn an agent
    # using tools" — a mention of a NON-live handle must spawn NOTHING;
    # dumb logic never initiates a token-spending process.
    wd = ResumeWatchdog(svc, interval=999)
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    ch = [{"channel": "rec-c-s1",
           "members": ["rec-c:s1", "rec-c-s1:a9"]}]
    msgs = {"rec-c-s1": []}
    _wire_channels(monkeypatch, wd, ch, msgs)
    wd.tick()                                     # baseline
    msgs["rec-c-s1"].append({"body": {"for": "rec-c-s1:a9"},
                             "kind": "steer"})
    wd.tick()
    assert not any(s.get("handle") == "rec-c-s1:a9"
                   for s in svc.sessions.values()), (
        "a mention of a non-live handle spawned a shell — spawning is an "
        "AGENT tool act, never watchdog logic")
