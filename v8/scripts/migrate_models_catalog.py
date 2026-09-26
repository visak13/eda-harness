"""One-time legacy models.json -> editable data-dir catalog migration.

Usage: python scripts/migrate_models_catalog.py SOURCE DEST [--apply]
Without --apply, validate and print the before/after resolution summary only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edp8.model_catalog import migrate, validate, write


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw = json.loads(args.source.read_text(encoding="utf-8"))
    migrated = migrate(raw)
    errors = validate(migrated.get("models") or {}, migrated.get("role_models") or {})
    if errors:
        parser.error("; ".join(errors))
    before = {role: ids[0] for role, ids in (raw.get("role_models") or {}).items()}
    after = {role: ids[0] for role, ids in migrated["role_models"].items()}
    assert before == after
    print(json.dumps({"defaults_before": before, "defaults_after": after,
                      "catalogs_equal": raw.get("role_models") == migrated.get("role_models"),
                      "seat_bindings_equal": raw.get("roles") == migrated.get("roles"),
                      "output": str(args.dest), "applied": args.apply}, indent=2))
    if args.apply:
        if args.dest.exists():
            parser.error(f"destination exists: {args.dest}; refusing to overwrite an edited catalog")
        write(migrated, args.dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
