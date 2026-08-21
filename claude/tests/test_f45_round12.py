"""F45 (2026-08-21) — campaign Round 12 (second convergence sweep) fixes.

Pins: acceptor-bound verdict attempts (own dispatch record + lineage
recipe), anchored G-RUNS command matching, plan-scoped review verdicts,
the pinned dispatch-abort record, spawn-seam dependency validation, the
lock-serialized handle index, and the loud index-degraded observe note.
(The pool release/registration lock and the broker atomic channel merge
are pinned in their own suites: edp-pool/tests/test_f45_release_lock.py
and edp-broker/tests/test_f45_channel_merge.py.)
"""

import threading
from datetime import datetime, timezone

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


# ── #1 — a spawned acceptor's verdict binds to ITS OWN dispatch ────────────
async def test_acceptor_refused_without_its_own_dispatch_record(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-stale01")
    monkeypatch.setenv("EDP_PARENT", "r45a")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45a")
    # only a RIVAL's dispatch exists — this shell's own was never recorded
    ctx.recipes.append_worklog("r45a", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-rival02",
        "fingerprint": "rival-fp"})
    t = _tools(ctx)
    res = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict", "recipe_id": "r45a",
        "body": {"verdict": "pass", "summary": "looks fine"}})
    assert isinstance(res, ToolError)
    assert "names your handle" in res.message
    assert not ctx.recipes.read_events_tail(
        "r45a", kinds=["acceptance_verdict"])


async def test_acceptor_verdict_carries_own_not_rival_fingerprint(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-mine03")
    monkeypatch.setenv("EDP_PARENT", "r45b")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45b")
    # an EARLIER rival attempt left its record; this shell's own dispatch is
    # the live one. (F46#1: a rival dispatched AFTER this shell would make
    # it SUPERSEDED and the verdict refused outright — that path is pinned
    # in test_f46_round13.py.) The old shape stamped whatever fingerprint
    # the recipe-global last record carried, not the emitter's own.
    ctx.recipes.append_worklog("r45b", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-rival04",
        "fingerprint": "rival-fp"})
    ctx.recipes.append_worklog("r45b", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-mine03",
        "fingerprint": "my-fp"})
    t = _tools(ctx)
    ok = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "summary": "delivery matches goal"}})
    assert isinstance(ok, ToolOk), ok
    v = ctx.recipes.read_events_tail("r45b", kinds=["acceptance_verdict"])
    assert v[-1]["body"]["fingerprint"] == "my-fp"


async def test_acceptor_refuses_foreign_recipe_id(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-mine05")
    monkeypatch.setenv("EDP_PARENT", "r45c")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45c")
    _save_recipe(ctx, "r45other")
    ctx.recipes.append_worklog("r45c", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-mine05",
        "fingerprint": "fp"})
    t = _tools(ctx)
    res = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict", "recipe_id": "r45other",
        "body": {"verdict": "pass", "summary": "…"}})
    assert isinstance(res, ToolError)
    assert "not it" in res.message
    assert not ctx.recipes.read_events_tail(
        "r45other", kinds=["acceptance_verdict"])


# ── #2 — G-RUNS is ANCHORED: an unknown prefix is not a wrapper ────────────
@pytest.mark.parametrize("cheat_cmd", [
    "true pytest -q",             # unknown no-op prefix carries the tokens
    "command echo pytest -q",     # unknown prefix hides the print verb
    "run-nothing pytest -q",      # arbitrary unrelated leading command
])
async def test_gruns_rejects_unknown_prefix_containment(
        tmp_path, monkeypatch, cheat_cmd):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r45d-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45d")
    _save_plan(ctx, "r45d", "r45d-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    ctx.plans.append_worklog("r45d-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r45d-s1:a1"})
    t = _tools(ctx)
    res = await t["record_action_status"].run({
        "plan_id": "r45d-s1", "action_id": "a1", "status": "done",
        "evidence": "ran the suite",
        "runs": [{"command": cheat_cmd, "exit_code": 0,
                  "output_tail": "ok"}]})
    assert isinstance(res, ToolError)
    assert "G-RUNS" in res.message


async def test_gruns_still_accepts_wrapped_declared_command(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r45e-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45e")
    _save_plan(ctx, "r45e", "r45e-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    ctx.plans.append_worklog("r45e-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r45e-s1:a1"})
    t = _tools(ctx)
    ok = await t["record_action_status"].run({
        "plan_id": "r45e-s1", "action_id": "a1", "status": "done",
        "evidence": "ran the suite",
        "runs": [{"command": "uv run pytest -q", "exit_code": 0,
                  "output_tail": "120 passed"}]})
    assert isinstance(ok, ToolOk), ok


# ── #3 — review verdicts are scoped to the reviewer's OWN plan ─────────────
async def test_reviewer_cannot_stamp_foreign_plan_verdict(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    monkeypatch.setenv("EDP_HANDLE", "r45f-s1:rev1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45f")
    _save_plan(ctx, "r45f", "r45f-s1", [_act("rev1"), _act("a1")])
    _save_plan(ctx, "r45f", "r45f-s2", [_act("b1", status="done")])
    t = _tools(ctx)
    res = await t["record_branch_verdict"].run({
        "recipe_id": "r45f", "plan_id": "r45f-s2", "branch_id": "b1",
        "verdict": "injected: this unrelated action failed its gate badly",
        "passed": False})
    assert isinstance(res, ToolError)
    assert "ITS OWN" in res.message or "not your plan" in res.message
    assert ctx.plans.load("r45f-s2").actions[0].review_verdict is None


async def test_reviewer_still_stamps_own_plan_verdict(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    monkeypatch.setenv("EDP_HANDLE", "r45g-s1:rev1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45g")
    _save_plan(ctx, "r45g", "r45g-s1", [
        _act("rev1"), _act("a1", status="done")])
    t = _tools(ctx)
    ok = await t["record_branch_verdict"].run({
        "recipe_id": "r45g", "plan_id": "r45g-s1", "branch_id": "a1",
        "verdict": "re-ran the acceptance command and its output matches "
                   "the declared expectation end to end",
        "passed": True})
    assert isinstance(ok, ToolOk), ok
    assert ctx.plans.load("r45g-s1").actions[1].review_verdict["passed"]


# ── #4 — the dispatch-abort record is gate-pinned ──────────────────────────
def test_dispatch_abort_is_pinned():
    from edp_claude.store.recipe_store import GATE_PINNED_KINDS, _pinned
    assert "acceptance_dispatch_aborted" in GATE_PINNED_KINDS
    assert _pinned({"kind": "acceptance_dispatch_aborted",
                    "acceptor_id": "acceptor-x"})


# ── #5 — the spawn seam refuses an unmet-dependency head ───────────────────
async def test_spawn_refuses_dependency_blocked_head(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45h")
    _save_plan(ctx, "r45h", "r45h-s1", [
        _act("x"),                       # pending, never finished
        _act("a1", deps=["x"])])
    t = _tools(ctx)
    res = await t["pool_spawn_worker"].run({
        "plan_id": "r45h-s1", "action_id": "a1", "action_ids": ["a1"]})
    assert isinstance(res, ToolError)
    assert "unmet dependencies" in res.message
    assert ctx.plans.load("r45h-s1").actions[1].status == "pending"


async def test_spawn_allows_deps_satisfied_by_earlier_unit_member(
        tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r45i")
    _save_plan(ctx, "r45i", "r45i-s1", [
        _act("a1", "g"),
        _act("a2", "g", deps=["a1"])])
    t = _tools(ctx)
    res = await t["pool_spawn_worker"].run({
        "plan_id": "r45i-s1", "action_id": "a1",
        "action_ids": ["a1", "a2"]})
    # a2's dep is a1, an EARLIER member of the same admitted unit — the
    # dependency guard must not refuse (whatever else the launch path does
    # downstream with the stub pool, the refusal reason must not be deps).
    if isinstance(res, ToolError):
        assert "unmet dependencies" not in res.message


# ── #8 — the handle index survives concurrent writers ──────────────────────
def test_handle_index_concurrent_registration_loses_nothing(tmp_path):
    from edp_claude.reactive import handle_index as hi
    root = tmp_path / ".reactive"
    n_threads, per_thread = 8, 15

    def _arm(t):
        for i in range(per_thread):
            hi.register_subscription(root, f"handle-{t}", f"sub-{t}-{i}")

    threads = [threading.Thread(target=_arm, args=(t,))
               for t in range(n_threads)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    for t in range(n_threads):
        got = hi.sids_for_handle(root, f"handle-{t}")
        assert len(got) == per_thread, (t, got)


async def test_observe_reports_index_degradation_loudly(
        tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    from edp_claude.reactive import handle_index as hi

    def _boom(*a, **kw):
        raise OSError("disk said no")

    monkeypatch.setattr(hi, "register_subscription", _boom)
    ok = await t["observe"].run({
        "spec": "rx.broker(me)", "bindings": {"me": "w-deg"},
        "subscription_id": "sub-deg"})
    assert isinstance(ok, ToolOk), ok
    data = ok.data if isinstance(ok.data, dict) else ok.data.model_dump()
    assert data["index_degraded"], "silent index failure must be loud"
    assert "re-run this observe" in data["index_degraded"]
