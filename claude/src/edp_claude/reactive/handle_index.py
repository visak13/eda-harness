"""Handle -> subscription-id index at the `.reactive` root (DESIGN-v6 §W2 leg 2).

Today `observe()` persists each subscription as `.reactive/<sid>.spec`
(+ `.bindings.json` / `.effect.json`), keyed ONLY by the opaque
`subscription_id`. There is NO association from the OWNING handle (a
plan_id / recipe_id / worker address) back to its subscription(s) — the
only handle-shaped field on a subscription is the free-form `owner` baked
into the driver command, and it is never persisted for lookup. So a
compacted shell that lost its `Monitor` wiring cannot be HANDED its own
subscriptions back: nothing on disk says "these sids belong to you".

This module is that missing association: a single JSON index at the
`.reactive` ROOT mapping `handle -> [sid, ...]`, WRITTEN by the observe
layer (`_tools.py`, which owns `.reactive`) at subscribe time, and READ by
the W2 rewire hand-back (`_rewire_block`) AND servable by the reactive
driver (`serve_handle_specs`) so a per-handle spec lookup exists.

DESIGN NOTES:
  * STDLIB-ONLY + atomic write (write-temp -> os.replace) so the MCP server
    and a standalone driver process agree on one on-disk shape regardless
    of cwd. Mirrors how `RuleRegistry` and the rest of the framework persist.
  * IDEMPOTENT + dedup: re-registering the same (handle, sid) is a no-op, so
    an observe re-arm (reused=True) can safely re-index without churn.
  * SELF-HEALING: `specs_for_handle` skips any indexed sid whose `.spec`
    artifact was swept by the observe GC — the index never resurrects a dead
    subscription, and a swept sid simply drops out of the hand-back.
  * NO clock / rng (principle 6): the index is pure derived association.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# F45#8 — the index RMW is serialized across MCP-server processes with the
# same advisory file lock the object stores use: every spawned shell runs
# its own server, so two concurrent observe() calls could both load the
# same index and the last atomic replace silently dropped the other
# shell's mapping (its subscription became un-handbackable after compact).
# StoreLockTimeout subclasses TimeoutError (an OSError), so the observe
# layer's existing except-OSError degradation path covers a held lock.
from ..store.ipc_lock import object_lock

# The index file lives directly under the `.reactive` root, a sibling of the
# `sub-*.spec` artifacts + the `registry/` and `effect_audit/` subdirs.
INDEX_NAME = "handle_index.json"


def index_path(reactive_root: Path) -> Path:
    """Absolute path of the handle->sid index under a `.reactive` root."""
    return Path(reactive_root) / INDEX_NAME


def _load(reactive_root: Path) -> dict[str, list[str]]:
    """Best-effort read of the index: `{handle: [sid, ...]}`. A missing or
    corrupt file reads as an empty index (never raises — a lost index just
    means a shell re-observes rather than being handed its wiring back)."""
    path = index_path(reactive_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for handle, sids in data.items():
        if isinstance(handle, str) and isinstance(sids, list):
            out[handle] = [s for s in sids if isinstance(s, str)]
    return out


def _atomic_write(reactive_root: Path, data: dict[str, list[str]]) -> None:
    """Atomic write-temp -> os.replace (atomic on Windows + POSIX), matching
    RuleRegistry._write so concurrent readers never see a half-written file."""
    root = Path(reactive_root)
    root.mkdir(parents=True, exist_ok=True)
    path = index_path(root)
    # F45#8 — pid-unique temp: a shared `.tmp` name let two processes
    # clobber each other's half-written temp before their os.replace.
    tmp = path.with_suffix(f".json.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def register_subscription(reactive_root: Path, handle: str, sid: str) -> None:
    """Associate subscription `sid` with the OWNING `handle` in the index.

    Called by the observe layer at subscribe time. A falsy `handle` or `sid`
    is a no-op (an anonymous subscription carries no owner to hand back to).
    Read-modify-write with an atomic replace; dedup preserves insertion order
    so the hand-back lists a handle's subscriptions in the order they armed.
    Best-effort: an OSError propagates to the caller, which logs-and-continues
    (indexing failure must never fail the observe() call itself)."""
    if not handle or not sid:
        return
    with object_lock(Path(reactive_root)):
        data = _load(reactive_root)
        sids = data.setdefault(handle, [])
        if sid not in sids:
            sids.append(sid)
            _atomic_write(reactive_root, data)


def unregister_subscription(reactive_root: Path, handle: str,
                            sid: str) -> bool:
    """Remove the (handle, sid) association; True when it existed. The
    unobserve verb's index half (2026-07-20 — until then subscriptions
    could only be re-specced or aged out by the TTL sweep, never
    surgically deleted by their owner). Same atomic write discipline as
    register_subscription."""
    if not handle or not sid:
        return False
    with object_lock(Path(reactive_root)):
        data = _load(reactive_root)
        sids = data.get(handle, [])
        if sid not in sids:
            return False
        sids.remove(sid)
        if not sids:
            data.pop(handle, None)
        _atomic_write(reactive_root, data)
    return True


def sids_for_handle(reactive_root: Path, handle: str) -> list[str]:
    """The subscription ids registered to `handle` (empty list if none)."""
    if not handle:
        return []
    return list(_load(reactive_root).get(handle, []))


def all_indexed_sids(reactive_root: Path) -> set[str]:
    """Every sid ANY handle owns (2026-08-17) — the observe GC's do-not-sweep
    set: an indexed subscription belongs to a shell that may be parked or
    idle past the TTL, and sweeping it emptied the resume rewire hand-back
    (the s4 planner incident)."""
    out: set[str] = set()
    for sids in _load(reactive_root).values():
        out.update(sids)
    return out


def _read_subscription(reactive_root: Path, sid: str) -> dict[str, Any] | None:
    """Read one persisted subscription's artifacts back into a dict
    `{sid, spec, bindings, effect}`. Returns None when the `.spec` artifact is
    absent (swept by the observe GC, or never written) so a stale index entry
    self-heals out of the hand-back rather than resurrecting a dead sub."""
    root = Path(reactive_root)
    spec_path = root / f"{sid}.spec"
    if not spec_path.exists():
        return None
    try:
        spec = spec_path.read_text(encoding="utf-8")
    except OSError:
        return None
    bindings: dict[str, Any] = {}
    b_path = root / f"{sid}.bindings.json"
    if b_path.exists():
        try:
            loaded = json.loads(b_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                bindings = loaded
        except (OSError, json.JSONDecodeError):
            bindings = {}
    effect: dict[str, Any] | None = None
    e_path = root / f"{sid}.effect.json"
    if e_path.exists():
        try:
            loaded = json.loads(e_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                effect = loaded
        except (OSError, json.JSONDecodeError):
            effect = None
    return {"sid": sid, "spec": spec, "bindings": bindings, "effect": effect}


def specs_for_handle(reactive_root: Path, handle: str) -> list[dict[str, Any]]:
    """Every persisted observe subscription registered to `handle`, each as
    `{sid, spec, bindings, effect}`. Deterministic (index order), read-only,
    stdlib. Indexed sids whose `.spec` artifact is gone are skipped, so a
    caller only ever sees LIVE, re-issuable subscriptions."""
    out: list[dict[str, Any]] = []
    for sid in sids_for_handle(reactive_root, handle):
        sub = _read_subscription(reactive_root, sid)
        if sub is not None:
            out.append(sub)
    return out
