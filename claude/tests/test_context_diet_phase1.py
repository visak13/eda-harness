"""Context-diet Phase 1 — bound the worker brief.

Locks the four Phase-1 mechanisms:

1a. The dispatch injection is a ranked BUDGET FILL (scope > relevance >
    recency, cut at EDP_WORKER_BRIEF_BUDGET) with a LOUD per-member elision
    marker — the path that measured ~47.6k tokens/action on the live Fit
    recipe is structurally bounded.
1b. `load_bearing` is scarce at write time: past the fold threshold NEW
    load-bearing decision writes refuse with the fold as the exit; past the
    scoping floor they must declare scope_plan_id or a subject tag (which
    now PERSISTS — an accepted-and-dropped tag would be the W9 silent-drop
    class again).
1c. The fold advisory has teeth: next_action carries a fold_obligation and
    pool_spawn_planner refuses past 2x the threshold.
1d. A full recipe read past 3x BUDGET degrades to the digest + oversize note
    unless confirm_oversize is passed (tiering shrinks disk, not hydration —
    the biggest live recipe hydrates ~194k tokens of decision text).
"""
from datetime import datetime, timezone

from edp_contracts import ToolError, ToolOk


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _refused(res, *needles):
    assert isinstance(res, ToolError), res
    assert res.code == "tool_precondition", res
    for n in needles:
        assert n in res.message, (n, res.message)
    return res


def _seed_lb(env, rid, n, size=400, prefix="seed"):
    """Append n active load-bearing decisions straight through the store
    (the write cap lives in the tool path; legacy-class bulk is store-side)."""
    from edp_claude.schemas import Decision
    r = env.ctx.recipes.load(rid)
    base = len(r.context.decisions)
    for i in range(n):
        r.context.decisions.append(Decision(
            id=f"{prefix}{base + i + 1}",
            text=f"{prefix} decision {i} " + ("x" * size),
            rationale="r", by="test",
            at=datetime.now(timezone.utc), load_bearing=True))
    env.ctx.recipes.save(r)


async def _plan_with_action(env, rid, action_id="a1", concerns=None):
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    kw = {"concerns": concerns} if concerns else {}
    _ok(await env.call("add_action", plan_id=pid, action_id=action_id,
                       description="work", **kw))
    return pid


# ── 1a: budget_fill primitive ──────────────────────────────────────────────

def test_budget_fill_prefix_and_first_item():
    from edp_claude.tools._bounds import approx_tokens, budget_fill
    items = [(f"d{i}", "x" * 400) for i in range(10)]     # ~100 tokens each
    taken, elided = budget_fill(items, budget=250)
    assert [k for k, _ in taken] == ["d0", "d1"], taken   # prefix, no packing
    assert elided == 8
    # the first item is taken even when it alone busts the budget
    taken, elided = budget_fill([("big", "y" * 9000)], budget=10)
    assert [k for k, _ in taken] == ["big"] and elided == 0
    # everything fits -> nothing elided
    taken, elided = budget_fill(items[:2], budget=10_000)
    assert len(taken) == 2 and elided == 0
    assert approx_tokens([t for _, t in taken]) < 10_000


# ── 1a: dispatch injection is bounded + loud ───────────────────────────────

async def test_injection_budget_caps_and_elides(env, monkeypatch):
    monkeypatch.setenv("EDP_WORKER_BRIEF_BUDGET", "300")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _seed_lb(env, rid, 12, size=400)                      # ~100+ tokens each
    pid = await _plan_with_action(env, rid)
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")

    p = env.ctx.plans.load(pid)
    a = next(x for x in p.actions if x.action_id == "a1")
    ptr = a.injected_context_ids or {}
    lb_ids = ptr.get("load_bearing_decisions", [])
    assert 0 < len(lb_ids) < 12, ptr                      # cut, not all-or-none
    assert ptr.get("elided_decisions"), "no elision pointer stamped"
    pmap = p.injected_context or {}
    note = pmap.get(ptr["elided_decisions"][0], "")
    assert "NOT injected" in note and "search_context" in note, note

    # the worker's read view carries the marker alongside the survivors
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    assert view["injected_context"]["elided_decisions"], view
    assert len(view["injected_context"]["load_bearing_decisions"]) == len(lb_ids)


async def test_injection_ranking_scope_then_relevance(env, monkeypatch):
    monkeypatch.setenv("EDP_WORKER_BRIEF_BUDGET", "250")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    # oldest first: an irrelevant recipe-wide filler fleet, then one decision
    # matching the action's concern, then one explicitly plan-scoped.
    _seed_lb(env, rid, 6, size=350, prefix="noise")
    from edp_claude.schemas import Decision
    r = env.ctx.recipes.load(rid)
    r.context.decisions.append(Decision(
        id="d-sec", text="security: sanitize every input " + "x" * 300,
        rationale="r", by="test", at=datetime.now(timezone.utc),
        load_bearing=True))
    env.ctx.recipes.save(r)
    pid = await _plan_with_action(env, rid, concerns=["security"])
    r = env.ctx.recipes.load(rid)
    r.context.decisions.append(Decision(
        id="d-scoped", text="scoped: this plan ships dark " + "x" * 300,
        rationale="r", by="test", at=datetime.now(timezone.utc),
        load_bearing=True, scope_plan_id=pid))
    env.ctx.recipes.save(r)

    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    p = env.ctx.plans.load(pid)
    a = next(x for x in p.actions if x.action_id == "a1")
    lb_ids = (a.injected_context_ids or {}).get("load_bearing_decisions", [])
    # the scoped decision wins rank 1, the concern-relevant one rank 2 —
    # the noise fleet is what the budget cuts.
    assert lb_ids[0] == "d-scoped", lb_ids
    assert "d-sec" in lb_ids, lb_ids
    assert not any(i.startswith("noise") for i in lb_ids[:2]), lb_ids


# ── 1b: load_bearing scarcity at write time ────────────────────────────────

async def test_lb_write_refused_at_fold_threshold(env, monkeypatch):
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "5")
    monkeypatch.setenv("EDP_LB_SCOPE_FLOOR", "3")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _seed_lb(env, rid, 5, size=50)
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="one more binding rule", load_bearing=True,
                         subject="rules")
    _refused(res, "fold threshold", "fold_decisions")
    # non-load-bearing writes stay open
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="an ordinary note-decision"))
    # escape hatch reverts to advisory
    monkeypatch.setenv("EDP_DECISION_FOLD_HARD", "0")
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="operator-overridden LB write", load_bearing=True))


async def test_lb_scoping_floor_requires_scope_or_subject(env, monkeypatch):
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "100")
    monkeypatch.setenv("EDP_LB_SCOPE_FLOOR", "2")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _seed_lb(env, rid, 2, size=50)
    res = await env.call("record_context", kind="decision", recipe_id=rid,
                         text="unscoped untagged LB", load_bearing=True)
    _refused(res, "scoping floor", "scope_plan_id")
    # a subject tag satisfies the floor AND persists (no silent drop)
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="tagged LB", load_bearing=True,
                       subject="embedder", title="Embedder stays MiniLM"))
    d = env.ctx.recipes.load(rid).context.decisions[-1]
    assert d.subject == "embedder" and d.title == "Embedder stays MiniLM"


# ── 1c: fold teeth ─────────────────────────────────────────────────────────

def _seed_active_plain(env, rid, n):
    from edp_claude.schemas import Decision
    r = env.ctx.recipes.load(rid)
    for i in range(n):
        r.context.decisions.append(Decision(
            id=f"p{i + 1}", text=f"plain {i}", rationale="r", by="test",
            at=datetime.now(timezone.utc)))
    env.ctx.recipes.save(r)


async def test_planner_spawn_refused_past_fold_ceiling(env, monkeypatch):
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "2")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    _seed_active_plain(env, rid, 5)                       # 5 > 2x2
    res = await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid)
    _refused(res, "fold ceiling", "fold_decisions")
    # under the ceiling the guard passes (spawn may still fail at the fake
    # pool — the point is it is NOT the fold refusal).
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "100")
    res2 = await env.call("pool_spawn_planner", recipe_id=rid, step_id=sid)
    if isinstance(res2, ToolError):
        assert "fold ceiling" not in res2.message


async def test_fold_obligation_over_threshold(env, monkeypatch):
    monkeypatch.setenv("EDP_DECISION_FOLD_THRESHOLD", "3")
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    from edp_claude.tools._tools import _fold_obligation
    r = env.ctx.recipes.load(rid)
    assert _fold_obligation(r) is None
    _seed_active_plain(env, rid, 4)
    r = env.ctx.recipes.load(rid)
    ob = _fold_obligation(r)
    assert ob and "fold_decisions" in ob and "execute it" in ob


# ── 1d: hydration interlock ────────────────────────────────────────────────

async def test_recipe_full_read_oversize_degrades_to_digest(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    # blow past 3x BUDGET (27k tokens ~= 108KB json): 30 x 4KB decisions
    _seed_lb(env, rid, 30, size=4000)
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "recipe", recipe_id=rid)
    assert view.get("oversize") is True, view.get("_detail")
    assert view.get("_detail") == "digest"
    assert "confirm_oversize" in view.get("full_available_via", "")
    assert view["approx_tokens_full"] > 27_000
    # the explicit override still hands back the whole object
    full = await objects.read_object(env.ctx, "recipe", recipe_id=rid,
                                     confirm_oversize=True)
    assert full.get("_detail") != "digest"
    assert len(full["context"]["decisions"]) >= 30


async def test_recipe_full_read_small_recipe_unchanged(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="small", load_bearing=True))
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "recipe", recipe_id=rid)
    assert view.get("_detail") != "digest"          # full read passes through
    assert "oversize" not in view


async def test_legacy_oversize_injected_context_self_labels(env):
    """A pre-budget action carrying a huge legacy full-text stamp self-labels
    with a budget report at read time (it cannot be re-cut — the text is the
    stamp — but the reader must be told what it is holding)."""
    from edp_claude.schemas import Plan
    pid = "plan-legacy-oversize"
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d", "status": "pending",
                  "depends_on": [], "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"},
                  "injected_context": {
                      "load_bearing_decisions": ["z" * 50_000]}}],
        context={})))
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    rep = view.get("injected_context_report")
    assert rep and rep["oversize"] is True, view.keys()
