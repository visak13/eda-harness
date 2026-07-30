"""seed_demo helper — seeds schema-valid artifacts; clean is namespaced
and never touches a non-demo recipe/plan."""

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "seed_demo",
    Path(__file__).resolve().parents[1] / "scripts" / "seed_demo.py",
)
seed_demo = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(seed_demo)

from edp_claude.schemas import Plan, Recipe  # noqa: E402


def test_seed_writes_schema_valid_artifacts(tmp_path):
    seed_demo.seed(tmp_path)
    rj = tmp_path / ".recipes" / seed_demo.RECIPE_ID / "recipe.json"
    pj = tmp_path / ".plans" / f"{seed_demo.PLAN_ID}.json"
    assert rj.exists() and pj.exists()
    # round-trips through the real models (would raise on invalid)
    Recipe.model_validate(json.loads(rj.read_text(encoding="utf-8")))
    plan = Plan.model_validate(json.loads(pj.read_text(encoding="utf-8")))
    assert plan.actions[0].action_id == seed_demo.ACTION_ID


def test_clean_is_namespaced_and_safe(tmp_path):
    seed_demo.seed(tmp_path)
    # a real, non-demo recipe sitting alongside MUST survive clean
    real = tmp_path / ".recipes" / "real-user-recipe"
    real.mkdir(parents=True)
    (real / "recipe.json").write_text("{}", encoding="utf-8")
    (tmp_path / seed_demo.SCRATCH).mkdir(exist_ok=True)

    seed_demo.clean(tmp_path)

    assert not (tmp_path / ".recipes" / seed_demo.RECIPE_ID).exists()
    assert not (tmp_path / ".plans" / f"{seed_demo.PLAN_ID}.json").exists()
    assert not (tmp_path / seed_demo.SCRATCH).exists()
    assert real.exists()  # untouched — clean is demo-namespaced only
