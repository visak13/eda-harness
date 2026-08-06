"""v7 WS3 — outcome-lineage write gates + affects persistence (§2.1/§2.5/§2.6).

Covers: add_step/add_action `serves` validation (unknown ids always refuse;
empty refuses only under EDP_V7_WRITE_GATES=1), and record_context(decision)
persisting `affects` (previously accepted-and-dropped on this route)."""

import pytest

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _mk_recipe_with_outcome(env) -> str:
    res = await env.call("start_recipe", goal="lineage gate test", domain="test")
    rid = res.data["recipe_id"]
    r = env.ctx.recipes.load(rid)
    from edp_claude.schemas.recipe import Outcome
    r.comprehension.expected_outcomes.append(
        Outcome(id="o1", description="it works", verification="tests pass"))
    env.ctx.recipes.save(r)
    return rid


async def test_add_step_refuses_unknown_serves_id(env):
    rid = await _mk_recipe_with_outcome(env)
    res = await env.call("add_step", recipe_id=rid, description="build it",
                         execution="inline", serves=["o9"])
    assert not res.ok and "unknown outcome id" in res.message


async def test_add_step_accepts_valid_serves_and_persists(env):
    rid = await _mk_recipe_with_outcome(env)
    res = await env.call("add_step", recipe_id=rid, description="build it",
                         execution="inline", serves=["o1"])
    assert res.ok
    r = env.ctx.recipes.load(rid)
    assert r.steps[-1].serves == ["o1"]


async def test_add_step_empty_serves_allowed_until_gates_flip(env):
    rid = await _mk_recipe_with_outcome(env)
    res = await env.call("add_step", recipe_id=rid, description="legacy style",
                         execution="inline")
    assert res.ok          # staged: guides don't teach serves yet


async def test_add_step_empty_serves_refused_under_gate_flag(env, monkeypatch):
    monkeypatch.setenv("EDP_V7_WRITE_GATES", "1")
    rid = await _mk_recipe_with_outcome(env)
    res = await env.call("add_step", recipe_id=rid, description="orphan work",
                         execution="inline")
    assert not res.ok and "serves is empty" in res.message


async def test_add_action_serves_validated_and_persisted(env):
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step",
                   serves=["o1"], execution="spawn_planner")
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         goal="do it", shape="linear-build")
    pid = res.data["plan_id"]
    bad = await env.call("add_action", plan_id=pid, action_id="a1",
                         description="build the thing", serves=["nope"])
    assert not bad.ok and "unknown outcome id" in bad.message
    ok = await env.call("add_action", plan_id=pid, action_id="a1",
                        description="build the thing", serves=["o1"])
    assert ok.ok
    p = env.ctx.plans.load(pid)
    assert p.actions[-1].serves == ["o1"]


async def test_record_context_decision_persists_affects(env):
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step one",
                   execution="inline", serves=["o1"])
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="use JSON tool output, not native calls",
                         title="json-tool-output", affects=["s1"])
    assert res.ok
    r = env.ctx.recipes.load(rid)
    d = r.context.decisions[-1]
    assert d.affects == ["s1"]
    # round-trips through the store (emission gate emits when non-empty)
    import json
    raw = json.loads(
        (env.ctx.recipes.root / rid / "recipe.json").read_text("utf-8"))
    assert raw["context"]["decisions"][-1]["affects"] == ["s1"]


async def test_review_policy_gates_review_legs(env):
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step",
                   execution="spawn_planner", serves=["o1"])
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         goal="do it", shape="linear-build",
                         review_policy={"triggers": ["protected surface"],
                                        "justify": {}})
    pid = res.data["plan_id"]
    p = env.ctx.plans.load(pid)
    assert p.review_policy["triggers"] == ["protected surface"]
    # unjustified review leg → refused
    bad = await env.call("add_action", plan_id=pid, action_id="r1",
                         description="review the build", serves=["o1"],
                         leg_kind="review")
    assert not bad.ok and "must be justified" in bad.message
    # justify it, then it lands
    p.review_policy = {"triggers": ["protected surface"],
                       "justify": {"r1": "touches auth middleware"}}
    env.ctx.plans.save(p)
    ok = await env.call("add_action", plan_id=pid, action_id="r1",
                        description="review the build", serves=["o1"],
                        leg_kind="review")
    assert ok.ok
    # build legs unaffected by the policy
    ok2 = await env.call("add_action", plan_id=pid, action_id="a2",
                         description="build more", serves=["o1"])
    assert ok2.ok


async def test_lineage_layers_counted(env):
    await env.call("record_test_lineage", test_id="t/u.spec.ts::x",
                   verifies=["outcome:r:o1"], covers=["src/u.ts"])
    await env.call("record_test_lineage", test_id="t/e2e.spec.ts::flow",
                   verifies=["outcome:r:o1"], covers=["src/u.ts"],
                   layer="e2e")
    rep = await env.call("test_lineage_report")
    assert rep.data["layer_counts"] == {"unit": 1, "e2e": 1}
