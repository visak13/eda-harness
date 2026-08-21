"""F46 (2026-08-21) — campaign Round 13 (third convergence sweep) fixes.

Pins: attempt-bound acceptance (superseded acceptors refused at emission,
at the close gate, and at the in-flight latch), the python-wrapper G-RUNS
grammar, and the lock-serialized RuleRegistry.
(The pool reap/registration protocol and the neuron-driver lifecycle lock
are pinned in edp-pool/tests/test_f46_reap_and_driver_lock.py.)
"""

import threading
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools._tools import (
    _acceptance_fingerprint,
    _acceptance_pass_current,
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


def _act(aid, gate=False, verify=None):
    acc = Acceptance(kind="manual_review", expected="x")
    if verify is not None:
        acc.verify = verify
    a = Action(action_id=aid, description=f"do {aid}", status="pending",
               executor_mode="inline", acceptance=acc, depends_on=[])
    if gate:
        a.gate = True
    return a


def _save_plan(ctx, rid, plan_id, actions):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=actions))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


# ── #1 — a superseded acceptor cannot settle anything ──────────────────────
async def test_superseded_acceptor_refused_at_emission(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-old01")
    monkeypatch.setenv("EDP_PARENT", "r46a")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46a")
    ctx.recipes.append_worklog("r46a", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-old01",
        "fingerprint": "fp-x"})
    # re-dispatch after latch expiry / force — the rival owns the attempt
    ctx.recipes.append_worklog("r46a", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-new02",
        "fingerprint": "fp-x"})
    t = _tools(ctx)
    res = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "summary": "late but confident"}})
    assert isinstance(res, ToolError)
    assert "SUPERSEDED" in res.message
    assert not ctx.recipes.read_events_tail(
        "r46a", kinds=["acceptance_verdict"])


async def test_superseded_acceptor_ignored_when_its_rival_aborted(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "acceptor")
    monkeypatch.setenv("EDP_HANDLE", "acceptor-old03")
    monkeypatch.setenv("EDP_PARENT", "r46b")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46b")
    ctx.recipes.append_worklog("r46b", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-old03",
        "fingerprint": "fp-y"})
    ctx.recipes.append_worklog("r46b", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-new04",
        "fingerprint": "fp-y"})
    # the rival's launch FAILED — this shell is the live attempt again
    ctx.recipes.append_worklog("r46b", {
        "kind": "acceptance_dispatch_aborted",
        "acceptor_id": "acceptor-new04", "stage": "spawn"})
    t = _tools(ctx)
    ok = await t["emit_recipe_event"].run({
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "summary": "delivery matches the goal"}})
    assert isinstance(ok, ToolOk), ok
    v = ctx.recipes.read_events_tail("r46b", kinds=["acceptance_verdict"])
    assert v[-1]["body"]["fingerprint"] == "fp-y"
    assert v[-1]["body"]["acceptor_id"] == "acceptor-old03"


async def test_close_gate_refuses_superseded_attempts_pass(tmp_path):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46c")
    r = ctx.recipes.load("r46c")
    fp = _acceptance_fingerprint(r, ctx=ctx)
    ctx.recipes.append_worklog("r46c", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-a",
        "fingerprint": fp})
    ctx.recipes.append_worklog("r46c", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-b",
        "fingerprint": fp})
    # A's late pass: delivery unchanged, so the fingerprint STILL matches —
    # only the attempt identity can catch it.
    ctx.recipes.append_worklog("r46c", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "fingerprint": fp,
                 "acceptor_id": "acceptor-a"}})
    ok, reason = _acceptance_pass_current(ctx, ctx.recipes.load("r46c"))
    assert not ok
    assert "SUPERSEDED" in reason
    # the live attempt's own pass closes normally
    ctx.recipes.append_worklog("r46c", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "fingerprint": fp,
                 "acceptor_id": "acceptor-b"}})
    ok, reason = _acceptance_pass_current(ctx, ctx.recipes.load("r46c"))
    assert ok, reason


async def test_latch_not_settled_by_a_rivals_verdict(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46d")
    ctx.recipes.append_worklog("r46d", {
        "kind": "acceptance_dispatched", "acceptor_id": "acceptor-live",
        "fingerprint": "fp-z"})
    # a SUPERSEDED shell's verdict lands after the live dispatch — it must
    # not settle the live attempt's latch (that would spawn a rival while
    # acceptor-live is still working)
    ctx.recipes.append_worklog("r46d", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "gaps", "acceptor_id": "acceptor-stale"}})
    t = _tools(ctx)
    res = await t["dispatch_acceptance"].run({"recipe_id": "r46d"})
    assert isinstance(res, ToolOk), res
    data = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert "ALREADY IN FLIGHT" in data.get("note", "")
    assert data["acceptor_id"] == "acceptor-live"


# ── #2 — python anchors G-RUNS only in `-m` form ───────────────────────────
@pytest.mark.parametrize("cheat_cmd", [
    "python pytest -q",        # executes a local FILE named pytest
    "python -c pytest -q",     # -c runs inline code, not the command
    "py pytest -q",
])
async def test_gruns_rejects_python_script_execution(tmp_path, monkeypatch,
                                                     cheat_cmd):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r46e-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46e")
    _save_plan(ctx, "r46e", "r46e-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    ctx.plans.append_worklog("r46e-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r46e-s1:a1"})
    t = _tools(ctx)
    res = await t["record_action_status"].run({
        "plan_id": "r46e-s1", "action_id": "a1", "status": "done",
        "evidence": "ran it",
        "runs": [{"command": cheat_cmd, "exit_code": 0,
                  "output_tail": "ok"}]})
    assert isinstance(res, ToolError)
    assert "G-RUNS" in res.message


async def test_gruns_accepts_python_dash_m_form(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r46f-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r46f")
    _save_plan(ctx, "r46f", "r46f-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    ctx.plans.append_worklog("r46f-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": "r46f-s1:a1"})
    t = _tools(ctx)
    ok = await t["record_action_status"].run({
        "plan_id": "r46f-s1", "action_id": "a1", "status": "done",
        "evidence": "ran the suite",
        "runs": [{"command": "python -m pytest -q", "exit_code": 0,
                  "output_tail": "9 passed"}]})
    assert isinstance(ok, ToolOk), ok


# ── #5 — the rule registry survives concurrent same-rule writers ───────────
def test_registry_concurrent_replace_is_serialized(tmp_path):
    from edp_claude.reactive.registry import RuleRegistry
    reg = RuleRegistry(tmp_path / "registry")
    errors: list[Exception] = []

    def _writer(t):
        for i in range(10):
            try:
                reg.register_rule(
                    name="watch", spec="rx.broker(me)", effect=None,
                    owner=f"owner-{t}", bindings={"me": f"h-{t}-{i}"},
                    replace=True)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

    threads = [threading.Thread(target=_writer, args=(t,))
               for t in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors, errors
    # the durable file is a coherent LAST writer, never torn/missing
    rule = reg.get("watch")
    assert rule.name == "watch"
    assert rule.owner.startswith("owner-")


def test_registry_exists_check_is_atomic(tmp_path):
    from edp_claude.reactive.registry import RuleExists, RuleRegistry
    reg = RuleRegistry(tmp_path / "registry")
    results: list[str] = []
    lock = threading.Lock()

    def _creator(t):
        try:
            reg.register_rule(name="once", spec="rx.broker(me)",
                              effect=None, owner=f"o{t}",
                              bindings={"me": "h"})
            with lock:
                results.append("created")
        except RuleExists:
            with lock:
                results.append("exists")

    threads = [threading.Thread(target=_creator, args=(t,))
               for t in range(6)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert results.count("created") == 1, results
