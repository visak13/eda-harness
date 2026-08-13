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
                   serves=["o1"], execution="spawn_planner", estimate={"hours": 1})
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
                   execution="spawn_planner", estimate={"hours": 1}, serves=["o1"])
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


async def test_review_policy_string_justify_refuses_not_crashes(env):
    """2026-08-13 live s1 crash + s3 friction. First a planner authored
    review_policy.justify as a plain STRING and the review-leg gate died
    with "'str' object has no attribute 'get'"; then the teaching refusal
    still left a trap — create_plan ACCEPTED the string, so every review
    leg was unauthorable with no working remedy (the refusal's update_object
    pointer refuses type=plan). Now refused at BOTH doors: create_plan (the
    root) and add_action (defense in depth for legacy plans on disk)."""
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step",
                   execution="spawn_planner", estimate={"hours": 1},
                   serves=["o1"])
    # door 1 — authoring: the malformed shape never enters the record
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         goal="do it", shape="linear-build",
                         review_policy={"triggers": ["protected surface"],
                                        "justify": "everything is risky"})
    assert not res.ok
    assert "must be a mapping" in res.message
    assert "str" in res.message
    # door 2 — a legacy plan already on disk with the bad shape still gets
    # the teaching refusal, not a traceback
    ok = await env.call("create_plan", recipe_id=rid, step_id="s1",
                        goal="do it", shape="linear-build")
    pid = ok.data["plan_id"]
    p = env.ctx.plans.load(pid)
    p.review_policy = {"triggers": ["protected surface"],
                       "justify": "everything is risky"}
    env.ctx.plans.save(p)
    bad = await env.call("add_action", plan_id=pid, action_id="r1",
                         description="review the build", serves=["o1"],
                         leg_kind="review")
    assert not bad.ok
    assert "must be a mapping" in bad.message
    assert "str" in bad.message


async def test_recreate_drafted_plan_preserves_authored_actions(env):
    """2026-08-13 s3 friction: re-creating a DRAFTED plan is the documented
    repair path for plan-level fields (update_object refuses type=plan) —
    so it must preserve authored actions, not wipe them."""
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step",
                   execution="spawn_planner", estimate={"hours": 1},
                   serves=["o1"])
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         goal="do it", shape="linear-build")
    pid = res.data["plan_id"]
    assert (await env.call("add_action", plan_id=pid, action_id="a1",
                           description="build the thing", serves=["o1"])).ok
    # repair: re-create with a corrected review_policy
    fixed = await env.call("create_plan", recipe_id=rid, step_id="s1",
                           goal="do it", shape="linear-build",
                           review_policy={"triggers": ["protected surface"],
                                          "justify": {"r1": "auth surface"}})
    assert fixed.ok
    p = env.ctx.plans.load(pid)
    assert [a.action_id for a in p.actions] == ["a1"], (
        "re-creating a drafted plan wiped its authored actions — the repair "
        "path destroyed the work it exists to save")
    assert p.review_policy["justify"] == {"r1": "auth surface"}


async def _mk_plan_with_sketch_step(env):
    """Recipe → step carrying an acceptance_sketch → drafted plan."""
    rid = await _mk_recipe_with_outcome(env)
    await env.call("add_step", recipe_id=rid, description="step",
                   execution="spawn_planner", estimate={"hours": 1},
                   serves=["o1"],
                   acceptance_sketch=["tests pass", "docs updated"])
    res = await env.call("create_plan", recipe_id=rid, step_id="s1",
                         goal="do it", shape="linear-build")
    return rid, res.data["plan_id"]


async def test_add_action_sketch_covers_folds_into_plan_mapping(env):
    """2026-08-13 s3 friction (operator steer): one-shot authoring —
    coverage declared per action at add_action must land in
    Plan.sketch_covered_by without a record_plan resend."""
    rid, pid = await _mk_plan_with_sketch_step(env)
    assert (await env.call("add_action", plan_id=pid, action_id="a1",
                           description="build + test", serves=["o1"],
                           sketch_covers=["tests pass"])).ok
    assert (await env.call("add_action", plan_id=pid, action_id="a2",
                           description="write the docs", serves=["o1"],
                           sketch_covers=["docs updated"])).ok
    p = env.ctx.plans.load(pid)
    assert p.sketch_covered_by == {"tests pass": ["a1"],
                                   "docs updated": ["a2"]}
    # and the flow-down gate now passes without any explicit plan-level map
    from edp_claude.tools._tools import _step_flowdown_gaps
    r = env.ctx.recipes.load(rid)
    assert _step_flowdown_gaps(r, p) == []


async def test_add_action_sketch_covers_refuses_unknown_line(env):
    """A typo'd sketch line refuses AT AUTHORING with the step's actual
    list — not later as an 'unmapped line' record_plan refusal."""
    _, pid = await _mk_plan_with_sketch_step(env)
    res = await env.call("add_action", plan_id=pid, action_id="a1",
                         description="build + test", serves=["o1"],
                         sketch_covers=["test pass"])  # typo: missing 's'
    assert not res.ok
    assert "not in the owning step's acceptance_sketch" in res.message
    assert "tests pass" in res.message  # the door that opens: real lines shown
