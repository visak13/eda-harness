"""/clear-test (P4) + tool precondition/validator behaviour + skill files."""

from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import ToolError, ToolOk, validate_skill

from edp_claude.server import make_context
from edp_claude.tools import build_registry

SKILLS_DIR = Path(__file__).resolve().parents[1] / ".claude" / "commands"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _recipe(state, steps):
    return {
        "recipe_id": "r", "user_goal_verbatim": "g",
        "user_goal_distilled": "", "domain": "generic", "state": state,
        "comprehension": {"branches": [{"id": "b1", "question": "?",
                                        "status": "resolved",
                                        "verdict": "v"}],
                          "expected_outcomes": []},
        "steps": steps, "context": {}, "final_outcome": None, "version": 1,
        "created_at": _now(), "updated_at": _now(),
    }


async def test_clear_test_resume_from_disk(tmp_path):
    """P4 /clear-test: disk is the single source of truth, and resume is
    deterministic — two INDEPENDENT fresh contexts, each reading only
    recipe.json, must return the SAME instruction at a resting state.

    (next_action is not idempotent across a transition — it advances state
    and persists; that is correct. The guarantee is that once a state is
    persisted, any fresh process resuming from disk agrees on what's next.)"""
    ctx = make_context(tmp_path)
    tools = {t.name: t for t in build_registry(ctx)}
    steps = [{"step_id": "s1", "kind": "research", "description": "d",
              "status": "pending", "depends_on": [], "execution": "inline"}]
    await tools["record_recipe"].run({"recipe": _recipe("planning", steps)})
    # First call drives planning->executing (inline step in progress) and
    # persists. The recipe now rests in 'executing, s1 in_progress'.
    await tools["next_action"].run({"handle": "r", "handle_type": "recipe"})

    # Two independent fresh contexts resume from disk alone.
    r1 = await {t.name: t for t in build_registry(make_context(tmp_path))}[
        "next_action"].run({"handle": "r", "handle_type": "recipe"})
    r2 = await {t.name: t for t in build_registry(make_context(tmp_path))}[
        "next_action"].run({"handle": "r", "handle_type": "recipe"})
    assert isinstance(r1, ToolOk) and isinstance(r2, ToolOk)
    assert r1.data["kind"] == r2.data["kind"] == "wait"  # correct resume


async def test_next_action_unknown_recipe_is_precondition(tmp_path):
    ctx = make_context(tmp_path)
    tools = {t.name: t for t in build_registry(ctx)}
    res = await tools["next_action"].run(
        {"handle": "nope", "handle_type": "recipe"})
    assert isinstance(res, ToolError)
    assert res.code == "tool_precondition"


async def test_record_action_done_requires_evidence(tmp_path):
    ctx = make_context(tmp_path)
    tools = {t.name: t for t in build_registry(ctx)}
    plan = {"plan_id": "p", "recipe_id": "r", "recipe_step_id": "s",
            "domain": "generic", "shape": "linear-build", "goal": "g",
            "state": "drafted",
            "actions": [{"action_id": "a1", "description": "d",
                         "status": "pending", "depends_on": [],
                         "executor_mode": "subagent",
                         "acceptance": {"kind": "tests_pass"}}],
            "context": {}, "version": 1}
    await tools["record_plan"].run({"plan": plan})
    res = await tools["record_action_status"].run(
        {"plan_id": "p", "action_id": "a1", "status": "done"})
    assert isinstance(res, ToolError) and res.code == "tool_precondition"


async def test_bad_input_is_envelope_not_raise(tmp_path):
    ctx = make_context(tmp_path)
    tools = {t.name: t for t in build_registry(ctx)}
    res = await tools["next_action"].run({"handle": "x"})  # missing type
    assert isinstance(res, ToolError) and res.code == "tool_input_invalid"


def test_skills_pass_validate_skill():
    # critic-review retired in v2.4 (the reviewer is a spawned-shell
    # brief, not a front-matter skill). goal-keeper-check deleted with its
    # dead role (owner ruling 2026-08-04).
    for name in ("ocak",):
        v = validate_skill(str(SKILLS_DIR / f"{name}.md"))
        assert v == [], f"{name}: {v}"
