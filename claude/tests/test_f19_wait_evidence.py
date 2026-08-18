"""F19 (2026-08-17) — a WAIT instruction carries its own liveness evidence.

Observed live: a worker crashed, the FSM said wait, the parent obeyed for 30
minutes. `_stamp_wait_evidence` probes pool liveness for every handle a WAIT
is actually on and stamps the result into args; a dead child makes the
rationale itself say "do NOT wait — reconcile now". Zero agent tokens spent
validating the FSM.
"""

from datetime import datetime, timezone

from edp_claude.schemas.instruction import Instruction, InstructionKind
from edp_claude.schemas import Recipe
from edp_claude.schemas.plan import Acceptance, Action, Plan
from edp_claude.server import make_context
from edp_claude.tools._tools import _stamp_wait_evidence


def _now():
    return datetime.now(timezone.utc)


def _wait():
    return Instruction(kind=InstructionKind.WAIT, args={}, rationale="wait.")


def _save_plan(ctx, plan_id, statuses):
    acts = [Action(action_id=aid, description=aid, status=st,
                   executor_mode="inline",
                   acceptance=Acceptance(kind="manual_review", expected="x"))
            for aid, st in statuses.items()]
    ctx.plans.save(Plan(
        plan_id=plan_id, recipe_id="recipe-f19", recipe_step_id="s1",
        domain="software_engineering", shape="parallel_multitool",
        goal="g", state="dispatching", actions=acts))


async def test_wait_on_plan_stamps_awaiting_and_flags_dead(tmp_path):
    ctx = make_context(tmp_path)
    _save_plan(ctx, "recipe-f19-s1",
               {"a1": "in_progress", "a2": "pending", "a3": "verify"})
    await ctx.pool.spawn_worker("recipe-f19-s1", "a3")     # a3 alive
    ctx.pool.mark_dead("recipe-f19-s1:a1")                 # a1 crashed

    instr = _wait()
    await _stamp_wait_evidence(ctx, instr, "recipe-f19-s1", "plan")
    rows = {r["handle"]: r for r in instr.args["awaiting"]}
    # only the in-flight actions are probed (pending a2 is not awaited)
    assert set(rows) == {"recipe-f19-s1:a1", "recipe-f19-s1:a3"}
    assert rows["recipe-f19-s1:a1"]["liveness"] == "dead"
    assert rows["recipe-f19-s1:a3"]["liveness"] == "alive"
    # the dead child rewrites the wait into an order to reconcile NOW
    assert "DEAD" in instr.rationale and "reconcile" in instr.rationale


async def test_wait_on_recipe_probes_planner_steps(tmp_path):
    ctx = make_context(tmp_path)
    ctx.recipes.save(Recipe(
        recipe_id="recipe-f19", user_goal_verbatim="g",
        user_goal_distilled="g", domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner"},
               {"step_id": "s2", "kind": "k", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"}],
        created_at=_now(), updated_at=_now(),
    ))
    ctx.pool.mark_dead("recipe-f19:s1")

    instr = _wait()
    await _stamp_wait_evidence(ctx, instr, "recipe-f19", "recipe")
    rows = instr.args["awaiting"]
    assert [r["handle"] for r in rows] == ["recipe-f19:s1"]
    assert rows[0]["liveness"] == "dead"
    assert "DEAD" in instr.rationale


async def test_non_wait_instruction_is_untouched(tmp_path):
    ctx = make_context(tmp_path)
    instr = Instruction(kind=InstructionKind.REASON, args={}, rationale="r.")
    await _stamp_wait_evidence(ctx, instr, "recipe-f19", "recipe")
    assert "awaiting" not in instr.args and instr.rationale == "r."
