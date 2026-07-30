"""s27/a1 — MACHINERY TRUTH (C7 + C10).

Per d76 the FSM is an ADVISOR, not an enforcer. An advisor may be ignored; it
may NOT lie about the world. These tests pin two lies and their fixes.

C7 — the FSM instructed a DOUBLE-DISPATCH.
    The premise recorded in d78 ("dispatch_action for an action already
    `in_progress`") is one fact off, and the correction matters for what these
    tests may safely assert. `plan_fsm._ready_actions` gates on
    `status == "pending"`, so the FSM STRUCTURALLY never dispatches an
    `in_progress` action. The state that actually shipped the double-dispatch
    (5x on s26, 1x on s27) is `pending` + a LIVE worker: a spawn performed
    OUTSIDE the FSM's dispatch instruction never stamps `in_progress`, and both
    the interleaved `pool_spawn_worker` that planner-phase-author MANDATES and
    crash recovery's explicit re-dispatch do exactly that. So `pending` is not
    a truthful proxy for "nothing is running this". Only the pool knows.
    Fix: liveness — never the status string — gates dispatch, both in the FSM
    (via a pure `live_action_ids` input) and in the spawn tool's guard.

C10 — `crash_recovery{action:'auto_re_dispatch'}` was logged with NO spawn.
    The branch detects a dead/phantom child and resets it to pending. It spawns
    nothing. Fix the LOG, not the code: per d76 the FSM does not spawn.

Every assertion below was mutation-proved: the exact guarded line was broken,
the test was watched to go RED at that site, and the line was reverted with
byte-identity confirmed. A test that cannot be driven RED guards nothing.
"""

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.fsm import plan_next_action, plan_ready_wave
from edp_claude.schemas import Plan


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _err(res):
    assert isinstance(res, ToolError), res
    return res


def _plan(pid="plan-truth", aid="a1", status="pending", attempt=0) -> Plan:
    return Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-absent", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": aid, "description": "d",
                  "status": status, "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"},
                  "attempt": attempt}],
    ))


async def _live(env, handle):
    """Make `handle` report liveness 'alive' the way the pool defines it:
    a recorded spawn that has not died. Uses the pool's own spawn verb rather
    than poking private state, so the test agrees with prod's oracle."""
    pid, aid = handle.rsplit(":", 1)
    await env.ctx.pool.spawn_worker(pid, aid)


# ── T1 — the FSM does not dispatch an action a live worker already holds ────

def test_t1_fsm_does_not_dispatch_action_with_live_session():
    """GUARDS: plan_fsm._ready_actions' `a.action_id not in live_action_ids`.

    The real drift state: status `pending`, a LIVE shell inside it. Before the
    fix this returned dispatch_action — the instruction that double-spawns."""
    p = _plan(status="pending")
    instr = plan_next_action(p, frozenset({"a1"}))

    assert instr.kind.value != "dispatch_action"
    assert instr.kind.value == "wait"
    # It emits the WAIT it already computes, and NAMES why (d78: "emit the wait
    # it already computes. Do not invent a new instruction kind").
    assert "a1" in instr.rationale and "LIVE" in instr.rationale
    # The action must NOT be stamped in_progress by a suppressed dispatch.
    assert p.actions[0].status == "pending"


def test_t1_wave_surface_also_suppresses_a_live_action():
    """The all-ready-wave shares `_ready_actions`, so it inherits the fix. Pinned
    because a second, divergent readiness rule is exactly what that predicate's
    docstring promises can never drift in."""
    p = _plan(status="pending")
    assert plan_ready_wave(p, frozenset({"a1"})) == []
    assert p.actions[0].status == "pending"   # not stamped

    fresh = _plan(status="pending")
    assert [i.kind.value for i in plan_ready_wave(fresh, frozenset())] \
        == ["dispatch_action"]


def test_t1_in_progress_is_never_dispatched_with_or_without_liveness():
    """The invariant d78's premise ASSUMED but never held: an `in_progress`
    action is already excluded by the status predicate, liveness or not. Pinned
    so a future edit to `_ready_actions` cannot quietly reopen it.

    This is the ENUMERATION d66 demands in place of an unverified universal:
    the two dispatch surfaces are `plan_next_action` and `plan_ready_wave`, and
    both are built on `_ready_actions` (verified by reading plan_fsm.py — it is
    the whole module; there is no third surface)."""
    for live in (frozenset(), frozenset({"a1"})):
        p = _plan(status="in_progress")
        assert plan_next_action(p, live).kind.value != "dispatch_action"
        assert plan_ready_wave(_plan(status="in_progress"), live) == []


# ── T2 — a DEAD session stays dispatchable (no crash-recovery deadlock) ──────

async def test_t2_dead_session_still_dispatches(env):
    """GUARDS: `_session_is_live` returning True ONLY on a confirmed 'alive'.

    The load-bearing direction. If suppression fired on anything other than
    positive proof of life, this double-dispatch fix would become a
    crash-recovery DEADLOCK — a dead worker's action could never be
    re-dispatched — which is strictly worse than the bug it fixes."""
    p = _plan(pid="plan-dead")
    env.ctx.plans.save(p)
    await _live(env, "plan-dead:a1")          # a session existed…
    env.ctx.pool.mark_dead("plan-dead:a1")    # …and then it died

    d = _ok(await env.call("next_action", handle="plan-dead",
                           handle_type="plan"))
    assert d["kind"] == "dispatch_action"
    assert d["args"]["action_id"] == "a1"


async def test_t2_unknown_session_still_dispatches(env):
    """The never-spawned handle (liveness 'unknown'). A first dispatch must not
    be suppressed by an absence of evidence — 'unknown' is not 'alive'."""
    env.ctx.plans.save(_plan(pid="plan-unknown"))
    d = _ok(await env.call("next_action", handle="plan-unknown",
                           handle_type="plan"))
    assert d["kind"] == "dispatch_action"


async def test_t2_live_session_suppresses_dispatch_through_the_tool(env):
    """The integration twin of T1: the tool layer probes the pool and hands the
    pure FSM its `live_action_ids`. Same fixture as T2's dead case except the
    worker never dies — so ONLY liveness distinguishes them."""
    env.ctx.plans.save(_plan(pid="plan-live"))
    await _live(env, "plan-live:a1")

    d = _ok(await env.call("next_action", handle="plan-live",
                           handle_type="plan"))
    assert d.get("kind") != "dispatch_action"
    # The action was not stamped, so no phantom in_progress is left behind.
    assert env.ctx.plans.load("plan-live").actions[0].status == "pending"


# ── T3 — the spawn tool refuses a live handle, and force=true escapes ────────

@pytest.fixture(autouse=True)
def _no_startup_sleep(monkeypatch):
    """The spawn path polls liveness for ~6s to catch a shell that dies at
    startup. Irrelevant here and slow; drive the poll to zero."""
    monkeypatch.setattr("edp_claude.tools._tools._SPAWN_STARTUP_POLL_SECS", 0)


async def test_t3_spawn_refuses_live_handle_and_force_accepts(env):
    """GUARDS: the `not m.force and await _session_is_live(...)` guard in
    PoolSpawnWorker — defence in depth behind the FSM fix."""
    env.ctx.plans.save(_plan(pid="plan-guard", status="in_progress"))
    await _live(env, "plan-guard:a1")
    spawns_before = len(env.ctx.pool.spawns)

    res = _err(await env.call("pool_spawn_worker",
                              plan_id="plan-guard", action_id="a1"))
    assert res.code == "tool_precondition"
    assert "LIVE worker" in res.message
    assert len(env.ctx.pool.spawns) == spawns_before   # refused BEFORE launch
    # The refusal must NOT roll the live worker's action back to pending.
    assert env.ctx.plans.load("plan-guard").actions[0].status == "in_progress"

    _ok(await env.call("pool_spawn_worker", plan_id="plan-guard",
                       action_id="a1", force=True))
    assert len(env.ctx.pool.spawns) == spawns_before + 1


async def test_t3_spawn_allows_dead_and_unknown_handles(env):
    """The guard's fail-open direction, at the tool boundary. A dead handle is
    the crash-recovery re-dispatch; an unknown handle is a first dispatch."""
    env.ctx.plans.save(_plan(pid="plan-g2", status="in_progress"))
    _ok(await env.call("pool_spawn_worker", plan_id="plan-g2",
                       action_id="a1"))                    # unknown → allowed

    env.ctx.pool.mark_dead("plan-g2:a1")
    _ok(await env.call("pool_spawn_worker", plan_id="plan-g2",
                       action_id="a1"))                    # dead → allowed


# ── T4 — the crash-recovery event states what the code did, and spawns none ──

def _wl(env, pid):
    import json
    from pathlib import Path
    wl = (Path(env.ctx.plans.root) / pid / "worklog.jsonl")
    return [json.loads(x) for x in
            wl.read_text(encoding="utf-8").splitlines() if x.strip()]


async def test_t4_crash_event_states_detection_and_recommendation(env):
    """GUARDS: the crash_recovery worklog payload in `_advance_plan_liveness`.

    Two claims, both required:
      (a) the event names DETECTION + RECOMMENDATION, not a performed spawn;
      (b) emitting it creates NO session — the FSM advises, it does not spawn
          (d76). The s26/a1 line claimed `auto_re_dispatch` while the session
          that appeared was created by the planner's own explicit call."""
    env.ctx.plans.save(_plan(pid="plan-c10", status="in_progress"))
    env.ctx.pool.mark_dead("plan-c10:a1")
    spawns_before = len(env.ctx.pool.spawns)

    _ok(await env.call("reconcile", handle="plan-c10", handle_type="plan"))

    ev = [e for e in _wl(env, "plan-c10") if e.get("kind") == "crash_recovery"]
    assert len(ev) == 1
    assert ev[0]["action"] == "crash_detected_redispatch_recommended"
    assert ev[0]["performed"] == "reset_action_to_pending"
    assert ev[0]["recommends"] == "dispatch_action"
    assert "NO spawn was performed here" in ev[0]["detail"]
    # (b) the emitting code spawned nothing.
    assert len(env.ctx.pool.spawns) == spawns_before
    assert env.ctx.plans.load("plan-c10").actions[0].status == "pending"


async def test_t4_no_stale_auto_re_dispatch_name_survives(env):
    """The old name asserted an action the code never took. Pin its absence so a
    revert cannot silently restore the false claim."""
    env.ctx.plans.save(_plan(pid="plan-c10b", status="in_progress"))
    env.ctx.pool.mark_dead("plan-c10b:a1")
    _ok(await env.call("reconcile", handle="plan-c10b", handle_type="plan"))

    assert not [e for e in _wl(env, "plan-c10b")
                if e.get("action") == "auto_re_dispatch"]
