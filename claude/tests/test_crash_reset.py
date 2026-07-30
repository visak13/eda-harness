"""Crash-recovery reset (REACTIVE-STREAMS): a worker dies → the rx
pool() crash event wakes the planner → it reaps the session and resets
the stuck `in_progress` action to `pending` via update_object → the plan
FSM re-dispatches it. This proves the reset is a legal, observable
transition that the FSM acts on (the cure for next_action's
WAIT-forever crash-blindness)."""

from edp_contracts import ToolOk

from edp_claude.fsm.plan_fsm import plan_next_action
from edp_claude.schemas import Plan


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _plan(env, pid="p-crash"):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
        context={})))
    return pid


async def test_inprogress_resets_to_pending_and_redispatches(env):
    pid = _plan(env)
    # a crashed worker leaves a1 stuck in_progress; the FSM would WAIT
    # on it forever.
    p = env.ctx.plans.load(pid)
    instr = plan_next_action(p)
    assert instr.kind.value == "wait"        # stuck — nothing to do

    # reactive recovery: reset via update_object (in_progress -> pending).
    out = _ok(await env.call("update_object", type="action",
                             ids={"plan_id": pid, "action_id": "a1"},
                             patch={"status": "pending",
                                    "evidence": "worker crashed; reset"}))
    assert out["result"]["status"] == "pending"

    # now the FSM re-dispatches the pending action.
    p = env.ctx.plans.load(pid)
    instr = plan_next_action(p)
    assert instr.kind.value == "dispatch_action"
    assert instr.args["action_id"] == "a1"


async def test_reset_is_worklogged(env):
    pid = _plan(env, "p-crash2")
    await env.call("update_object", type="action",
                   ids={"plan_id": pid, "action_id": "a1"},
                   patch={"status": "pending", "evidence": "OOM crash"})
    rows = env.ctx.plans.read_worklog(pid)
    reset = [r for r in rows if r.get("kind") == "action_reset"]
    assert reset and reset[0]["action_id"] == "a1"
    assert "OOM crash" in reset[0]["detail"]
