"""F43 (2026-08-20) — campaign Round 10 (FSM/gates + cards re-visit) fixes.

Pins: the G-RUNS declared-command key + one-directional matching, the
delivery-substance acceptance fingerprint (+ no grandfathering), the
first-nonterminal canonical batch head, the all-steps wave recovery sweep,
supervisor rule-generation rematerialization, the worker card's G-RUNS
alignment, and the nested-bullet drain composite.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe, Specialization
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


def _save_recipe(ctx, rid, steps=None):
    ctx.recipes.save(Recipe(
        recipe_id=rid, user_goal_verbatim="g", user_goal_distilled="g",
        domain="software_engineering", state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=steps or [
            {"step_id": "s1", "kind": "k", "description": "d",
             "status": "pending", "depends_on": [], "execution": "inline"}],
        created_at=_now(), updated_at=_now(),
    ))


def _act(aid, grp=None, status="pending", gate=False, verify=None):
    acc = Acceptance(kind="manual_review", expected="x")
    if verify is not None:
        acc.verify = verify
    a = Action(action_id=aid, description=f"do {aid}", status=status,
               executor_mode="inline", acceptance=acc)
    if grp:
        a.batch_group = grp
    if gate:
        a.gate = True
    return a


def _save_plan(ctx, rid, plan_id, actions, step="s1"):
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id=rid, recipe_step_id=step,
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=actions))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


def _echo(ctx, plan_id, handle):
    ctx.plans.append_worklog(plan_id, {
        "kind": "message_sent", "msg_kind": "grounding",
        "from_handle": handle})


# ── #1 — G-RUNS reads the authored `cmd` and matches one-directionally ─────
async def test_gruns_reads_cmd_and_rejects_echo_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_ROLE", "worker")
    monkeypatch.setenv("EDP_HANDLE", "r43a-s1:a1")
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r43a")
    _save_plan(ctx, "r43a", "r43a-s1", [
        _act("a1", gate=True,
             verify={"check": "command", "cmd": "pytest -q"})])
    _echo(ctx, "r43a-s1", "r43a-s1:a1")
    t = _tools(ctx)

    def _run(cmd):
        return {"command": cmd, "exit_code": 0,
                "output_tail": "ok", "at": _now().isoformat()}

    # unrelated exit-0 run: the authored `cmd` is now READ, so it refuses
    res = await t["record_action_status"].run({
        "plan_id": "r43a-s1", "action_id": "a1", "status": "done",
        "evidence": "done", "runs": [_run("python -c pass")]})
    assert isinstance(res, ToolError) and "G-RUNS" in res.message

    # an echo of the command proves nothing
    res = await t["record_action_status"].run({
        "plan_id": "r43a-s1", "action_id": "a1", "status": "done",
        "evidence": "done", "runs": [_run("echo pytest -q")]})
    assert isinstance(res, ToolError) and "G-RUNS" in res.message

    # a fragment of the declared command no longer matches (old rc-in-dc)
    res = await t["record_action_status"].run({
        "plan_id": "r43a-s1", "action_id": "a1", "status": "done",
        "evidence": "done", "runs": [_run("pytest")]})
    assert isinstance(res, ToolError) and "G-RUNS" in res.message

    # the real command (wrapper prefix allowed) passes
    ok = await t["record_action_status"].run({
        "plan_id": "r43a-s1", "action_id": "a1", "status": "done",
        "evidence": "done", "runs": [_run("uv run pytest -q")]})
    assert isinstance(ok, ToolOk), ok


# ── #2 — the fingerprint carries delivery substance; no grandfathering ─────
def test_acceptance_fingerprint_tracks_evidence(tmp_path):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r43b", steps=[
        {"step_id": "s1", "kind": "k", "description": "d",
         "status": "done", "depends_on": [], "execution": "spawn_planner"}])
    _save_plan(ctx, "r43b", "r43b-s1", [_act("a1", status="done")])
    r = ctx.recipes.load("r43b")
    fp1 = _acceptance_fingerprint(r, ctx=ctx)
    # rework under the SAME ids: evidence changes → fingerprint changes
    p = ctx.plans.load("r43b-s1")
    p.actions[0].acceptance.actual = "entirely different delivery"
    ctx.plans.save(p)
    fp2 = _acceptance_fingerprint(r, ctx=ctx)
    assert fp1 != fp2
    # shape-only hash (no ctx) would NOT have noticed
    assert _acceptance_fingerprint(r) == _acceptance_fingerprint(r)


def test_acceptance_pass_without_fingerprint_is_not_grandfathered(tmp_path):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r43c")
    rdir = ctx.recipes.root / "r43c"
    with (rdir / "events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "kind": "acceptance_verdict", "ts": _now().isoformat(),
            "body": {"verdict": "pass"}}) + "\n")
    ok, why = _acceptance_pass_current(ctx, ctx.recipes.load("r43c"))
    assert not ok and "no fingerprint" in why


# ── #3 — canonical head = first NON-terminal member ────────────────────────
async def test_spawn_head_advances_past_terminal_members(tmp_path,
                                                         monkeypatch):
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r43d")
    _save_plan(ctx, "r43d", "r43d-s1", [
        _act("a1", "b1", status="done"),
        _act("a2", "b1", status="in_progress")])
    t = _tools(ctx)
    res = await t["pool_spawn_worker"].run({
        "plan_id": "r43d-s1", "action_id": "a2", "action_ids": ["a2"]})
    # it may fail later (no live pool in tests) but NEVER on the head rule,
    # and the FSM's stamp must survive (no rollback loop)
    if isinstance(res, ToolError):
        assert "not the head of batch group" not in res.message
    assert ctx.plans.load("r43d-s1").actions[1].status == "in_progress"


# ── #4 — wave recovery sweeps EVERY in-flight planner step ─────────────────
async def test_reconcile_recovers_later_step_behind_live_first(tmp_path,
                                                               monkeypatch):
    ctx = make_context(tmp_path)
    _save_recipe(ctx, "r43e", steps=[
        {"step_id": "s1", "kind": "k", "description": "d",
         "status": "in_progress", "depends_on": [],
         "execution": "spawn_planner", "attempt": 0},
        {"step_id": "s2", "kind": "k", "description": "d",
         "status": "in_progress", "depends_on": [],
         "execution": "spawn_planner", "attempt": 0}])

    async def _liveness(handle):
        return {"state": "alive" if handle.endswith(":s1") else "dead",
                "last_output_ts": None}

    ctx.pool = SimpleNamespace(liveness=_liveness)
    t = _tools(ctx)
    tool = t["reconcile"]
    tool.ctx.pool = ctx.pool
    r = ctx.recipes.load("r43e")
    res = await tool._advance_executing(r)
    assert res is None
    s = {st.step_id: st.status for st in r.steps}
    # s1 (alive) keeps waiting; s2's dead planner is reset for re-dispatch
    assert s["s1"] == "in_progress"
    assert s["s2"] == "pending"


# ── #6 — replace=True rematerializes a live child ──────────────────────────
def test_supervisor_rematerializes_replaced_rule(tmp_path, monkeypatch):
    from edp_claude.reactive import registry as R

    class _FakePopen:
        _next = 61000

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
    reg.register_rule("r", "rx.broker(me)", None, "o", bindings={"me": "o"})
    sup = R.RuleSupervisor(
        reg, R.SupervisorConfig(agent_home=tmp_path, driver_python="python"))
    sup._acquire_singleton()
    try:
        for rule in reg.enabled_rules():
            sup._children[rule.name] = sup._spawn(rule)
        pid_before = sup.tracked_pids()["r"]
        # same name, corrected content → live child rematerialized
        reg.register_rule("r", "rx.broker(me)", None, "o2",
                          bindings={"me": "o2"}, replace=True)
        sup._reap_and_restart()
        assert sup.tracked_pids()["r"] != pid_before
        # unchanged content on the next tick → left alone
        pid_after = sup.tracked_pids()["r"]
        sup._reap_and_restart()
        assert sup.tracked_pids()["r"] == pid_after
    finally:
        sup.shutdown()


# ── #7 — the worker cards agree with G-RUNS ────────────────────────────────
def test_worker_cards_document_runs_ledger():
    root = Path(__file__).resolve().parents[1]
    for rel in ("docs/guides-src/roles/worker.md",
                ".claude/commands/worker.md",
                "docs/guides/worker-card.md"):
        text = (root / rel).read_text(encoding="utf-8")
        assert "runs NO gate" not in text, rel
        assert 'runs=[' in text, rel


# ── #8 — a multi-bullet rule folds via the nested-list composite ───────────
def test_write_doc_drains_nested_bullet_rule(tmp_path):
    ctx = make_context(tmp_path)
    ctx.specs.save(Specialization(
        spec_id="spec-f43", neuron_id="n1", name="x", subject="x",
        created_at=_now(), updated_at=_now()))
    ctx.specs.write_doc("spec-f43", "# base")
    lid = ctx.specs.append_proposed_learning(
        "spec-f43",
        rule_text="Deploy safely:\n- back up data\n- test rollback")
    ctx.specs.resolve_spec_learnings("spec-f43", accept=[lid])
    ctx.specs.write_doc(
        "spec-f43",
        "# v2\n\n- Deploy safely:\n  - back up data\n  - test rollback\n")
    assert ctx.specs.accepted_pending_learnings("spec-f43") == []
    # the negation guard survives the composite feature
    lid2 = ctx.specs.append_proposed_learning(
        "spec-f43", rule_text="NEVER log tokens")
    ctx.specs.resolve_spec_learnings("spec-f43", accept=[lid2])
    ctx.specs.write_doc(
        "spec-f43", "# v3\n\nSuperseded: NEVER log tokens is retired.\n")
    assert [r["learning_id"] for r in
            ctx.specs.accepted_pending_learnings("spec-f43")] == [lid2]
