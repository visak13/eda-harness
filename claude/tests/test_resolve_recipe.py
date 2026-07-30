"""resolve_recipe — the cross-session resume front door (THE killer-check
fix). Exact open goal → resume; closed → create; near → confirm."""

from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.tools import build_registry


def _now():
    return datetime.now(timezone.utc)


def _save(ctx, rid, goal, state, final=None):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim=goal, user_goal_distilled=goal,
        domain="software_engineering", state=state,
        comprehension={"branches": [], "expected_outcomes": []},
        steps=([] if state == "created" else [{
            "step_id": "s1", "kind": "k", "description": "d",
            "status": "pending", "depends_on": [], "execution": "inline"}]),
        final_outcome=final, created_at=_now(), updated_at=_now(),
    ))


async def _resolve(ctx, goal):
    tools = {t.name: t for t in build_registry(ctx)}
    r = await tools["resolve_recipe"].run({"goal": goal})
    assert isinstance(r, ToolOk), r
    return r.data


async def test_no_recipes_create(tmp_path):
    d = await _resolve(make_context(tmp_path), "build a thing")
    assert d["decision"] == "create"


async def test_exact_open_goal_resumes(tmp_path):
    ctx = make_context(tmp_path)
    _save(ctx, "r1", "Build a stateless auth method", "executing")
    # whitespace/case variation must still match (normalized)
    d = await _resolve(ctx, "  build a STATELESS auth   method ")
    assert d["decision"] == "resume"
    assert d["recipe_id"] == "r1"


async def test_closed_recipe_not_resumed(tmp_path):
    ctx = make_context(tmp_path)
    _save(ctx, "r1", "Build a stateless auth method", "closed",
          final={"status": "succeeded", "summary": "done"})
    d = await _resolve(ctx, "Build a stateless auth method")
    assert d["decision"] == "create"  # finished → new, not resume


async def test_near_match_confirms(tmp_path):
    ctx = make_context(tmp_path)
    _save(ctx, "r1",
          "build a stateless auth method with rotating keys", "executing")
    d = await _resolve(ctx, "build a stateless auth method with keys")
    assert d["decision"] == "confirm"
    assert d["recipe_id"] == "r1"


async def test_unrelated_open_recipe_confirms_not_orphans(tmp_path):
    # 2026-05-26: an open recipe exists but the new text doesn't match it.
    # We must NOT silently `create` (that orphans the open work) — surface
    # it as `confirm` with open_recipes so the user chooses (resume vs
    # fresh). Creating-and-orphaning was the resume bug.
    ctx = make_context(tmp_path)
    _save(ctx, "r1", "write a chess engine in rust", "executing")
    d = await _resolve(ctx, "build a stateless auth method")
    assert d["decision"] == "confirm"
    assert any(o["recipe_id"] == "r1" for o in d["open_recipes"])


async def test_resume_by_intent_surfaces_open_recipe(tmp_path):
    # the actual bug: `/neuron resume working` → goal "resume working"
    # has ~zero overlap with the real goal → previously `create` (orphan).
    # Now → `confirm` with the open recipe in open_recipes so the neuron
    # can resume by intent.
    ctx = make_context(tmp_path)
    _save(ctx, "r1", "build a java rest application", "executing")
    d = await _resolve(ctx, "resume working")
    assert d["decision"] == "confirm"
    assert d["recipe_id"] == "r1"                 # most-recent open
    assert d["open_recipes"][0]["recipe_id"] == "r1"


async def test_create_only_when_no_open_recipes(tmp_path):
    # with zero open recipes, a fresh goal still creates.
    ctx = make_context(tmp_path)
    _save(ctx, "r1", "old done thing", "closed",
          final={"status": "succeeded", "summary": "done"})
    d = await _resolve(ctx, "a brand new goal")
    assert d["decision"] == "create"


def test_recipe_store_list_ids(tmp_path):
    ctx = make_context(tmp_path)
    assert ctx.recipes.list_ids() == []
    _save(ctx, "rA", "goal a", "created")
    _save(ctx, "rB", "goal b", "created")
    assert ctx.recipes.list_ids() == ["rA", "rB"]
