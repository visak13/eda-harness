"""Item 1 Part B — comprehension recurrence (the FSM SUGGESTS a fresh-shell
curiosity re-consult at meaningful points, not every step).

Curiosity's implementation is unchanged (separate, unbiased shell). The only
change: recipe_context surfaces a `comprehension_recheck` suggestion when a
meaningful trigger fires — REPEATED FAILURES (a step re-dispatched >=2x) OR
MAJOR SCOPE CHANGE vs the comprehension baseline (the map grew past what was
grounded). Not before initial comprehension; not on a clean recipe.
"""
from datetime import datetime, timezone

from edp_claude.fsm.recipe_fsm import recipe_context
from edp_claude.schemas import Recipe


def _recipe(attempt, cleared=True):
    return Recipe.model_validate(dict(
        recipe_id="r-i1", user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "curiosity_cleared": cleared,
                       "expected_outcomes": [{"id": "o1", "description": "d",
                                              "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner", "attempt": attempt}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))


def test_item1_recheck_suggested_on_repeated_failures():
    ctx = recipe_context(_recipe(attempt=2))
    assert "comprehension_recheck" in ctx
    msg = ctx["comprehension_recheck"]
    assert "consult_curiosity" in msg and "FRESH" in msg


def test_item1_no_recheck_on_a_clean_recipe():
    ctx = recipe_context(_recipe(attempt=0))
    assert "comprehension_recheck" not in ctx


def test_item1_no_recheck_before_initial_comprehension():
    # repeated failures but comprehension itself isn't done yet -> no re-check
    ctx = recipe_context(_recipe(attempt=3, cleared=False))
    assert "comprehension_recheck" not in ctx


def _recipe_with_baseline(n_steps, n_outcomes, base_steps, base_outcomes,
                          cleared=True):
    """A cleared recipe carrying a comprehension baseline + a live map of a
    given size (no repeated failures — isolates the scope-change trigger)."""
    outcomes = [{"id": f"o{i}", "description": "d", "verification": "v"}
                for i in range(n_outcomes)]
    steps = [{"step_id": f"s{i}", "kind": "work", "description": "d",
              "status": "pending", "depends_on": [],
              "execution": "spawn_planner", "attempt": 0}
             for i in range(n_steps)]
    return Recipe.model_validate(dict(
        recipe_id="r-i1b", user_goal_verbatim="g", domain="generic",
        state="executing",
        comprehension={"branches": [], "curiosity_cleared": cleared,
                       "expected_outcomes": outcomes,
                       "baseline": {"n_steps": base_steps,
                                    "n_outcomes": base_outcomes}},
        steps=steps, context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))


def test_item1_recheck_on_major_step_growth():
    # grew from 2 -> 4 steps (>=2 more) since comprehension -> suggest
    ctx = recipe_context(_recipe_with_baseline(
        n_steps=4, n_outcomes=2, base_steps=2, base_outcomes=2))
    assert "comprehension_recheck" in ctx
    assert "SCOPE CHANGE" in ctx["comprehension_recheck"]


def test_item1_recheck_on_new_outcome_midflight():
    # one new outcome added after the map was comprehended -> suggest
    ctx = recipe_context(_recipe_with_baseline(
        n_steps=2, n_outcomes=3, base_steps=2, base_outcomes=2))
    assert "comprehension_recheck" in ctx
    assert "SCOPE CHANGE" in ctx["comprehension_recheck"]


def test_item1_no_recheck_on_minor_growth():
    # +1 step, no new outcome -> below the threshold -> no suggestion
    ctx = recipe_context(_recipe_with_baseline(
        n_steps=3, n_outcomes=2, base_steps=2, base_outcomes=2))
    assert "comprehension_recheck" not in ctx


def test_item1_no_baseline_means_no_scope_trigger():
    # a recipe that never snapshotted a baseline (legacy) -> no false fire
    ctx = recipe_context(_recipe(attempt=0))  # baseline is None
    assert "comprehension_recheck" not in ctx


def test_item1_baseline_set_leaving_comprehending():
    # the FSM snapshots the baseline as the recipe leaves COMPREHENDING.
    # P6 (2026-06-10): leaving now ALSO requires user signoff (or a
    # recorded skip) — the old test locked in the user-bypass; and the
    # baseline gained the load-bearing-drift counters.
    from edp_claude.fsm.recipe_fsm import recipe_next_action
    r = Recipe.model_validate(dict(
        recipe_id="r-i1c", user_goal_verbatim="g", domain="generic",
        state="comprehending",
        comprehension={"branches": [], "curiosity_cleared": True,
                       "user_signoff": True, "signoff_quote": "proceed",
                       "expected_outcomes": [
                           {"id": "o1", "description": "d",
                            "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "work", "description": "d",
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner", "attempt": 0}],
        context={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    recipe_next_action(r)  # advances COMPREHENDING -> PLANNING, snapshots
    assert r.comprehension.baseline == {
        "n_steps": 1, "n_outcomes": 1,
        "n_load_bearing": 0, "n_superseded": 0,
    }


def test_item1_baseline_gate_omits_when_unset():
    # emission gate: an un-snapshotted comprehension serializes WITHOUT the
    # baseline key (byte-shape parity for a pre-restart reader).
    r = _recipe(attempt=0)
    dumped = r.model_dump()
    assert "baseline" not in dumped["comprehension"]
