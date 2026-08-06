"""Recipe load/save + snapshot + events trail (LLD §1).

Store maintenance (DESIGN-v6 W1 items 3 & 4) lives here too:
- **Snapshot retention GC** — `save` snapshots EVERY version, so a long recipe
  accumulates hundreds of ~100KB snapshots. Retention policy (as DATA below):
  keep the most-recent N full snapshots + every Kth older version. GC runs on
  save ONLY when `EDP_SNAPSHOT_GC` is set (default OFF → byte-for-byte current
  behavior); `compact_recipe_store()` applies the same retention on demand.
- **Event rollups** — when `events.jsonl` reaches a threshold, archive the head
  into a numbered segment + a CODE-generated (no-LLM) digest, leaving the recent
  tail on the hot read path. `events.jsonl`'s on-disk FORMAT is unchanged (same
  jsonl records, just bounded length) — `read_object`/`get_recipe_digest` read
  it exactly as before.
"""

import json
import os
from collections import Counter
from pathlib import Path

from ..schemas import Recipe
from .attribution import actor
from .atomic import (
    append_jsonl,
    read_jsonl,
    should_write_snapshot,
    write_atomic,
    write_snapshot,
)
from .tiering import dehydrate_recipe_payload, hydrate_recipe_payload
from .vault_mirror import mirror_recipe

# ── Store-maintenance policy as data (DESIGN-v6 W1 items 3 & 4) ──────────────
# Same tables-as-data house style as the FSM transition tables.
SNAPSHOT_KEEP_RECENT = 10   # always keep the last N full snapshots …
SNAPSHOT_KEEP_EVERY = 25    # … plus every Kth older version (coarse history).
EVENTS_ROLLUP_THRESHOLD = 1000  # roll up events.jsonl once it hits this many.
EVENTS_TAIL_KEEP = 100          # records left on the hot path after a rollup.
# C3 (s18): the smallest a countable non-blank jsonl record can be ('{}' / '1'
# + newline ≥ 2 bytes). A file below threshold*this many bytes therefore CANNOT
# hold `threshold` records, so the full-file line scan can be skipped entirely.
EVENTS_MIN_RECORD_BYTES = 2


def _snapshot_gc_enabled() -> bool:
    """Save-time GC is opt-in (default OFF = unchanged behavior). Read at call
    time (not import) so a spawn/env flip takes effect without reimport."""
    return os.environ.get("EDP_SNAPSHOT_GC", "").strip().lower() in {
        "1", "true", "yes", "on"}


def _default_recipes_root() -> Path:
    """Resolve the recipes root the same way the server does — EDP_AGENT_HOME
    (or the repo root, three parents up from this file) / ".recipes"."""
    env = os.environ.get("EDP_AGENT_HOME")
    root = Path(env) if env else Path(__file__).resolve().parents[3]
    return root / ".recipes"


# ── snapshot retention GC ────────────────────────────────────────────────────

def _snapshot_versions(snap_dir: Path) -> list[int]:
    """Sorted version ints present as v<N>.json in the snapshots dir."""
    if not snap_dir.exists():
        return []
    out: list[int] = []
    for p in snap_dir.glob("v*.json"):
        try:
            out.append(int(p.stem[1:]))   # 'v123' -> 123
        except (ValueError, IndexError):
            continue
    return sorted(out)


def _snapshots_to_keep(versions: list[int]) -> set[int]:
    """Retention policy as pure data: the most-recent SNAPSHOT_KEEP_RECENT
    versions, plus every SNAPSHOT_KEEP_EVERY-th older version."""
    if not versions:
        return set()
    recent = set(versions[-SNAPSHOT_KEEP_RECENT:])
    every = {v for v in versions if v % SNAPSHOT_KEEP_EVERY == 0}
    return recent | every


def gc_snapshots(snap_dir: Path) -> list[int]:
    """Apply snapshot retention; delete the pruned versions. Returns the sorted
    list of deleted versions (empty when nothing is prunable — a no-op below the
    keep floor)."""
    versions = _snapshot_versions(snap_dir)
    keep = _snapshots_to_keep(versions)
    deleted: list[int] = []
    for v in versions:
        if v not in keep:
            try:
                (snap_dir / f"v{v}.json").unlink()
                deleted.append(v)
            except OSError:
                continue
    return deleted


# ── event rollup (code-generated digest, no LLM) ─────────────────────────────

def _line_count(path: Path) -> int:
    """Cheap threshold gate — count lines without JSON-parsing every record, so
    the common (under-threshold) save path never reads full history."""
    if not path.exists():
        return 0
    n = 0
    with open(path, "r", encoding="utf-8") as f:
        for _ in f:
            n += 1
    return n


def _next_segment_index(rdir: Path, stem: str = "events") -> int:
    """Next <stem>.NNNN.jsonl index (1-based, zero-padded to 4 at write time)."""
    existing: list[int] = []
    for p in rdir.glob(f"{stem}.[0-9][0-9][0-9][0-9].jsonl"):
        parts = p.name.split(".")   # <stem> . NNNN . jsonl
        if len(parts) == 3 and parts[0] == stem and parts[2] == "jsonl":
            try:
                existing.append(int(parts[1]))
            except ValueError:
                continue
    return (max(existing) + 1) if existing else 1


def _build_segment_digest(records: list[dict], seg_index: int,
                          stem: str = "events") -> str:
    """CODE-generated (deterministic, NO-LLM) markdown digest of an archived
    events segment: counts by kind, ts range, learning/spec tallies."""
    n = len(records)
    kinds = Counter(str(r.get("kind", "?")) for r in records)
    ts = [str(r.get("ts", "")) for r in records if r.get("ts")]
    ts_first = ts[0] if ts else "?"
    ts_last = ts[-1] if ts else "?"
    lines = [
        f"# {stem} segment {seg_index:04d} digest",
        "",
        f"- records: {n}",
        f"- ts range: {ts_first} … {ts_last}",
        f"- learning events: {kinds.get('learning', 0)}",
        f"- spec_learning_proposed events: "
        f"{kinds.get('spec_learning_proposed', 0)}",
        "",
        "## counts by kind",
        "",
    ]
    # deterministic order: most-frequent first, then alphabetical for ties.
    for kind, c in sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {kind}: {c}")
    lines.append("")
    return "\n".join(lines)


def _dump_records(records: list[dict]) -> str:
    """jsonl encoding matching append_jsonl (default=str, one record/line)."""
    return "".join(json.dumps(r, default=str) + "\n" for r in records)


def rollup_events(rdir: Path,
                  threshold: int | None = None,
                  tail_keep: int | None = None,
                  filename: str = "events.jsonl") -> dict | None:
    """If `filename` holds ≥ threshold records, archive the HEAD into the next
    numbered segment (<stem>.NNNN.jsonl) + a code-generated digest
    (<stem>.NNNN.digest.md), and atomically rewrite the hot file to the recent
    TAIL. Returns a summary dict, or None if under threshold.

    Nothing is lost — the head is preserved full-fidelity in the segment, just
    off the hot read path. The hot file's format is unchanged, so
    read_object/get_recipe_digest read it exactly as before.

    v7 WS3 (§2.1): `filename` generalizes the SAME mechanism to plan
    worklogs (worklog.jsonl — 558KB live hot files today), which never
    rolled. ARCHIVE-tier files are never re-read raw; the digest is the read."""
    # Resolve policy at CALL time (module globals), not def time — a test or
    # operator override of the module constants takes effect immediately.
    if threshold is None:
        threshold = EVENTS_ROLLUP_THRESHOLD
    if tail_keep is None:
        tail_keep = EVENTS_TAIL_KEEP
    stem = filename.rsplit(".", 1)[0]
    events = rdir / filename
    # C3 (s18): cheap O(1) stat gate BEFORE the full-file _line_count scan. A
    # file under threshold*EVENTS_MIN_RECORD_BYTES bytes cannot hold `threshold`
    # records, so a rollup is impossible — skip the scan (result is provably the
    # same None). Behavior above the floor is unchanged.
    try:
        size = events.stat().st_size
    except OSError:            # missing/unreadable → nothing to roll up
        return None
    if size < threshold * EVENTS_MIN_RECORD_BYTES:
        return None
    if _line_count(events) < threshold:
        return None
    records = read_jsonl(events)
    if len(records) < threshold:      # blank/corrupt lines inflated the count
        return None
    head = records[:-tail_keep] if tail_keep else records
    tail = records[-tail_keep:] if tail_keep else []
    seg_index = _next_segment_index(rdir, stem)
    seg_path = rdir / f"{stem}.{seg_index:04d}.jsonl"
    write_atomic(seg_path, _dump_records(head))
    write_atomic(rdir / f"{stem}.{seg_index:04d}.digest.md",
                 _build_segment_digest(head, seg_index, stem))
    write_atomic(events, _dump_records(tail))   # same format, bounded length
    return {"segment": seg_index, "archived": len(head),
            "kept_tail": len(tail), "segment_path": str(seg_path)}


def compact_recipe_store(recipe_id: str,
                         root: Path | str | None = None) -> dict:
    """One-shot maintenance for an existing recipe dir: apply snapshot retention
    AND roll up an oversized events.jsonl. Unlike the save-time GC this is
    explicit/on-demand and NOT gated by EDP_SNAPSHOT_GC — calling it IS the
    opt-in. `root` is the recipes root (dir of recipe dirs); defaults to the
    server's resolved .recipes root. Returns a summary of what it did."""
    base = Path(root) if root is not None else _default_recipes_root()
    rdir = base / recipe_id
    deleted = gc_snapshots(rdir / "snapshots")
    rolled = rollup_events(rdir)
    return {
        "recipe_id": recipe_id,
        "snapshots_deleted": deleted,
        "events_rolled_up": rolled,
    }


class RecipeStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        # C1 (s18): per-store last-saved state, so save() can snapshot only on a
        # state TRANSITION (or every Kth version) instead of every save. A fresh
        # process has an empty map, so the first save of any recipe snapshots.
        self._last_state: dict[str, str] = {}

    def _dir(self, rid: str) -> Path:
        return self.root / rid

    def _file(self, rid: str) -> Path:
        return self._dir(rid) / "recipe.json"

    def exists(self, rid: str) -> bool:
        return self._file(rid).exists()

    def list_ids(self) -> list[str]:
        """Recipe ids present on disk (dirs containing recipe.json).
        The resume scan reads these — disk is the source of truth that
        survives a session `/clear`."""
        if not self.root.exists():
            return []
        return sorted(
            p.name for p in self.root.iterdir()
            if p.is_dir() and (p / "recipe.json").exists()
        )

    def load(self, rid: str) -> Recipe:
        data = json.loads(self._file(rid).read_text(encoding="utf-8"))
        # P2 tiering: resolve sidecar refs to full text BEFORE validation so
        # the in-memory model ALWAYS carries full text (every consumer is
        # byte-identical by construction). Legacy data (no refs) is a no-op.
        warnings: list[str] = []
        data = hydrate_recipe_payload(data, self._dir(rid), warnings)
        for w in warnings:
            append_jsonl(self._dir(rid) / "events.jsonl",
                         {"kind": "tiering_degraded", "detail": w})
        return Recipe.model_validate(data)

    def save(self, recipe: Recipe) -> int:
        """Validate (model already validated), bump version, atomic write,
        snapshot, append an events entry. Returns new version."""
        recipe.version += 1
        payload = recipe.model_dump(mode="json")
        # P2 tiering: long texts move to sidecars; live file AND snapshot
        # store the small dehydrated shape. Adoption gated by EDP_TIER_WRITE;
        # already-reffed fields always re-dehydrate (one-way consistency).
        payload = dehydrate_recipe_payload(payload, self._dir(recipe.recipe_id))
        write_atomic(self._file(recipe.recipe_id), json.dumps(payload, indent=2))
        # C1 (s18): snapshot only on a state transition or every SNAPSHOT_KEEP_
        # EVERY-th version (aligned with the GC retention cadence), not on every
        # save. The live recipe.json above is always current, so nothing is lost.
        if should_write_snapshot(
            self._last_state.get(recipe.recipe_id),
            recipe.state,
            recipe.version,
            every=SNAPSHOT_KEEP_EVERY,
        ):
            write_snapshot(
                self._dir(recipe.recipe_id) / "snapshots",
                recipe.version,
                payload,
            )
        self._last_state[recipe.recipe_id] = recipe.state
        append_jsonl(
            self._dir(recipe.recipe_id) / "events.jsonl",
            # W15 (a4): stamp actor attribution (by:{role,handle}) resolved
            # IN CODE from the environment (attribution.actor(), principle-6),
            # reusing a2's shared helper so who-wrote is identical across every
            # store. Additive to this NEW record only — legacy events untouched.
            {"kind": "recipe_saved", "version": recipe.version,
             "state": recipe.state, "by": actor()},
        )
        # Sol-harness vault projection (2026-07-19): re-render the Obsidian
        # note on every save — best-effort, never fails the durable write.
        mirror_recipe(recipe, self.root)
        # W1 maintenance: bound the events trail (active, threshold-gated) and
        # prune snapshots when GC is opted in. Both are no-ops in the common
        # case — under threshold / flag unset — so current behavior is intact.
        rdir = self._dir(recipe.recipe_id)
        rollup_events(rdir)
        if _snapshot_gc_enabled():
            gc_snapshots(rdir / "snapshots")
        return recipe.version

    def read_events_tail(self, recipe_id: str, kinds=None,
                         limit: int = EVENTS_TAIL_KEEP) -> list[dict]:
        """BOUNDED read of the recipe's LIVE events trail (DESIGN-v7 2.2 —
        the briefing-delta's read path). Reads ONLY `events.jsonl` — the hot
        segment the rollup keeps under EVENTS_ROLLUP_THRESHOLD records — and
        NEVER the archived `events.NNNN.jsonl` segments, so this can never
        become an unbounded full-history load however long the recipe runs.

        `kinds` (optional iterable) filters by record kind BEFORE the tail cut,
        so the caller gets the newest `limit` records OF THOSE KINDS (not the
        few that happen to survive a kind-blind tail). Returned in file order
        (oldest → newest), matching every other jsonl reader here; missing or
        unreadable file → [] (a briefing is best-effort, never a dispatch
        blocker)."""
        path = self._dir(recipe_id) / "events.jsonl"
        if not path.exists():
            return []
        try:
            records = read_jsonl(path)
        except OSError:
            return []
        if kinds is not None:
            kset = set(kinds)
            records = [r for r in records if r.get("kind") in kset]
        return records[-limit:] if limit else records

    # ── DESIGN-v7 P6.1 — the per-handle ACK LEDGER ──────────────────────────
    # {handle: {decision_ids, superseded_ids, done_step_ids, at}} written when
    # a shell's echoed ack_epoch MATCHES (it provably internalized that
    # ground). On the next reground the delta against this entry is what the
    # shell reads FIRST — "what changed since YOU last grounded", a screenful,
    # instead of re-internalizing a 170-decision digest cold. Best-effort on
    # both sides: no ledger → full digest only (legacy behaviour, no crash).

    def read_ack_ledger(self, recipe_id: str) -> dict:
        try:
            return json.loads(
                (self._dir(recipe_id) / "ack_ledger.json").read_text(
                    encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def write_ack_entry(self, recipe_id: str, handle: str,
                        entry: dict) -> None:
        try:
            led = self.read_ack_ledger(recipe_id)
            led[handle] = entry
            write_atomic(self._dir(recipe_id) / "ack_ledger.json",
                         json.dumps(led, indent=2))
        except OSError:
            pass   # a failed ledger write costs a wider reground, never a tick

    def write_state_synthesis(self, recipe_id: str, content: str) -> None:
        """v7 P6.3 — the human/cold-shell-readable 'state of the recipe'
        markdown, refreshed on every step close. Lives beside the tiering
        sidecars in context/ so it survives as a FILE a compacted shell or
        the operator reads first."""
        cdir = self._dir(recipe_id) / "context"
        cdir.mkdir(parents=True, exist_ok=True)
        write_atomic(cdir / "state-synthesis.md", content)

    def append_worklog(self, recipe_id: str, record: dict) -> None:
        """Append an arbitrary recipe-level worklog entry (crash
        recovery judgments, etc.). Lands in events.jsonl alongside the
        recipe_saved trail. `ts` added by append_jsonl."""
        rdir = self._dir(recipe_id)
        append_jsonl(rdir / "events.jsonl", record)
        rollup_events(rdir)   # same trail grows here — keep it bounded too.
