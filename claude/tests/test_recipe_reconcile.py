"""wake reconcile (2026-05-20 HITL fix) — the sync logic must NOT rest on
a single miss-able broker message (DESIGN-v5).

Post FSM-RESPONSIBILITY (2026-05-30): the sync moved OUT of next_action
into the explicit `reconcile` tool. The flow is now reconcile (sync to
broker/pool/disk reality) → next_action (decide the phase); together they
must reproduce exactly what next_action-alone did before. A recipe with a
spawn_planner step in flight advances when EITHER:
  (a) a `plan_closed` lands on the recipe_id inbox (fast path), OR
  (b) the step's plan is `terminal` on disk (deterministic backstop),
and stays `wait` when the plan exists but is not terminal.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

RID = "recipe-x"
SID = "s1"
PID = f"{RID}-{SID}"  # the agentic-plan.md plan_id convention


def _executing_recipe(env):
    r = env.ctx.recipes  # store
    from edp_claude.schemas import Recipe

    rec = Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={
            "branches": [{"id": "b1", "question": "?",
                          "status": "resolved", "verdict": "v" * 50}],
            "expected_outcomes": [{"id": "o1", "description": "d",
                                   "verification": "v"}],
        },
        steps=[{"step_id": SID, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    r.save(rec)
    return rec


def _save_plan(env, *, state: str):
    from edp_claude.schemas import Plan

    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=PID, recipe_id=RID, recipe_step_id=SID,
        domain="generic", shape="x", goal="g", state=state,
        terminal_status=("succeeded" if state == "terminal" else None),
        actions=[],
    )))


async def _na(env, rid=RID):
    # the decoupled flow: reconcile (sync to broker/pool/disk) THEN
    # next_action (decide). Together == old next_action-alone.
    rc = await env.call("reconcile", handle=rid, handle_type="recipe")
    assert isinstance(rc, ToolOk), rc
    res = await env.call("next_action", handle=rid, handle_type="recipe")
    assert isinstance(res, ToolOk), res
    return res.data


async def test_plan_closed_on_recipe_inbox_advances(env):
    # fast path: planner sent plan_closed to <recipe_id> (the FIX — the
    # 2026-05-20 wedge was "my-neuron", a dead-letter address).
    _executing_recipe(env)
    await env.call("broker_send", to=RID, kind="plan_closed",
                   body={"plan_id": PID})
    d = await _na(env)
    assert d["kind"] != "wait"
    assert env.ctx.recipes.load(RID).steps[0].status == "done"


async def test_stale_plan_closed_from_earlier_step_does_not_advance(env):
    # 2026-05-22 fitness HITL bug: the broker inbox is append-only, so a
    # plan_closed from an EARLIER step lingers. reconcile must
    # filter by THIS step's plan_id or it falsely completes the next
    # step (the neuron saw "FSM jumped to done=2 while s2 still
    # version(1)"). Here: step s2 in flight, a stale plan_closed for s1
    # in the inbox, s2's plan NOT terminal → must STAY wait.
    from edp_claude.schemas import Recipe
    rid = "recipe-stale"
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1",
                                              "description": "d",
                                              "verification": "v"}]},
        steps=[
            {"step_id": "s1", "kind": "work", "description": "d",
             "status": "done", "depends_on": [],
             "execution": "spawn_planner"},
            {"step_id": "s2", "kind": "work", "description": "d",
             "status": "in_progress", "depends_on": ["s1"],
             "execution": "spawn_planner"},
        ],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    # stale plan_closed for s1 (an earlier, already-done step)
    await env.call("broker_send", to=rid, kind="plan_closed",
                   body={"plan_id": f"{rid}-s1"})
    d = await _na(env, rid)
    assert d["kind"] == "wait"  # s2 must NOT be falsely completed
    assert env.ctx.recipes.load(rid).steps[1].status == "in_progress"

    # the CORRECT plan_closed (for s2) does advance it
    await env.call("broker_send", to=rid, kind="plan_closed",
                   body={"plan_id": f"{rid}-s2"})
    d2 = await _na(env, rid)
    assert d2["kind"] != "wait"
    assert env.ctx.recipes.load(rid).steps[1].status == "done"


async def test_offconvention_plan_id_still_found_by_scan(env):
    # plan-lookup-by-step: a planner that named the plan OFF the
    # `{recipe_id}-{step_id}` convention is still reconciled — the F2
    # backstop scans by the plan's recipe_id/recipe_step_id fields, so
    # there's no silent stall.
    _executing_recipe(env)
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id="some-weird-plan-name-xyz",  # NOT the convention
        recipe_id=RID, recipe_step_id=SID,
        domain="generic", shape="x", goal="g", state="terminal",
        terminal_status="succeeded", actions=[],
    )))
    d = await _na(env)
    assert d["kind"] != "wait"  # reconciled via scan, not convention
    assert env.ctx.recipes.load(RID).steps[0].status == "done"


async def test_terminal_plan_on_disk_advances_without_broker(env):
    # DESIGN-v5 backstop: NO broker message at all; planner died after
    # the plan went terminal. Disk is the can't-miss guarantee.
    _executing_recipe(env)
    _save_plan(env, state="terminal")
    d = await _na(env)
    assert d["kind"] != "wait"
    assert env.ctx.recipes.load(RID).steps[0].status == "done"


async def test_nonterminal_plan_on_disk_still_waits(env):
    # plan exists but is mid-flight → genuinely not done → keep waiting.
    _executing_recipe(env)
    _save_plan(env, state="dispatching")
    d = await _na(env)
    assert d["kind"] == "wait"
    assert env.ctx.recipes.load(RID).steps[0].status == "in_progress"


async def test_no_plan_no_broker_still_waits(env):
    # nothing has happened yet → wait (not a false advance).
    _executing_recipe(env)
    d = await _na(env)
    assert d["kind"] == "wait"
