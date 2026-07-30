"""Fix B (2026-05-24) — trust the specialist.

Covers: mark_outcome_met gate (close 'succeeded' requires verified
outcomes); reviewer-fork checks recipe-conformance; update_specialist
resumes the base to refine; the lifecycle (create/update/recreate).
"""

from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe

_CMD = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _stable_specialist(env, base="base-1"):
    c = _ok(await env.call("create_specialization", name="Java Expert",
                           subject="Java", description="java spring boot"))
    nid = c["neuron_id"]
    _ok(await env.call("neuron_set_base_session", neuron_id=nid,
                       session_id=base))
    _ok(await env.call("neuron_set_status", neuron_id=nid,
                       status="pending_review"))
    _ok(await env.call("neuron_set_status", neuron_id=nid, status="stable"))
    return nid


# ── mark_outcome_met ──────────────────────────────────────────────────────
async def test_mark_outcome_met_requires_evidence(env):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id="r", user_goal_verbatim="g", domain="generic",
        state="reviewing",
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "done", "depends_on": [],
                "execution": "spawn_planner"}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    thin = await env.call("mark_outcome_met", recipe_id="r",
                          outcome_id="o1", evidence="ok")
    assert isinstance(thin, ToolError)        # too thin
    _ok(await env.call("mark_outcome_met", recipe_id="r", outcome_id="o1",
                       evidence="reviewer pass + user confirmed live run"))
    o = env.ctx.recipes.load("r").comprehension.expected_outcomes[0]
    assert o.met is True and o.met_evidence


# ── update_specialist (lifecycle) ─────────────────────────────────────────
async def test_update_specialist_resumes_base(env):
    nid = await _stable_specialist(env, base="base-v1")
    out = _ok(await env.call(
        "update_specialist", neuron_id=nid,
        update_instructions="enforce writing JUnit tests; the last "
                            "output skipped them",
        handle="recipe-x"))
    sp = [s for s in env.ctx.pool.spawns if s["role"] == "specialist"][-1]
    # resumes the OLD base, pins a NEW refined snapshot, visible mode
    assert sp["resume_session"] == "base-v1"
    assert sp["claude_session"] == out["base_session_id"] != "base-v1"
    assert sp["mode"] == "monitor"
    task = (await env.ctx.broker.poll(out["specialist_id"]))[0]
    assert task.body["task"] == "update"
    assert "tests" in task.body["update_instructions"]
    assert task.body["resume_from"] == "base-v1"


async def test_planner_stamps_spec_id_so_fresh_worker_loads_doc(env):
    # 2026-06-03 (SPECIALIST-COMPILED-DOCS): execution no longer forks. The
    # planner RESOLVES a specialization to its stable neuron and stamps the
    # spec_id onto the action via the object surface; a FRESH worker then
    # loads that spec's compiled doc (no branch). This is the dispatch path.
    from edp_claude.schemas import Plan
    nid = await _stable_specialist(env, base="b1")
    spec_id = f"spec-{nid}"
    env.ctx.plans.save(Plan.model_validate(dict(
        plan_id="p1", recipe_id="r", recipe_step_id="s1", domain="x",
        shape="x", goal="g", state="dispatching",
        actions=[{"action_id": "a1", "description": "do it",
                  "status": "in_progress", "depends_on": [],
                  "executor_mode": "subagent",
                  "specialization": "X",
                  "acceptance": {"kind": "manual_review"}}],
    )))
    _ok(await env.call("update_object", type="action",
                       ids={"plan_id": "p1", "action_id": "a1"},
                       patch={"spec_id": spec_id}))
    a = env.ctx.plans.load("p1").actions[0]
    # MULTI-SPEC (2026-06-03): the legacy spec_id patch folds into spec_ids
    assert a.effective_spec_ids() == [spec_id]   # the fresh worker loads this doc


def test_brief_warns_expensive_command_verify():
    # 2026-05-31 planner phasing: the verify-authoring discipline lives in
    # the author phase guide (the dispatcher routes there), not the brief.
    ap = (Path(__file__).resolve().parents[1] / "docs" / "guides"
          / "planner-phase-author.md").read_text(encoding="utf-8").lower()
    assert "npm run build" in ap and "is a bug" in ap
    assert "fast" in ap and "artifact" in ap


async def test_update_specialist_requires_existing_base(env):
    c = _ok(await env.call("create_specialization", name="X", subject="x",
                           description="x"))  # no base yet
    r = await env.call("update_specialist", neuron_id=c["neuron_id"],
                       update_instructions="x", handle="r")
    assert isinstance(r, ToolError) and "base_session_id" in r.message


# ── reviewer conformance brief ────────────────────────────────────────────
def test_reviewer_checks_recipe_conformance():
    b = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    assert "conformance" in b
    assert "tests" in b                       # the concrete example
    # 2026-06-02 compiled docs: the reviewer enforces the SAME compiled
    # per-stack doc the coder built against, by its [adherence] tags.
    assert "get_specialist_doc" in b
    assert "adherence" in b
    assert "fail" in b                         # required gap = fail


def test_phase_e_marks_outcomes_and_gates_close():
    e = (Path(__file__).resolve().parents[1] / "docs" / "guides"
         / "neuron-phase-e.md").read_text(encoding="utf-8").lower()
    assert "mark_outcome_met" in e
    assert "conformance" in e
    assert "refuses" in e or "requires every outcome" in e
    # three-tier, cheapest-first, domain-neutral (not code-specific)
    assert "deterministic gate" in e
    assert "only when judgment is needed" in e or "wasted tokens" in e
    # the gate is domain-neutral, not code-only
    assert "validator" in e or "link-checker" in e or "domain" in e


def test_reject_producer_verify_blocks_builds_allows_tests():
    # Bug B (the recurrence source): a producer command as a verify is
    # rejected; tests/linters/validators and artifact checks pass through.
    from edp_claude.tools._tools import _reject_producer_verify
    for cmd in ["npm run build", "vite build", "npm install", "npm ci",
                "yarn build", "pnpm dev", "cargo build", "go build",
                "mvn package", "docker build .", "tsc -b"]:
        assert _reject_producer_verify(
            {"check": "command", "cmd": cmd}) is not None, cmd
    for cmd in ["pytest -q", "npm test", "ruff check", "npm run lint",
                "python validate.py", "markdown-link-check README.md"]:
        assert _reject_producer_verify(
            {"check": "command", "cmd": cmd}) is None, cmd
    assert _reject_producer_verify({"check": "file_exists", "path": "x"}) \
        is None
    assert _reject_producer_verify(None) is None


async def test_add_action_refuses_producer_command_verify(env):
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id="r", user_goal_verbatim="g", domain="generic",
        state="created",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[], context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    _ok(await env.call("create_plan", recipe_id="r", step_id="s1",
                       shape="x", goal="g"))
    bad = await env.call(
        "add_action", plan_id="r-s1", action_id="a1",
        description="build the UI",
        verify={"check": "command", "cmd": "npm run build",
                "cwd": "/x", "expect_exit": 0})
    assert isinstance(bad, ToolError)
    assert "artifact" in bad.message.lower()
    # the artifact form is accepted (same action_id is now free)
    _ok(await env.call(
        "add_action", plan_id="r-s1", action_id="a1",
        description="build the UI",
        verify={"check": "file_min_bytes", "path": "/x/dist/index.html",
                "min": 100}))


def test_spawned_role_briefs_forbid_prompting_user():
    # 2026-05-26: a spawned curiosity shell (EDP_ROLE/HANDLE/BROKER_URL
    # all set) on first activation produced a meta-refusal — "no consult
    # in inbox / I wasn't spawned by a neuron broker" — and asked the
    # human "which?". The model read the skill body as documentation
    # instead of a protocol. Every spawned-role brief must carry a
    # forceful first-turn directive that explicitly forbids prompting
    # the human, so a meta-refusal can't slip back in.
    for name in ("worker.md", "curiosity.md", "specialist.md",
                 "reviewer.md"):
        body = (_CMD / name).read_text(encoding="utf-8").lower()
        assert "never prompt the user" in body, name


def test_reviewer_and_gate_are_domain_neutral():
    # the agent builds more than code — no tech-stack lock-in in the
    # standards-enforcement path.
    rv = (_CMD / "reviewer.md").read_text(encoding="utf-8").lower()
    assert "research specialist" in rv or "design specialist" in rv \
        or "whatever your domain" in rv
    ap = (Path(__file__).resolve().parents[1] / "docs" / "guides"
          / "planner-phase-author.md").read_text(encoding="utf-8").lower()
    assert "domain-neutral" in ap
    assert "research" in ap and "data" in ap   # non-code examples present
