"""W9 part 1 — RE-POINTED (d128 user correction; d129 Part A item 1; d132).

This file used to pin the FSM-scheduled direction-review CHECKPOINT: a
`DIRECTION_REVIEW_DUE` instruction telling the NEURON to branch a direction
reviewer, a reconcile-stamped action counter, an overdue nag riding every
worker spawn, and an `off_track` verdict nagging on the recipe_context push.

THE USER'S CORRECTION KILLED THAT CONTRACT: **the reviewer is the PLANNER's
subagent and is never available to the neuron.** A checkpoint ordering the
neuron to spawn one asserted a capability the neuron does not hold. The neuron's
direction integrity is CURIOSITY (OCAK) + SIGNOFF — recheck comprehension,
consult curiosity when bias-risk is high / the decision is large / the recipe is
fresh, record the signoff (a mutually-agreed decision may skip the consult).

So these tests are re-pointed at the NEW contract: THE SURFACE IS GONE AND STAYS
GONE. They are the regression suite — each one FAILS if the neuron-facing
instruction, counter, or nag comes back.

Tests REMOVED (subject genuinely no longer exists — d66: never delete a test to
turn red green; state the reason):
  * T1/T2/T2b/T2c/T2d/T2e — the emission, the 4-vs-5 boundary, the latch, the
    curiosity gate, and the latch's persistence across a tick. All of them
    asserted properties OF the DIRECTION_REVIEW_DUE instruction. The instruction
    does not exist; there is nothing left to bound, latch or gate. Their whole
    subject is now covered by T-A1/T-A2 below, which assert it never fires at
    all.
  * T1b — the counter's step-reachable inclusion predicate
    (`PlanStore.count_done_actions`). The counter is gone and so is the store
    method; nothing counts done actions any more.
  * T3/T3b/T3c — the overdue nag warns-but-never-refuses on the spawn path. The
    nag is gone. T-A3 replaces it: the spawn payload carries NO direction-review
    surface at all, and (the property T3b really protected) the spawn still
    SUCCEEDS.
  * T3d — reconcile stamps the counter the FSM reads. Replaced by T-A4:
    reconcile stamps nothing.
  * T4/T4b — the off_track push and the re-anchor. Replaced by T-A5.

T5 (o6 legacy byte-identity) SURVIVES UNCHANGED and is now load-bearing for a
NEW reason: the two recipe fields are VESTIGIAL — retained with no reader
because `Recipe` is extra="forbid" and recipes on disk still carry them, so
deleting them would refuse to load every existing recipe. T5 pins that a legacy
recipe still round-trips byte-identically through the vestigial fields.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.fsm.recipe_fsm import recipe_context, recipe_next_action
from edp_claude.schemas import InstructionKind, Recipe, RecipeState
from edp_claude.schemas.recipe import Outcome

_SRC = Path(__file__).resolve().parents[1] / "src" / "edp_claude"

K = InstructionKind


def _now():
    return datetime.now(timezone.utc)


def _recipe(*, steps, curiosity_cleared=True, state="executing", **over):
    return Recipe.model_validate(dict(
        recipe_id="r-w9", user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="framework", state=state,
        comprehension={
            "branches": [], "curiosity_cleared": curiosity_cleared,
            "user_signoff": True,
            "expected_outcomes": [
                {"id": "o1", "description": "d", "verification": "v"}],
        },
        steps=steps,
        context={"decisions": [], "assumptions": [], "rejected_options": []},
        created_at=_now(), updated_at=_now(), **over,
    ))


def _step(step_id, status="in_progress"):
    return {"step_id": step_id, "kind": "work", "description": "d",
            "status": status, "depends_on": [], "execution": "spawn_planner"}


def _data(res):
    assert isinstance(res, ToolOk), res
    return res.data


async def _recipe_with_plan(t):
    rid = _data(await t["start_recipe"].run({"goal": "g", "domain": "api"}))[
        "recipe_id"]
    sid = _data(await t["add_step"].run(
        {"recipe_id": rid, "description": "build",
         "execution": "spawn_planner", "estimate": {"hours": 1}}))["step_id"]
    pid = _data(await t["create_plan"].run(
        {"recipe_id": rid, "step_id": sid, "shape": "poc-iterate-build",
         "goal": "build the thing"}))["plan_id"]
    await t["add_action"].run(
        {"plan_id": pid, "action_id": "a1",
         "description": "do generic narrow work"})
    return rid, sid, pid


# ══════════════════════════════════════════════════════════════════════════
# T-A1 — THE INSTRUCTION KIND DOES NOT EXIST
# ══════════════════════════════════════════════════════════════════════════
def test_ta1_no_direction_review_instruction_kind_exists():
    """The strongest pin available: the enum member itself is gone, so no code
    path can construct the instruction even by accident."""
    assert not hasattr(InstructionKind, "DIRECTION_REVIEW_DUE")
    assert "direction_review_due" not in {k.value for k in InstructionKind}


# ══════════════════════════════════════════════════════════════════════════
# T-A2 — THE STATE MACHINE NEVER EMITS IT, at the exact states it used to
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("state,steps,expect", [
    # the old N-actions crossing, mid-flight: used to emit at >=5. Now: WAIT.
    ("executing", [_step("s1", "in_progress")], "wait"),
    # the old step-completion crossing: used to emit. Now: dispatch.
    ("planning", [_step("s1", "done"), _step("s2", "pending")],
     "spawn_planner"),
])
def test_ta2_the_old_crossings_now_dispatch_or_wait(state, steps, expect):
    """RED-if-restored: drive the FSM through the two states that USED to trip
    the checkpoint, with the counter pushed far past every old threshold (150 —
    the live framework recipe's real value, 30x the old every_n=5, and past the
    2N overdue line). It must simply dispatch or wait."""
    r = _recipe(steps=steps, state=state)
    r.actions_done_since_direction_review = 150   # the real live value

    instr = recipe_next_action(r)
    assert instr.kind.value == expect, (
        f"the FSM emitted {instr.kind.value!r} at the old crossing — the "
        "neuron-facing direction-review checkpoint is back")
    assert "direction" not in instr.rationale.lower()
    assert "branch_reviewer" not in instr.rationale
    # and it stays gone tick after tick (the old latch let it re-arm per tier)
    for _ in range(3):
        r.state = RecipeState(state)
        for s in r.steps:
            if s.status == "in_progress" and state == "planning":
                s.status = "pending"
        assert recipe_next_action(r).kind.value != "direction_review_due"


def test_ta2b_the_fsm_module_holds_no_direction_review_symbols():
    """The helpers themselves are gone — not merely unreferenced. A future edit
    cannot re-wire a surviving private helper back into next_action."""
    import edp_claude.fsm.recipe_fsm as fsm

    for gone in ("direction_review_status", "_direction_review_instruction",
                 "mark_direction_reviewed", "_direction_review_off_track"):
        assert not hasattr(fsm, gone), f"{gone} came back"

    import edp_claude.fsm as fsm_pkg
    assert "direction_review_status" not in fsm_pkg.__all__
    assert "mark_direction_reviewed" not in fsm_pkg.__all__


# ══════════════════════════════════════════════════════════════════════════
# T-A3 — THE WORKER SPAWN CARRIES NO NAG (and still succeeds)
# ══════════════════════════════════════════════════════════════════════════
async def test_ta3_overdue_recipe_spawn_carries_no_direction_surface(env):
    """The nag that fired on THIS action's own spawn ("DIRECTION REVIEW OVERDUE
    — 149 actions done since the last one … Branch a direction reviewer
    (branch_reviewer(scope='direction', …))"). Driven through the REAL tool on a
    recipe whose counter is far past the old overdue line.

    Two claims: (a) no direction-review surface anywhere in the payload or the
    worklog; (b) the spawn still SUCCEEDS — the property the old test_t3b
    protected survives the removal of the thing it was protecting against."""
    t = env.tools
    rid, sid, pid = await _recipe_with_plan(t)

    r = env.ctx.recipes.load(rid)
    r.actions_done_since_direction_review = 149      # would have been overdue
    env.ctx.recipes.save(r)

    res = await t["pool_spawn_worker"].run({"plan_id": pid, "action_id": "a1"})

    assert isinstance(res, ToolOk), res              # (b) the spawn still lands
    assert "direction_review" not in res.data, (
        "the spawn payload carries a direction-review nag again")
    blob = json.dumps(res.data).lower()
    assert "direction review" not in blob and "branch_reviewer" not in blob
    # the shell really launched
    assert [s for s in env.ctx.pool.spawns if s.get("handle") == f"{pid}:a1"]
    # ...and nothing was written to the worklog trail either
    assert env.ctx.plans.read_worklog(
        pid, tail=50, kinds=["direction_review_overdue"]) == []


def test_ta3b_the_overdue_warning_helper_is_gone():
    import edp_claude.tools._tools as tools
    assert not hasattr(tools, "_direction_review_overdue_warning")


# ══════════════════════════════════════════════════════════════════════════
# T-A4 — RECONCILE STAMPS NOTHING
# ══════════════════════════════════════════════════════════════════════════
async def test_ta4_reconcile_no_longer_counts_done_actions(env):
    """The counter was reconcile's; the FSM only read it. Both halves are gone:
    a done action moves no counter, and the store method that aggregated them
    does not exist."""
    t = env.tools
    rid, sid, pid = await _recipe_with_plan(t)

    p = env.ctx.plans.load(pid)
    p.actions[0].status = "done"
    env.ctx.plans.save(p)

    await t["reconcile"].run({"handle": rid, "handle_type": "recipe"})
    assert env.ctx.recipes.load(rid).actions_done_since_direction_review == 0, (
        "reconcile is stamping the direction-review counter again")

    assert not hasattr(env.ctx.plans, "count_done_actions")
    assert not hasattr(env.ctx.plans, "harvest_artifact_paths")


# ══════════════════════════════════════════════════════════════════════════
# T-A5 — NOTHING RIDES THE NEURON'S CONTEXT PUSH
# ══════════════════════════════════════════════════════════════════════════
def test_ta5_recipe_context_carries_no_direction_review_key():
    """The off_track nag rode `context.direction_review` every tick. Even with
    a stale verdict left on the vestigial field by a PRE-removal recipe, the
    push must stay silent — a legacy recipe cannot resurrect the surface."""
    r = _recipe(steps=[_step("s1")])
    r.direction_review.last_verdict = {          # what an old run left behind
        "verdict": "off_track",
        "findings": ["hardcoded HTML generation against a simple ask"],
        "sampled_paths": ["src/gen.py"],
    }
    ctx = recipe_context(r)
    assert "direction_review" not in ctx, (
        "a stale on-disk verdict resurrected the neuron-facing nag")
    blob = json.dumps(ctx).lower()
    assert "off_track" not in blob and "direction review" not in blob


async def test_ta5b_the_recipe_digest_carries_no_direction_review_key(env):
    """The same nag also rode the digest, so a compacted/re-grounded shell
    re-saw it. That relay is gone too."""
    t = env.tools
    rid, sid, pid = await _recipe_with_plan(t)
    r = env.ctx.recipes.load(rid)
    r.direction_review.last_verdict = {"verdict": "off_track",
                                       "findings": ["f"], "sampled_paths": []}
    env.ctx.recipes.save(r)

    d = _data(await t["get_recipe_digest"].run({"recipe_id": rid}))
    assert "direction_review" not in json.dumps(d)


# ══════════════════════════════════════════════════════════════════════════
# T-A6 — the GUIDES no longer instruct the neuron to branch one
# ══════════════════════════════════════════════════════════════════════════
def test_ta6_neuron_guides_name_curiosity_and_signoff_not_a_reviewer():
    """The removal is only real if the neuron's own instructions changed. The
    phase-d guide must state the CORRECT mechanism and must not name the verb."""
    guides = Path(__file__).resolve().parents[1] / "docs" / "guides"
    phase_d = (guides / "neuron-phase-d.md").read_text(encoding="utf-8")
    ref = (guides / "neuron-protocol-reference.md").read_text(encoding="utf-8")

    for name, text in (("neuron-phase-d.md", phase_d),
                       ("neuron-protocol-reference.md", ref)):
        assert 'scope="direction"' not in text, name
        assert "scope='direction'" not in text, name
        assert "direction_review_due" not in text, name

    # ...and phase-d names the mechanism that REPLACED it (leanly — d50)
    low = phase_d.lower()
    assert "curiosity" in low and "signoff" in low
    assert "comprehension_recheck" in low


# ══════════════════════════════════════════════════════════════════════════
# T5 (SURVIVES) — o6: the legacy fixture is still byte-identical
# ══════════════════════════════════════════════════════════════════════════
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
RECIPES = Path(__file__).resolve().parents[1] / ".recipes"


def test_t5_legacy_fixture_byte_identical_with_the_vestigial_fields_present(
        monkeypatch, tmp_path):
    """o6, and now the pin on the VESTIGIAL fields' reason for existing.

    `direction_review` + `actions_done_since_direction_review` have NO reader
    left. They stay on the model because `Recipe` is extra="forbid" and recipes
    already on disk carry them — deleting the fields would refuse to load every
    one of those recipes, and purging them from disk would be a store rewrite
    (which lazy migration forbids). This test pins both halves: the fields still
    default-populate on a legacy recipe, and they still serialize away."""
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), (
        f"legacy fixture {LEGACY_RID} missing under {RECIPES}")
    original = (rdir / "recipe.json").read_text(encoding="utf-8")

    raw = json.loads(original)
    assert "direction_review" not in raw
    assert "actions_done_since_direction_review" not in raw

    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))

    # PRESENT in memory (this is what keeps a post-W9 recipe loadable) ...
    assert model.actions_done_since_direction_review == 0
    assert model.direction_review.every_n == 5
    assert model.direction_review.baseline == {}
    assert model.direction_review.last_verdict is None

    # ... and ABSENT on disk: re-serializing reproduces the original bytes.
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)
    assert reserialized == original, (
        "legacy fixture round-trip is NOT byte-identical")


def test_t5b_a_recipe_carrying_the_vestigial_fields_still_loads():
    """The reason the fields cannot simply be deleted, asserted rather than
    argued. `extra="forbid"` means a model without them REFUSES this payload —
    and the live framework recipe on disk looks exactly like this."""
    r = _recipe(steps=[_step("s1")])
    raw = r.model_dump(mode="json")
    raw["actions_done_since_direction_review"] = 150      # the live value
    raw["direction_review"] = {"every_n": 5,
                               "baseline": {"actions_done": 0, "steps_done": 0},
                               "emitted": {"tier": 30, "steps": 28},
                               "last_verdict": None}

    reloaded = Recipe.model_validate(raw)     # must not raise
    assert reloaded.actions_done_since_direction_review == 150
    # ...and the loaded recipe still emits no checkpoint from that state
    assert recipe_next_action(reloaded).kind.value != "direction_review_due"
