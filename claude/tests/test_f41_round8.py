"""F41 (2026-08-20) — campaign Round 8 (second convergence pass) fixes.

Pins the confirmed twins from the R8 lens: SpecStore optimistic locking,
plan-sidecar mutator ownership, the budget gate at the paid bridge seam,
batch declared-order enforcement, the content-checked overlay drain, the
pinned dispatch-intent event, the degraded-tiering pointer round-trip, and
the truthful _sender framing.
"""

import json
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe, Specialization
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.store.ipc_lock import StoreConflict
from edp_claude.store.recipe_store import GATE_PINNED_KINDS
from edp_claude.store.tiering import (
    FILE_MARKER,
    dehydrate_plan_payload,
    hydrate_plan_payload,
)
from edp_claude.tools import build_registry
from edp_claude.tools._tools import _INBOX_FRAMING

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid, budget=None):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(), budget=budget or {},
    ))


def _save_plan(ctx, rid, plan_id, batch=None):
    def _act(aid, grp=None):
        a = Action(
            action_id=aid, description=f"do {aid}",
            status="pending", executor_mode="inline",
            acceptance=Acceptance(kind="manual_review", expected="x"))
        if grp:
            a.batch_group = grp
        return a
    acts = [_act("a1", batch), _act("a2", batch), _act("a3")]
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=acts))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _save_spec(ctx, sid="spec-f41"):
    ctx.specs.save(Specialization(
        spec_id=sid, neuron_id="n1", name=sid, subject="x stack",
        created_at=_now(), updated_at=_now()))
    return sid


# ── #1 — SpecStore conflicts loudly, never last-writer-wins ────────────────
def test_spec_store_concurrent_save_conflicts(tmp_path):
    ctx = make_context(tmp_path)
    sid = _save_spec(ctx)
    a = ctx.specs.load(sid)
    b = ctx.specs.load(sid)
    a.subject = "amender A"
    ctx.specs.save(a)
    b.subject = "amender B"
    with pytest.raises(StoreConflict):
        ctx.specs.save(b)
    # A's write survived; B was told to re-read, nothing was erased.
    assert ctx.specs.load(sid).subject == "amender A"


# ── #2 — plan-sidecar mutators bound to the planner's own plan ─────────────
async def test_planner_sidecar_mutators_refuse_foreign_plan(tmp_path,
                                                            monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "r41a:s1")     # own plan = r41a-s1
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r41a")
    _save_recipe(ctx, "r41b")
    _save_plan(ctx, "r41a", "r41a-s1")
    _save_plan(ctx, "r41b", "r41b-s1")
    t = _tools(ctx)

    res = await t["record_grounding_brief"].run({
        "plan_id": "r41b-s1", "content": "foreign map", "paths": []})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    res = await t["record_context"].run({
        "kind": "challenge_waiver", "plan_id": "r41b-s1",
        "text": "trivial, honest"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    res = await t["record_context"].run({
        "kind": "challenge_adjudication", "plan_id": "r41b-s1",
        "challenge_id": "c-x", "disposition": "rejected", "text": "no"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    # plan-target adversarial challenge refused BEFORE any paid call
    res = await t["adversarial_challenge"].run({
        "target_kind": "plan", "target_id": "r41b-s1",
        "content": "attack it", "lens": "break-the-acceptance"})
    assert isinstance(res, ToolError) and "not your plan" in res.message
    assert not (ctx.plans.root / "r41b-s1" / "challenges.jsonl").exists()

    # own plan stays writable
    ok = await t["record_grounding_brief"].run({
        "plan_id": "r41a-s1", "content": "own map", "paths": ["a.py"]})
    assert isinstance(ok, ToolOk), ok


# ── #3 — the budget gate sits at the paid seam itself ──────────────────────
async def test_delegate_call_refused_when_recipe_budget_exceeded(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r41c-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r41c", budget={"delegate_usd": 1.0})
    bdir = tmp_path / ".bridge"
    bdir.mkdir()
    (bdir / "audit-x.jsonl").write_text(
        json.dumps({"cost_usd": 2.0, "ok": True,
                    "caller": "r41c-s1:a1"}) + "\n", encoding="utf-8")

    from edp_claude.tools import bridge as B

    def _boom(**_kw):
        raise AssertionError("paid call went out past an exceeded budget")

    monkeypatch.setattr(B, "delegate_call", _boom)
    t = _tools(ctx)
    res = await t["delegate_generate"].run({"task": "write code"})
    assert isinstance(res, ToolError), res
    assert "over its declared budget" in res.message


# ── #4 — batch siblings record in DECLARED order ───────────────────────────
async def test_batch_head_cannot_skip_ahead_of_declared_order(tmp_path,
                                                              monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r41d-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r41d")
    _save_plan(ctx, "r41d", "r41d-s1", batch="b1")   # a1+a2 share b1
    t = _tools(ctx)

    # a2 terminal while a1 is still pending → refused
    res = await t["record_action_status"].run({
        "plan_id": "r41d-s1", "action_id": "a2", "status": "skipped",
        "evidence": "never reached a1"})
    assert isinstance(res, ToolError), res
    assert "declared order" in res.message
    assert ctx.plans.load("r41d-s1").actions[1].status == "pending"

    # non-terminal sibling progress is still fine (the member loop)
    ok = await t["record_action_status"].run({
        "plan_id": "r41d-s1", "action_id": "a2", "status": "in_progress"})
    assert isinstance(ok, ToolOk), ok

    # after a1 fails, marking the rest skipped stays legal (stop-on-failure).
    # (terminal claims need the grounding echo — post it like a worker would)
    ctx.plans.append_worklog("r41d-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r41d-s1:a1"})
    ok = await t["record_action_status"].run({
        "plan_id": "r41d-s1", "action_id": "a1", "status": "failed",
        "evidence": "tests failed"})
    assert isinstance(ok, ToolOk), ok
    ok = await t["record_action_status"].run({
        "plan_id": "r41d-s1", "action_id": "a2", "status": "skipped",
        "evidence": "earlier member failed"})
    assert isinstance(ok, ToolOk), ok


# ── #5 — the recompile drain is content-checked, never blind ───────────────
def test_write_doc_keeps_unfolded_learning_overlaid(tmp_path):
    ctx = make_context(tmp_path)
    sid = _save_spec(ctx)
    ctx.specs.write_doc(sid, "# base doc")
    l1 = ctx.specs.append_proposed_learning(
        sid, rule_text="NEVER log access tokens")
    l2 = ctx.specs.append_proposed_learning(
        sid, rule_text="always pin the port")
    ctx.specs.resolve_spec_learnings(sid, accept=[l1, l2])

    # recompile folds l2's text but OMITS l1's rule
    ctx.specs.write_doc(sid, "# recompiled\n\n- always pin the port\n")
    pending = {r["learning_id"] for r in
               ctx.specs.accepted_pending_learnings(sid)}
    assert pending == {l1}          # l2 drained, l1 retained
    # the omitted rule still reaches workers via the overlay
    doc = ctx.specs.read_doc(sid, with_overlay=True)
    assert "NEVER log access tokens" in doc

    # a recompile that folds it (reflowed case/spacing tolerated) drains it
    ctx.specs.write_doc(
        sid, "# recompiled v2\n\n- never  LOG access\n  tokens\n"
             "- always pin the port\n")
    assert ctx.specs.accepted_pending_learnings(sid) == []


# ── #6 — the dispatch-intent stamp is pinned to the hot tail ───────────────
def test_step_dispatch_emitted_is_gate_pinned():
    assert "step_dispatch_emitted" in GATE_PINNED_KINDS


# ── #8 — a degraded hydration keeps its recovery pointer through a save ────
def test_degraded_injected_context_keeps_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "1")
    plan_dir = tmp_path / "p1"
    plan_dir.mkdir()
    text = "landmine: the retention rule\n" + ("x" * 700)
    payload = {"actions": [], "injected_context": {"d1": text}}
    payload = dehydrate_plan_payload(payload, plan_dir)
    marker = payload["injected_context"]["d1"]
    assert marker.startswith(FILE_MARKER)
    ref = marker[len(FILE_MARKER):].splitlines()[0].strip()

    # sidecar goes missing → hydrate serves the digest (degraded)
    (plan_dir / ref).unlink()
    warnings: list[str] = []
    data = hydrate_plan_payload(payload, plan_dir, warnings)
    assert warnings and not data["injected_context"]["d1"].startswith(
        FILE_MARKER)

    # the next save must NOT persist the digest as an apparently-complete
    # inline value — the pointer survives, so a restored sidecar hydrates.
    again = dehydrate_plan_payload(data, plan_dir)
    val = again["injected_context"]["d1"]
    assert val.startswith(FILE_MARKER)
    assert ref in val


# ── #9 — the framing never sells _sender as verified provenance ────────────
def test_inbox_framing_does_not_claim_server_stamp():
    assert "server-stamped" not in _INBOX_FRAMING
    assert "claim" in _INBOX_FRAMING
