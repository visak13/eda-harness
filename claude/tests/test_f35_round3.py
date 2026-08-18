"""F35 (2026-08-18) — campaign Round 3 (FSM & gates) fixes.

Covers the acceptance-integrity package (R3a#1/R3b#1/R3b#7), the
failed-dependency deadlock reopen (R3a#2), skipped-action verdicts
(R3b#9-adjacent), batch ownership (R3a#4), partial-plan step honesty
(R3a#7), closed-recipe add_step (R3a#10), post-signoff scope growth
(R3a#6), G-RUNS proof (R3b#8), G-SPEC missing specs (R3b#10), the
grounding restatement (R3b#11), and G-EST/G-CHALLENGE typing (R3b#13).
"""

from datetime import datetime, timezone

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm import plan_next_action
from edp_claude.fsm.plan_fsm import _ready_actions
from edp_claude.schemas import Plan, Recipe
from edp_claude.server import make_context
from edp_claude.tools._tools import (
    DispatchAcceptance,
    NextAction,
    _acceptance_fingerprint,
    _challenge_required,
    _DispatchAcceptanceIn,
)
from edp_claude.tools._tools import _NAIn as _NA_In


def _now():
    return datetime.now(timezone.utc)


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


def _err(res):
    assert not isinstance(res, ToolOk), res
    return res.message


def _all_met_recipe(ctx, rid="recipe-f35"):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="build X",
        user_goal_distilled="g", domain="software_engineering",
        state="reviewing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v",
             "met": True, "met_evidence": "e"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "done", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now()))


# ── acceptance integrity ───────────────────────────────────────────────────

async def test_interim_pass_does_not_downgrade_to_done(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    ctx.recipes.append_worklog("recipe-f35", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "interim": True}})
    res = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f35", handle_type="recipe"))
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert d["kind"] == "dispatch_acceptance"
    assert "INTERIM" in d["rationale"]


async def test_stale_fingerprint_pass_does_not_downgrade(
        tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_GATE", "1")
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    ctx.recipes.append_worklog("recipe-f35", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "fingerprint": "deadbeef0000"}})
    res = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f35", handle_type="recipe"))
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    assert d["kind"] == "dispatch_acceptance"
    assert "predates" in d["rationale"]
    # matching fingerprint → DONE
    fp = _acceptance_fingerprint(ctx.recipes.load("recipe-f35"))
    ctx.recipes.append_worklog("recipe-f35", {
        "kind": "acceptance_verdict",
        "body": {"verdict": "pass", "fingerprint": fp}})
    res2 = await NextAction(ctx)._run(_NA_In(
        handle="recipe-f35", handle_type="recipe"))
    d2 = res2.data if isinstance(res2.data, dict) else res2.data.model_dump()
    assert d2["kind"] == "done"


async def test_worker_cannot_mint_acceptance_verdict(env, monkeypatch):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    monkeypatch.setenv("EDP_ROLE", "worker")
    msg = _err(await env.call("emit_recipe_event",
                              kind="acceptance_verdict",
                              recipe_id=rid, body={"verdict": "pass"}))
    assert "ACCEPTOR" in msg


async def test_final_dispatch_not_suppressed_by_interim_latch(tmp_path):
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    r1 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f35", interim=True))
    d1 = r1.data if isinstance(r1.data, dict) else r1.data.model_dump()
    # a FINAL request while an interim pass is in flight spawns fresh
    r2 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f35", interim=False))
    d2 = r2.data if isinstance(r2.data, dict) else r2.data.model_dump()
    assert d2["acceptor_id"] != d1["acceptor_id"]


async def test_latch_expires_after_ttl(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ACCEPT_LATCH_TTL_SECS", "0")
    ctx = make_context(tmp_path)
    _all_met_recipe(ctx)
    r1 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f35"))
    d1 = r1.data if isinstance(r1.data, dict) else r1.data.model_dump()
    r2 = await DispatchAcceptance(ctx)._run(
        _DispatchAcceptanceIn(recipe_id="recipe-f35"))
    d2 = r2.data if isinstance(r2.data, dict) else r2.data.model_dump()
    assert d2["acceptor_id"] != d1["acceptor_id"], (
        "an expired latch must not suppress recovery forever")


# ── plan FSM ───────────────────────────────────────────────────────────────

def _plan(actions, state="dispatching"):
    return Plan.model_validate(dict(
        plan_id="p", recipe_id="r", recipe_step_id="s1",
        domain="software_engineering", shape="linear-build", goal="g",
        state=state, actions=actions, context={}))


def test_failed_blocker_with_pending_dependent_reopens():
    p = _plan([
        {"action_id": "a1", "description": "d", "status": "failed",
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass"}},
        {"action_id": "a2", "description": "d", "status": "pending",
         "depends_on": ["a1"], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass"}},
    ])
    i = plan_next_action(p)
    assert "G-DEPS" in i.rationale
    assert p.actions[0].status == "pending"
    i2 = plan_next_action(p)
    assert i2.kind == "dispatch_action"          # rework dispatches


def test_lone_failed_action_still_terminates_partial():
    p = _plan([{"action_id": "a1", "description": "d", "status": "failed",
                "depends_on": [], "executor_mode": "subagent",
                "acceptance": {"kind": "tests_pass"}}])
    plan_next_action(p)
    assert p.terminal_status == "partial"


def test_skipped_action_with_fail_verdict_reopens():
    p = _plan([{"action_id": "a1", "description": "d", "status": "skipped",
                "depends_on": [], "executor_mode": "subagent",
                "acceptance": {"kind": "tests_pass"},
                "review_verdict": {
                    "verdict": "re-ran the gate: the skipped surface is "
                               "load-bearing and broken",
                    "passed": False}}])
    i = plan_next_action(p)
    assert "G-VERDICT" in i.rationale
    assert p.actions[0].status == "pending"


def test_batch_member_owned_by_live_head_not_ready():
    p = _plan([
        {"action_id": "b1", "description": "d", "status": "in_progress",
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass"}, "batch_group": "g"},
        {"action_id": "b2", "description": "d", "status": "pending",
         "depends_on": [], "executor_mode": "subagent",
         "acceptance": {"kind": "tests_pass"}, "batch_group": "g",
         "batch_owner": "b1"},
    ])
    assert _ready_actions(p, frozenset({"b1"})) == []
    # head gone → member dispatches freely
    assert [a.action_id for a in _ready_actions(p, frozenset())] == ["b2"]


# ── recipe plane ───────────────────────────────────────────────────────────

async def test_partial_plan_does_not_complete_its_step(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner",
                             estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    r = env.ctx.recipes.load(rid)
    r.state = "executing"
    for s in r.steps:
        s.status = "in_progress"
    env.ctx.recipes.save(r)
    p = env.ctx.plans.load(pid)
    p.state = "terminal"
    p.terminal_status = "partial"
    p.actions[0].status = "failed"
    env.ctx.plans.save(p)
    _ok(await env.call("reconcile", handle=rid, handle_type="recipe"))
    r2 = env.ctx.recipes.load(rid)
    assert r2.steps[0].status == "in_progress", (
        "a PARTIAL plan must not silently complete its step")


async def test_add_step_refused_on_closed_recipe(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("add_step", recipe_id=rid, description="build",
                       execution="inline"))
    r = env.ctx.recipes.load(rid)
    r.steps[0].status = "done"
    r.state = "closed"
    r.final_outcome = {"status": "succeeded", "summary": "s"}
    env.ctx.recipes.save(r)
    msg = _err(await env.call("add_step", recipe_id=rid,
                              description="late work",
                              execution="spawn_planner",
                              estimate={"hours": 1}))
    assert "CLOSED" in msg


async def test_add_step_in_reviewing_stales_signoff(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("add_step", recipe_id=rid, description="build",
                       execution="spawn_planner", estimate={"hours": 1}))
    r = env.ctx.recipes.load(rid)
    r.comprehension.user_signoff = True
    r.comprehension.signoff_quote = "go"
    r.state = "reviewing"
    r.steps[0].status = "done"
    env.ctx.recipes.save(r)
    _ok(await env.call("add_step", recipe_id=rid, description="more work",
                       execution="spawn_planner", estimate={"hours": 1}))
    r2 = env.ctx.recipes.load(rid)
    assert r2.comprehension.signoff_stale is True
    # the FSM holds the reopen on the user
    res = await env.call("next_action", handle=rid, handle_type="recipe")
    d = _ok(res)
    assert d["kind"] == "await_user"
    assert "signoff" in d["rationale"].lower()
    # a fresh signoff clears the marker and the reopen dispatches
    _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                       user_quote="yes, add it"))
    d2 = _ok(await env.call("next_action", handle=rid,
                            handle_type="recipe"))
    assert d2["kind"] != "await_user"


# ── gate hardenings ────────────────────────────────────────────────────────

async def test_g_runs_requires_a_proving_run(env, monkeypatch):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_comprehension_signoff", recipe_id=rid,
                       user_quote="proceed"))
    _ok(await env.call("record_outcome", recipe_id=rid,
                       description="d", verification="v"))
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner",
                             estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="run suite", serves=["o1"],
                       verify={"check": "command", "command": "pytest -q"}))
    monkeypatch.setenv("EDP_ROLE", "")
    # unrelated red run does NOT prove the gate
    msg = _err(await env.call(
        "record_action_status", plan_id=pid, action_id="a1", status="done",
        evidence="ran it",
        runs=[{"command": "echo never-tested", "exit_code": 99,
               "output_tail": "x", "at": _now().isoformat()}]))
    assert "PROVES" in msg or "G-RUNS" in msg
    # a matching exit-0 run does
    _ok(await env.call(
        "record_action_status", plan_id=pid, action_id="a1", status="done",
        evidence="ran it",
        runs=[{"command": "pytest -q", "exit_code": 0,
               "output_tail": "12 passed", "at": _now().isoformat()}]))


async def test_grounding_echo_requires_restatement(env, monkeypatch):
    monkeypatch.setenv("EDP_HANDLE", "plan-x:a1")
    msg = _err(await env.call("notify_above", kind="grounding", body={}))
    assert "restatement" in msg


async def test_g_est_rejects_junk_and_challenge_fails_closed(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    msg = _err(await env.call("add_step", recipe_id=rid, description="big",
                              execution="spawn_planner",
                              estimate={"hours": "large"}))
    assert "G-EST" in msg
    msg2 = _err(await env.call("add_step", recipe_id=rid, description="big",
                               execution="spawn_planner",
                               estimate={"hours": -2}))
    assert "G-EST" in msg2
    # a malformed persisted estimate fails CLOSED at G-CHALLENGE
    p = _plan([{"action_id": "a1", "description": "d", "status": "pending",
                "depends_on": [], "executor_mode": "subagent",
                "acceptance": {"kind": "tests_pass"}}])
    step = type("S", (), {"estimate": {"hours": "large"}})()
    import os
    os.environ["EDP_CHALLENGE_GATE_MIN_ACTIONS"] = "3"
    try:
        assert _challenge_required(p, step) is True
    finally:
        os.environ["EDP_CHALLENGE_GATE_MIN_ACTIONS"] = "0"
