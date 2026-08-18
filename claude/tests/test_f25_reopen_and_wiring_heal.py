"""F25 (2026-08-17, live s4 incident) — two fixes from one wedged planner.

1. PLAN REOPEN: a step reopened for new work while its plan sat
   terminal-succeeded had no author surface (plan_id is deterministic, so no
   fresh plan; terminal refused re-create). create_plan(reopen=true) resets
   the terminal plan to dispatching, preserving done actions.
2. WIRING SURVIVES GC: the observe TTL sweep took a parked shell's indexed
   spec artifacts; specs_for_handle then skipped them and the resume rewire
   handed back EMPTY wiring. The sweep now skips every indexed sid, and an
   empty hand-back names arm_wiring() instead of silence.
"""

import time
from datetime import datetime, timezone

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    CreatePlan,
    _CreatePlanIn,
    _gc_stale_subscriptions,
    _rewire_block,
)


def _now():
    return datetime.now(timezone.utc)


def _setup(ctx, step_status="in_progress"):
    ctx.recipes.save(Recipe(
        recipe_id="recipe-f25", user_goal_verbatim="g",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "o5 fix",
                "status": step_status, "depends_on": [],
                "execution": "spawn_planner"}],
        created_at=_now(), updated_at=_now()))
    ctx.plans.save(Plan(
        plan_id="recipe-f25-s1", recipe_id="recipe-f25",
        recipe_step_id="s1", domain="software_engineering",
        shape="linear-build", goal="old o4 build", state="terminal",
        terminal_status="succeeded",
        actions=[Action(
            action_id="a1", description="old work", status="done",
            executor_mode="inline",
            acceptance=Acceptance(kind="manual_review", expected="x",
                                  actual="done"))]))


# ── reopen ──────────────────────────────────────────────────────────────────

async def test_reopen_resets_terminal_plan_preserving_actions(tmp_path):
    ctx = make_context(tmp_path)
    _setup(ctx)
    res = await CreatePlan(ctx)._run(_CreatePlanIn(
        recipe_id="recipe-f25", step_id="s1", shape="diagnose-fix-verify",
        goal="o5 continuity fix", reopen=True))
    assert res.ok, res
    p = ctx.plans.load("recipe-f25-s1")
    assert str(getattr(p.state, "value", p.state)) == "dispatching"
    assert p.terminal_status is None
    assert p.goal == "o5 continuity fix"
    assert [a.action_id for a in p.actions] == ["a1"]      # history kept
    assert p.actions[0].status == "done"
    log = ctx.plans.read_worklog("recipe-f25-s1", tail=5)
    assert any(e.get("kind") == "plan_reopened"
               and e.get("prior_terminal_status") == "succeeded"
               for e in log)


async def test_reopen_refused_on_live_plan_and_done_step(tmp_path):
    ctx = make_context(tmp_path)
    _setup(ctx, step_status="done")
    refused = await CreatePlan(ctx)._run(_CreatePlanIn(
        recipe_id="recipe-f25", step_id="s1", shape="x", goal="g",
        reopen=True))
    assert not refused.ok
    assert "reopen the STEP first" in refused.message

    # live (non-terminal) plan: reopen is meaningless — refused
    from edp_claude.schemas.instruction import PlanState
    p = ctx.plans.load("recipe-f25-s1")
    p.state = PlanState.DISPATCHING
    p.terminal_status = None
    ctx.plans.save(p)
    refused2 = await CreatePlan(ctx)._run(_CreatePlanIn(
        recipe_id="recipe-f25", step_id="s1", shape="x", goal="g",
        reopen=True))
    assert not refused2.ok and "not terminal" in refused2.message


async def test_terminal_recreate_refusal_names_the_reopen_path(tmp_path):
    ctx = make_context(tmp_path)
    _setup(ctx)
    refused = await CreatePlan(ctx)._run(_CreatePlanIn(
        recipe_id="recipe-f25", step_id="s1", shape="x", goal="g"))
    assert not refused.ok
    assert "reopen=true" in refused.message


# ── wiring survives GC ─────────────────────────────────────────────────────

def test_gc_never_sweeps_indexed_sids(tmp_path):
    from edp_claude.reactive.handle_index import register_subscription
    root = tmp_path / ".reactive"
    root.mkdir(parents=True)
    old = time.time() - 100 * 3600            # way past any TTL
    for sid in ("sub-owned", "sub-anon"):
        (root / f"{sid}.spec").write_text("rx.broker(me)", encoding="utf-8")
    import os
    for sid in ("sub-owned", "sub-anon"):
        os.utime(root / f"{sid}.spec", (old, old))
    register_subscription(root, "recipe-f25:s1", "sub-owned")

    removed = _gc_stale_subscriptions(
        root, keep="sub-none", ttl_secs=3600, now_ts=time.time())
    assert removed == 1
    assert (root / "sub-owned.spec").exists()      # indexed — protected
    assert not (root / "sub-anon.spec").exists()   # anonymous — swept


def test_empty_rewire_names_arm_wiring(tmp_path):
    ctx = make_context(tmp_path)
    block = _rewire_block(ctx, "recipe-f25:s1")
    assert block["observe_specs"] == []
    assert "arm_wiring" in block["empty_wiring_note"]
