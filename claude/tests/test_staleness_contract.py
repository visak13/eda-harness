"""DESIGN-v7 1.5.6 — the plan STALENESS CONTRACT (revalidate on pickup).

A plan is grounded in a snapshot (Plan.grounded_at, stamped by create_plan);
a sibling step's diff landing while the plan sits DRAFTED can invalidate the
DAG (the d39 class), and parallel planners (1.5.1) make that the common case.
This suite proves the code-computed defense on the live tool seam:

  (a) OVERLAPPING-fingerprint sibling closure → a non-empty staleness delta
      is computed at first pickup and the FIRST dispatch is REFUSED until a
      `plan_revalidated` worklog line newer than the delta exists;
  (b) DISJOINT sibling closure → empty delta, no gate, dispatch proceeds;
  (c) next_action(revalidate=true) writes the worklog artifact, clears the
      gate, refreshes grounded_at — and the delta is recomputed FRESH after
      revalidation (a later overlapping closure gates again via reground).

Kept fast (pure in-memory tool calls, no broker/pool restart, no LLM).
"""

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Plan

RID = "recipe-stale"
OLD_TS = "2020-01-01T00:00:00+00:00"   # predates every live worklog write


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _action(aid, spec_ids, status="pending", deps=()):
    return dict(action_id=aid, description=f"do {aid}", status=status,
                depends_on=list(deps), executor_mode="subagent",
                acceptance={"kind": "tests_pass"}, spec_ids=spec_ids)


def _save_plan(env, pid, sid, actions, *, state="drafted", grounded_at=OLD_TS):
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id=RID, recipe_step_id=sid, domain="generic",
        shape="x", goal=f"goal of {pid}", state=state, actions=actions,
        grounded_at=grounded_at,
    )))


def _close_sibling(env, pid, aid):
    """Simulate a sibling's landed work AFTER this suite's grounded_at: the
    done-transition worklog line (what record_action_status writes) plus the
    plan_closed line (what next_action writes at the TERMINAL crossing)."""
    env.ctx.plans.append_worklog(pid, {
        "kind": "action_status_changed", "action_id": aid, "status": "done",
    })
    env.ctx.plans.append_worklog(pid, {
        "kind": "plan_closed", "plan_id": pid, "terminal_status": "succeeded",
    })


async def _na(env, pid, **extra):
    return await env.call("next_action", handle=pid, handle_type="plan",
                          **extra)


# ── (a) overlapping sibling closure → delta + dispatch refused ──────────────
async def test_overlapping_sibling_closure_gates_first_dispatch(env):
    _save_plan(env, f"{RID}-s1", "s1",
               [_action("a1", ["spec-x"], status="done")], state="terminal")
    _close_sibling(env, f"{RID}-s1", "a1")
    # our plan: DRAFTED, grounded BEFORE the sibling's closure, overlapping
    # fingerprint (shares spec-x).
    _save_plan(env, f"{RID}-s2", "s2", [_action("b1", ["spec-x"])])

    res = await _na(env, f"{RID}-s2")
    assert isinstance(res, ToolError), res
    assert "STALENESS GATE" in res.message
    assert "revalidate=true" in res.message
    assert "spec-x" in res.message              # the delta names the overlap
    # the gate stamp is durable — the hand-out moment survives a restart.
    p = env.ctx.plans.load(f"{RID}-s2")
    assert p.staleness_delta_at
    # still refused on a retry (the gate holds until revalidation) — and the
    # wave surface is gated identically.
    again = await _na(env, f"{RID}-s2", all_ready=True)
    assert isinstance(again, ToolError)
    assert "STALENESS GATE" in again.message
    # nothing was stamped in_progress by the refused calls.
    assert env.ctx.plans.load(f"{RID}-s2").actions[0].status == "pending"


async def test_revalidation_clears_the_gate_and_dispatch_proceeds(env):
    _save_plan(env, f"{RID}-s1", "s1",
               [_action("a1", ["spec-x"], status="done")], state="terminal")
    _close_sibling(env, f"{RID}-s1", "a1")
    _save_plan(env, f"{RID}-s2", "s2", [_action("b1", ["spec-x"])])
    assert isinstance(await _na(env, f"{RID}-s2"), ToolError)

    # revalidate=true writes the worklog artifact, clears the gate, and the
    # SAME call proceeds to dispatch.
    res = _ok(await _na(env, f"{RID}-s2", revalidate=True))
    assert res["kind"] == "dispatch_action", res
    p = env.ctx.plans.load(f"{RID}-s2")
    assert p.staleness_delta_at is None
    assert p.grounded_at > OLD_TS               # revalidation re-grounds
    rows = env.ctx.plans.read_worklog(f"{RID}-s2",
                                      kinds=["plan_revalidated"])
    assert rows, "the gate's artifact (plan_revalidated line) must exist"


# ── (b) disjoint sibling closure → no delta, no gate ────────────────────────
async def test_disjoint_sibling_closure_does_not_gate(env):
    _save_plan(env, f"{RID}-s1", "s1",
               [_action("a1", ["spec-OTHER"], status="done")],
               state="terminal")
    _close_sibling(env, f"{RID}-s1", "a1")
    _save_plan(env, f"{RID}-s2", "s2", [_action("b1", ["spec-x"])])

    res = _ok(await _na(env, f"{RID}-s2"))
    assert res["kind"] == "dispatch_action", res    # dispatched, ungated
    p = env.ctx.plans.load(f"{RID}-s2")
    assert p.staleness_delta_at is None
    assert "staleness_delta" not in res.get("context", {})


# ── (c) the delta is recomputed FRESH after revalidation ────────────────────
async def test_delta_recomputed_fresh_after_revalidation(env):
    _save_plan(env, f"{RID}-s1", "s1",
               [_action("a1", ["spec-x"], status="done")], state="terminal")
    _close_sibling(env, f"{RID}-s1", "a1")
    _save_plan(env, f"{RID}-s2", "s2",
               [_action("b1", ["spec-x"]), _action("b2", ["spec-x"],
                                                   deps=["b1"])])
    assert isinstance(await _na(env, f"{RID}-s2"), ToolError)
    _ok(await _na(env, f"{RID}-s2", revalidate=True))   # gate cleared

    # a SECOND overlapping sibling closure lands AFTER the revalidation's
    # refreshed grounded_at…
    _save_plan(env, f"{RID}-s3", "s3",
               [_action("c1", ["spec-x"], status="done")], state="terminal")
    _close_sibling(env, f"{RID}-s3", "c1")
    # …and an explicit reground pickup recomputes a FRESH delta: only the
    # NEW closure is in it (the revalidated one is behind grounded_at), and
    # the gate re-arms against the ready b2 once b1 closes. Here b1 is still
    # in_progress so nothing is ready — the delta rides the context instead
    # of a refusal.
    res = _ok(await _na(env, f"{RID}-s2", reground=True))
    delta = res.get("context", {}).get("staleness_delta")
    assert delta, res
    plans_in_delta = {e["plan_id"] for e in delta["sibling_actions"]}
    assert plans_in_delta == {f"{RID}-s3"}, delta
    # the fresh hand-out re-armed the gate for the next dispatch attempt.
    assert env.ctx.plans.load(f"{RID}-s2").staleness_delta_at


# ── create_plan stamps the grounding provenance at authoring ────────────────
async def test_create_plan_stamps_grounded_at(env):
    from datetime import datetime, timezone
    from edp_claude.schemas import Recipe
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s9", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"}],
        context={}, created_at=now, updated_at=now,
    )))
    _ok(await env.call("create_plan", recipe_id=RID, step_id="s9",
                       shape="x", goal="g9"))
    p = env.ctx.plans.load(f"{RID}-s9")
    assert p.grounded_at, "create_plan must stamp grounding provenance"
    # a legacy plan (no grounded_at) has no baseline → no delta machinery.
    assert p.grounding_fingerprint is None
