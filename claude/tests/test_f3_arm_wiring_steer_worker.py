"""F3/F5 (2026-08-17) — arm_wiring (post-shadow one-call wiring) and
steer_worker (the planner's routed correction verb).

arm_wiring composes the role's default rx spec SERVER-SIDE and returns
verbatim monitor_cmd + cron args, so no shell learns the rx DSL. rx.orphaned
must never appear in a composed spec (known dash/colon false-flood defect).
steer_worker resolves the live worker's address from the caller's OWN plan,
refuses dead/unknown targets, and records the send for ack correlation.
"""

from datetime import datetime, timezone

from edp_claude.cadence import RECONCILE_LOOP_CRON_PROMPT
from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    ArmWiring,
    SteerWorker,
    _ArmWiringIn,
    _SteerWorkerIn,
)


def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"}],
        created_at=_now(), updated_at=_now(),
    ))


def _save_plan(ctx, rid, plan_id):
    def _act(aid):
        return Action(
            action_id=aid, description=f"do {aid}",
            status="pending", executor_mode="inline",
            acceptance=Acceptance(kind="manual_review", expected="x"))
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=[_act("a1"), _act("a2")]))


# ── arm_wiring ──────────────────────────────────────────────────────────────

async def test_arm_wiring_worker_returns_runnable_parts(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "recipe-f3-s1:a1")
    monkeypatch.delenv("EDP_SHADOW_NONCE", raising=False)
    ctx = make_context(tmp_path)
    res = await ArmWiring(ctx)._run(_ArmWiringIn())
    assert res.ok, res
    out = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert out["spec"] == "rx.broker(me)"
    assert "edp_claude.reactive.driver" in out["monitor_cmd"]
    assert out["cron_expr"] == "*/5 * * * *"
    assert "check_inbox" in out["cron_prompt"]
    assert out["reused"] is False

    # idempotent: the second arm reuses the same subscription
    res2 = await ArmWiring(ctx)._run(_ArmWiringIn())
    out2 = res2.data if isinstance(res2.data, dict) else res2.data.model_dump()
    assert res2.ok and out2["reused"] is True
    assert out2["subscription_id"] == out["subscription_id"]


async def test_arm_wiring_planner_spec_merges_without_orphaned(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-f3:s1")
    monkeypatch.delenv("EDP_SHADOW_NONCE", raising=False)
    ctx = make_context(tmp_path)
    res = await ArmWiring(ctx)._run(_ArmWiringIn())
    assert res.ok, res
    out = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert "rx.merge" in out["spec"] and "rx.orphaned" not in out["spec"]
    assert out["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


async def test_arm_wiring_neuron_requires_and_uses_handle(
        tmp_path, monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_SHADOW_NONCE"):
        monkeypatch.delenv(var, raising=False)
    ctx = make_context(tmp_path)
    refused = await ArmWiring(ctx)._run(_ArmWiringIn())
    assert not refused.ok
    res = await ArmWiring(ctx)._run(_ArmWiringIn(handle="recipe-f3"))
    assert res.ok, res
    nd = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert "rx.recipe_events" in nd["spec"]
    assert "rx.orphaned" not in nd["spec"]
    assert nd["cron_prompt"] == RECONCILE_LOOP_CRON_PROMPT


# ── steer_worker ────────────────────────────────────────────────────────────

async def test_steer_worker_refuses_dead_target_and_unknown_action(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-f3:s1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-f3")
    _save_plan(ctx, "recipe-f3", "recipe-f3-s1")

    unknown = await SteerWorker(ctx)._run(
        _SteerWorkerIn(action_id="nope", body={"note": "x"}))
    assert not unknown.ok

    # a1 has no live shell → the steer would dead-letter → refuse
    dead = await SteerWorker(ctx)._run(
        _SteerWorkerIn(action_id="a1", body={"note": "x"}))
    assert not dead.ok
    assert "not alive" in dead.message


async def test_steer_worker_sends_to_live_worker_and_records(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "recipe-f3:s1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "recipe-f3")
    _save_plan(ctx, "recipe-f3", "recipe-f3-s1")
    # a recorded spawn makes the stub pool report the handle alive
    await ctx.pool.spawn_worker("recipe-f3-s1", "a1")

    empty = await SteerWorker(ctx)._run(
        _SteerWorkerIn(action_id="a1", body={}))
    assert not empty.ok      # empty body refused — nothing to restate

    res = await SteerWorker(ctx)._run(_SteerWorkerIn(
        action_id="a1", body={"change": "use the v2 endpoint"}))
    assert res.ok, res

    # delivered to the worker's inbox as kind=steer
    msgs = await ctx.broker.poll("recipe-f3-s1:a1", since_ts=None)
    assert any(x.kind == "steer" for x in msgs)
    # …and the send is durably recorded for ack correlation
    sent = [e for e in ctx.plans.read_worklog("recipe-f3-s1", tail=20)
            if e.get("kind") == "message_sent"
            and e.get("msg_kind") == "steer"]
    assert sent and sent[-1]["to"] == "recipe-f3-s1:a1"
