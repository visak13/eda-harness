"""F40 (2026-08-20) — campaign Round 7 (convergence re-attack) fixes.

Pins the confirmed unfixed twins and fix-introduced gaps from the R7 lens:
planner native-verb ownership, worker action-granularity, unconditional
_sender stamping, invalid-findings arrays, slot orphans, effect-content
reuse, GC heartbeat lease, EDP_PARENT lineage, budget honesty notes.
"""

import json
import os
import time
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools import bridge as B
from edp_claude.tools import build_registry
from edp_claude.tools._tools import (
    _budget_check,
    _self_and_parent_addresses,
    _sol_caller,
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


# ── #2 — planner NATIVE verbs bound to its own plan ────────────────────────
async def test_planner_native_verbs_refuse_foreign_plan(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "planner")
    monkeypatch.setenv("EDP_HANDLE", "r40a:s1")     # own plan = r40a-s1
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r40a")
    _save_recipe(ctx, "r40b")
    _save_plan(ctx, "r40a", "r40a-s1")
    _save_plan(ctx, "r40b", "r40b-s1")
    t = _tools(ctx)

    res = await t["add_action"].run({
        "plan_id": "r40b-s1", "action_id": "x1",
        "description": "foreign append"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    res = await t["record_action_status"].run({
        "plan_id": "r40b-s1", "action_id": "a1", "status": "skipped",
        "evidence": "foreign skip"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    res = await t["create_plan"].run({
        "recipe_id": "r40b", "step_id": "s1", "shape": "linear-build",
        "goal": "hostile"})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    res = await t["record_step_result"].run({
        "recipe_id": "r40b", "step_id": "s1",
        "result": {"status": "done", "summary": "foreign close"}})
    assert isinstance(res, ToolError) and "not your plan" in res.message

    # own plan stays fully writable
    ok = await t["add_action"].run({
        "plan_id": "r40a-s1", "action_id": "x1", "description": "own"})
    assert isinstance(ok, ToolOk), ok


# ── #3 — worker ownership is ACTION-granular (batch siblings allowed) ──────
async def test_worker_cannot_touch_unrelated_same_plan_action(tmp_path,
                                                              monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r40c-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r40c")
    _save_plan(ctx, "r40c", "r40c-s1", batch="b1")   # a1+a2 share b1; a3 not
    t = _tools(ctx)

    res = await t["record_action_status"].run({
        "plan_id": "r40c-s1", "action_id": "a3", "status": "skipped",
        "evidence": "unrelated skip"})
    assert isinstance(res, ToolError), res
    assert "outside your batch unit" in res.message
    assert ctx.plans.load("r40c-s1").actions[2].status == "pending"

    # a batch sibling records fine (the one-shell member loop)
    ok = await t["record_action_status"].run({
        "plan_id": "r40c-s1", "action_id": "a2", "status": "in_progress"})
    assert isinstance(ok, ToolOk), ok


# ── #9 — _sender is stamped UNCONDITIONALLY (spoof dropped) ────────────────
async def test_sender_stamp_overwrites_caller_supplied(monkeypatch):
    import httpx
    from edp_claude.clients.http_broker import HttpBroker
    from edp_contracts import BrokerMessage

    captured = {}

    class _FakeClient:
        async def post(self, url, json=None):
            captured.update(json or {})

            class _R:
                status_code = 200

                @staticmethod
                def json():
                    return {"msg_id": json["msg_id"]}
            return _R()

    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "p:a1")
    b = HttpBroker("http://x", _FakeClient())
    await b.send(BrokerMessage(
        msg_id="m1", ts=_now(), **{"from": "p:a1"}, to="dest", kind="fyi",
        body={"note": "hi", "_sender": {"role": "acceptor",
                                        "handle": "forged"}}))
    assert captured["body"]["_sender"] == {"role": "worker", "handle": "p:a1"}


# ── #4 — a non-empty array with zero valid findings breaks the contract ────
def test_all_invalid_findings_array_is_contract_break():
    assert B.parse_findings('[{"finding": 123}]') is None
    assert B.parse_findings('[{"x": "y"}, 42]') is None
    assert B.parse_findings('[{"finding": "real"}]') == [
        {"finding": "real", "evidence": "", "severity": "medium",
         "target": ""}]
    assert B.parse_findings("[]") == []


# ── #14 — a pid-less slot past the stale age is reaped, not immortal ───────
def test_pidless_orphan_slot_is_reaped(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv(B._CLI_MAX_ENV, "1")
    slots = tmp_path / ".bridge" / "cli-slots"
    slots.mkdir(parents=True)
    slot = slots / "slot-0.lock"
    slot.mkdir()                                   # crash before pid write
    old = time.time() - B._CLI_SLOT_STALE_S - 60
    os.utime(slot, (old, old))
    monkeypatch.setattr(B, "_CLI_SLOT_WAIT_S", 5.0)
    assert B._cli_slot_acquire() is not None       # orphan reaped, acquired


# ── #11 — subscription reuse compares effect CONTENT ───────────────────────
def test_subscription_reuse_rejects_changed_effect(tmp_path):
    sid = "sub-x"
    (tmp_path / f"{sid}.spec").write_text("rx.broker(me)", encoding="utf-8")
    eff_old = {"action": "notify_above", "args": {}, "rule_id": sid}
    (tmp_path / f"{sid}.effect.json").write_text(
        json.dumps(eff_old), encoding="utf-8")
    assert _subscription_matches(
        tmp_path, sid, "rx.broker(me)", {}, {"action": "notify_above",
                                             "args": {}})
    changed = {"action": "notify_above", "args": {"kind": {"const": "x"}}}
    assert not _subscription_matches(
        tmp_path, sid, "rx.broker(me)", {}, changed)


# ── #13/#7 — EDP_PARENT lineage for bare-handle seats ──────────────────────
def test_bare_handle_parent_and_caller_lineage(monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-deadbeef")
    monkeypatch.setenv("EDP_PARENT", "r40d")
    me, parent = _self_and_parent_addresses()
    assert me == "acceptor-deadbeef" and parent == "r40d"
    assert _sol_caller() == "r40d:acceptor-deadbeef"
    from edp_claude.tools._tools import _caller_recipe
    assert _caller_recipe(_sol_caller()) == "r40d"
    # without the stamp: bare handle, no parent, unattributed caller
    monkeypatch.delenv("EDP_PARENT", raising=False)
    me, parent = _self_and_parent_addresses()
    assert parent is None
    assert _sol_caller() == "acceptor-deadbeef"


# ── #7/#6 — the budget gate names unattributed spend + degraded audit ──────
async def test_budget_detail_names_unattributed_and_degraded(tmp_path,
                                                             monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id="r40e", user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "inline"}],
        created_at=_now(), updated_at=_now(), budget={"delegate_usd": 5.0}))
    bdir = tmp_path / ".bridge"
    bdir.mkdir()
    (bdir / "audit-x.jsonl").write_text(
        json.dumps({"cost_usd": 3.0, "ok": True,
                    "caller": "acceptor-ffff"}) + "\n", encoding="utf-8")
    (bdir / B._AUDIT_DEGRADED_MARKER).write_text("t", encoding="utf-8")
    bc = _budget_check(ctx, "r40e")
    assert "unattributed" in bc["detail"]
    assert "DEGRADED" in bc["detail"]
