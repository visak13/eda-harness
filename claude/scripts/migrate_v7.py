"""DESIGN-v7 Phase 0 — the one-shot break-and-migrate.

Run ONCE, LAST, after all v7 schema changes are final:

    uv run python scripts/migrate_v7.py            # dry-run (default)
    uv run python scripts/migrate_v7.py --apply    # do it

What it does (idempotent — a second --apply run is a no-op):
  1. ARCHIVE every recipe under .recipes/ and its plans under .plans/ to
     .archive/v6/, EXCEPT the one in-flight recipe that must stay runnable:
     the local-gemma-agent recipe (KEEP_RECIPE below). Old recipes are
     archives, not live state (user ruling, 2026-07-12).
  2. DELETE the .backup/ pre-restart snapshot trees (four full copies of the
     repo docs/plans that pollute every grep) and the _s27_item1field_backup
     leftover in src/.
  3. MIGRATE the kept recipe + its plans forward: load with the CURRENT v7
     schemas (new fields default, hydration intact) and re-save atomically.
     The migration's own acceptance check: get_recipe_digest assembles and
     next_action returns an instruction on the migrated recipe.

Windows-safe: shutil.move within one volume, no POSIX.
"""

import argparse
import shutil
import sys
from pathlib import Path

CLAUDE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLAUDE / "src"))

KEEP_RECIPE = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
ARCHIVE = CLAUDE / ".archive" / "v6"


def _move(src: Path, dst_root: Path, apply: bool) -> None:
    dst = dst_root / src.name
    print(f"  {'MOVE' if apply else 'would move'} {src.relative_to(CLAUDE)} "
          f"-> {dst.relative_to(CLAUDE)}")
    if apply:
        dst_root.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def _delete(path: Path, apply: bool) -> None:
    if not path.exists():
        return
    print(f"  {'DELETE' if apply else 'would delete'} "
          f"{path.relative_to(CLAUDE)}")
    if apply:
        shutil.rmtree(path, ignore_errors=True)


def archive_dead_state(apply: bool) -> None:
    recipes = CLAUDE / ".recipes"
    plans = CLAUDE / ".plans"
    print("[1] archive dead recipes/plans")
    if recipes.is_dir():
        for d in sorted(recipes.iterdir()):
            if d.is_dir() and d.name != KEEP_RECIPE:
                _move(d, ARCHIVE / ".recipes", apply)
    if plans.is_dir():
        for f in sorted(plans.iterdir()):
            # keep the gemma recipe's plans: <recipe_id>-s<N>.json + dirs
            if f.name.startswith(KEEP_RECIPE):
                continue
            _move(f, ARCHIVE / ".plans", apply)
    print("[2] delete backup trees")
    _delete(CLAUDE / ".backup", apply)
    for leftover in (CLAUDE / "src" / "edp_claude").glob("_s27_*backup*"):
        _delete(leftover, apply)


def migrate_kept_recipe(apply: bool) -> bool:
    print(f"[3] forward-migrate {KEEP_RECIPE}")
    from edp_claude.store.plan_store import PlanStore
    from edp_claude.store.recipe_store import RecipeStore

    rstore = RecipeStore(CLAUDE / ".recipes")
    pstore = PlanStore(CLAUDE / ".plans")
    if not rstore.exists(KEEP_RECIPE):
        print("  kept recipe not found (already archived elsewhere?) — skip")
        return True
    r = rstore.load(KEEP_RECIPE)   # v7 schemas: new fields default on load
    print(f"  loaded: state={r.state} steps={len(r.steps)} "
          f"decisions={len(r.context.decisions)} v{r.version}")
    if apply:
        rstore.save(r)             # re-serialize under the v7 shape
    migrated_plans = 0
    for p in pstore.list_for_recipe(KEEP_RECIPE):
        if apply:
            pstore.save(p)
        migrated_plans += 1
    print(f"  plans {'re-saved' if apply else 'loadable'}: {migrated_plans}")
    # acceptance: the digest assembles + the FSM answers on the migrated shape
    import asyncio

    from edp_claude.server import make_context
    from edp_claude.tools._tools import (GetRecipeDigest,
                                         _GetRecipeDigestIn)

    try:
        res = asyncio.run(GetRecipeDigest(make_context(CLAUDE))._run(
            _GetRecipeDigestIn(recipe_id=KEEP_RECIPE)))
        ok = bool(getattr(res, "ok", False))
        print(f"  acceptance get_recipe_digest: {'OK' if ok else res}")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"  acceptance FAILED: {e}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="perform the migration (default: dry-run)")
    args = ap.parse_args()
    archive_dead_state(args.apply)
    ok = migrate_kept_recipe(args.apply)
    print(f"\n{'DONE' if args.apply else 'DRY-RUN COMPLETE'} — "
          f"acceptance {'passed' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
