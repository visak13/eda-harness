"""s15 item (b) — add_action MID-FLIGHT regression (2026-06-07).

Proves the s12-authorized one-guard widening of AddAction._run
(_tools.py:804ff) from {drafted} to {drafted, dispatching}:

  (1) add_action SUCCEEDS on a plan already in `dispatching`, the new
      action enters `pending`, respects depends_on, and is dispatchable
      by the FSM (next_action picks up a ready appended action; an
      appended action with unmet deps waits).
  (2) add_action REOPENS `acceptance_review` to dispatching with a
      `plan_reopened` advisory (P3 advisory FSM, 2026-06-10 — the old
      flat refusal pushed agents into recording a whole new plan), and
      still HARD-REFUSES on `terminal` (immutable history).

Invariants preserved: no new state; new action enters pending; deps
respected; its own acceptance gate still applies at done-time; bulk
record_plan remains the reopen path. See
eda-ml/docs/s12_framework_audit/ADD-ACTION-MIDFLIGHT-RCA.md.
"""

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _dispatching_plan(env, rid="recipe-s15mf", *, state="dispatching",
                      a1_status="in_progress"):
    """Save a plan directly in an in-flight (or past-dispatch) state with
    one existing action a1 — mirrors test_plan_builder's setup."""
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=f"{rid}-s1", recipe_id=rid, recipe_step_id="s1",
        domain="webdev", shape="x", goal="g", state=state,
        actions=[{"action_id": "a1", "description": "existing work",
                  "status": a1_status, "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    )))
    return f"{rid}-s1"


async def test_add_action_succeeds_midflight_and_is_dispatchable(env):
    pid = _dispatching_plan(env)

    # (1) append a no-dep action to the DISPATCHING plan — the fix.
    _ok(await env.call(
        "add_action", plan_id=pid, action_id="a2",
        description="appended mid-flight",
        acceptance_kind="file_exists",
        verify={"check": "file_exists", "path": "/tmp/x"}))

    p = env.ctx.plans.load(pid)
    a2 = next(a for a in p.actions if a.action_id == "a2")
    # enters pending (never sneaks in as done/in_progress), own gate kept
    assert a2.status == "pending"
    assert a2.acceptance.verify == {"check": "file_exists", "path": "/tmp/x"}
    # existing in-flight action untouched (no double-dispatch / no clobber)
    a1 = next(a for a in p.actions if a.action_id == "a1")
    assert a1.status == "in_progress"

    # dispatchable: a1 is in_progress (skipped), a2 is the first ready
    # pending action -> the FSM dispatches it on the next tick.
    d = _ok(await env.call("next_action", handle=pid, handle_type="plan"))
    assert d["kind"] == "dispatch_action"
    assert d["args"]["action_id"] == "a2"


async def test_add_action_midflight_respects_depends_on(env):
    # a1 is in_progress (NOT done); an appended action depending on a1 must
    # NOT be dispatched until a1 completes — deps respected, no out-of-order.
    pid = _dispatching_plan(env)
    _ok(await env.call(
        "add_action", plan_id=pid, action_id="a2",
        description="waits on a1", depends_on=["a1"]))

    p = env.ctx.plans.load(pid)
    a2 = next(a for a in p.actions if a.action_id == "a2")
    assert a2.status == "pending" and a2.depends_on == ["a1"]

    # No ready action (a1 in_progress, a2 blocked on a1) -> FSM does not
    # dispatch a2.
    d = _ok(await env.call("next_action", handle=pid, handle_type="plan"))
    assert d["kind"] != "dispatch_action" or d["args"]["action_id"] != "a2"


async def test_add_action_reopens_acceptance_review(env):
    """P3 advisory FSM (2026-06-10): this test USED to lock in a flat
    refusal ('reopening past dispatch stays record_plan/replan territory'),
    which in practice pushed agents into recording a whole NEW plan to add
    one missing action. add_action now REOPENS an acceptance_review plan to
    dispatching, with a `plan_reopened` advisory + audit-trail record.
    Terminal stays hard-refused (next test)."""
    pid = _dispatching_plan(env, rid="recipe-s15ar",
                            state="acceptance_review", a1_status="done")
    got = _ok(await env.call("add_action", plan_id=pid, action_id="a2",
                             description="the missing leg"))
    assert any(a["code"] == "plan_reopened"
               for a in (got.get("advisories") or []))
    p = env.ctx.plans.load(pid)
    assert [a.action_id for a in p.actions] == ["a1", "a2"]
    assert str(getattr(p.state, "value", p.state)) == "dispatching"


async def test_add_action_refused_in_terminal(env):
    pid = _dispatching_plan(env, rid="recipe-s15term",
                            state="terminal", a1_status="done")
    res = await env.call("add_action", plan_id=pid, action_id="a2",
                         description="plan finished")
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    p = env.ctx.plans.load(pid)
    assert [a.action_id for a in p.actions] == ["a1"]


async def test_drafted_append_still_works(env):
    # the original drafting-phase path is unchanged.
    pid = _dispatching_plan(env, rid="recipe-s15draft", state="drafted",
                            a1_status="pending")
    _ok(await env.call("add_action", plan_id=pid, action_id="a2",
                       description="drafting append"))
    p = env.ctx.plans.load(pid)
    assert [a.action_id for a in p.actions] == ["a1", "a2"]
