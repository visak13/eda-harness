"""v7 WS3 §2.1 — scoped invalidation: decision writes/supersedes wake ONLY
the handles in the transitive affects-closure, as `ground_delta` digests."""

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _seed(env) -> str:
    res = await env.call("start_recipe", goal="delta wake test", domain="test")
    rid = res.data["recipe_id"]
    from edp_claude.schemas.recipe import Outcome
    r = env.ctx.recipes.load(rid)
    r.comprehension.expected_outcomes.append(
        Outcome(id="o1", description="works", verification="tests"))
    env.ctx.recipes.save(r)
    await env.call("add_step", recipe_id=rid, description="one",
                   execution="inline", serves=["o1"])
    await env.call("add_step", recipe_id=rid, description="two",
                   execution="inline", serves=["o1"], depends_on=["s1"])
    return rid


async def test_scoped_decision_wakes_only_affected_handles(env):
    rid = await _seed(env)
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="tool output rides JSON", title="json-out",
                         affects=["s1"])
    assert res.ok
    # s1 is affected directly; s2 depends on s1 → transitive closure
    for handle in (f"{rid}:s1", f"{rid}:s2"):
        msgs = await env.ctx.broker.poll(handle)
        kinds = [m.kind for m in msgs]
        assert "ground_delta" in kinds, (handle, kinds)
        body = [m for m in msgs if m.kind == "ground_delta"][-1].body
        assert body["digest"] == "json-out" and body["change"] == "recorded"


async def test_unscoped_decision_wakes_nobody(env):
    rid = await _seed(env)
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="recipe-wide direction", title="wide")
    assert res.ok
    for handle in (f"{rid}:s1", f"{rid}:s2"):
        msgs = await env.ctx.broker.poll(handle)
        assert not [m for m in msgs if m.kind == "ground_delta"], handle


async def test_supersede_publishes_delta_with_replacement(env):
    rid = await _seed(env)
    await env.call("record_context", kind="decision", recipe_id=rid,
                   text="old choice", title="old", affects=["s1"])
    await env.call("record_context", kind="decision", recipe_id=rid,
                   text="new choice", title="new")
    res = await env.call("supersede_decision", recipe_id=rid,
                         decision_id="d1", replaced_by="d2")
    assert res.ok
    msgs = await env.ctx.broker.poll(f"{rid}:s1")
    deltas = [m for m in msgs if m.kind == "ground_delta"
              and m.body.get("change") == "superseded"]
    assert deltas and deltas[-1].body["replaced_by"] == "d2"
