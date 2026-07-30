"""Team-architecture Phase 7 (2026-05-21) — crash recovery via
liveness. The 2026-05-21 messaging-app HITL surfaced: a child that
dies BEFORE terminal leaves work in_progress forever (F1 broker +
F2 disk-terminal don't catch it). Option C: first crash auto-re-
dispatches; second surfaces via CHILD_CRASHED. Judgments recorded
to the worklog.
"""

from datetime import datetime, timedelta, timezone

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _executing_recipe(env, rid="recipe-crash", sid="s1", attempt=0):
    from edp_claude.schemas import Recipe

    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={
            "branches": [],
            "expected_outcomes": [{"id": "o1", "description": "d",
                                   "verification": "v"}],
        },
        steps=[{"step_id": sid, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner", "attempt": attempt}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def _na_recipe(env, rid):
    return _ok(await env.call("next_action", handle=rid,
                              handle_type="recipe"))


# ---- recipe-level (dead planner) ----------------------------------------

async def test_dead_planner_first_crash_auto_redispatches(env):
    rid = "recipe-crash"
    _executing_recipe(env, rid, "s1", attempt=0)
    env.ctx.pool.mark_dead(f"{rid}:s1")  # planner crashed

    # reconcile (sync) detects the dead planner → resets the step, recipe
    # → PLANNING; then next_action (decide) re-emits spawn_planner. The two
    # together reproduce what next_action-alone did before the decoupling.
    rc = _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert rc["changed"] is True and rc["alert"] is None
    d = await _na_recipe(env, rid)
    assert d["kind"] == "spawn_planner"
    r = env.ctx.recipes.load(rid)
    assert r.steps[0].attempt == 1
    # worklog records the judgment
    import json
    from pathlib import Path
    events = Path(env.ctx.recipes.root) / rid / "events.jsonl"
    lines = [json.loads(x) for x in
             events.read_text(encoding="utf-8").splitlines() if x.strip()]
    recoveries = [x for x in lines if x.get("kind") == "crash_recovery"]
    assert len(recoveries) == 1
    # s27/C10: the event names DETECTION + RECOMMENDATION. Nothing was spawned
    # by the emitting code — `performed` says what it actually did.
    assert recoveries[0]["action"] == "crash_detected_redispatch_recommended"
    assert recoveries[0]["performed"] == "reset_step_to_pending"
    assert recoveries[0]["recommends"] == "spawn_planner"
    assert recoveries[0]["agent_role"] == "neuron"


async def test_dead_planner_second_crash_surfaces(env):
    rid = "recipe-crash2"
    # attempt already 1 (auto-re-dispatch spent)
    _executing_recipe(env, rid, "s1", attempt=1)
    env.ctx.pool.mark_dead(f"{rid}:s1")

    # auto-recovery spent → reconcile SURFACES the crash as an `alert`
    # (next_action no longer carries crash instructions).
    rc = _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    assert rc["alert"] is not None
    assert rc["alert"]["kind"] == "child_crashed"
    assert rc["alert"]["args"]["kind"] == "planner"
    assert rc["alert"]["args"]["step_id"] == "s1"
    # worklog records the surface
    import json
    from pathlib import Path
    events = Path(env.ctx.recipes.root) / rid / "events.jsonl"
    lines = [json.loads(x) for x in
             events.read_text(encoding="utf-8").splitlines() if x.strip()]
    surfaced = [x for x in lines
                if x.get("action") == "surfaced_to_user"]
    assert len(surfaced) == 1


async def test_alive_planner_keeps_waiting(env):
    rid = "recipe-alive"
    _executing_recipe(env, rid, "s1")
    # Mark the planner alive by recording a spawn for its handle.
    await env.ctx.pool.spawn_planner(rid, "s1")  # handle = rid:s1, alive
    d = await _na_recipe(env, rid)
    assert d["kind"] == "wait"  # no crash action


async def test_unknown_liveness_keeps_waiting(env):
    # No spawn recorded, not marked dead → "unknown" → conservative.
    rid = "recipe-unknown"
    _executing_recipe(env, rid, "s1")
    d = await _na_recipe(env, rid)
    assert d["kind"] == "wait"  # unknown is NOT treated as crashed


# ---- plan-level (dead worker) -------------------------------------------

def _dispatching_plan(env, pid="plan-crash", aid="a1", attempt=0):
    from edp_claude.schemas import Plan

    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": aid, "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "tests_pass"},
                  "attempt": attempt}],
    )))


async def _na_plan(env, pid):
    return _ok(await env.call("next_action", handle=pid,
                              handle_type="plan"))


async def test_dead_worker_first_crash_auto_redispatches(env):
    pid = "plan-crash"
    _dispatching_plan(env, pid, "a1", attempt=0)
    env.ctx.pool.mark_dead(f"{pid}:a1")

    rc = _ok(await env.call("reconcile", handle=pid, handle_type="plan"))
    assert rc["changed"] is True and rc["alert"] is None
    d = await _na_plan(env, pid)
    # Reset to pending → FSM re-emits dispatch_action (and stamps
    # in_progress again at dispatch).
    assert d["kind"] == "dispatch_action"
    p = env.ctx.plans.load(pid)
    assert p.actions[0].attempt == 1


async def test_dead_worker_second_crash_surfaces(env):
    pid = "plan-crash2"
    _dispatching_plan(env, pid, "a1", attempt=1)
    env.ctx.pool.mark_dead(f"{pid}:a1")

    rc = _ok(await env.call("reconcile", handle=pid, handle_type="plan"))
    assert rc["alert"] is not None
    assert rc["alert"]["kind"] == "child_crashed"
    assert rc["alert"]["args"]["kind"] == "worker"
    assert rc["alert"]["args"]["action_id"] == "a1"


# ---- failed-dispatch rollback (2026-05-26 eda-ml phantom-lock) -----------
# plan_fsm pre-stamps `status=in_progress` at dispatch so next_action
# doesn't re-select (load-bearing). If the planner's subsequent spawn
# FAILS (POOL_CAPACITY_EXCEEDED, broker error, anything), the action sits
# in_progress with no live worker → FSM waits forever ("phantom lock"
# stall in the eda-ml run). Fix: dispatch tools ROLL BACK the pre-stamp
# on failure, so the invariant holds: in_progress ⇒ a spawn really
# happened. The fix lives at the dispatch boundary, not in the liveness
# sweep — the FSM's conservative "unknown keeps waiting" stays intact.
async def test_pool_spawn_worker_rolls_back_on_failure(env):
    from edp_contracts import ErrorCode, Tool
    pid = "plan-rollback"
    _dispatching_plan(env, pid, "a1", attempt=0)
    # Simulate the eda-ml POOL_CAPACITY_EXCEEDED — patch the stub.
    fail = Tool.propagate(source="edp-pool",
                          code=ErrorCode.POOL_CAPACITY_EXCEEDED,
                          message="max workers reached")

    async def _no(*_a, **_kw):
        return fail
    env.ctx.pool.spawn_worker = _no  # type: ignore[method-assign]

    res = await env.call("pool_spawn_worker",
                         plan_id=pid, action_id="a1")
    assert getattr(res, "ok", True) is False        # failure surfaced
    # rollback ran: action is back to pending so the FSM re-dispatches
    a = env.ctx.plans.load(pid).actions[0]
    assert a.status == "pending"
    # worklog records the rollback
    import json
    from pathlib import Path
    wl = (Path(env.ctx.plans.root) / pid / "worklog.jsonl") \
        .read_text(encoding="utf-8")
    rb = [json.loads(x) for x in wl.splitlines() if x.strip()
          if json.loads(x).get("kind") == "dispatch_failed"]
    assert len(rb) == 1 and rb[0]["action"] == "rollback_in_progress"


# (the action-integrated execution fork is fully retired — branch_specialist
#  no longer exists; the "no fork path" guarantee is asserted in
#  test_mcp_server. Execution dispatch + rollback live in pool_spawn_worker.)


async def test_unknown_liveness_keeps_waiting_at_plan_level(env):
    # Companion to recipe-level test_unknown_liveness_keeps_waiting:
    # with the rollback fix at the dispatch boundary, plan-level
    # `in_progress + unknown` is now a "spawn-just-succeeded but lock
    # not visible yet" window, NOT a phantom — so the FSM stays
    # conservative and waits. Phantom prevention is the dispatch
    # tool's job, not this sweep's.
    pid = "plan-unknown"
    _dispatching_plan(env, pid, "a1", attempt=0)
    # No spawn recorded, not dead → liveness == "unknown".
    d = await _na_plan(env, pid)
    assert d["kind"] == "wait"
    assert env.ctx.plans.load(pid).actions[0].status == "in_progress"


# ---- s16 phantom-dispatch + liveness integrity --------------------------
# A phantom = an in_progress action whose handle is liveness=unknown, backed
# by NO pool lock/session, quiet past one heartbeat-cadence grace window. It
# means "no live spawn is doing this action" (the FSM pre-stamp stranded when
# a spawn never happened / was rolled back), so it is recovered exactly like a
# 'dead' worker — reset→pending + re-dispatch. Phantom is computed CLIENT-SIDE
# (pool.locks()/pool.sessions()), no pool restart.
def _aged_worklog(env, pid, *, age_secs):
    ts = (datetime.now(timezone.utc) - timedelta(seconds=age_secs)).isoformat()
    env.ctx.plans.append_worklog(pid, {"ts": ts, "kind": "progress"})


def _wl_entries(env, pid):
    import json
    from pathlib import Path
    wl = (Path(env.ctx.plans.root) / pid / "worklog.jsonl") \
        .read_text(encoding="utf-8")
    return [json.loads(x) for x in wl.splitlines() if x.strip()]


async def test_phantom_in_progress_reaped_past_grace(env):
    # in_progress + liveness unknown + no backing lock/session + trail quiet
    # past a heartbeat cadence → PHANTOM → reconcile resets→pending, then
    # next_action re-dispatches (exactly the 'dead' recovery path).
    pid = "plan-phantom"
    _dispatching_plan(env, pid, "a1", attempt=0)
    _aged_worklog(env, pid, age_secs=3600)     # grace elapsed
    rc = _ok(await env.call("reconcile", handle=pid, handle_type="plan"))
    assert rc["changed"] is True and rc["alert"] is None
    d = await _na_plan(env, pid)
    assert d["kind"] == "dispatch_action"       # re-dispatched
    assert env.ctx.plans.load(pid).actions[0].attempt == 1
    phantom = [e for e in _wl_entries(env, pid) if e.get("cause") == "phantom"]
    assert len(phantom) == 1
    assert phantom[0]["action"] == "crash_detected_redispatch_recommended"
    assert phantom[0]["performed"] == "reset_action_to_pending"


async def test_phantom_not_reaped_within_grace(env):
    # Same shape but the trail is FRESH (within one heartbeat) → a
    # just-dispatched worker whose lock is not yet visible must NOT be reaped.
    pid = "plan-phantom-grace"
    _dispatching_plan(env, pid, "a1", attempt=0)
    _aged_worklog(env, pid, age_secs=5)         # within grace
    _ok(await env.call("reconcile", handle=pid, handle_type="plan"))
    assert env.ctx.plans.load(pid).actions[0].status == "in_progress"


async def test_backed_worker_not_reaped_when_liveness_unknown(env, monkeypatch):
    # The orphaned-but-locked case: liveness reports 'unknown' but a live pool
    # lock/session still backs the handle → NOT a phantom → not reaped, even
    # past grace. Guards against reaping every unknown-liveness held lock.
    pid = "plan-backed"
    _dispatching_plan(env, pid, "a1", attempt=0)
    await env.ctx.pool.spawn_worker(pid, "a1")   # records lock + session
    _aged_worklog(env, pid, age_secs=3600)       # past grace

    async def _unknown(_handle):
        return {"state": "unknown", "last_output_ts": None}
    monkeypatch.setattr(env.ctx.pool, "liveness", _unknown)

    _ok(await env.call("reconcile", handle=pid, handle_type="plan"))
    assert env.ctx.plans.load(pid).actions[0].status == "in_progress"


async def test_status_ping_classifies_phantom(env):
    pid = "plan-sp-phantom"
    _dispatching_plan(env, pid, "a1", attempt=0)   # in_progress, no spawn
    d = _ok(await env.call("status_ping", handle=f"{pid}:a1"))
    assert d["liveness"] == "unknown"
    assert "PHANTOM" in d["liveness_note"]
    # the optimistic "a spawn really happened" note is genuinely REPLACED
    assert "a spawn really happened" not in d["liveness_note"]


async def test_status_ping_backed_unknown_stays_conservative(env, monkeypatch):
    pid = "plan-sp-backed"
    _dispatching_plan(env, pid, "a1", attempt=0)
    await env.ctx.pool.spawn_worker(pid, "a1")

    async def _unknown(_handle):
        return {"state": "unknown", "last_output_ts": None}
    monkeypatch.setattr(env.ctx.pool, "liveness", _unknown)

    d = _ok(await env.call("status_ping", handle=f"{pid}:a1"))
    assert "PHANTOM" not in d["liveness_note"]
    assert "conservative wait" in d["liveness_note"]


async def test_inspect_worker_classifies_phantom(env):
    pid = "plan-iw-phantom"
    _dispatching_plan(env, pid, "a1", attempt=0)   # in_progress, no spawn
    d = _ok(await env.call("inspect_worker", plan_id=pid, action_id="a1"))
    assert d["liveness"] == "unknown"
    assert "PHANTOM" in d["note"]


async def test_early_precondition_refusal_rolls_back_in_progress(env):
    # s16 part 3: an action pre-stamped in_progress that a PRE-LAUNCH guard
    # refuses (here: declares a specialization but has no resolved spec_ids)
    # must be rolled back to pending so it does not strand in_progress with no
    # live worker.
    pid = "plan-precond-rollback"
    _dispatching_plan(env, pid, "a1", attempt=0)   # a1 pre-stamped in_progress
    p = env.ctx.plans.load(pid)
    p.actions[0].specializations = ["Java Spring Boot REST API"]
    env.ctx.plans.save(p)
    res = await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert env.ctx.plans.load(pid).actions[0].status == "pending"
    rb = [e for e in _wl_entries(env, pid)
          if e.get("kind") == "dispatch_failed"]
    assert rb and rb[0]["action"] == "rollback_in_progress"
