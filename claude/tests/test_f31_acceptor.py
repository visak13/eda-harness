"""F31 (2026-08-18, owner ruling) — the FINAL ACCEPTANCE PASS is
FSM-explicit and runs in the advisor seat's OWN shell.

- recipe_next_action emits DISPATCH_ACCEPTANCE at all-outcomes-met (pure).
- NextAction downgrades it to DONE when the latest acceptance_verdict is
  'pass' (or the gate is off), and annotates on 'gaps'.
- dispatch_acceptance posts the brief (verbatim goal, outcomes, workspace)
  BEFORE spawning the acceptor — consult-before-spawn.
"""

from datetime import datetime, timezone

from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    DispatchAcceptance,
    NextAction,
    _DispatchAcceptanceIn,
)
from edp_claude.tools._tools import _NAIn as _NA_In


def _now():
    return datetime.now(timezone.utc)


def _all_met_recipe(ctx, rid="recipe-f31"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="build X per SKILL.md",
        user_goal_distilled="g", domain="software_engineering",
        state="reviewing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "X works", "verification": "run it",
             "met": True, "met_evidence": "ran clean"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "done", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now()))


async def test_all_met_emits_dispatch_acceptance_then_done_on_pass(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)

    res = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f31", handle_type="recipe"))
    assert res.ok, res
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert d["kind"] == "dispatch_acceptance"

    # a 'gaps' verdict keeps the instruction and names the blocker
    ctx.recipes.append_worklog("recipe-f31", {
        "kind": "acceptance_verdict", "body": {"verdict": "gaps"}})
    res2 = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f31", handle_type="recipe"))
    d2 = res2.data if isinstance(res2.data, dict) else res2.data.model_dump()
    assert d2["kind"] == "dispatch_acceptance"
    assert "'gaps'" in d2["rationale"]

    # a later 'pass' downgrades to DONE
    ctx.recipes.append_worklog("recipe-f31", {
        "kind": "acceptance_verdict", "body": {"verdict": "pass"}})
    res3 = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f31", handle_type="recipe"))
    d3 = res3.data if isinstance(res3.data, dict) else res3.data.model_dump()
    assert d3["kind"] == "done"
    assert "pass" in d3["rationale"]


async def test_gate_off_goes_straight_to_done(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "0")
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    res = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f31", handle_type="recipe"))
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert d["kind"] == "done"


async def test_dispatch_acceptance_briefs_before_spawn(tmp_path):
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    res = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f31", interim=True))
    assert res.ok, res
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    aid = d["acceptor_id"]
    assert aid.startswith("acceptor-") and d["interim"] is True

    # the brief landed in the acceptor's inbox BEFORE the spawn, carrying
    # the verbatim goal + outcomes
    msgs = await ctx.broker.poll(aid, since_ts=None)
    assert len(msgs) == 1 and msgs[0].kind == "consult"
    body = msgs[0].body
    assert body["user_goal_verbatim"] == "build X per SKILL.md"
    assert body["outcomes"][0]["id"] == "o1"
    assert body["interim"] is True

    # the stub pool recorded an acceptor-role spawn
    assert any(s.get("role") == "acceptor" and s.get("handle") == aid
               for s in ctx.pool.spawns)
