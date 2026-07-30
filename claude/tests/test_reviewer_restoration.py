"""DESIGN-v7 Phase 4 — reviewer restoration.

d67 → d100 → d74 lineage closed:
  * 4.1: dispatching `role="reviewer"` code-composes and SENDS the review
    brief (kind="consult") BEFORE the shell spawns — an empty-inbox reviewer
    (the d100 honest no-op) is structurally impossible; a failed send refuses
    the dispatch whole.
  * 4.2: a reviewer that fixed something in-session states it as DATA
    (`fixed_inline=true`); the plan FSM then advises ONE latched
    DISPATCH_VERIFY_LEG so the reviewer's own fix — the one artifact nothing
    re-ran (d74) — gets its judgment-free re-run.

(The own-leg record_action_status guard and the reviewed-action refusal are
pinned in test_s26_shell_lifecycle.py.)
"""

from edp_contracts import ToolOk

from edp_claude.fsm.plan_fsm import plan_next_action, plan_verify_leg_instruction
from edp_claude.schemas import Plan
from edp_claude.schemas.instruction import InstructionKind as K


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _plan_with_done_work(env):
    rid = _ok(await env.call("start_recipe", goal="g", domain="api"))["recipe_id"]
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner"))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="build the widget"))
    _ok(await env.call("add_action", plan_id=pid, action_id="a9",
                       description="review a1", depends_on=["a1"]))
    # a1 carries recorded work for the reviewer to review.
    p = env.ctx.plans.load(pid)
    a1 = next(x for x in p.actions if x.action_id == "a1")
    a1.status = "done"
    a1.acceptance.actual = "suite green: 12 passed"
    env.ctx.plans.save(p)
    return rid, pid


# ── 4.1 the dispatcher-composed review brief ────────────────────────────────
async def test_reviewer_spawn_sends_the_review_brief_first(env):
    _rid, pid = await _plan_with_done_work(env)
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a9",
                       role="reviewer"))
    inbox = await env.ctx.broker.poll(f"{pid}:a9")
    consults = [m for m in inbox if m.kind == "consult"]
    assert consults, "reviewer spawned with an EMPTY inbox — the d100 no-op"
    body = consults[-1].body
    assert body["task"] == "domain-review"
    assert body["caller"] == pid
    targets = {t["action_id"]: t for t in body["target"]}
    assert "a1" in targets and "a9" not in targets, (
        "the brief must cover the reviewed work, never the review leg itself")
    assert "suite green" in targets["a1"]["evidence"]
    assert "record_branch_verdict" in body["criteria"]


async def test_worker_spawn_sends_no_review_brief(env):
    _rid, pid = await _plan_with_done_work(env)
    _ok(await env.call("pool_spawn_worker", plan_id=pid, action_id="a9",
                       role="worker"))
    inbox = await env.ctx.broker.poll(f"{pid}:a9")
    assert not [m for m in inbox if m.kind == "consult"], (
        "a plain worker dispatch must stay byte-identical — no brief")


# ── 4.2 fixed_inline → one latched DISPATCH_VERIFY_LEG ──────────────────────
def _plan(verdict=None):
    return Plan.model_validate(dict(
        plan_id="r-s1", recipe_id="r", recipe_step_id="s1", domain="generic",
        shape="x", goal="g", state="dispatching",
        actions=[dict(action_id="a1", description="build", status="done",
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass",
                                  "expected": "suite green"},
                      review_verdict=verdict),
                 dict(action_id="a2", description="next", status="pending",
                      depends_on=[], executor_mode="subagent",
                      acceptance={"kind": "tests_pass"})],
    ))


def test_fixed_inline_verdict_advises_exactly_one_verify_leg():
    p = _plan({"verdict": "ok", "fixed_inline": True, "at": "t1"})
    instr = plan_next_action(p)
    assert instr.kind == K.DISPATCH_VERIFY_LEG
    assert instr.args["action_id"] == "a1"
    assert "verify-only" in instr.rationale
    # the very next tick falls through to the dispatch — never wedged (d76)
    nxt = plan_next_action(p)
    assert nxt.kind == K.DISPATCH_ACTION and nxt.args["action_id"] == "a2"


def test_no_fixed_inline_no_advisory():
    p = _plan({"verdict": "ok", "passed": True, "at": "t1"})
    assert plan_verify_leg_instruction(p) is None


def test_a_newer_verdict_on_the_same_action_re_arms_the_latch():
    p = _plan({"verdict": "ok", "fixed_inline": True, "at": "t1"})
    assert plan_next_action(p).kind == K.DISPATCH_VERIFY_LEG
    a1 = next(x for x in p.actions if x.action_id == "a1")
    a1.review_verdict = {"verdict": "again", "fixed_inline": True, "at": "t2"}
    assert plan_verify_leg_instruction(p) is not None, (
        "a NEWER fixed_inline verdict must re-arm the latch")
    assert plan_verify_leg_instruction(p) is None, "…exactly once"


async def test_record_branch_verdict_stamps_fixed_inline(env, monkeypatch):
    _rid, pid = await _plan_with_done_work(env)
    monkeypatch.setenv("EDP_HANDLE", f"{pid}:a9")
    monkeypatch.setenv("EDP_ROLE", "reviewer")
    _ok(await env.call(
        "record_branch_verdict", recipe_id=_rid, plan_id=pid, branch_id="a1",
        verdict=("Re-ran the acceptance command in a fresh shell: 12 passed. "
                 "FIXED: dangling import in widget.py (verified by re-run)."),
        passed=True, fixed_inline=True))
    a1 = next(x for x in env.ctx.plans.load(pid).actions
              if x.action_id == "a1")
    assert a1.review_verdict["fixed_inline"] is True
