"""F6 (2026-08-17) — the flow-down gate moved: ADVISORY at dispatch,
ENFORCED at step close.

The old dispatch-time hard refusal forced the whole plan to exist before the
first worker could spawn. Now: pool_spawn_worker proceeds and carries a
`flowdown_gaps` advisory; record_step_result refuses to flip the step done
while any step concern is uncovered or any acceptance_sketch line unmapped.
"""

from datetime import datetime, timezone

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    PoolSpawnWorker,
    RecordStepResult,
    _SpawnWorkerIn,
    _StepResIn,
)


def _now():
    return datetime.now(timezone.utc)


def _setup(ctx, *, covered: bool):
    ctx.recipes.save(Recipe(
        recipe_id="recipe-f6", user_goal_verbatim="g",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "build", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "inline", "concerns": ["security"]}],
        created_at=_now(), updated_at=_now(),
    ))
    ctx.plans.save(Plan(
        plan_id="recipe-f6-s1", recipe_id="recipe-f6", recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching",
        actions=[Action(
            action_id="a1", description="do a1", status="pending",
            executor_mode="inline",
            concerns=(["security"] if covered else []),
            acceptance=Acceptance(kind="manual_review", expected="x"))]))


async def test_dispatch_proceeds_with_flowdown_advisory(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _setup(ctx, covered=False)
    res = await PoolSpawnWorker(ctx)._run(
        _SpawnWorkerIn(plan_id="recipe-f6-s1", action_id="a1"))
    assert res.ok, res
    data = res.data if isinstance(res.data, dict) else res.data.model_dump()
    advisories = data.get("advisories") or []
    assert any(a.get("kind") == "flowdown_gaps" for a in advisories), data


async def test_step_close_refuses_until_covered(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _setup(ctx, covered=False)

    refused = await RecordStepResult(ctx)._run(_StepResIn(
        recipe_id="recipe-f6", step_id="s1", result={"outputs": []}))
    assert not refused.ok
    assert "flow-down" in refused.message

    # cover the concern → the close proceeds
    p = ctx.plans.load("recipe-f6-s1")
    p.actions[0].concerns = ["security"]
    ctx.plans.save(p)
    ok = await RecordStepResult(ctx)._run(_StepResIn(
        recipe_id="recipe-f6", step_id="s1", result={"outputs": []}))
    assert ok.ok, ok
    assert ctx.recipes.load("recipe-f6").steps[0].status == "done"
