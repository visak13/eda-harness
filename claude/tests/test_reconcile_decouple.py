"""FSM-RESPONSIBILITY Step 3/4 — next_action is now a PURE phase pacer;
the broker/pool/disk state-sync moved into the explicit `reconcile` tool.

The acceptance bar: next_action ALONE no longer advances a recipe on a
plan_closed (it has zero external IO); `reconcile` does the sync; and
reconcile+next_action together reproduce the old next_action-alone
progression. This is the determinism preserved + the planes decoupled.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

RID = "recipe-dc"
SID = "s1"
PID = f"{RID}-{SID}"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _executing(env, rid=RID, sid=SID):
    from edp_claude.schemas import Recipe
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [],
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[{"step_id": sid, "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))


async def test_next_action_alone_does_NOT_advance_on_plan_closed(env):
    # the decoupling proof: a plan_closed sits in the broker, but
    # next_action (pure) does NOT poll it — the recipe stays EXECUTING and
    # the step stays in_progress. (Before: next_action would have
    # reconciled and advanced.)
    _executing(env)
    await env.call("broker_send", to=RID, kind="plan_closed",
                   body={"plan_id": PID})
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe"))
    assert d["kind"] == "wait"
    assert env.ctx.recipes.load(RID).steps[0].status == "in_progress"
    assert env.ctx.recipes.load(RID).state == "executing"


async def test_reconcile_syncs_then_next_action_advances(env):
    # reconcile (sync) marks the step done + recipe → planning; THEN
    # next_action (decide) advances off the synced record.
    _executing(env)
    await env.call("broker_send", to=RID, kind="plan_closed",
                   body={"plan_id": PID})
    rc = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert rc["changed"] is True and rc["alert"] is None
    assert env.ctx.recipes.load(RID).steps[0].status == "done"
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe"))
    assert d["kind"] != "wait"


async def test_reconcile_noop_when_nothing_to_sync(env):
    # no plan_closed, planner alive/unknown → reconcile changes nothing.
    _executing(env)
    rc = _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    assert rc["changed"] is False and rc["alert"] is None
    assert "nothing to reconcile" in rc["detail"]
    # and next_action still just waits
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe"))
    assert d["kind"] == "wait"


async def test_reconcile_then_next_action_equals_old_progression(env):
    # the determinism bar: reconcile+next_action on a plan_closed produces
    # the SAME terminal the old next_action-alone produced — a single
    # in-flight step that closes → recipe reaches `done`.
    _executing(env)
    await env.call("broker_send", to=RID, kind="plan_closed",
                   body={"plan_id": PID})
    _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    d = _ok(await env.call("next_action", handle=RID, handle_type="recipe"))
    assert d["kind"] == "done"                 # all steps done → honest close
