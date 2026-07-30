"""v7 (2026-07-13) — ONE open curiosity interrogator per recipe.

Measured defect: a neuron consumed the open curiosity's questions from its
inbox, spawned a SECOND curiosity for the same recipe, and declared itself
blocked — both conversation halves stranded. The guard: consult_curiosity
refuses a fresh spawn while the recipe's recorded interrogator is still
alive; follow-ups are unaffected; a dead open id is stale bookkeeping and
the spawn proceeds; the clear/done convergence releases the latch.
"""

from datetime import datetime, timezone

from edp_contracts import ToolOk

from edp_claude.schemas import Recipe

RID = "recipe-curi"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _save_recipe(env):
    now = datetime.now(timezone.utc)
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=RID, user_goal_verbatim="g", domain="generic",
        state="comprehending",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[], context={}, created_at=now, updated_at=now,
    )))


async def test_spawn_stamps_the_open_id(env):
    _save_recipe(env)
    d = _ok(await env.call("consult_curiosity", decision="d", context="c",
                           handle=RID))
    cid = d["curiosity_id"]
    r = env.ctx.recipes.load(RID)
    assert r.comprehension.curiosity_open_id == cid


async def test_second_spawn_refused_while_open_and_alive(env, monkeypatch):
    _save_recipe(env)
    d = _ok(await env.call("consult_curiosity", decision="d", context="c",
                           handle=RID))
    cid = d["curiosity_id"]
    # the stub pool reports the spawned curiosity alive
    res = await env.call("consult_curiosity", decision="d2", context="c2",
                         handle=RID)
    assert not isinstance(res, ToolOk), "second interrogator must be refused"
    msg = str(res)
    assert cid in msg and "FOLLOW-UP" in msg


async def test_followup_is_never_blocked_by_the_guard(env):
    _save_recipe(env)
    d = _ok(await env.call("consult_curiosity", decision="d", context="c",
                           handle=RID))
    cid = d["curiosity_id"]
    f = _ok(await env.call("consult_curiosity", decision="answers",
                           context="round 2", handle=RID,
                           curiosity_id=cid))
    assert f["mode"] == "followup"


async def test_dead_open_id_is_stale_and_spawn_proceeds(env):
    _save_recipe(env)
    r = env.ctx.recipes.load(RID)
    r.comprehension.curiosity_open_id = "curiosity-deadbeef"  # never spawned
    env.ctx.recipes.save(r)
    d = _ok(await env.call("consult_curiosity", decision="d", context="c",
                           handle=RID))
    assert d["mode"] == "spawned"
    r = env.ctx.recipes.load(RID)
    assert r.comprehension.curiosity_open_id == d["curiosity_id"]


async def test_clear_releases_the_latch(env):
    _save_recipe(env)
    d = _ok(await env.call("consult_curiosity", decision="d", context="c",
                           handle=RID))
    _ok(await env.call("broker_send", to=RID, kind="answer",
                       from_=d["curiosity_id"],
                       body={"clear": True, "status": "done"}))
    _ok(await env.call("reconcile", handle=RID, handle_type="recipe"))
    r = env.ctx.recipes.load(RID)
    assert r.comprehension.curiosity_cleared is True
    assert r.comprehension.curiosity_open_id is None
