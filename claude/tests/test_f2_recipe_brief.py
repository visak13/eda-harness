"""F2 (2026-08-17) — the compiled recipe brief.

Three contracts:
1. IDEMPOTENCY — the renderer is a pure function: same state, byte-identical
   markdown.
2. SCHEMA COVERAGE — every top-level Recipe field is either rendered or
   consciously excluded; a NEW field fails here until accounted for.
3. CURRENCY — RecipeStore.save() regenerates brief.md on every mutation, and
   read_object(detail='brief') serves the live-rendered form.
"""

from datetime import datetime, timezone

from edp_claude.objects import read_object
from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.store.recipe_brief import (
    BRIEF_FILENAME,
    EXCLUDED_FIELDS,
    RENDERED_FIELDS,
    render_recipe_brief,
)


def _now():
    return datetime.now(timezone.utc)


def _recipe(rid="recipe-f2"):
    return Recipe(
        recipe_id=rid,
        user_goal_verbatim="Build me X\nwith constraint Y",
        user_goal_distilled="build X",
        domain="software_engineering", state="executing",
        comprehension={
            "branches": [],
            "expected_outcomes": [
                {"id": "o1", "description": "X exists and passes tests",
                 "verification": "run the suite",
                 "met": True, "met_evidence": "12 tests green"},
                {"id": "o2", "description": "Y is honored",
                 "verification": "inspect Y", "met": False},
            ],
        },
        steps=[{"step_id": "s1", "kind": "build", "description": "build X",
                "status": "in_progress", "depends_on": [],
                "execution": "spawn_planner",
                "concerns": ["security"],
                "acceptance_sketch": ["X passes its suite"]}],
        context={
            "decisions": [
                {"id": "d1", "text": "use postgres, not sqlite",
                 "rationale": "ops standard", "by": "neuron",
                 "at": _now().isoformat(), "load_bearing": True},
                {"id": "d2", "text": "logging via structlog",
                 "rationale": "consistency", "by": "neuron",
                 "at": _now().isoformat(), "load_bearing": False},
            ],
            "assumptions": [], "rejected_options": [
                {"id": "x1", "text": "no ORM code generation",
                 "reason": "owner ban"}],
            "open_questions": [],
        },
        budget={"wall_clock_hours": 8},
        created_at=_now(), updated_at=_now(),
    )


def test_renderer_is_deterministic_and_carries_the_load():
    r = _recipe()
    a, b = render_recipe_brief(r), render_recipe_brief(r)
    assert a == b                                # idempotent by construction
    # goal VERBATIM, multi-line preserved as quote
    assert "Build me X" in a and "with constraint Y" in a
    # outcomes with met flags, load-bearing decision text, ban, step concerns
    assert "- [x] **o1**" in a and "- [ ] **o2**" in a
    assert "use postgres, not sqlite" in a
    assert "no ORM code generation" in a
    assert "concerns: security" in a
    assert "acceptance sketch: X passes its suite" in a


def test_every_schema_field_is_rendered_or_consciously_excluded():
    fields = set(Recipe.model_fields)
    unaccounted = fields - RENDERED_FIELDS - EXCLUDED_FIELDS
    assert not unaccounted, (
        f"Recipe field(s) {sorted(unaccounted)} are neither rendered in the "
        "brief nor listed in EXCLUDED_FIELDS — account for them in "
        "store/recipe_brief.py (render, or exclude with a why).")
    ghost = (RENDERED_FIELDS | EXCLUDED_FIELDS) - fields
    assert not ghost, (
        f"{sorted(ghost)} are listed in recipe_brief.py but no longer exist "
        "on the Recipe schema — prune them.")


def test_save_regenerates_brief_and_read_object_serves_it(tmp_path):
    ctx = make_context(tmp_path)
    r = _recipe()
    ctx.recipes.save(r)
    brief_path = ctx.recipes.root / r.recipe_id / BRIEF_FILENAME
    assert brief_path.exists()
    first = brief_path.read_text(encoding="utf-8")
    assert "Build me X" in first

    # a mutation regenerates the brief — it can never lag the record
    r.context.open_questions.append({"question": "which region?"})
    ctx.recipes.save(r)
    second = brief_path.read_text(encoding="utf-8")
    assert "which region?" in second and second != first


async def test_read_object_detail_brief(tmp_path):
    ctx = make_context(tmp_path)
    ctx.recipes.save(_recipe())
    out = await read_object(ctx, "recipe", detail="brief",
                            recipe_id="recipe-f2")
    assert out["_detail"] == "brief"
    assert "Build me X" in out["brief_md"]
