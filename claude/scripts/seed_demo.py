"""Isolated worker-with-brief HITL helper.

`seed`  — writes ONE schema-valid demo recipe + plan with a single
          trivial action (create a file) under the agent-home root, so a
          worker spawned for that action has a real brief to execute.
`clean` — removes ONLY the demo-namespaced paths (its recipe dir, its
          plan file+dir, its scratch artifact). Never touches any other
          recipe/plan — every delete target's name must contain the
          demo prefix.

Usage (from the claude repo):
    uv run python scripts/seed_demo.py seed
    uv run python scripts/seed_demo.py clean
"""

import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# import the package's own schemas/stores so the seeded artifacts are
# exactly what the running MCP server will read.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from edp_claude.schemas import (  # noqa: E402
    Acceptance,
    Action,
    Comprehension,
    Plan,
    Recipe,
    RecipeStep,
)
from edp_claude.store import PlanStore, RecipeStore  # noqa: E402

PREFIX = "demo-worker-smoke"
RECIPE_ID = PREFIX
PLAN_ID = f"{PREFIX}-plan"
ACTION_ID = "a1"
SCRATCH = ".demo-scratch"  # artifact dir, namespaced for safe cleanup
HANDLE = f"{PLAN_ID}:{ACTION_ID}"


def _root() -> Path:
    # agent-home = the claude repo (this file is scripts/seed_demo.py)
    return Path(__file__).resolve().parents[1]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed(root: Path | None = None) -> None:
    root = root or _root()
    recipes = RecipeStore(root / ".recipes")
    plans = PlanStore(root / ".plans")

    recipe = Recipe(
        recipe_id=RECIPE_ID,
        user_goal_verbatim="DEMO: prove a worker executes a brief",
        user_goal_distilled="demo worker smoke",
        domain="software_engineering",
        state="executing",
        comprehension=Comprehension(
            branches=[], expected_outcomes=[]
        ),
        steps=[
            RecipeStep(
                step_id="s1",
                kind="demo",
                description="single demo action",
                status="in_progress",
                depends_on=[],
                execution="spawn_planner",
                plan_ref=PLAN_ID,
            )
        ],
        created_at=_now(),
        updated_at=_now(),
    )
    recipes.save(recipe)

    plan = Plan(
        plan_id=PLAN_ID,
        recipe_id=RECIPE_ID,
        recipe_step_id="s1",
        domain="software_engineering",
        shape="linear-build",
        goal="DEMO: create one file",
        state="dispatching",
        actions=[
            Action(
                action_id=ACTION_ID,
                description=(
                    f"Create the file '{SCRATCH}/hello.txt' (relative to "
                    f"your cwd, the agent-home repo) containing exactly: "
                    f"edp ok. Then record_action_status done with the "
                    f"file path as evidence."
                ),
                status="pending",
                depends_on=[],
                executor_mode="subagent",
                acceptance=Acceptance(
                    kind="file_exists",
                    expected=f"{SCRATCH}/hello.txt contains 'edp ok'",
                ),
            )
        ],
    )
    plans.save(plan)

    print("seeded demo recipe + plan.")
    print(f"  recipe: {root / '.recipes' / RECIPE_ID}")
    print(f"  plan:   {root / '.plans' / (PLAN_ID + '.json')}")
    print()
    print("spawn a worker for the demo action (monitor mode):")
    print(
        '  curl.exe -X POST http://127.0.0.1:9200/v1/spawn '
        '-H "Content-Type: application/json" '
        f'-d \'{{\\"role\\":\\"worker\\",\\"handle\\":\\"{HANDLE}\\",'
        '\\"mode\\":\\"monitor\\"}\''
    )
    print()
    print("when done, clean up:")
    print("  uv run python scripts/seed_demo.py clean")


def clean(root: Path | None = None) -> None:
    root = root or _root()
    targets = [
        root / ".recipes" / RECIPE_ID,
        root / ".plans" / f"{PLAN_ID}.json",
        root / ".plans" / PLAN_ID,
        root / SCRATCH,
    ]
    removed = []
    for t in targets:
        # safety: every target's name must carry the demo prefix
        if PREFIX not in t.name and t.name != SCRATCH:
            continue
        if t.is_dir():
            shutil.rmtree(t, ignore_errors=True)
            removed.append(str(t))
        elif t.exists():
            t.unlink()
            removed.append(str(t))
    print(f"cleaned {len(removed)} demo path(s):")
    for r in removed:
        print(f"  {r}")
    if not removed:
        print("  (nothing to remove)")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else ""
    if cmd == "seed":
        seed()
    elif cmd == "clean":
        clean()
    else:
        print("usage: seed_demo.py [seed|clean]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
