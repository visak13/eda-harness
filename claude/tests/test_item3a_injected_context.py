"""Item 3A — automatic decision -> worker propagation.

Locks the core delivery-channel fix: a LOAD-BEARING recipe decision (and the
banned/rejected options) reach the FRESH worker automatically via the
read_object('action') it already does — no silent hand-copy. Non-load-bearing
decisions are kept OUT (grounding stays tight). The s26 embedder-drift class
('worker used legacy nomic because the never-nomic decision never reached it')
becomes structurally impossible.

s17 RP-A (2026-06-07) UPDATE — STORE-ONCE-BY-ID. The dispatcher no longer
duplicates the decision TEXT onto every action. It stamps only by-id POINTERS
on the action (`injected_context_ids`) and stores each referenced text ONCE in
the plan's by-id map (`Plan.injected_context`). `read_object('action')` resolves
the pointer to full text at read time, so the WORKER VIEW is byte-identical to
the pre-RP-A behaviour. These tests assert BOTH halves: (1) the storage is
deduped (ids on the action, text once on the plan, no per-action text); (2) the
read-time resolution returns the same full-text grounding dict a worker expects.
Also guards the emission gate and pre-RP-A back-compat.
"""
from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def test_item3a_spawn_stamps_load_bearing_context(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="MiniLM is the settled embedder; never nomic",
                       load_bearing=True))
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="a non-load-bearing aside"))   # load_bearing=False
    _ok(await env.call("record_context", kind="rejected_option", recipe_id=rid,
                       text="ollama/nomic-embed-text"))
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build",
                             goal="build the thing"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic work"))   # generic -> passes Guard B

    # spawn may fail at the fake pool, but the stamp runs BEFORE the spawn and
    # is persisted regardless — assert on the saved plan.
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    p = env.ctx.plans.load(pid)
    a = next(a for a in p.actions if a.action_id == "a1")

    # RP-A storage: the action carries only by-id POINTERS, NOT the text.
    assert a.injected_context_ids is not None, "no pointer was stamped"
    assert a.injected_context is None, "RP-A must NOT duplicate text on action"
    lb_ids = a.injected_context_ids.get("load_bearing_decisions", [])
    banned_ids = a.injected_context_ids.get("banned_options", [])
    assert lb_ids and banned_ids, a.injected_context_ids
    # the non-load-bearing decision id is NOT pointed at (grounding stays tight)
    assert len(lb_ids) == 1, lb_ids

    # RP-A storage: the TEXT lives ONCE in the plan by-id map.
    pmap = p.injected_context or {}
    assert any("never nomic" in pmap.get(i, "") for i in lb_ids), pmap
    assert not any("aside" in t for t in pmap.values()), pmap
    assert any("ollama/nomic-embed-text" in pmap.get(i, "")
               for i in banned_ids), pmap

    # RP-A read-time resolution: a worker reading the action gets byte-identical
    # full-text grounding (the legacy shape), and never sees the raw ids.
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    assert "injected_context_ids" not in view, "raw ids leaked to read view"
    lb = view["injected_context"]["load_bearing_decisions"]
    assert any("never nomic" in x for x in lb), lb
    assert not any("aside" in x for x in lb), lb
    assert "ollama/nomic-embed-text" in view["injected_context"]["banned_options"]


async def test_item3a_no_load_bearing_context_leaves_action_clean(env):
    # with no load_bearing decisions and no rejected options, nothing is
    # stamped — both pointer and text stay absent (and serialize away).
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="ordinary decision"))   # not load_bearing
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build",
                             goal="build the thing"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic work"))
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    p = env.ctx.plans.load(pid)
    a = next(a for a in p.actions if a.action_id == "a1")
    assert a.injected_context is None
    assert a.injected_context_ids is None
    # emission gates: neither new key appears in the serialized action/plan
    assert "injected_context" not in a.model_dump()
    assert "injected_context_ids" not in a.model_dump()
    assert "injected_context" not in p.model_dump()


async def test_item3a_storage_is_deduped_across_actions(env):
    """RP-A's win: the SAME load-bearing text is stored ONCE in the plan map,
    not once per action — even with many actions sharing it."""
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    big = "NEVER nomic; settled MiniLM-384d embedder. " * 40   # ~1.7KB
    # >1200 chars: the routed write verb refuses (W1.1 write cap), so seed
    # the oversized LEGACY-class decision through the store — the schema is
    # deliberately cap-free (o6) and RP-A dedup must handle old big texts.
    from datetime import datetime, timezone

    from edp_claude.schemas import Decision
    _r = env.ctx.recipes.load(rid)
    _r.context.decisions.append(Decision(
        id="d1", text=big, rationale="r", by="test",
        at=datetime.now(timezone.utc), load_bearing=True))
    env.ctx.recipes.save(_r)
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    for aid in ("a1", "a2", "a3"):
        _ok(await env.call("add_action", plan_id=pid, action_id=aid,
                           description="work"))
        await env.call("pool_spawn_worker", plan_id=pid, action_id=aid)

    p = env.ctx.plans.load(pid)
    # the big text appears exactly ONCE in the whole serialized plan (the map),
    # not 3× (one per action) as the pre-RP-A duplication would.
    import json
    blob = json.dumps(p.model_dump(mode="json"))
    assert blob.count("NEVER nomic; settled MiniLM-384d embedder.") == 40, \
        "decision text should be stored once (40 reps in the single map entry)"
    # but every action still resolves to the full text at read time
    from edp_claude import objects
    for aid in ("a1", "a2", "a3"):
        view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                         action_id=aid)
        assert big in view["injected_context"]["load_bearing_decisions"][0]


async def test_item3a_pre_rpa_full_text_action_still_reads(env):
    """Back-compat: an OLD action that carries full-text injected_context (and
    NO by-id pointer) — written before RP-A — must still read unchanged."""
    from datetime import datetime, timezone
    from edp_claude.schemas import Plan
    pid = "plan-legacy-rpa"
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d", "status": "pending",
                  "depends_on": [], "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"},
                  "injected_context": {
                      "load_bearing_decisions": ["legacy never-nomic text"],
                      "banned_options": ["nomic"]}}],
        context={})))
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    assert view["injected_context"]["load_bearing_decisions"] == [
        "legacy never-nomic text"]
    assert view["injected_context"]["banned_options"] == ["nomic"]
