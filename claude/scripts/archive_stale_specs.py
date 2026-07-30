"""One-off maintenance: archive the domain specializations carried over
from a previous project (SPECIALIZATION-LAYERED-RULESETS.md follow-up, task
(a), 2026-06-01).

Why: a 2026-05-30 reset wiped the neuron registry but left these domain
spec FILES behind. Four have no neuron row at all (invisible to
neuron_search); one (`ai-ml-interview-prep-gap-curator`) is `trained`, not
`stable`. NONE has a `base_session_id`, so NONE is branchable — they are
inert, stale carryover, not usable specialists.

What this does (REVERSIBLE — moves, never deletes):
  - moves each stale `<spec>.json` + its `<spec>/` snapshot dir into
    `.specs/.archived/`,
  - marks any matching neuron row `archived` (trained -> archived is legal).

It deliberately KEEPS the shipped comprehension seeds (actor-*, feasibility,
role-clarity, concern-validator, new-tech-detector, estimation, goal-setter),
the orchestrator, and the universal layer.

Run:  ./.venv/Scripts/python.exe scripts/archive_stale_specs.py [--dry-run]
"""

import shutil
import sys
from pathlib import Path

from edp_claude.store.neuron_store import NeuronStore

# stale domain carryover (explicit — no auto-classification of user data)
STALE_SPECS = [
    "spec-ai-ml-interview-prep-gap-curator",
    "spec-ai-ml-interview-prep-gap-curator-0b5fbe",
    "spec-graphrag-citable-retrieval-over-falkordb-ollama",
    "spec-java-spring-boot-rest-api",
    "spec-local-llm-fine-tuning-for-codebase-framework-und",
    "spec-react-vite-typescript-frontend",
]
# the only carryover that still has a (non-stable) neuron row
STALE_NEURONS = ["ai-ml-interview-prep-gap-curator"]


def main(dry_run: bool) -> None:
    root = Path(__file__).resolve().parents[1]      # the claude/ dir
    specs_dir = root / ".specs"
    archived = specs_dir / ".archived"
    tag = "[dry-run] would" if dry_run else "archived"

    if not dry_run:
        archived.mkdir(parents=True, exist_ok=True)

    moved, missing = [], []
    for sid in STALE_SPECS:
        targets = [specs_dir / f"{sid}.json", specs_dir / sid]
        found = [t for t in targets if t.exists()]
        if not found:
            missing.append(sid)
            continue
        for t in found:
            dest = archived / t.name
            if not dry_run:
                shutil.move(str(t), str(dest))
        moved.append(sid)
        print(f"  {tag}: move {sid} (json + snapshot dir) -> .specs/.archived/")

    neurons = NeuronStore(root / ".neurons" / "registry.db")
    for nid in STALE_NEURONS:
        rec = neurons.get(nid)
        if rec is None:
            print(f"  (no neuron row for {nid} — nothing to archive)")
            continue
        if rec.status == "archived":
            print(f"  ({nid} already archived)")
            continue
        if not dry_run:
            neurons.set_status(nid, "archived")
        print(f"  {tag}: neuron {nid} status {rec.status!r} -> 'archived'")

    print(f"\nSummary: {len(moved)} spec(s) archived, "
          f"{len(missing)} already absent {missing or ''}.")
    if dry_run:
        print("Dry run — nothing changed. Re-run without --dry-run to apply.")
    else:
        print("Done. Reverse by moving files back from .specs/.archived/ and "
              "neuron_set_status(...) if needed.")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
