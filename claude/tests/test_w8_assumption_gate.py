"""W8 (DESIGN-v6 §W8): Assumption acknowledgement-gate schema tests.

The W8 fields (load_bearing / status / acked_by / acked_at / affects) are
purely ADDITIVE. This asserts the d24 grandfather contract: a legacy shape
loads as "acked"; a load_bearing assumption stays "pending"; a plain new
non-load-bearing one resolves to "acked".
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.recipe import Assumption, Decision
from edp_claude.server import make_context
from edp_claude.tools import build_registry


# ── env discipline (d7/d8): neutralise the inherited worker shell env so
# every tool test starts from a known baseline (no `env`/`env -u` prefix —
# all env control is in-process monkeypatch). ────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _make_recipe(rid):
    return Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "short",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        context={},
        created_at=_now(), updated_at=_now(),
    ))


def test_legacy_shape_grandfathered_acked():
    # A legacy Assumption carrying NONE of the W8 fields must load and
    # resolve to status == "acked" (grandfathered, d24).
    a = Assumption(
        id="as1",
        text="the target repo is a git worktree",
        by="neuron",
        at=datetime(2026, 1, 1, 0, 0, 0),
    )
    assert a.status == "acked"
    assert a.load_bearing is False
    # Emission-gated: a legacy assumption serializes byte-shape-identical to
    # the pre-W8 schema (no new keys leak to an extra='forbid' old reader).
    dumped = a.model_dump()
    for k in ("load_bearing", "status", "acked_by", "acked_at", "affects"):
        assert k not in dumped


def test_new_load_bearing_is_pending():
    a = Assumption(
        id="as2",
        text="MiniLM is the settled embedder",
        by="neuron",
        at=datetime(2026, 1, 1, 0, 0, 0),
        load_bearing=True,
    )
    assert a.status == "pending"
    assert a.load_bearing is True


def test_new_non_load_bearing_is_acked():
    a = Assumption(
        id="as3",
        text="tests run under uv",
        by="neuron",
        at=datetime(2026, 1, 1, 0, 0, 0),
        load_bearing=False,
    )
    assert a.status == "acked"


# ════════════════════════════════════════════════════════════════════════════
# a2 — record_context(kind=assumption) PERSISTS the W8 fields; the digest and
# recipe_context SURFACE the unacked load-bearing set; a reload re-lists them.
# ════════════════════════════════════════════════════════════════════════════
async def test_record_context_assumption_persists_load_bearing_and_affects(
        tmp_path):
    """record_context(kind=assumption, load_bearing=true, affects=[...])
    persists load_bearing + affects and resolves status to "pending"; a plain
    non-load-bearing write persists as "acked". Previously the route DROPPED
    load_bearing/affects and everything persisted as acked."""
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-w8"))

    ok = await t["record_context"].run(
        {"kind": "assumption", "recipe_id": "r-w8",
         "text": "MiniLM is the settled embedder", "load_bearing": True,
         "affects": ["s3", "a4"]})
    assert isinstance(ok, ToolOk), ok

    # read back off disk — the load-bearing assumption is pending w/ affects.
    r = ctx.recipes.load("r-w8")
    lb = next(a for a in r.context.assumptions if a.load_bearing)
    assert lb.status == "pending"
    assert lb.affects == ["s3", "a4"]
    assert lb.text == "MiniLM is the settled embedder"

    # a non-load-bearing write grandfathers straight to "acked".
    ok2 = await t["record_context"].run(
        {"kind": "assumption", "recipe_id": "r-w8",
         "text": "tests run under uv"})
    assert isinstance(ok2, ToolOk), ok2
    r = ctx.recipes.load("r-w8")
    plain = next(a for a in r.context.assumptions
                 if a.text == "tests run under uv")
    assert plain.status == "acked" and plain.load_bearing is False


async def test_get_recipe_digest_lists_pending_assumptions(tmp_path):
    """get_recipe_digest carries the unacked load-bearing assumption under
    pending_assumptions as {id, title, body}; a non-load-bearing (acked) one
    does NOT appear."""
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-w8d"))
    await t["record_context"].run(
        {"kind": "assumption", "recipe_id": "r-w8d",
         "text": "the target repo is a git worktree", "load_bearing": True,
         "affects": ["s1"]})
    await t["record_context"].run(
        {"kind": "assumption", "recipe_id": "r-w8d",
         "text": "an acked side note"})

    res = await t["get_recipe_digest"].run({"recipe_id": "r-w8d"})
    assert isinstance(res, ToolOk), res
    data = res.data if isinstance(res.data, dict) else res.data.model_dump(
        mode="json")
    pend = data["pending_assumptions"]
    assert len(pend) == 1, pend
    row = pend[0]
    assert set(row) == {"id", "title", "body"}
    assert row["body"] == "the target repo is a git worktree"
    assert row["title"]  # a non-empty derived handle
    # the acked one is not surfaced as pending
    assert all("side note" not in p["body"] for p in pend)
    # the count is also reflected in the pending-counts part
    assert data["pending"]["load_bearing_pending"] == 1


async def test_reload_relists_pending_assumptions(tmp_path):
    """Compaction-safety: pending_assumptions is re-derived from persisted
    state, so a FRESH context/store built over the same dir still lists the
    unacked load-bearing assumption (no cached epoch state)."""
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-w8r"))
    await t["record_context"].run(
        {"kind": "assumption", "recipe_id": "r-w8r",
         "text": "embeddings live in the pgvector store", "load_bearing": True})

    # a brand-new context over the same tmp dir (simulates a restart/compact)
    ctx2 = make_context(tmp_path)
    t2 = _tools(ctx2)
    res = await t2["get_recipe_digest"].run({"recipe_id": "r-w8r"})
    data = res.data if isinstance(res.data, dict) else res.data.model_dump(
        mode="json")
    bodies = [p["body"] for p in data["pending_assumptions"]]
    assert "embeddings live in the pgvector store" in bodies


# ════════════════════════════════════════════════════════════════════════════
# a3 — FAIL-CLOSED DISPATCH GUARD (both spawn tools) + record_user_answer
# ack/reject mode + affects-scoping + the W8 §5 direction escape hatch.
# ════════════════════════════════════════════════════════════════════════════
def _data(res):
    return res.data if isinstance(res.data, dict) else res.data.model_dump()


async def _recipe_with_plan(t, *, action_ids=("a1",)):
    """Build a real recipe + step + plan (+ actions) via the tool surface, so
    both pool_spawn_worker (plan/action) and pool_spawn_planner (recipe/step)
    have a live target to refuse/allow."""
    rid = _data(await t["start_recipe"].run(
        {"goal": "g", "domain": "api"}))["recipe_id"]
    sid = _data(await t["add_step"].run(
        {"recipe_id": rid, "description": "build",
         "execution": "spawn_planner"}))["step_id"]
    pid = _data(await t["create_plan"].run(
        {"recipe_id": rid, "step_id": sid, "shape": "poc-iterate-build",
         "goal": "build the thing"}))["plan_id"]
    for aid in action_ids:
        await t["add_action"].run(
            {"plan_id": pid, "action_id": aid,
             "description": "do generic narrow work"})
    return rid, sid, pid


async def _add_load_bearing(t, rid, text, *, affects=None):
    ok = await t["record_context"].run(
        {"kind": "assumption", "recipe_id": rid, "text": text,
         "load_bearing": True, "affects": list(affects or [])})
    assert isinstance(ok, ToolOk), ok


async def test_worker_spawn_refused_on_pending_assumption(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _add_load_bearing(t, rid, "MiniLM is the settled embedder")

    res = await t["pool_spawn_worker"].run(
        {"plan_id": pid, "action_id": "a1"})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    # names the count, the id, and the VERBATIM fix
    assert "1 unacked load-bearing assumptions" in res.message
    assert "MiniLM" in res.message  # the title/body of the named assumption
    assert "record_user_answer(assumption_id" in res.message
    # fail-closed: nothing was dispatched
    assert not [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


async def test_planner_spawn_refused_on_pending_assumption(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _add_load_bearing(t, rid, "the graph store is Neo4j")

    res = await t["pool_spawn_planner"].run(
        {"recipe_id": rid, "step_id": sid})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "unacked load-bearing assumptions" in res.message
    assert "Neo4j" in res.message
    assert "record_user_answer(assumption_id" in res.message
    assert not [s for s in ctx.pool.spawns
                if s.get("role") == "planner"]


async def test_ack_via_record_user_answer_unblocks_spawn(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _add_load_bearing(t, rid, "MiniLM is the settled embedder")
    aid = ctx.recipes.load(rid).context.assumptions[0].id

    # refused before ack
    pre = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(pre, ToolError)

    ack = await t["record_user_answer"].run(
        {"recipe_id": rid, "assumption_id": aid, "answer": "ack",
         "by": "user"})
    assert isinstance(ack, ToolOk), ack
    a = next(x for x in ctx.recipes.load(rid).context.assumptions
             if x.id == aid)
    assert a.status == "acked" and a.acked_by == "user" and a.acked_at

    # now the spawn proceeds (a worker dispatch is recorded)
    post = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(post, ToolOk), post
    assert [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


async def test_reject_via_record_user_answer_becomes_rejected_option(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _add_load_bearing(t, rid, "the deploy target is k8s")
    aid = ctx.recipes.load(rid).context.assumptions[0].id

    rej = await t["record_user_answer"].run(
        {"recipe_id": rid, "assumption_id": aid, "answer": "reject",
         "by": "user"})
    assert isinstance(rej, ToolOk), rej

    r = ctx.recipes.load(rid)
    a = next(x for x in r.context.assumptions if x.id == aid)
    assert a.status == "rejected"
    # a rejected_option CANDIDATE carrying the assumption text now exists
    assert any(x.text == "the deploy target is k8s"
               for x in r.context.rejected_options)
    # and it no longer blocks dispatch (not pending)
    post = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(post, ToolOk), post


async def test_branch_id_and_assumption_id_mutually_exclusive(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-uax"))
    res = await t["record_user_answer"].run(
        {"recipe_id": "r-uax", "branch_id": "b1", "assumption_id": "a1",
         "answer": "ack"})
    assert isinstance(res, ToolError)
    assert "mutually exclusive" in res.message


async def test_affects_scoping_blocks_only_targeted_spawn(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t, action_ids=("a1", "a2"))
    # the assumption bears ONLY on action a1
    await _add_load_bearing(t, rid, "a1 needs the pinned CUDA build",
                            affects=["a1"])

    blocked = await t["pool_spawn_worker"].run(
        {"plan_id": pid, "action_id": "a1"})
    assert isinstance(blocked, ToolError), blocked

    allowed = await t["pool_spawn_worker"].run(
        {"plan_id": pid, "action_id": "a2"})
    assert isinstance(allowed, ToolOk), allowed
    assert [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a2"]


async def test_direction_decision_escape_hatch_unblocks_and_is_auditable(
        tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _add_load_bearing(t, rid, "MiniLM is the settled embedder")
    aid = ctx.recipes.load(rid).context.assumptions[0].id

    # blocked until the neuron records the explicit W8 §5 direction decision
    pre = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(pre, ToolError)

    r = ctx.recipes.load(rid)
    r.context.decisions.append(Decision(
        id="d1",
        text=f"proceeding on unacked assumption {aid} at user risk",
        rationale="user explicitly accepted the risk",
        by="neuron", at=_now(), kind="direction"))
    ctx.recipes.save(r)

    # the escape hatch unblocks the spawn
    post = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(post, ToolOk), post
    assert [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]

    # ...and the override is auditable: the direction decision persists in the
    # recipe context (and thus every digest thereafter).
    dg = _data(await t["get_recipe_digest"].run({"recipe_id": rid}))
    blob = json.dumps(dg)
    assert "at user risk" in blob and aid in blob

    # a direction naming a DIFFERENT id must NOT unblock (boundary-safe token):
    # re-pend by adding a second load-bearing assumption the direction ignores.
    await _add_load_bearing(t, rid, "the reranker is bge-large")
    aid2 = ctx.recipes.load(rid).context.assumptions[-1].id
    assert aid2 != aid
    still = await t["pool_spawn_worker"].run(
        {"plan_id": pid, "action_id": "a1"})
    assert isinstance(still, ToolError), (
        "a2 has no direction override, so the gate must still block")


# ── o6 REGRESSION BAR: legacy fixture loads byte-identically AND its dispatch
# is UNAFFECTED (legacy assumptions grandfathered acked → guard never fires).
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical_and_dispatch_unaffected(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)   # tiering OFF
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )
    from edp_claude.fsm import pending_load_bearing_assumptions
    from edp_claude.tools._tools import _blocking_load_bearing_assumptions

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), (
        f"legacy fixture {LEGACY_RID} missing under {RECIPES}")
    original = (rdir / "recipe.json").read_text(encoding="utf-8")

    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    # a9: dehydrate into tmp_path, never the live fixture dir. For an
    # already-reffed field dehydrate ALWAYS re-writes the sidecar
    # (tiering.py:97), so pointing it at `rdir` rewrites 370 real files
    # per run and races test_w1_context_diet's copytree. The payload is
    # root-independent, so this changes nothing the test ASSERTS.
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)
    assert reserialized == original, (
        "legacy fixture round-trip is NOT byte-identical — W8 leaked a field")

    # dispatch UNAFFECTED: no legacy assumption is pending, so the guard's
    # blocking set is empty for ANY target (grandfathered acked).
    assert pending_load_bearing_assumptions(model) == []
    assert _blocking_load_bearing_assumptions(model, "any-action") == []
    assert _blocking_load_bearing_assumptions(model, None) == []
