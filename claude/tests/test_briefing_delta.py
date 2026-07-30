"""DESIGN-v7 2.2 — the code-assembled BRIEFING DELTA (learning propagation).

THE ROOT CAUSE: the injection seam shipped only load-bearing decisions;
DESIGN-v6 recorded 248 `learning` events that structurally never reached a
worker unless the neuron hand-flagged one. Now, at dispatch, the recipe's
recent `learning`/`review_finding`/`discovery` events relevant to the action
ride the SAME store-once-by-id injection the decisions do — pointers in
`Action.injected_context_ids["briefing"]`, text once in
`Plan.injected_context`, resolved by `read_object('action')` with zero
worker-side change.

Locked here:
- scope filtering: spec-intersect / same-plan / recipe-wide-unscoped IN,
  another plan's unshared traffic OUT;
- cap (8, newest-first) + per-entry truncation (~300 chars);
- idempotency: a re-dispatch over unchanged events does NOT churn the plan
  version (content-hash ids → identical pointer → no save);
- end-to-end read_object resolution (the worker-facing view);
- quarantine honesty: an ACCEPTED spec-learning is tagged `[rule]`, anything
  unratified is labeled `proposed (unratified)`.
"""

from edp_contracts import ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _scaffold(env, goal="g"):
    rid = _ok(await env.call("start_recipe", goal=goal,
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="do generic work"))
    return rid, sid, pid


def _stamp_spec(env, pid, aid, spec_ids):
    p = env.ctx.plans.load(pid)
    a = next(x for x in p.actions if x.action_id == aid)
    a.spec_ids = list(spec_ids)
    env.ctx.plans.save(p)


async def _briefing_view(env, pid, aid):
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id=aid)
    return (view.get("injected_context") or {}).get("briefing", [])


# ── scope filtering ──────────────────────────────────────────────────────────

async def test_spec_scoped_events_reach_only_matching_spec_actions(env):
    rid, _, pid = await _scaffold(env)
    env.ctx.specs.write_doc("spec-x", "# spec-x doc")
    _stamp_spec(env, pid, "a1", ["spec-x"])
    # spec-scoped learnings, neither emitted under any plan (no lineage)
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "lesson for x", "spec_id": "spec-x"}))
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "lesson for y", "spec_id": "spec-y"}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    briefing = await _briefing_view(env, pid, "a1")
    assert any("lesson for x" in b for b in briefing), briefing
    # spec-y does not intersect this action's spec_ids — filtered OUT
    assert not any("lesson for y" in b for b in briefing), briefing


async def test_plan_scoped_and_unscoped_in_other_plans_traffic_out(
        env, monkeypatch):
    rid, sid, pid = await _scaffold(env)
    # a sibling plan under a second step — its unshared events are noise here
    sid2 = _ok(await env.call("add_step", recipe_id=rid, description="other",
                              execution="spawn_planner"))["step_id"]
    pid2 = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid2,
                              shape="poc-iterate-build", goal="g2"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid2, action_id="b1",
                       description="other work"))

    # (b) same-plan: emitted by a worker of THIS plan (lineage stamps plan_id)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a1")
    monkeypatch.setenv("EDP_ROLE", "worker")
    _ok(await env.call("emit_recipe_event", kind="review_finding",
                       body={"summary": "same-plan finding"}))
    # OUT: another plan's spec-less event
    monkeypatch.setenv("EDP_HANDLE", f"{pid2}:b1")
    _ok(await env.call("emit_recipe_event", kind="discovery",
                       body={"summary": "other-plan discovery"}))
    monkeypatch.delenv("EDP_HANDLE")
    monkeypatch.delenv("EDP_ROLE")
    # (c) recipe-wide, no spec scope (the neuron's broadcast)
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="discovery",
                       body={"summary": "recipe-wide discovery"}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    briefing = await _briefing_view(env, pid, "a1")
    assert any("same-plan finding" in b for b in briefing), briefing
    assert any("recipe-wide discovery" in b for b in briefing), briefing
    assert not any("other-plan discovery" in b for b in briefing), briefing


# ── cap + truncation ─────────────────────────────────────────────────────────

async def test_cap_is_eight_newest_first_and_entries_truncate(env):
    rid, _, pid = await _scaffold(env)
    for i in range(1, 13):
        _ok(await env.call("emit_recipe_event", recipe_id=rid,
                           kind="discovery",
                           body={"summary": f"finding number {i:02d}"}))
    # one oversized entry, newest of all — must be truncated, not dropped
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="discovery",
                       body={"summary": "LONGEST " + "x" * 500}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    briefing = await _briefing_view(env, pid, "a1")
    assert len(briefing) == 8, briefing
    # newest-first: the oversized latest entry leads …
    assert "LONGEST" in briefing[0]
    assert "…" in briefing[0] and len(briefing[0]) < 400
    # … the oldest five (01–05) fell off the cap
    joined = "\n".join(briefing)
    assert "finding number 12" in joined
    assert "finding number 06" in joined
    assert "finding number 05" not in joined


# ── idempotency ──────────────────────────────────────────────────────────────

async def test_redispatch_with_unchanged_events_does_not_churn_plan(env):
    rid, _, pid = await _scaffold(env)
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "stable lesson"}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    p1 = env.ctx.plans.load(pid)
    assert p1.actions[0].injected_context_ids.get("briefing")

    # unchanged events → identical content-hash ids → no save, no churn
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1",
                   force=True)
    p2 = env.ctx.plans.load(pid)
    assert p2.version == p1.version, (
        "re-dispatch over unchanged events must not churn the plan version")
    assert p2.actions[0].injected_context_ids == \
        p1.actions[0].injected_context_ids

    # a NEW event does change the stamp on the next dispatch
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "fresh lesson"}))
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1",
                   force=True)
    p3 = env.ctx.plans.load(pid)
    assert p3.version > p2.version
    assert len(p3.actions[0].injected_context_ids["briefing"]) == 2


# ── end-to-end worker view ───────────────────────────────────────────────────

async def test_read_object_resolves_briefing_alongside_decisions(env):
    rid, _, pid = await _scaffold(env)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="settled: MiniLM embedder", load_bearing=True))
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "the loader chokes on BOM files"}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    # the raw pointer never leaks; both buckets resolve to full text
    assert "injected_context_ids" not in view
    inj = view["injected_context"]
    assert any("MiniLM" in t for t in inj["load_bearing_decisions"])
    assert any("chokes on BOM files" in t for t in inj["briefing"])
    # storage half: text lives ONCE in the plan map, ids on the action
    p = env.ctx.plans.load(pid)
    ev_ids = p.actions[0].injected_context_ids["briefing"]
    assert all(i.startswith("ev-") for i in ev_ids)
    assert all(i in (p.injected_context or {}) for i in ev_ids)


# ── quarantine honesty ───────────────────────────────────────────────────────

async def test_accepted_spec_learning_tags_rule_pending_stays_unratified(env):
    from datetime import datetime, timezone

    from edp_claude.schemas import Specialization

    rid, _, pid = await _scaffold(env)
    now = datetime.now(timezone.utc)
    env.ctx.specs.save(Specialization(
        spec_id="spec-x", neuron_id="n1", name="x", subject="x stack",
        created_at=now, updated_at=now))
    env.ctx.specs.write_doc("spec-x", "# spec-x doc")
    _stamp_spec(env, pid, "a1", ["spec-x"])

    # RATIFIED: proposed then accepted through the W3 gate (status 'promoted')
    lid = env.ctx.specs.append_proposed_learning(
        "spec-x", rule_text="always pin the port")
    env.ctx.specs.resolve_spec_learnings("spec-x", accept=[lid])
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "always pin the port",
                             "spec_id": "spec-x"}))
    # UNRATIFIED: emitted, never resolved
    _ok(await env.call("emit_recipe_event", recipe_id=rid, kind="learning",
                       body={"summary": "never guess ports",
                             "spec_id": "spec-x"}))

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    briefing = await _briefing_view(env, pid, "a1")
    ratified = [b for b in briefing if "always pin the port" in b]
    pending = [b for b in briefing if "never guess ports" in b]
    assert ratified and "[rule]" in ratified[0], briefing
    assert pending and "proposed (unratified)" in pending[0], briefing
    assert "[rule]" not in pending[0]
