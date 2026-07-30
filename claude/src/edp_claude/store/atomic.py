"""Atomic write + snapshot (LLD §1 store/). tmpfile + os.replace."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)  # atomic on same filesystem
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_snapshot(snap_dir: Path, version: int, payload: dict) -> Path:
    snap_dir.mkdir(parents=True, exist_ok=True)
    p = snap_dir / f"v{version}.json"
    write_atomic(p, json.dumps(payload, indent=2, default=str))
    return p


# Coarse-history cadence for the save-time snapshot gate (DESIGN-v6 s18/C1).
SNAPSHOT_EVERY = 25


def should_write_snapshot(
    prev_state: str | None,
    new_state: str,
    version: int,
    every: int = SNAPSHOT_EVERY,
) -> bool:
    """C1 (DESIGN-v6 s18): stop snapshot-on-EVERY-save. A versioned snapshot is
    written only on a STATE TRANSITION — the meaningful rollback point — or on
    every `every`-th version as coarse history. `prev_state` is None on the
    first save of a recipe/plan in a process, so a fresh object always
    snapshots. The live JSON is rewritten by `save` on EVERY save (write_atomic
    above), so the current state is never lost; only the redundant per-tick
    snapshot WRITE is skipped."""
    if prev_state != new_state:
        return True
    return version % every == 0


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    """Parse a jsonl trail; skips blank/corrupt lines (a torn append must
    not poison the whole read)."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def filter_entries(
    entries: list[dict],
    kinds: list[str] | None = None,
    since: str | None = None,
    action_id: str | None = None,
) -> list[dict]:
    """Shared worklog/events filter (read-efficiency P1). Filters are
    applied BEFORE any tail-N cut so `tail=20, kinds=[...]` means "the
    last 20 of that kind", not "matching entries among the last 20".

    - kinds: keep entries whose `kind` is in the list.
    - since: ISO timestamp; keep entries with `ts` strictly after it.
    - action_id: keep entries that carry that `action_id` field, or whose
      `from`/`handle` is the worker handle ending in `:<action_id>`.
    """
    out = entries
    if kinds:
        kindset = set(kinds)
        out = [e for e in out if e.get("kind") in kindset]
    if since:
        out = [e for e in out if str(e.get("ts", "")) > since]
    if action_id:
        suffix = f":{action_id}"
        out = [
            e for e in out
            if e.get("action_id") == action_id
            or str(e.get("from", "")).endswith(suffix)
            or str(e.get("handle", "")).endswith(suffix)
        ]
    return out
