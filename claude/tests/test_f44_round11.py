"""F44 (2026-08-20) — campaign Round 11 (full-framework convergence) fixes.

Pins: dispatch-bound verdict fingerprints (+ abort releases the latch),
the whole-object replacement gate, terminal-plan verdict immutability,
ready-wave batch_owner stamps, atomic observe re-spec, the
dependency-aware canonical head, and wrapper-aware G-RUNS.
(The broker append lock and pool starting-reservation fixes are pinned in
their own suites: edp-broker/tests/test_f44_append_lock.py and
edp-pool/tests/test_f44_starting_reservation.py.)
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools import build_registry

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


def _act(aid, grp=None, status="pending", deps=None, gate=False,
         verify=None):
    acc = Acceptance(kind="manual_review", expected="x")
    if verify is not None:
        acc.verify = verify
    a = Action(action_id=aid, description=f"do {aid}", status=status,
               executor_mode="inline", acceptance=acc,
               depends_on=deps or [])
    if grp:
        a.batch_group = grp
    if gate:
        a.gate = True
    return a


def _save_plan(ctx, rid, plan_id, actions, state="dispatching"):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state=state, actions=actions))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


# ── #1 — verdicts bind to the DISPATCHED fingerprint; abort frees latch ────
async def test_verdict_stamped_with_dispatched_fingerprint(tmp_path,
                                                           monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-f44test")
    monkeypatch.setenv("EDP_PARENT", "r44a")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44a")
    ctx.recipes.append_worklog("r44a", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-f44test",
        "fingerprint": "attempt-fp-1234"})
    t = _tools(ctx)
    ok = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict", "recipe_id": "r44a",
        "body": {"verdict": "pass", "summary": "delivery matches goal"}})
    assert isinstance(ok, ToolOk), ok
    v = ctx.recipes.read_events_tail("r44a", kinds=["acceptance_verdict"])
    # the verdict carries the fingerprint the DISPATCH recorded — never a
    # recomputed current one (which would grandfather a mid-review mutation)
    assert v[-1]["body"]["fingerprint"] == "attempt-fp-1234"


async def test_aborted_dispatch_releases_the_latch(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44b")
    t = _tools(ctx)
    tool = t["dispatch_acceptance"]

    async def _spawn_fail(*a, **kw):
        return SimpleNamespace(ok=False, message="pool down")

    async def _spawn_ok(*a, **kw):
        return SimpleNamespace(ok=True)

    tool.ctx.pool = SimpleNamespace(spawn_acceptor=_spawn_fail)
    res = await tool.run({"recipe_id": "r44b"})
    assert not getattr(res, "ok", False)          # the spawn failure surfaced
    aborted = ctx.recipes.read_events_tail(
        "r44b", kinds=["acceptance_dispatch_aborted"])
    assert aborted, "failed launch must release the in-flight latch"
    # a retry proceeds instead of reporting ALREADY IN FLIGHT for the TTL
    tool.ctx.pool = SimpleNamespace(spawn_acceptor=_spawn_ok)
    ok = await tool.run({"recipe_id": "r44b"})
    assert isinstance(ok, ToolOk), ok
    assert "ALREADY IN FLIGHT" not in (ok.data.get("note", "")
                                       if isinstance(ok.data, dict)
                                       else ok.data.note)


# ── #2 — whole-object replacement requires the current version ─────────────
async def test_record_plan_refuses_versionless_replacement(tmp_path,
                                                           monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44c")
    _save_plan(ctx, "r44c", "r44c-s1", [_act("a1", status="done")])
    p = ctx.plans.load("r44c-s1")
    ctx.plans.save(p)                              # bump to v2+
    disk_v = ctx.plans.load("r44c-s1").version
    t = _tools(ctx)

    # a post-compaction "reconstruction" with no version → refused
    recon = {"plan_id": "r44c-s1", "recipe_id": "r44c",
             "recipe_step_id": "s1", "domain": "software_engineering",
             "shape": "linear-build", "goal": "g", "state": "dispatching",
             "actions": [{"action_id": "a3", "description": "new only",
                          "status": "pending", "executor_mode": "inline",
                          "acceptance": {"kind": "manual_review",
                                         "expected": "x"}}]}
    res = await t["record_plan"].run({"plan": recon})
    assert isinstance(res, ToolError), res
    assert "carries no version" in res.message
    assert ctx.plans.load("r44c-s1").actions[0].action_id == "a1"  # intact

    # carrying the current version replaces legitimately
    recon["version"] = disk_v
    ok = await t["record_plan"].run({"plan": recon})
    assert isinstance(ok, ToolOk), ok


# ── #3 — a terminal plan's verdicts are settled ────────────────────────────
async def test_branch_verdict_refused_on_terminal_plan(tmp_path,
                                                       monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.setenv("EDP_HANDLE", "other:shell")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44d")
    _save_plan(ctx, "r44d", "r44d-s1", [_act("a1", status="done")],
               state="terminal")
    t = _tools(ctx)
    res = await t["record_branch_verdict"].run({
        "recipe_id": "r44d", "plan_id": "r44d-s1", "branch_id": "a1",
        "passed": False,
        "verdict": "re-ran the gate after close and it fails on the edge "
                   "case X — this must reopen, not silently stand."})
    assert isinstance(res, ToolError), res
    assert "TERMINAL" in res.message and "reopen" in res.message


# ── #6 — the ready wave stamps batch_owner like the single dispatch ────────
def test_ready_wave_stamps_batch_owner():
    from edp_claude.fsm.plan_fsm import plan_ready_wave
    p = Plan(plan_id="p", recipe_id="r", recipe_step_id="s1",
             domain="software_engineering", shape="parallel_multitool",
             goal="g", state="dispatching",
             actions=[_act("a1", "b1"), _act("a2", "b1")])
    instrs = plan_ready_wave(p)
    assert instrs
    assert p.actions[0].status == "in_progress"
    assert p.actions[1].batch_owner == "a1"


# ── #7 — observe re-spec is atomic ─────────────────────────────────────────
async def test_invalid_effect_leaves_live_wiring_untouched(tmp_path,
                                                           monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ok = await t["observe"].run({
        "spec": "rx.broker(me)", "bindings": {"me": "x1"},
        "subscription_id": "sub-atomic"})
    assert isinstance(ok, ToolOk), ok
    root = ctx.recipes.root.parent / ".reactive"
    # changed spec + INVALID effect → refused BEFORE any overwrite
    res = await t["observe"].run({
        "spec": "rx.worklog(plan_id)", "bindings": {"plan_id": "x1"},
        "subscription_id": "sub-atomic",
        "effect": {"action": "rm_rf", "args": {}}})
    assert isinstance(res, ToolError), res
    assert (root / "sub-atomic.spec").read_text(
        encoding="utf-8") == "rx.broker(me)"       # old driver undisturbed


async def test_respec_removes_obsolete_sidecars(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ok = await t["observe"].run({
        "spec": "rx.broker(me)", "bindings": {"me": "x2"},
        "subscription_id": "sub-shed",
        "effect": {"action": "notify_above",
                   "args": {"kind": {"const": "alert"},
                            "body": {"from_event": "body"}}}})
    assert isinstance(ok, ToolOk), ok
    root = ctx.recipes.root.parent / ".reactive"
    assert (root / "sub-shed.effect.json").exists()
    # re-spec WITHOUT bindings/effect sheds the old sidecars
    ok = await t["observe"].run({
        "spec": "rx.pool()", "subscription_id": "sub-shed"})
    assert isinstance(ok, ToolOk), ok
    assert not (root / "sub-shed.effect.json").exists()
    assert not (root / "sub-shed.bindings.json").exists()


# ── #8 — canonical head honors dependency readiness ────────────────────────
async def test_spawn_accepts_fsm_selected_ready_head(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44e")
    # a1 (group g) depends on x; a2 (group g) is free; x depends on a2 —
    # the FSM's ready head is a2, and demanding a1 would deadlock.
    _save_plan(ctx, "r44e", "r44e-s1", [
        _act("a1", "g", deps=["x"]),
        _act("a2", "g", status="in_progress"),
        _act("x", deps=["a2"])])
    t = _tools(ctx)
    res = await t["pool_spawn_worker"].run({
        "plan_id": "r44e-s1", "action_id": "a2", "action_ids": ["a2"]})
    if isinstance(res, ToolError):
        assert "not the head of batch group" not in res.message
    assert ctx.plans.load("r44e-s1").actions[1].status == "in_progress"


# ── #9 — a wrapped print run proves nothing ────────────────────────────────
async def test_gruns_rejects_wrapped_echo(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r44f-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r44f")
    _save_plan(ctx, "r44f", "r44f-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    ctx.plans.append_worklog("r44f-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r44f-s1:a1"})
    t = _tools(ctx)
    res = await t["record_action_status"].run({
        "plan_id": "r44f-s1", "action_id": "a1", "status": "done",
        "evidence": "done", "runs": [{
            "command": "cmd /c echo pytest -q", "exit_code": 0,
            "output_tail": "pytest -q", "at": _now().isoformat()}]})
    assert isinstance(res, ToolError) and "G-RUNS" in res.message
