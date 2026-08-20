"""F42 (2026-08-20) — campaign Round 9 (wake plane + F41 convergence) fixes.

Pins: wiring-CRUD ownership, supervisor registry reconcile, full-identity
subscription reuse, cross-restart effect dedup, heartbeat-protected GC for
unindexed subs, unique action ids + canonical batch head, foreign-plan
notes, idempotent learning resolution, anchored overlay drain, anchored
digest detection, steer pinning, and the locked ack ledger.
"""

import json
import time
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe, Specialization
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.store.recipe_store import GATE_PINNED_KINDS, _pinned
from edp_claude.store.tiering import FILE_MARKER, dehydrate_plan_payload
from edp_claude.tools import build_registry
from edp_claude.tools._tools import (
    _gc_stale_subscriptions,
    _subscription_matches,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _act(aid, grp=None, status="pending"):
    a = Action(action_id=aid, description=f"do {aid}", status=status,
               executor_mode="inline",
               acceptance=Acceptance(kind="manual_review", expected="x"))
    if grp:
        a.batch_group = grp
    return a


def _save_plan(ctx, rid, plan_id, actions):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=actions))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


# ── #1 — monitor CRUD is bound to the caller's own wiring ──────────────────
async def test_wiring_crud_refuses_foreign_handle(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r42a-s1:a1")
    ctx = make_context(tmp_path)
    t = _tools(ctx)

    res = await t["list_subscriptions"].run({"handle": "r42b-s1"})
    assert isinstance(res, ToolError) and "not your wiring" in res.message

    res = await t["unobserve"].run({"subscription_id": "sub-x",
                                    "handle": "r42b-s1"})
    assert isinstance(res, ToolError) and "not your wiring" in res.message

    # observe with a foreign owner refused before any artifact lands
    res = await t["observe"].run({
        "spec": "rx.broker(me)", "bindings": {"me": "r42b-s1"}})
    assert isinstance(res, ToolError) and "not your wiring" in res.message
    root = ctx.recipes.root.parent / ".reactive"
    assert not list(root.glob("sub-*.spec")) if root.exists() else True

    # own handle passes
    ok = await t["list_subscriptions"].run({"handle": "r42a-s1:a1"})
    assert isinstance(ok, ToolOk), ok


async def test_observe_refuses_overwriting_foreign_indexed_sid(
        tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    # the OTHER shell's subscription, created from its own (foreground) seat
    ok = await t["observe"].run({
        "spec": "rx.broker(me)", "bindings": {"me": "r42v-s1"},
        "subscription_id": "sub-victim"})
    assert isinstance(ok, ToolOk), ok
    # a spawned worker tries a genuine re-spec of that sid
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r42w-s1:a1")
    res = await t["observe"].run({
        "spec": "rx.worklog(plan_id)", "bindings": {"plan_id": "r42w-s1"},
        "subscription_id": "sub-victim"})
    assert isinstance(res, ToolError), res
    assert "not to you" in res.message
    root = ctx.recipes.root.parent / ".reactive"
    assert (root / "sub-victim.spec").read_text(
        encoding="utf-8") == "rx.broker(me)"       # untouched


# ── #3 — owner/rate are part of subscription identity ──────────────────────
def test_subscription_reuse_rejects_changed_runtime(tmp_path):
    sid = "sub-rt"
    (tmp_path / f"{sid}.spec").write_text("rx.broker(me)", encoding="utf-8")
    (tmp_path / f"{sid}.runtime.json").write_text(
        json.dumps({"owner": "", "min_interval_ms": 0}), encoding="utf-8")
    same = {"owner": "", "min_interval_ms": 0}
    assert _subscription_matches(tmp_path, sid, "rx.broker(me)", {}, None,
                                 runtime=same)
    changed = {"owner": "", "min_interval_ms": 2000}
    assert not _subscription_matches(tmp_path, sid, "rx.broker(me)", {},
                                     None, runtime=changed)


# ── #2 — the supervisor reconciles with the on-disk registry ───────────────
def test_supervisor_discovers_and_retires_rules_live(tmp_path, monkeypatch):
    from edp_claude.reactive import registry as R

    class _FakePopen:
        _next = 51000

        def __init__(self, cmd, **kw):
            self.cmd = cmd
            _FakePopen._next += 1
            self.pid = _FakePopen._next
            self._rc = None

        def poll(self):
            return self._rc

        @property
        def returncode(self):
            return self._rc

        def terminate(self):
            self._rc = -15

        def kill(self):
            self._rc = -9

        def wait(self, timeout=None):
            return self._rc

    monkeypatch.setattr(R.subprocess, "Popen", _FakePopen)
    reg = R.RuleRegistry(tmp_path / "reg")
    reg.register_rule("a", "rx.broker(me)", None, "o", bindings={"me": "o"})
    sup = R.RuleSupervisor(
        reg, R.SupervisorConfig(agent_home=tmp_path, driver_python="python"))
    sup._acquire_singleton()
    for rule in reg.enabled_rules():
        sup._children[rule.name] = sup._spawn(rule)
    assert set(sup.tracked_pids()) == {"a"}
    try:
        # ANOTHER process registers rule b → next tick discovers it
        reg.register_rule("b", "rx.broker(me)", None, "o2",
                          bindings={"me": "o2"})
        sup._reap_and_restart()
        assert set(sup.tracked_pids()) == {"a", "b"}
        # ANOTHER process disables a → next tick retires its live child
        reg.disable("a")
        sup._reap_and_restart()
        assert set(sup.tracked_pids()) == {"b"}
        # an exhausted rule cools down, then is re-discovered with a
        # fresh budget
        sup._children["b"]._rc = 1
        sup._restarts["b"] = sup.cfg.max_child_restarts
        sup._reap_and_restart()
        assert "b" not in sup.tracked_pids()          # exhausted this tick
        sup._exhausted_at["b"] -= sup.cfg.restart_reset_secs + 1
        sup._reap_and_restart()
        assert "b" in sup.tracked_pids()              # respawned, budget reset
        assert sup._restarts["b"] == 0
    finally:
        sup.shutdown()


# ── #4 — a restarted dispatcher does not re-execute audited effects ────────
def test_effect_dispatcher_seen_seed_dedupes_replay():
    from edp_claude.reactive.effects import (
        OUTCOME_DEDUPED,
        OUTCOME_EXECUTED,
        EffectDispatcher,
        EffectSpec,
    )

    spec = EffectSpec.compile({
        "action": "notify_above", "rule_id": "t42",
        "args": {"kind": {"const": "alert"}, "body": {"from_event": "body"}}})
    calls: list = []

    def _exec(action, args):
        calls.append((action, args))
        return {"ok": True}

    lines: list = []
    d1 = EffectDispatcher(spec, owner="o", executor=_exec,
                          audit_sink=lines.append)
    event = {"body": {"plan_id": "p1", "n": 7}}
    first = d1.handle(event)
    assert first.outcome == OUTCOME_EXECUTED
    # "crash": a REPLACEMENT process seeds from the audit trail's keys
    d2 = EffectDispatcher(spec, owner="o", executor=_exec,
                          audit_sink=lines.append,
                          seen_seed=[ln["idem_key"] for ln in lines])
    replay = d2.handle(event)
    assert replay.outcome == OUTCOME_DEDUPED
    assert len(calls) == 1


# ── #5 — GC spares an unindexed sub with a fresh heartbeat ─────────────────
def test_gc_spares_unindexed_sub_with_fresh_heartbeat(tmp_path):
    now = time.time()
    old = now - 25 * 3600                       # past the 24h TTL
    spec = tmp_path / "sub-live.spec"
    spec.write_text("rx.worklog(plan_id)", encoding="utf-8")
    import os as _os
    _os.utime(spec, (old, old))
    (tmp_path / "sub-live.spec.hb").write_text(
        json.dumps({"pid": 1, "ts": _now().isoformat()}), encoding="utf-8")
    removed = _gc_stale_subscriptions(tmp_path, keep="other",
                                      ttl_secs=24 * 3600, now_ts=now)
    assert removed == 0 and spec.exists()
    # stale heartbeat → swept, heartbeat file collected too
    (tmp_path / "sub-live.spec.hb").write_text(
        json.dumps({"pid": 1, "ts": "2020-01-01T00:00:00+00:00"}),
        encoding="utf-8")
    removed = _gc_stale_subscriptions(tmp_path, keep="other",
                                      ttl_secs=24 * 3600, now_ts=now)
    assert removed == 1
    assert not spec.exists()
    assert not (tmp_path / "sub-live.spec.hb").exists()


# ── #6 — unique action ids + canonical batch head ──────────────────────────
def test_plan_refuses_duplicate_action_ids():
    with pytest.raises(ValueError, match="duplicate action_id"):
        Plan(plan_id="p", recipe_id="r", recipe_step_id="s1",
             domain="software_engineering", shape="linear-build", goal="g",
             state="dispatching", actions=[_act("a1"), _act("a1")])


async def test_spawn_refuses_non_canonical_batch_head(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r42c")
    _save_plan(ctx, "r42c", "r42c-s1",
               [_act("a1", "b1", status="in_progress"),
                _act("a2", "b1", status="in_progress")])
    t = _tools(ctx)
    res = await t["pool_spawn_worker"].run({
        "plan_id": "r42c-s1", "action_id": "a2",
        "action_ids": ["a1", "a2"]})
    assert isinstance(res, ToolError), res
    assert "not the head of batch group" in res.message
    # the pre-launch refusal rolled the stamped members back to pending
    p = ctx.plans.load("r42c-s1")
    assert [a.status for a in p.actions] == ["pending", "pending"]


# ── #7 — notes land in the caller's own plan worklog only ──────────────────
async def test_note_refuses_foreign_plan(tmp_path, monkeypatch):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r42d")
    _save_recipe(ctx, "r42e")
    _save_plan(ctx, "r42d", "r42d-s1", [_act("a1")])
    _save_plan(ctx, "r42e", "r42e-s1", [_act("a1")])
    t = _tools(ctx)

    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "r42d:s1")
    res = await t["record_context"].run({
        "kind": "note", "plan_id": "r42e-s1", "text": "skip this branch"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r42d-s1:a1")
    res = await t["record_context"].run({
        "kind": "note", "plan_id": "r42e-s1", "text": "misleading note"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    ok = await t["record_context"].run({
        "kind": "note", "plan_id": "r42d-s1", "text": "own note"})
    assert isinstance(ok, ToolOk), ok


# ── #8 — learning resolution is idempotent ─────────────────────────────────
def test_resolve_spec_learnings_retry_is_noop(tmp_path):
    ctx = make_context(tmp_path)
    ctx.specs.save(Specialization(
        spec_id="spec-f42", neuron_id="n1", name="x", subject="x",
        created_at=_now(), updated_at=_now()))
    lid = ctx.specs.append_proposed_learning(
        "spec-f42", rule_text="always pin the port")
    r1 = ctx.specs.resolve_spec_learnings("spec-f42", accept=[lid])
    assert r1["accepted"] == [lid]
    r2 = ctx.specs.resolve_spec_learnings("spec-f42", accept=[lid])  # retry
    assert r2["accepted"] == []                    # idempotent no-op
    spec = ctx.specs.load("spec-f42")
    assert len([e for e in spec.entries
                if e.text == "always pin the port"]) == 1


# ── #9 — a negated mention cannot drain the rule ───────────────────────────
def test_write_doc_drain_is_unit_anchored(tmp_path):
    ctx = make_context(tmp_path)
    ctx.specs.save(Specialization(
        spec_id="spec-f42b", neuron_id="n1", name="x", subject="x",
        created_at=_now(), updated_at=_now()))
    ctx.specs.write_doc("spec-f42b", "# base")
    lid = ctx.specs.append_proposed_learning(
        "spec-f42b", rule_text="NEVER log access tokens")
    ctx.specs.resolve_spec_learnings("spec-f42b", accept=[lid])
    # the rule text appears only inside a negating sentence → NOT drained
    ctx.specs.write_doc(
        "spec-f42b",
        "# v2\n\nSuperseded rule: NEVER log access tokens; logging them "
        "is now required.\n")
    assert [r["learning_id"] for r in
            ctx.specs.accepted_pending_learnings("spec-f42b")] == [lid]
    # the rule as its own (wrapped) bullet DOES drain
    ctx.specs.write_doc(
        "spec-f42b", "# v3\n\n- never LOG access\n  tokens\n")
    assert ctx.specs.accepted_pending_learnings("spec-f42b") == []


# ── #10 — digest recognition is anchored ───────────────────────────────────
def test_tiering_prose_mentioning_ref_is_not_a_digest(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "1")
    plan_dir = tmp_path / "p"
    plan_dir.mkdir()
    # a one-liner that merely resembles a digest gains no bogus marker
    payload = {"actions": [], "injected_context": {
        "d1": "Example: [42 bytes; full text in README.md]"}}
    out = dehydrate_plan_payload(payload, plan_dir)
    assert not out["injected_context"]["d1"].startswith(FILE_MARKER)
    # an EDIT that mentions its own ref is re-dehydrated as new content,
    # not mistaken for the old digest (which would resurrect stale bytes)
    (plan_dir / "evidence").mkdir()
    (plan_dir / "evidence" / "a1-actual-record.md").write_text(
        "old stale bytes", encoding="utf-8")
    act = {"action_id": "a1", "acceptance": {
        "actual": "note that full text in evidence/a1-actual-record.md is "
                  "unavailable today " + ("x" * 700),
        "actual_ref": "evidence/a1-actual-record.md"}}
    out = dehydrate_plan_payload({"actions": [act]}, plan_dir)
    acc = out["actions"][0]["acceptance"]
    assert "old stale bytes" != acc["actual"]
    assert acc["actual_ref"] != "evidence/a1-actual-record.md"  # new CAS name


# ── #12 — steer records are pinned to the hot tail ─────────────────────────
def test_steer_records_are_pinned():
    assert "steer_sent" in GATE_PINNED_KINDS
    assert _pinned({"kind": "message_sent", "msg_kind": "steer"})
    assert not _pinned({"kind": "message_sent", "msg_kind": "fyi"})


# ── #13 — ack ledger writes never erase a peer's entry ─────────────────────
def test_ack_ledger_preserves_both_handles(tmp_path):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r42f")
    ctx.recipes.write_ack_entry("r42f", "h1", {"epoch": "e1"})
    ctx.recipes.write_ack_entry("r42f", "h2", {"epoch": "e1"})
    led = ctx.recipes.read_ack_ledger("r42f")
    assert set(led) == {"h1", "h2"}
