"""WALK-1 (binding) — full spine over stubs.

Post-HITL sweep 2026-05-20: OCAK is no longer a forced pre-reasoning
checklist. The new flow is: start_recipe → REASON (free reasoning) →
record_outcome → RUN_AUDIT (post-reasoning audit gate) →
record_audit_verdict → DECLARE_STEP → add_step → spawn_planner → wait
→ broker plan_closed → honest PARTIAL close. Context is still PUSHED
every call (v5 P2/P3 invariant preserved). See
`docs/design/philosophy/ocak-as-helper-not-enforcer.md`.
"""

from edp_contracts import ToolError, ToolOk

GOAL = "design and implement a stateless auth method"
PID = "plan-stateless-auth"


def _ok(res) -> dict:
    assert isinstance(res, ToolOk), res
    return res.data


async def _na(env, handle, htype):
    d = _ok(await env.call("next_action", handle=handle, handle_type=htype))
    return d["kind"], d


async def test_walk_1_full_trace(env):
    # 1 — intent-level create (tool fills recipe_id/state/timestamps)
    rid = _ok(await env.call(
        "start_recipe", goal=GOAL, domain="software_engineering")
    )["recipe_id"]
    assert rid.startswith("recipe-")

    # 2 — free reasoning: FSM emits REASON (not the old 7-branch loop).
    # Context is still PUSHED every call.
    k, d = await _na(env, rid, "recipe")
    assert k == "reason"
    assert d["context"]["recap"].startswith(f"recipe={rid}")
    assert "audit=none" in d["context"]["recap"]

    # 2026-05-28 gate: outcomes require comprehension convergence. This
    # walkthrough doesn't exercise curiosity, so open the gate via the
    # explicit user-sign-off escape (the verbatim proceed-instruction).
    _ok(await env.call(
        "record_comprehension_signoff", recipe_id=rid,
        user_quote="proceed — comprehension is clear to me"))

    # 3 — agent declares outcome after reasoning. Tool fills the id.
    _ok(await env.call(
        "record_outcome", recipe_id=rid,
        description="A working stateless auth implementation",
        verification="integration test passes; tokens validated "
                     "and tamper-rejected"))

    # 4 — declare_step (no self-audit gate; team-architecture
    # restoration Phase 1: `/critic` (Phase 5) is the real audit
    # surface).
    k, d = await _na(env, rid, "recipe")
    assert k == "declare_step"
    sid = _ok(await env.call(
        "add_step", recipe_id=rid,
        description="Implement + test the stateless auth scheme",
        execution="spawn_planner", estimate={"hours": 1}))["step_id"]

    # 6 — spawn_planner, then wait
    k, d = await _na(env, rid, "recipe")
    assert k == "spawn_planner" and d["args"]["step_id"] == sid
    assert env.ctx.recipes.load(rid).state == "executing"
    _ok(await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid))
    k, d = await _na(env, rid, "recipe")
    assert k == "wait"
    # wake: WAIT carries the deterministic heartbeat directive (zero
    # LLM discretion at the protocol layer).
    assert d["args"]["handle"] == rid
    assert d["args"]["handle_type"] == "recipe"
    assert d["args"]["heartbeat_secs"] == 1800

    # 7 — planner authors + drives the plan
    plan = {
        "plan_id": PID, "recipe_id": rid, "recipe_step_id": sid,
        "domain": "software_engineering", "shape": "modular-build",
        "goal": "implement stateless auth", "state": "drafted",
        "actions": [
            {"action_id": "a1", "description": "signer",
             "status": "pending", "depends_on": [],
             "executor_mode": "subagent",
             "acceptance": {"kind": "tests_pass", "expected": "green"}},
        ],
        "context": {}, "version": 1,
    }
    _ok(await env.call("record_plan", plan=plan))

    # team-architecture restoration Phase 1: plan-level self-audit
    # gate removed. DRAFTED → DISPATCHING directly.
    k, d = await _na(env, PID, "plan")
    assert k == "dispatch_action" and d["args"]["action_id"] == "a1"
    _ok(await env.call("pool_spawn_worker", plan_id=PID, action_id="a1"))
    _ok(await env.call("record_action_status", plan_id=PID, action_id="a1",
                       status="done", evidence="SignerTest green"))
    k, _ = await _na(env, PID, "plan")
    assert k == "done"
    assert env.ctx.plans.load(PID).terminal_status == "succeeded"

    # 8 — planner notifies neuron; reconcile syncs the plan_closed, then
    # next_action advances to honest close (reconcile+next_action == the
    # old next_action-alone progression)
    _ok(await env.call("broker_send", to=rid, kind="plan_closed",
                       body={"plan_id": PID}, from_="my-planner"))
    await env.call("reconcile", handle=rid, handle_type="recipe")
    k, d = await _na(env, rid, "recipe")
    # work driven + outcome declared but not verified → honest PARTIAL
    assert k == "done"
    assert d["args"].get("partial") is True
    assert "not yet verified" in d["rationale"]


async def test_walk_self_audit_gate_is_removed(env):
    """Team-architecture-restoration Phase 1 (2026-05-21): the self-
    audit gate is GONE. REASON → record_outcome → DECLARE_STEP, no
    intermediate FSM gate. The discipline (don't self-evaluate) lives
    in the brief; the real audit will be `/critic` (Phase 5, separate
    shell)."""
    rid = _ok(await env.call(
        "start_recipe", goal="x", domain="generic"))["recipe_id"]

    k, _ = await _na(env, rid, "recipe")
    assert k == "reason"

    # 2026-05-28 gate: open via user sign-off (this test isn't about
    # curiosity, only the audit-gate removal).
    _ok(await env.call(
        "record_comprehension_signoff", recipe_id=rid,
        user_quote="proceed"))
    _ok(await env.call(
        "record_outcome", recipe_id=rid, description="d",
        verification="v"))

    # No audit gate — declare_step immediately.
    k, _ = await _na(env, rid, "recipe")
    assert k == "declare_step"


async def test_get_guide_loads_and_caches(env):
    """get_guide returns markdown content from docs/guides/ and is
    cached in-process (LRU). Falsifiable via the precondition path:
    unknown guide name returns tool_precondition."""
    res = await env.call("get_guide", name="framework-ocak")
    assert isinstance(res, ToolOk)
    assert "post-reasoning" in res.data["content"].lower()

    res2 = await env.call("get_guide", name="does-not-exist")
    assert isinstance(res2, ToolError)
    assert res2.code == "tool_precondition"


async def test_consult_specialist_returns_guide_plus_prompt(env):
    """consult_specialist is a PURE helper (no LLM inside): returns
    the specialist guide content plus a structured prompt template.
    The AGENT does the reasoning and calls record_specialist_consult."""
    res = await env.call(
        "consult_specialist", specialist_id="feasibility",
        query="can we send anonymous emails?")
    assert isinstance(res, ToolOk)
    assert "feasibility" in res.data["specialist_id"]
    assert "blocker" in res.data["knowledge"].lower()
    assert "record_specialist_consult" in res.data["structured_prompt"]


async def test_record_specialist_consult_persists(env):
    rid = _ok(await env.call(
        "start_recipe", goal="x", domain="generic"))["recipe_id"]
    _ok(await env.call(
        "record_specialist_consult", recipe_id=rid,
        specialist_id="feasibility", query="q",
        verdict={"feasible": True, "blockers": [],
                 "requires_user_input": False, "evidence": "all clear"}))
    r = env.ctx.recipes.load(rid)
    assert len(r.specialist_consults) == 1
    assert r.specialist_consults[0].specialist_id == "feasibility"

    # next_action's recap surfaces the consult
    _, d = await _na(env, rid, "recipe")
    assert "feasibility" in d["context"]["recap"]
