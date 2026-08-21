"""F47 (2026-08-21) — campaign Round 14 (fourth convergence sweep) fixes.

Pins: POSIX `sh -c` G-RUNS semantics, the locked close/dispatch recipe
transaction (terminal refusal + single reservation), the supervisor's
OS-lock singleton, and commit-point waiver events.
(The pool persist-snapshot lock is pinned in
edp-pool/tests/test_f47_persist_lock.py.)
"""

import asyncio
from datetime import datetime, timezone

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools import _tools as T

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _now():
    return datetime.now(timezone.utc)


def _save_recipe(ctx, rid, outcomes=None, step_status="pending"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": outcomes or []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": step_status, "depends_on": [],
                "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _save_plan(ctx, rid, plan_id, actions):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=actions))


def _gate_act(aid, cmd):
    acc = Acceptance(kind="manual_review", expected="x")
    acc.verify = {"check": "command", "cmd": cmd}
    a = Action(action_id=aid, description=f"do {aid}", status="pending",
               executor_mode="inline", acceptance=acc, depends_on=[])
    a.gate = True
    return a


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


async def _gruns(tmp_path, monkeypatch, rid, run_cmd, declared="pytest -q"):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", f"{rid}-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, rid)
    _save_plan(ctx, rid, f"{rid}-s1", [_gate_act("a1", declared)])
    ctx.plans.append_worklog(f"{rid}-s1", {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": f"{rid}-s1:a1"})
    t = _tools(ctx)
    return await t["record_action_status"].run({
        "plan_id": f"{rid}-s1", "action_id": "a1", "status": "done",
        "evidence": "ran it",
        "runs": [{"command": run_cmd, "exit_code": 0, "output_tail": "ok"}]})


# ── #1 — POSIX `-c` executes only its next argument ────────────────────────
async def test_gruns_rejects_unquoted_sh_dash_c(tmp_path, monkeypatch):
    # sh executes only `python`; `-m pytest -q` are positional parameters
    res = await _gruns(tmp_path, monkeypatch, "r47a",
                       "sh -c python -m pytest -q",
                       declared="python -m pytest -q")
    assert isinstance(res, ToolError)
    assert "G-RUNS" in res.message


async def test_gruns_rejects_shell_script_form(tmp_path, monkeypatch):
    res = await _gruns(tmp_path, monkeypatch, "r47b",
                       "bash run_tests.sh pytest -q")
    assert isinstance(res, ToolError)
    assert "G-RUNS" in res.message


async def test_gruns_accepts_quoted_sh_dash_c(tmp_path, monkeypatch):
    ok = await _gruns(tmp_path, monkeypatch, "r47c",
                      'sh -c "uv run pytest -q"')
    assert isinstance(ok, ToolOk), ok


# ── #3 — a closed recipe accepts no acceptance dispatch ────────────────────
async def test_dispatch_refused_on_closed_recipe(tmp_path, monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r47d")
    r = ctx.recipes.load("r47d")
    r.state = "closed"
    r.final_outcome = {"status": "abandoned", "summary": "done with it"}
    ctx.recipes.save(r)
    t = _tools(ctx)
    res = await t["dispatch_acceptance"].run({"recipe_id": "r47d"})
    assert isinstance(res, ToolError)
    assert "CLOSED" in res.message
    assert not ctx.recipes.read_events_tail(
        "r47d", kinds=["acceptance_dispatched"])


# ── #5 — concurrent dispatches reserve exactly one attempt ─────────────────
async def test_concurrent_dispatches_reserve_one_attempt(tmp_path,
                                                         monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r47e")
    t = _tools(ctx)
    tool = t["dispatch_acceptance"]

    async def _spawn_ok(*a, **kw):
        await asyncio.sleep(0.05)          # keep the first launch in flight
        return SimpleNamespace(ok=True)

    tool.ctx.pool = SimpleNamespace(spawn_acceptor=_spawn_ok)
    r1, r2 = await asyncio.gather(
        tool.run({"recipe_id": "r47e"}), tool.run({"recipe_id": "r47e"}))
    assert isinstance(r1, ToolOk) and isinstance(r2, ToolOk)
    disp = ctx.recipes.read_events_tail(
        "r47e", kinds=["acceptance_dispatched"])
    assert len(disp) == 1, "exactly one attempt reserved"
    notes = [(x.data if isinstance(x.data, dict) else x.data.model_dump())
             .get("note", "") for x in (r1, r2)]
    assert sum("ALREADY IN FLIGHT" in n for n in notes) == 1


# ── #4 — the supervisor singleton is an OS lock, not a pid file ────────────
def test_supervisor_singleton_excludes_second_and_frees_on_release(tmp_path):
    from edp_claude.reactive import registry as R
    reg = R.RuleRegistry(tmp_path / "registry")
    cfg = R.SupervisorConfig(agent_home=tmp_path, driver_python="python")
    s1 = R.RuleSupervisor(reg, cfg)
    s2 = R.RuleSupervisor(reg, cfg)
    s1._acquire_singleton()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            s2._acquire_singleton()
    finally:
        s1._release_singleton()
    # once released, the lock is free for the next supervisor
    s2._acquire_singleton()
    s2._release_singleton()


# ── #6 — waiver events land only at the commit point ───────────────────────
async def test_waiver_event_deferred_until_close_commits(tmp_path,
                                                         monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r47f", step_status="done", outcomes=[
        {"id": "o1", "description": "d", "verification": "v",
         "met": False}])
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")     # tests default it off
    # only the outcome waiver's own ref validates — G-ACCEPT stays armed
    monkeypatch.setattr(T, "_gate_override_ok",
                        lambda ctx_, rid_, ref, tgt: ref == "ans-1")
    t = _tools(ctx)
    close_in = {"recipe_id": "r47f",
                "final_outcome": {"status": "succeeded", "summary": "s"},
                "outcome_waivers": {"o1": "ans-1"}}
    res = await t["close_recipe"].run(dict(close_in))
    assert isinstance(res, ToolError)
    assert "G-ACCEPT" in res.message
    # the refused close left NO durable waiver claim (the old shape did,
    # and the retry was then judged against the trail's word)
    assert not ctx.recipes.read_events_tail(
        "r47f", kinds=["outcome_waived"])
    assert not ctx.recipes.load("r47f").comprehension.expected_outcomes[
        0].waived
    # with acceptance recorded, the SAME call closes and commits the event
    r = ctx.recipes.load("r47f")
    fp = T._acceptance_fingerprint(r, ctx=ctx)
    ctx.recipes.append_worklog("r47f", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "fingerprint": fp}})
    ok = await t["close_recipe"].run(dict(close_in))
    assert isinstance(ok, ToolOk), ok
    waived = ctx.recipes.read_events_tail("r47f", kinds=["outcome_waived"])
    assert len(waived) == 1
    assert str(getattr(ctx.recipes.load("r47f").state, "value",
                       ctx.recipes.load("r47f").state)) == "closed"
