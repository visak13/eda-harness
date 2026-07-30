"""DESIGN-v6 s18 C1+C3 — per-tick store IO optimizations, over the REAL store
code, fast (no live spawn, no LLM — principle-6).

C1  stop snapshot-on-EVERY-save: RecipeStore/PlanStore.save now writes a
    versioned snapshot only on a STATE TRANSITION or every Kth version, not on
    every save. The live recipe.json/plan.json is still rewritten every save,
    so current state is never lost. o6: the legacy fixture 0e7ca8 still
    round-trips BYTE-IDENTICAL (the load→dehydrate path is untouched).
C3  cheap-gate rollup_events: an O(1) stat() gate skips the full-file
    _line_count scan for events.jsonl below a byte floor (a rollup is
    impossible there); behavior above the floor is unchanged.
"""

import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edp_claude.schemas import Plan, Recipe
from edp_claude.schemas.instruction import PlanState, RecipeState
from edp_claude.store import recipe_store as rs
from edp_claude.store.plan_store import PlanStore
from edp_claude.store.recipe_store import (
    EVENTS_MIN_RECORD_BYTES,
    EVENTS_ROLLUP_THRESHOLD,
    RecipeStore,
    rollup_events,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES = REPO_ROOT / ".recipes"
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    # d7/d8: control env explicitly (GC flag must not leak in from the worker
    # shell and perturb the snapshot cadence assertions).
    monkeypatch.delenv("EDP_SNAPSHOT_GC", raising=False)
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)


def _make_recipe(rid, state=RecipeState.EXECUTING):
    return Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled="g", domain="software_engineering",
        state=state,
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "short",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        context={"decisions": [
            {"id": "d1", "text": "a decision", "rationale": "r",
             "by": "neuron", "at": _now().isoformat()}]},
        created_at=_now(), updated_at=_now(),
    ))


def _make_plan(pid, state=PlanState.DISPATCHING):
    return Plan.model_validate(dict(
        plan_id=pid, recipe_id="r-s18", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state=state,
        actions=[{"action_id": "a1", "description": "build",
                  "status": "pending", "depends_on": [],
                  "executor_mode": "subagent",
                  "acceptance": {"kind": "artifact", "expected": "e",
                                 "actual": None}}],
        context={},
    ))


# ════════════════════════════════════════════════════════════════════════════
# C1 — snapshot only on transition / every Kth, not every save
# ════════════════════════════════════════════════════════════════════════════
def test_recipe_non_transition_save_writes_no_snapshot(tmp_path):
    store = RecipeStore(tmp_path / ".recipes")
    snap = tmp_path / ".recipes" / "r1" / "snapshots"

    v1 = store.save(_make_recipe("r1"))          # first save → transition
    assert (snap / f"v{v1}.json").exists(), "first save must snapshot"

    v2 = store.save(store.load("r1"))            # same state, non-Kth
    assert not (snap / f"v{v2}.json").exists(), \
        "a non-transition save must NOT write a snapshot"

    r3 = store.load("r1")
    r3.state = RecipeState.REVIEWING             # executing → reviewing
    v3 = store.save(r3)
    assert (snap / f"v{v3}.json").exists(), \
        "a state-transition save MUST write a snapshot"


def test_recipe_snapshot_written_every_kth_version(tmp_path):
    store = RecipeStore(tmp_path / ".recipes")
    snap = tmp_path / ".recipes" / "r-kth" / "snapshots"
    every = rs.SNAPSHOT_KEEP_EVERY

    store.save(_make_recipe("r-kth"))            # v1 (transition)
    # keep saving the SAME state; only the every-Kth version snapshots.
    last_v = 1
    while last_v < every:
        last_v = store.save(store.load("r-kth"))
    assert last_v == every
    assert (snap / f"v{every}.json").exists(), "the Kth version must snapshot"
    assert not (snap / f"v{every - 1}.json").exists(), \
        "the version before the Kth must NOT snapshot"


def test_plan_non_transition_save_writes_no_snapshot(tmp_path):
    store = PlanStore(tmp_path / ".plans")
    snap = tmp_path / ".plans" / "p1" / "snapshots"

    v1 = store.save(_make_plan("p1"))
    assert (snap / f"v{v1}.json").exists(), "first plan save must snapshot"

    v2 = store.save(store.load("p1"))            # same state (dispatching)
    assert not (snap / f"v{v2}.json").exists(), \
        "a non-transition plan save must NOT write a snapshot"

    p3 = store.load("p1")
    p3.state = PlanState.ACCEPTANCE_REVIEW
    v3 = store.save(p3)
    assert (snap / f"v{v3}.json").exists(), \
        "a plan state-transition save MUST write a snapshot"


def test_o6_legacy_fixture_still_byte_identical(monkeypatch, tmp_path):
    # o6 GUARD: C1/C3 touch only save cadence + a rollup stat gate, never the
    # tiering/serialization path — the legacy fixture must still round-trip
    # byte-for-byte (load→hydrate→validate→dehydrate→dumps == original).
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), "legacy fixture 0e7ca8 missing"
    original = (rdir / "recipe.json").read_text(encoding="utf-8")
    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    # a9: dehydrate into tmp_path, never the live fixture dir. For an
    # already-reffed field dehydrate ALWAYS re-writes the sidecar
    # (tiering.py:97), so pointing it at `rdir` rewrites 370 real files
    # per run and races test_w1_context_diet's copytree. The payload is
    # root-independent, so this changes nothing the test ASSERTS.
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    assert json.dumps(payload, indent=2) == original, \
        "legacy 0e7ca8 round-trip is NOT byte-identical after the s18 change"


def test_o6_legacy_fixture_hydrate_dehydrate_rehydrate_roundtrip(
        monkeypatch, tmp_path):
    """o6 under the s24/B1 content guard: hydrate → dehydrate → RE-hydrate must
    return the original model. The guard skips a sidecar write only on a content
    match, so the dangerous direction is a FALSE-EQUAL — a skipped write that
    the live text needed, which would make the re-hydrate serve stale bytes.
    Re-hydrating from the dir we dehydrated INTO is what would expose that.
    """
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)
    from edp_claude.store.tiering import (
        dehydrate_recipe_payload,
        hydrate_recipe_payload,
    )

    rdir = RECIPES / LEGACY_RID
    assert (rdir / "recipe.json").exists(), "legacy fixture 0e7ca8 missing"
    raw = json.loads((rdir / "recipe.json").read_text(encoding="utf-8"))
    original = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))

    # dehydrate into tmp (never the live fixture): sidecars are written there.
    payload = dehydrate_recipe_payload(
        original.model_dump(mode="json"), tmp_path)
    assert any(tmp_path.rglob("*.md")), \
        "dehydrate wrote no sidecar into tmp — the round-trip proves nothing"

    # re-hydrate FROM tmp: every tiered field must reinflate to the original.
    round_tripped = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(payload), tmp_path))
    assert round_tripped.model_dump(mode="json") == \
        original.model_dump(mode="json"), \
        "0e7ca8 hydrate→dehydrate→re-hydrate lost content under the B1 guard"

    # a second dehydrate over the SAME dir is where the guard engages: content
    # is unchanged, so it must write nothing AND still round-trip identically.
    from edp_claude.store import tiering
    writes: list[str] = []
    orig_write = tiering.write_atomic
    monkeypatch.setattr(
        tiering, "write_atomic",
        lambda p, t: (writes.append(str(p)), orig_write(p, t))[1])
    payload2 = dehydrate_recipe_payload(
        original.model_dump(mode="json"), tmp_path)
    assert writes == [], \
        f"re-dehydrating unchanged content rewrote {len(writes)} sidecars"
    assert payload2 == payload, "the skipped-write path changed the payload"
    assert Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(payload2), tmp_path)
    ).model_dump(mode="json") == original.model_dump(mode="json")


def test_o6_legacy_migration_stays_lazy_no_batch_rewrite(monkeypatch, tmp_path):
    """Migration must stay LAZY: a LOAD of a legacy recipe writes NOTHING. The
    B1 guard must not have turned the read path into a repair-on-load."""
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)
    from edp_claude.store import tiering

    writes: list[str] = []
    orig_write = tiering.write_atomic
    monkeypatch.setattr(
        tiering, "write_atomic",
        lambda p, t: (writes.append(str(p)), orig_write(p, t))[1])

    store = RecipeStore(RECIPES)
    r = store.load(LEGACY_RID)          # read-only: hydrate-on-load
    assert r.recipe_id == LEGACY_RID
    assert writes == [], f"loading a legacy recipe wrote {writes}"


# ════════════════════════════════════════════════════════════════════════════
# C3 — rollup_events skips the full-file line scan below a byte floor
# ════════════════════════════════════════════════════════════════════════════
def _spy_line_count(monkeypatch):
    calls: list[int] = []
    orig = rs._line_count

    def spy(path):
        calls.append(1)
        return orig(path)

    monkeypatch.setattr(rs, "_line_count", spy)
    return calls


def test_rollup_skips_line_scan_below_byte_floor(tmp_path, monkeypatch):
    rdir = tmp_path / "r-small"
    rdir.mkdir(parents=True)
    events = rdir / "events.jsonl"
    # a handful of tiny records — comfortably below threshold*MIN bytes.
    events.write_text(
        "".join(json.dumps({"kind": "recipe_saved", "n": i}) + "\n"
                for i in range(5)),
        encoding="utf-8",
    )
    assert events.stat().st_size < EVENTS_ROLLUP_THRESHOLD * EVENTS_MIN_RECORD_BYTES

    calls = _spy_line_count(monkeypatch)
    assert rollup_events(rdir) is None
    assert calls == [], "the full-file line scan must be SKIPPED below the floor"


def test_rollup_runs_line_scan_above_byte_floor(tmp_path, monkeypatch):
    rdir = tmp_path / "r-big-bytes"
    rdir.mkdir(parents=True)
    events = rdir / "events.jsonl"
    # bytes ABOVE the floor but FEWER than `threshold` records → the scan must
    # run (proving the gate lets it through), and rollup still returns None
    # because the record count is under threshold (behavior unchanged).
    floor = EVENTS_ROLLUP_THRESHOLD * EVENTS_MIN_RECORD_BYTES
    line = json.dumps({"kind": "recipe_saved", "pad": "x" * 40}) + "\n"
    n = (floor // len(line)) + 5
    events.write_text(line * n, encoding="utf-8")
    assert events.stat().st_size >= floor
    assert n < EVENTS_ROLLUP_THRESHOLD

    calls = _spy_line_count(monkeypatch)
    assert rollup_events(rdir) is None          # still under record threshold
    assert calls, "the line scan MUST run once the file is above the byte floor"
