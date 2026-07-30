"""record_action_status — d30 PURE WRITE (USER DIRECTIVE, refines d29).

History: 2026-05-21 introduced an in-process acceptance gate at
record_action_status(done); 2026-05-28 softened a failing gate to PARK the
action in `verify` instead of hard-rejecting; d29 stopped running COMMAND
acceptance in the tool (worker/reviewer re-run it in-shell) but KEPT the pure
in-process stat/glob checks (file_exists / file_min_bytes / glob_matches)
gating the done path.

d30 removes that too: record_action_status now runs LITERALLY NOTHING. It
records status + evidence as INERT DATA, spawns nothing, executes nothing, and
NEVER routes to `verify`. The file/glob acceptance criteria survive as
action.acceptance DATA and are enforced by the WORKER (own shell) and the
REVIEWER (fresh shell) — the dual-gate model. A done-claim lands directly as
`done` (worker-done-awaiting-review); the needs_review + worker->reviewer chain
is the gate before the step closes. These tests pin that pure-write contract:
a done-claim lands `done` EVEN WHEN the verify deliverable is absent (the tool
no longer checks), and NO acceptance_verified / verify_pending worklog is
written on the record path.
"""

from edp_contracts import ToolOk


def _plan_with_verify(env, pid, verify, aid="a1"):
    from edp_claude.schemas import Plan

    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id=pid, recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": aid, "description": "build a file",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "file_exists", "verify": verify}}],
    )))


async def test_done_lands_done_even_when_file_missing(env, tmp_path):
    # d30 inversion of the old calendar case: the tool runs NO check, so a
    # done-claim lands `done` even though the deliverable is absent. The
    # worker (own shell) and reviewer (fresh shell) are the real gate now.
    missing = tmp_path / "index.html"
    _plan_with_verify(env, "plan-v1",
                      {"check": "file_exists", "path": str(missing)})
    res = await env.call(
        "record_action_status", plan_id="plan-v1", action_id="a1",
        status="done", evidence="I built index.html")
    assert isinstance(res, ToolOk)
    assert res.data["status"] == "done"          # NOT verify — pure write
    assert env.ctx.plans.load("plan-v1").actions[0].status == "done"


async def test_done_lands_done_when_file_present(env, tmp_path):
    real = tmp_path / "index.html"
    real.write_text("<html></html>", encoding="utf-8")
    _plan_with_verify(env, "plan-v2",
                      {"check": "file_exists", "path": str(real)})
    res = await env.call(
        "record_action_status", plan_id="plan-v2", action_id="a1",
        status="done", evidence="built index.html")
    assert isinstance(res, ToolOk)
    assert env.ctx.plans.load("plan-v2").actions[0].status == "done"


async def test_file_min_bytes_verify_is_not_gated(env, tmp_path):
    # A tiny file that would have FAILED the old d29 min-bytes gate now lands
    # `done` unchanged — the criterion is data the worker/reviewer re-run.
    small = tmp_path / "app.html"
    small.write_text("hi", encoding="utf-8")  # 2 bytes
    _plan_with_verify(env, "plan-v3",
                      {"check": "file_min_bytes", "path": str(small),
                       "min": 1000})
    res = await env.call(
        "record_action_status", plan_id="plan-v3", action_id="a1",
        status="done", evidence="built it")
    assert isinstance(res, ToolOk)
    assert res.data["status"] == "done"
    assert env.ctx.plans.load("plan-v3").actions[0].status == "done"


async def test_glob_verify_is_not_gated(env, tmp_path):
    # No matching files, yet the claim lands `done` — the tool runs no glob.
    _plan_with_verify(env, "plan-v4",
                      {"check": "glob_matches",
                       "pattern": str(tmp_path / "*.js"),
                       "min_count": 1})
    res = await env.call(
        "record_action_status", plan_id="plan-v4", action_id="a1",
        status="done", evidence="wrote modules")
    assert isinstance(res, ToolOk)
    assert res.data["status"] == "done"


async def test_no_verify_block_is_unchanged_behavior(env):
    # Actions without a verify block keep the evidence-string behavior.
    from edp_claude.schemas import Plan
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id="plan-v5", recipe_id="r", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "d",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "manual_review"}}],
    )))
    res = await env.call(
        "record_action_status", plan_id="plan-v5", action_id="a1",
        status="done", evidence="reviewed, looks good")
    assert isinstance(res, ToolOk)
    assert res.data["status"] == "done"


async def test_done_requires_evidence(env, tmp_path):
    # The ONE precondition the pure write still enforces: `done` needs
    # evidence (a claim with no proof is refused — nothing recorded).
    from edp_contracts import ToolError
    _plan_with_verify(env, "plan-ve",
                      {"check": "file_exists", "path": str(tmp_path / "z")})
    res = await env.call(
        "record_action_status", plan_id="plan-ve", action_id="a1",
        status="done", evidence=None)
    assert isinstance(res, ToolError)
    assert env.ctx.plans.load("plan-ve").actions[0].status == "in_progress"


async def test_record_path_writes_no_gate_worklog(env, tmp_path):
    # d30: the tool writes NEITHER acceptance_verified NOR verify_pending on
    # the record/status=done path — it runs no gate, so there is nothing to
    # log. (These kinds are only produced now if something appends them
    # directly, e.g. in unrelated rx/read-efficiency fixtures.)
    missing = tmp_path / "out.html"
    _plan_with_verify(env, "plan-v6",
                      {"check": "file_exists", "path": str(missing)})
    await env.call("record_action_status", plan_id="plan-v6",
                   action_id="a1", status="done", evidence="done")
    import json
    from pathlib import Path
    wl = Path(env.ctx.plans.root) / "plan-v6" / "worklog.jsonl"
    kinds = []
    if wl.exists():
        kinds = [json.loads(x)["kind"]
                 for x in wl.read_text(encoding="utf-8").splitlines()
                 if x.strip()]
    assert "acceptance_verified" not in kinds
    assert "verify_pending" not in kinds


async def test_verify_criteria_retained_as_data(env, tmp_path):
    # The acceptance.verify block is PRESERVED as data (the read surface the
    # worker/reviewer re-run) — the pure write does not strip or consume it.
    missing = tmp_path / "keep.html"
    _plan_with_verify(env, "plan-v7",
                      {"check": "file_exists", "path": str(missing)})
    await env.call("record_action_status", plan_id="plan-v7",
                   action_id="a1", status="done", evidence="claim")
    a = env.ctx.plans.load("plan-v7").actions[0]
    assert a.acceptance.verify == {"check": "file_exists", "path": str(missing)}
    assert a.acceptance.actual == "claim"          # evidence recorded as data


async def test_plan_advances_past_done_action_not_parked(env, tmp_path):
    # A done-claim is TERMINAL now (not parked in a non-terminal verify): the
    # plan does not WAIT on it as if a gate were pending.
    missing = tmp_path / "z.html"
    _plan_with_verify(env, "plan-vfsm",
                      {"check": "file_exists", "path": str(missing)})
    r = await env.call("record_action_status", plan_id="plan-vfsm",
                       action_id="a1", status="done", evidence="claim")
    assert r.data["status"] == "done"
    d = await env.call("next_action", handle="plan-vfsm", handle_type="plan")
    # single action is done → plan moves toward acceptance/terminal, it does
    # NOT sit on a `verify` wait.
    assert "verify" not in d.data.get("rationale", "").lower()
