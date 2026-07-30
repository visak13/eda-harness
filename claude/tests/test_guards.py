"""W2 leg 3+4 (DESIGN-v6 §W2): fail-closed CONSTRAINT guards + DUPLICATE-
DISPATCH guard.

Covers `edp_claude.guards.check_constraints` (the deterministic, read-only
engine) and its four wired seams in `tools/_tools.py`:
- RecordActionStatus  → action_result constraint REFUSES a violating done.
- PoolSpawnWorker      → spec_doc constraint REFUSES the spawn; a
                         done/needs_review action re-spawn is refused unless
                         force=true.
- emit_recipe_event / broker_send → llm_payload is WARN-ONLY (never blocks).

Env discipline (d7/d8): the inherited worker shell env (EDP_ROLE/EDP_HANDLE/
EDP_TIER_WRITE) is neutralised IN-PROCESS via monkeypatch — no `env` prefix,
no external shell. All doc/text assertions are done in PYTHON, never grep
(the acceptance verify shell has neither env nor grep). d24: guards.py adds
NO schema/hydration validator — the o6 legacy fixture 0e7ca8 still loads
byte-identically (asserted below).
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.guards import Violation, check_constraints, describe
from edp_claude.schemas import Recipe
from edp_claude.schemas.recipe import Constraint, Decision, RejectedOption
from edp_claude.server import make_context
from edp_claude.tools import build_registry


# ── env discipline (d7/d8): clear the inherited worker env so every test
# starts from a known baseline; all env control is in-process. ────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE"):
        monkeypatch.delenv(var, raising=False)


def _now():
    return datetime.now(timezone.utc)


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _data(res):
    return res.data if isinstance(res.data, dict) else res.data.model_dump()


def _make_recipe(rid, *, decisions=(), rejected=()):
    r = Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "short",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        context={},
        created_at=_now(), updated_at=_now(),
    ))
    r.context.decisions.extend(decisions)
    r.context.rejected_options.extend(rejected)
    return r


def _decision(did, *, match, applies_to, message, kind="constraint",
              match_kind="substring", status="active"):
    return Decision(
        id=did, text=f"decision {did}", rationale="settled",
        by="neuron", at=_now(), kind=kind, status=status,
        constraint=Constraint(match=match, match_kind=match_kind,
                              applies_to=list(applies_to), message=message),
    )


# ════════════════════════════════════════════════════════════════════════════
# check_constraints — the deterministic read-only engine
# ════════════════════════════════════════════════════════════════════════════
def test_substring_hit_names_decision_and_message():
    r = _make_recipe("r1", decisions=[_decision(
        "d10", match="nomic", applies_to=["action_result"],
        message="use MiniLM, never nomic")])
    vios = check_constraints(r, "action_result", "I wired the nomic embedder")
    assert len(vios) == 1
    v = vios[0]
    assert isinstance(v, Violation)
    assert v.decision_id == "d10"
    assert v.message == "use MiniLM, never nomic"
    assert v.source == "decision"
    assert v.payload_kind == "action_result"
    # describe() surfaces id + message + pattern for the refusal string
    blob = describe(vios)
    assert "d10" in blob and "never nomic" in blob


def test_regex_hit():
    r = _make_recipe("r2", decisions=[_decision(
        "d11", match=r"nomic|instructor-xl", match_kind="regex",
        applies_to=["action_result"], message="banned embedders")])
    assert check_constraints(r, "action_result", "used instructor-xl")
    assert not check_constraints(r, "action_result", "used MiniLM")


def test_applies_to_filters_by_payload_kind():
    # a spec_doc-only constraint must NOT fire on an action_result payload.
    r = _make_recipe("r3", decisions=[_decision(
        "d12", match="nomic", applies_to=["spec_doc"], message="m")])
    assert check_constraints(r, "action_result", "nomic here") == []
    assert len(check_constraints(r, "spec_doc", "nomic here")) == 1


def test_superseded_decision_does_not_bite():
    r = _make_recipe("r4", decisions=[_decision(
        "d13", match="nomic", applies_to=["action_result"], message="m",
        status="superseded")])
    assert check_constraints(r, "action_result", "nomic") == []


def test_legacy_prose_decision_is_noop():
    # a decision with constraint=None (every legacy prose decision) is skipped.
    d = Decision(id="d14", text="prose only, no teeth", rationale="x",
                 by="neuron", at=_now())
    r = _make_recipe("r5", decisions=[d])
    assert check_constraints(r, "action_result", "anything at all") == []


def test_rejected_option_constraint_bites():
    r = _make_recipe("r6", rejected=[RejectedOption(
        id="x1", text="the nomic embedder", reason="rejected",
        constraint=Constraint(match="nomic", match_kind="substring",
                             applies_to=["spec_doc"], message="banned ban"))])
    vios = check_constraints(r, "spec_doc", "spec says use nomic")
    assert len(vios) == 1 and vios[0].source == "rejected_option"
    assert vios[0].decision_id == "x1"


def test_invalid_regex_is_no_hit_not_crash():
    # an un-compilable stored pattern must not raise — it can never match.
    r = _make_recipe("r7", decisions=[_decision(
        "d15", match="[unclosed(", match_kind="regex",
        applies_to=["action_result"], message="m")])
    assert check_constraints(r, "action_result", "[unclosed( literal") == []


def test_empty_text_and_none_recipe_are_safe():
    r = _make_recipe("r8", decisions=[_decision(
        "d16", match="x", applies_to=["action_result"], message="m")])
    assert check_constraints(r, "action_result", "") == []
    assert check_constraints(None, "action_result", "x") == []


# ════════════════════════════════════════════════════════════════════════════
# Seam wiring — build a real recipe+plan via the tool surface
# ════════════════════════════════════════════════════════════════════════════
async def _recipe_with_plan(t, *, action_ids=("a1",)):
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


async def _append_decision(ctx, rid, decision):
    r = ctx.recipes.load(rid)
    r.context.decisions.append(decision)
    ctx.recipes.save(r)


# ── (a) RecordActionStatus: action_result constraint refuses a violating done
async def test_record_action_status_refuses_banned_completion(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _append_decision(ctx, rid, _decision(
        "d20", match="nomic", applies_to=["action_result"],
        message="use MiniLM, never nomic"))

    res = await t["record_action_status"].run(
        {"plan_id": pid, "action_id": "a1", "status": "done",
         "evidence": "wired up the nomic embedder as requested"})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "d20" in res.message
    assert "never nomic" in res.message
    # fail-closed: nothing recorded — the action is NOT done.
    assert ctx.plans.load(pid).actions[0].status != "done"


async def test_record_action_status_clean_completion_proceeds(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    await _append_decision(ctx, rid, _decision(
        "d21", match="nomic", applies_to=["action_result"], message="m"))

    res = await t["record_action_status"].run(
        {"plan_id": pid, "action_id": "a1", "status": "done",
         "evidence": "wired up the MiniLM embedder as settled"})
    assert isinstance(res, ToolOk), res
    assert _data(res)["status"] == "done"
    assert ctx.plans.load(pid).actions[0].status == "done"


# ── (b) PoolSpawnWorker: spec_doc constraint refuses the spawn
async def test_spawn_refused_on_contradicting_spec_doc(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    ctx.specs.write_doc(
        "spec-embed", "House style: always use the nomic embedder for RAG.")
    p = ctx.plans.load(pid)
    p.actions[0].spec_ids = ["spec-embed"]
    ctx.plans.save(p)
    await _append_decision(ctx, rid, _decision(
        "d30", match="nomic", applies_to=["spec_doc"],
        message="MiniLM is settled; nomic is banned"))

    res = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "spec-embed" in res.message
    assert "d30" in res.message
    # fail-closed: nothing dispatched
    assert not [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


async def test_spawn_proceeds_when_spec_doc_clean(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    ctx.specs.write_doc(
        "spec-ok", "House style: use the settled MiniLM embedder for RAG.")
    p = ctx.plans.load(pid)
    p.actions[0].spec_ids = ["spec-ok"]
    ctx.plans.save(p)
    await _append_decision(ctx, rid, _decision(
        "d31", match="nomic", applies_to=["spec_doc"], message="banned"))

    res = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(res, ToolOk), res
    assert [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


# ── (b) PoolSpawnWorker: duplicate-dispatch guard (W2 leg 4)
async def test_duplicate_dispatch_refused_and_echoes_completion(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    p = ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.actions[0].acceptance.actual = "RESULT: the computed answer is 42"
    ctx.plans.save(p)

    res = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"
    assert "already 'done'" in res.message
    # the recorded completion is attached (answer comes back, not a re-spawn)
    assert "42" in res.message
    assert not [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


async def test_duplicate_dispatch_needs_review_also_refused(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    p = ctx.plans.load(pid)
    p.actions[0].status = "needs_review"
    ctx.plans.save(p)
    res = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})
    assert isinstance(res, ToolError) and "needs_review" in res.message


async def test_duplicate_dispatch_force_overrides(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid, sid, pid = await _recipe_with_plan(t)
    p = ctx.plans.load(pid)
    p.actions[0].status = "done"
    p.actions[0].acceptance.actual = "done earlier"
    ctx.plans.save(p)

    res = await t["pool_spawn_worker"].run(
        {"plan_id": pid, "action_id": "a1", "force": True})
    assert isinstance(res, ToolOk), res
    assert [s for s in ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]


# ── (c) emit_recipe_event / broker_send: warn-only (never blocks comms)
async def test_emit_recipe_event_warns_but_never_blocks(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    rid = _data(await t["start_recipe"].run(
        {"goal": "g", "domain": "api"}))["recipe_id"]
    await _append_decision(ctx, rid, _decision(
        "d40", match="secret", applies_to=["llm_payload"],
        message="do not leak the secret"))

    # a body matching an llm_payload constraint STILL flows (warn-only).
    res = await t["emit_recipe_event"].run(
        {"kind": "learning", "recipe_id": rid,
         "body": {"summary": "the secret sauce is X"}})
    assert isinstance(res, ToolOk), res
    # detection itself is proven at the engine level (belt-and-braces):
    assert check_constraints(
        ctx.recipes.load(rid), "llm_payload", "the secret sauce is X")


async def test_broker_send_not_blocked_by_constraint(tmp_path):
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    # broker_send resolves the recipe from lineage; with a clean env it has
    # none, so the warn path is a no-op — the key contract is it NEVER blocks.
    res = await t["broker_send"].run(
        {"to": "topic:x", "kind": "observation", "body": {"note": "secret"}})
    assert isinstance(res, ToolOk), res


# ── o6 REGRESSION BAR: legacy fixture loads byte-identically AND the guards
# are a structural no-op on it (legacy prose decisions carry no constraint).
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_o6_legacy_fixture_byte_identical_and_guards_noop(monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)   # tiering OFF
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

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
        "legacy fixture round-trip is NOT byte-identical — a guard field "
        "leaked into the schema")

    # guards no-op: no legacy decision carries a constraint, so EVERY
    # payload kind scans clean (advisory continuity).
    for kind in ("action_result", "spec_doc", "llm_payload"):
        assert check_constraints(model, kind, "any text at all") == []
