"""F21/F22 (2026-08-17) — the two enforcement gates discipline never fired.

F21 G-ACCEPT: a succeeded close requires a recorded goal-vs-delivery
acceptance verdict (emit_recipe_event kind='acceptance_verdict',
body.verdict='pass'). Outcomes are neuron-authored; meeting them all can
still under-deliver the verbatim ask — this is the gate that re-reads it.

F22 G-CHALLENGE: a plan of >= min actions dispatches no build leg until an
adversarial challenge ran or a waiver was consciously recorded
(record_context kind='challenge_waiver').

Both default ON in production; tests/conftest.py defaults them OFF for the
legacy suite, so these tests re-enable explicitly.
"""

from datetime import datetime, timezone

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    CloseRecipe,
    PoolSpawnWorker,
    RecordContext,
    _CloseRecipeIn,
    _RecordContextIn,
    _SpawnWorkerIn,
)


def _now():
    return datetime.now(timezone.utc)


def _closed_ready_recipe(ctx, rid):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="build X",
        user_goal_distilled="build X", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "X", "verification": "v",
             "met": True, "met_evidence": "seen"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "done", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _plan(ctx, plan_id, n_actions):
    acts = [Action(action_id=f"a{i}", description=f"do a{i}",
                   status="pending", executor_mode="inline",
                   acceptance=Acceptance(kind="manual_review", expected="x"))
            for i in range(1, n_actions + 1)]
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id="recipe-f22", recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=acts))


# ── F21 G-ACCEPT ────────────────────────────────────────────────────────────

async def test_succeeded_close_requires_acceptance_verdict(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f21")

    refused = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f21",
        final_outcome={"status": "succeeded", "summary": "done"}))
    assert not refused.ok
    assert "G-ACCEPT" in refused.message
    assert "acceptance_verdict" in refused.message

    # a recorded 'gaps' verdict still refuses — gaps block close
    ctx.recipes.append_worklog("recipe-f21", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "gaps", "gaps": ["Y missing"]}})
    refused2 = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f21",
        final_outcome={"status": "succeeded", "summary": "done"}))
    assert not refused2.ok and "'gaps'" in refused2.message

    # a later 'pass' verdict clears the gate (F43#2: it must carry the
    # CURRENT delivery fingerprint — an unfingerprinted pass is never
    # grandfathered)
    from edp_claude.tools._tools import _acceptance_fingerprint
    ctx.recipes.append_worklog("recipe-f21", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "by": "reviewer-leg",
                 "fingerprint": _acceptance_fingerprint(
                     ctx.recipes.load("recipe-f21"), ctx=ctx)}})
    ok = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f21",
        final_outcome={"status": "succeeded", "summary": "done"}))
    assert ok.ok, ok


async def test_partial_close_carries_no_acceptance_gate(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f21b")
    ok = await CloseRecipe(ctx)._run(_CloseRecipeIn(
        recipe_id="recipe-f21b",
        final_outcome={"status": "failed", "summary": "abandoning"}))
    assert ok.ok, ok


# ── F22 G-CHALLENGE ─────────────────────────────────────────────────────────

def _advisories(res):
    data = res.data if isinstance(res.data, dict) else (
        res.data.model_dump() if hasattr(res.data, "model_dump") else {})
    return data.get("advisories") or []


async def test_build_dispatch_proceeds_with_challenge_advisory(
        tmp_path, monkeypatch):
    # Revised contract (owner, 2026-08-17): dispatch is NEVER held hostage
    # to the adversary — a worker builds while the plan is challenged. The
    # dispatch carries the advisory; the STEP CLOSE enforces.
    monkeypatch.setenv("EDP_CHALLENGE_GATE_MIN_ACTIONS", "3")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f22")
    _plan(ctx, "recipe-f22-s1", n_actions=3)

    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="recipe-f22-s1", action_id="a1"))
    assert res.ok, res
    assert any(a["kind"] == "challenge_missing" for a in _advisories(res))


async def test_step_close_refused_without_challenge_or_waiver(
        tmp_path, monkeypatch):
    from edp_claude.tools._tools import RecordStepResult, _StepResIn
    monkeypatch.setenv("EDP_CHALLENGE_GATE_MIN_ACTIONS", "3")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f22")
    # step must be closable: recipe helper marks s1 done — flip to
    # in_progress so record_step_result exercises the gate.
    r = ctx.recipes.load("recipe-f22")
    r.steps[0].status = "in_progress"
    ctx.recipes.save(r)
    _plan(ctx, "recipe-f22-s1", n_actions=3)

    refused = await RecordStepResult(ctx)._run(_StepResIn(
        recipe_id="recipe-f22", step_id="s1", result={"outputs": []}))
    assert not refused.ok
    assert "G-CHALLENGE" in refused.message

    # a recorded waiver clears the close
    monkeypatch.setenv("EDP_ROLE", "planner")
    ok = await RecordContext(ctx)._run(_RecordContextIn(
        kind="challenge_waiver", plan_id="recipe-f22-s1",
        text="three-line config plan; nothing to break"))
    assert ok.ok, ok
    monkeypatch.delenv("EDP_ROLE", raising=False)
    closed = await RecordStepResult(ctx)._run(_StepResIn(
        recipe_id="recipe-f22", step_id="s1", result={"outputs": []}))
    assert closed.ok, closed


async def test_waiver_requires_rationale(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f22")
    _plan(ctx, "recipe-f22-s1", n_actions=3)
    bad = await RecordContext(ctx)._run(_RecordContextIn(
        kind="challenge_waiver", plan_id="recipe-f22-s1", text=""))
    assert not bad.ok


async def test_small_plans_carry_no_challenge_advisory(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_CHALLENGE_GATE_MIN_ACTIONS", "3")
    ctx = make_context(tmp_path)
    _closed_ready_recipe(ctx, "recipe-f22")
    _plan(ctx, "recipe-f22-s1", n_actions=2)
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="recipe-f22-s1", action_id="a1"))
    assert res.ok, res
    assert not any(a["kind"] == "challenge_missing"
                   for a in _advisories(res))
