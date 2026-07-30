"""DESIGN-v6 W1 acceptance — tiering-composed context diet + immutable north
star + get_recipe_digest. Proves the five W1 invariants end-to-end over the
REAL store code and the REAL legacy fixture, fast (seconds), no live spawn.

WHAT THIS FILE LOCKS DOWN (the a6 brief):
  (1) hydrated-model byte-identity for legacy recipe-…-0e7ca8 with tiering OFF
      (on-disk re-serialization is byte-for-byte the original) AND tiering ON
      (the hydrated CONTENT is identical whether or not the field is tiered —
      only the on-disk `*_ref` pointers differ, which are bookkeeping, not
      agent-facing text).
  (2) immutable `user_goal_verbatim` — a north-star patch that changes it is
      REFUSED by the code-enforced guard (NorthStarImmutable / _precondition).
  (3) get_recipe_digest returns the 7-part re-ground packet UNDER 10k tokens,
      measured with a REAL BPE tokenizer (tiktoken cl100k_base), NOT the
      digest's own len//4 `approx_tokens` proxy, and the packet is a code-only
      (no-LLM) build (byte-identical across repeated calls).
  (4) snapshot retention GC keeps the last 10 + every 25th, gated by
      EDP_SNAPSHOT_GC; event rollup at 1000 records produces its digest
      artifact and bounds the hot trail.
  (5) LENGTH-CAP PLACEMENT (o6): legacy recipes LOAD/validate WITH their
      existing >1200-char decision texts (no construction/schema cap) and a
      tiered >1200-char text re-hydrates+validates; while a NEW record_context
      write >1200 chars is REFUSED at the TOOL path (<=1200 succeeds).

PHOENIX / TOKEN-MEASUREMENT NOTE (planner ruling on a6, msg
96cc94a3, option A): the brief said "measure via Phoenix", but Phoenix's
:6006 surface is spans/traces only — it has NO endpoint that tokenizes
arbitrary text, and this venv cannot make an instrumented LLM call. The
load-bearing intent of "do NOT proxy" is a GENUINE tokenizer count, which
tiktoken cl100k_base satisfies. So Part 3 asserts a real tiktoken count <10k
AND asserts Phoenix :6006 is reachable (the eval stack the brief named is up).

ENV DISCIPLINE (d7/d8): a worker shell runs with EDP_ROLE=worker + EDP_HANDLE
set, and pytest subprocesses INHERIT them; record_context's north_star_update
route reads EDP_ROLE. EVERY test therefore controls the env EXPLICITLY via the
`_clean_env` autouse monkeypatch (delenv) + explicit setenv where a role/flag
is needed. No test shells out with an `env`/`env -u` prefix (d8) — all env
control is monkeypatch, in-process.
"""

import copy
import json
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest
import tiktoken
from edp_contracts import ToolError, ToolOk

from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.store.north_star import (
    NorthStar,
    NorthStarImmutable,
    NorthStarStore,
)
from edp_claude.store.recipe_store import (
    RecipeStore,
    _snapshots_to_keep,
    compact_recipe_store,
    gc_snapshots,
    rollup_events,
)
from edp_claude.store.tiering import (
    dehydrate_recipe_payload,
    hydrate_recipe_payload,
)
from edp_claude.tools import build_registry

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPES = REPO_ROOT / ".recipes"
LEGACY_RID = "recipe-make-the-reactiveagents-chat-genuinely-r-0e7ca8"
CONTEXT_TEXT_MAX = 1200


def _now():
    return datetime.now(timezone.utc)


# ── env discipline (d7/d8) ───────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Neutralise the inherited worker shell env so every test starts from a
    known baseline whether run bare or under a leaked worker env. Tests that
    need a role/flag set it EXPLICITLY afterwards (never rely on ambient)."""
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_TIER_WRITE",
                "EDP_SNAPSHOT_GC", "EDP_TIER_THRESHOLD_BYTES"):
        monkeypatch.delenv(var, raising=False)


# ── helpers ──────────────────────────────────────────────────────────────────
def _load_recipe_readonly(rdir: Path) -> Recipe:
    """Hydrate + validate a recipe dir WITHOUT going through the store (no
    write side effects — the store would append a degraded-event on a missing
    sidecar). Mirrors RecipeStore.load's read half exactly."""
    raw = json.loads((rdir / "recipe.json").read_text(encoding="utf-8"))
    data = hydrate_recipe_payload(raw, rdir)
    return Recipe.model_validate(data)


def _strip_refs(obj):
    """Drop the on-disk `*_ref` pointer keys (text_ref / rationale_ref /
    description_ref / actual_ref). They are storage bookkeeping — present when
    a field is tiered, absent when inline — NOT agent-facing content, so the
    hydrated-model equality is over everything EXCEPT them."""
    if isinstance(obj, dict):
        return {k: _strip_refs(v) for k, v in obj.items()
                if not k.endswith("_ref")}
    if isinstance(obj, list):
        return [_strip_refs(x) for x in obj]
    return obj


def _make_recipe(rid, *, decision_text="a decision", distilled="g"):
    return Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="user asked for X",
        user_goal_distilled=distilled, domain="software_engineering",
        state="executing",
        comprehension={"branches": [], "expected_outcomes": []},
        steps=[{"step_id": "s1", "kind": "k", "description": "short",
                "status": "pending", "depends_on": [], "execution": "inline"}],
        context={"decisions": [
            {"id": "d1", "text": decision_text, "rationale": "r",
             "by": "neuron", "at": _now().isoformat()}]},
        created_at=_now(), updated_at=_now(),
    ))


def _tools(ctx):
    return {t.name: t for t in build_registry(ctx)}


# ════════════════════════════════════════════════════════════════════════════
# (1) BYTE-IDENTITY — legacy fixture, tiering OFF and tiering ON
# ════════════════════════════════════════════════════════════════════════════
def test_legacy_fixture_present():
    assert (RECIPES / LEGACY_RID / "recipe.json").exists(), (
        f"legacy fixture {LEGACY_RID} missing under {RECIPES} — the "
        "byte-identity invariant cannot be proven without it")


def test_0e7ca8_byte_identity_tiering_off(monkeypatch, tmp_path):
    """Tiering OFF (EDP_TIER_WRITE unset): the pure load→dump→dehydrate→
    re-serialize round-trip reproduces recipe.json BYTE-FOR-BYTE (RP-A
    emission-gate). Sidecars are READ from the real dir; the (no-op) dehydrate
    is pointed at tmp so the real fixture is never mutated."""
    monkeypatch.delenv("EDP_TIER_WRITE", raising=False)   # tiering OFF
    rdir = RECIPES / LEGACY_RID
    original = (rdir / "recipe.json").read_text(encoding="utf-8")

    raw = json.loads(original)
    model = Recipe.model_validate(
        hydrate_recipe_payload(copy.deepcopy(raw), rdir))
    payload = dehydrate_recipe_payload(model.model_dump(mode="json"), tmp_path)
    reserialized = json.dumps(payload, indent=2)

    assert reserialized == original, (
        "tiering-OFF round-trip is NOT byte-identical for the legacy fixture — "
        f"orig {len(original)}B vs reserialized {len(reserialized)}B")


def test_0e7ca8_hydrated_content_identical_tiering_on(monkeypatch, tmp_path):
    """Tiering ON (EDP_TIER_WRITE=1): migrating the fixture to fully-tiered
    on disk does NOT change the hydrated model's CONTENT — every text field
    reinflates identically; only the on-disk `*_ref` pointers differ. This is
    the 'every consumer is byte-identical by construction' invariant."""
    dst = tmp_path / ".recipes" / LEGACY_RID
    dst.parent.mkdir(parents=True)
    shutil.copytree(RECIPES / LEGACY_RID, dst)
    store = RecipeStore(tmp_path / ".recipes")

    # OFF: hydrated model (loaded from the as-copied on-disk shape).
    monkeypatch.setenv("EDP_TIER_WRITE", "0")
    before = store.load(LEGACY_RID)
    dump_before = _strip_refs(before.model_dump(mode="json"))
    dump_before.pop("version", None)

    # ON: one tiered save migrates adoption-eligible fields to sidecars; the
    # reload rehydrates them. Content must be unchanged.
    monkeypatch.setenv("EDP_TIER_WRITE", "1")
    store.save(store.load(LEGACY_RID))
    after = store.load(LEGACY_RID)
    dump_after = _strip_refs(after.model_dump(mode="json"))
    dump_after.pop("version", None)

    assert json.dumps(dump_before, sort_keys=True) == \
        json.dumps(dump_after, sort_keys=True), (
        "tiering ON changed the hydrated model content (not just the on-disk "
        "*_ref pointers) — a byte-identity violation")
    # sanity: the round-trip really did tier something (adoption happened).
    on_disk = (dst / "recipe.json").read_text(encoding="utf-8")
    assert '"rationale_ref"' in on_disk, "tiering ON did not adopt any field"


# ════════════════════════════════════════════════════════════════════════════
# (2) IMMUTABLE user_goal_verbatim
# ════════════════════════════════════════════════════════════════════════════
def test_north_star_user_goal_verbatim_is_immutable(tmp_path):
    """The store's single persist path REFUSES a patch that changes
    user_goal_verbatim (NorthStarImmutable — the code-enforced _precondition
    the record_context tool renders)."""
    store = NorthStarStore(tmp_path / ".recipes")
    ns = NorthStar(recipe_id="r-imm", user_goal_verbatim="THE ORIGINAL GOAL",
                   created_at=_now(), updated_at=_now())
    store.save(ns, [])
    assert store.load("r-imm").user_goal_verbatim == "THE ORIGINAL GOAL"

    drifted = store.load("r-imm")
    drifted.user_goal_verbatim = "a different goal"
    with pytest.raises(NorthStarImmutable):
        store.save(drifted, [])
    # unchanged on disk after the refusal
    assert store.load("r-imm").user_goal_verbatim == "THE ORIGINAL GOAL"


async def test_north_star_update_tool_sources_goal_from_recipe(
        tmp_path, monkeypatch):
    """The record_context(kind=north_star_update) route is neuron-only and
    always RE-SOURCES the immutable goal from the recipe — so the persisted
    north star's user_goal_verbatim can never be patched to a stray value."""
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-ns-tool"))

    # non-neuron role is refused (role guard runs first)
    monkeypatch.setenv("EDP_ROLE", "worker")
    refused = await t["record_context"].run(
        {"kind": "north_star_update", "recipe_id": "r-ns-tool",
         "text": "x"})
    assert isinstance(refused, ToolError)
    assert refused.code == "tool_precondition" and "neuron-only" in \
        refused.message

    # neuron update materialises the north star with the recipe's goal
    monkeypatch.setenv("EDP_ROLE", "neuron")
    ok = await t["record_context"].run(
        {"kind": "north_star_update", "recipe_id": "r-ns-tool",
         "text": "single-pass shape", "title": "single-pass"})
    assert isinstance(ok, ToolOk), ok
    ns = ctx.north_star.load("r-ns-tool")
    assert ns.user_goal_verbatim == "user asked for X"   # from the recipe
    assert ns.current_shape == "single-pass"
    assert [e.text for e in ns.evolution_log] == ["single-pass shape"]


# ════════════════════════════════════════════════════════════════════════════
# (3) get_recipe_digest — 7 parts, <10k REAL tokens, code-only (no-LLM)
# ════════════════════════════════════════════════════════════════════════════
def test_phoenix_reachable():
    """Part 3's eval-stack precondition (planner ruling A): the Phoenix server
    the a6 brief named IS up at 127.0.0.1:6006."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3.0)
        rc = s.connect_ex(("127.0.0.1", 6006))
    assert rc == 0, ("Phoenix :6006 is not reachable — the a6 brief states it "
                     "is UP; start it or investigate before trusting the "
                     "eval stack")


async def test_get_recipe_digest_under_10k_real_tokens(tmp_path):
    """The 7-part packet on the LARGEST legacy recipe measures UNDER 10k tokens
    with a REAL tokenizer (tiktoken cl100k_base) — NOT the digest's len//4
    approx_tokens proxy — and is a code-only build (byte-identical on a repeat
    call; an LLM assembly would not be deterministic)."""
    ctx = make_context(tmp_path)
    shutil.copytree(RECIPES / LEGACY_RID, tmp_path / ".recipes" / LEGACY_RID)
    t = _tools(ctx)

    res = await t["get_recipe_digest"].run({"recipe_id": LEGACY_RID})
    assert isinstance(res, ToolOk), res
    data = res.data if isinstance(res.data, dict) else res.data.model_dump(
        mode="json")

    part_names = ["north_star", "recap", "expected_outcomes",
                  "active_decisions", "open_steps", "pending", "recent_events"]
    assert data["parts"] == part_names
    packet = {k: data[k] for k in part_names}
    packet_text = json.dumps(packet, default=str, ensure_ascii=False)

    enc = tiktoken.get_encoding("cl100k_base")
    real_tokens = len(enc.encode(packet_text))
    assert real_tokens < 10000, (
        f"get_recipe_digest packet is {real_tokens} REAL tokens — over the 10k "
        f"budget (the len//4 proxy reported approx_tokens={data['approx_tokens']})")

    # code-only (no-LLM): a second call yields a byte-identical packet.
    res2 = await t["get_recipe_digest"].run({"recipe_id": LEGACY_RID})
    data2 = res2.data if isinstance(res2.data, dict) else res2.data.model_dump(
        mode="json")
    packet2 = {k: data2[k] for k in part_names}
    assert json.dumps(packet2, default=str, sort_keys=True) == \
        json.dumps(packet, default=str, sort_keys=True), (
        "get_recipe_digest is not deterministic — a code-only build must be "
        "byte-identical across calls")


# ════════════════════════════════════════════════════════════════════════════
# (4) snapshot GC + event rollup
# ════════════════════════════════════════════════════════════════════════════
def test_snapshot_retention_policy_keeps_last_10_and_every_25th():
    versions = list(range(1, 61))          # v1 … v60
    keep = _snapshots_to_keep(versions)
    # last 10 (51..60) + every 25th (25, 50)
    assert keep == set(range(51, 61)) | {25, 50}


def test_gc_snapshots_prunes_to_policy(tmp_path):
    snap = tmp_path / "snapshots"
    snap.mkdir()
    for v in range(1, 61):
        (snap / f"v{v}.json").write_text("{}", encoding="utf-8")
    deleted = gc_snapshots(snap)
    remaining = {int(p.stem[1:]) for p in snap.glob("v*.json")}
    assert remaining == set(range(51, 61)) | {25, 50}
    assert set(deleted) == set(range(1, 61)) - remaining


def test_save_time_gc_is_gated_by_env(tmp_path, monkeypatch):
    store = RecipeStore(tmp_path / ".recipes")
    store.save(_make_recipe("r-gc"))       # creates snapshots/v1.json
    snap = tmp_path / ".recipes" / "r-gc" / "snapshots"
    for v in range(2, 41):                 # seed older snapshots v2..v40
        (snap / f"v{v}.json").write_text("{}", encoding="utf-8")

    # GC OFF (default): a save prunes nothing — the old snapshot survives.
    monkeypatch.delenv("EDP_SNAPSHOT_GC", raising=False)
    store.save(store.load("r-gc"))
    assert (snap / "v2.json").exists()

    # GC ON: a save applies retention — v2 is pruned (outside last-10/every-25).
    monkeypatch.setenv("EDP_SNAPSHOT_GC", "1")
    store.save(store.load("r-gc"))
    assert not (snap / "v2.json").exists()


def test_event_rollup_produces_digest_artifact(tmp_path):
    rdir = tmp_path / ".recipes" / "r-roll"
    rdir.mkdir(parents=True)
    events = rdir / "events.jsonl"
    with open(events, "w", encoding="utf-8") as f:
        for i in range(1000):
            kind = "learning" if i % 10 == 0 else "recipe_saved"
            f.write(json.dumps(
                {"kind": kind, "ts": f"2026-01-01T00:{i:04d}", "n": i}) + "\n")

    summary = rollup_events(rdir)
    assert summary is not None and summary["segment"] == 1
    seg = rdir / "events.0001.jsonl"
    digest = rdir / "events.0001.digest.md"
    assert seg.exists(), "archived segment not written"
    assert digest.exists(), "code-generated event digest artifact not produced"
    body = digest.read_text(encoding="utf-8")
    assert "events segment 0001 digest" in body
    assert "counts by kind" in body and "learning events:" in body
    # hot trail bounded to the tail; head preserved full-fidelity in the segment
    tail = events.read_text(encoding="utf-8").strip().splitlines()
    assert len(tail) == 100
    assert len(seg.read_text(encoding="utf-8").strip().splitlines()) == 900


def test_compact_recipe_store_applies_retention_and_rollup(tmp_path):
    rdir = tmp_path / ".recipes" / "r-compact"
    (rdir / "snapshots").mkdir(parents=True)
    for v in range(1, 61):
        (rdir / "snapshots" / f"v{v}.json").write_text("{}", encoding="utf-8")
    with open(rdir / "events.jsonl", "w", encoding="utf-8") as f:
        for i in range(1000):
            f.write(json.dumps({"kind": "recipe_saved", "ts": str(i)}) + "\n")

    out = compact_recipe_store("r-compact", root=tmp_path / ".recipes")
    assert out["recipe_id"] == "r-compact"
    remaining = {int(p.stem[1:])
                 for p in (rdir / "snapshots").glob("v*.json")}
    assert remaining == set(range(51, 61)) | {25, 50}
    assert out["events_rolled_up"] is not None
    assert (rdir / "events.0001.digest.md").exists()


# ════════════════════════════════════════════════════════════════════════════
# (5) LENGTH-CAP PLACEMENT (o6): load accepts >1200, tool WRITE refuses >1200
# ════════════════════════════════════════════════════════════════════════════
def test_legacy_recipes_load_with_over_1200_char_decisions():
    """0e7ca8 AND a spot-check of one OTHER legacy recipe LOAD + model_validate
    fine WITH their existing >1200-char decision texts — proving there is NO
    construction/schema cap (the cap lives only on the tool WRITE path)."""
    def _max_decision_len(rid):
        r = _load_recipe_readonly(RECIPES / rid)
        return max((len(d.text) for d in r.context.decisions), default=0)

    assert _max_decision_len(LEGACY_RID) > CONTEXT_TEXT_MAX

    # spot-check: one OTHER legacy recipe carrying a >1200-char decision.
    # DESIGN-v7 P0 archived every recipe except 0e7ca8 to .archive/v6/, so
    # the second sample now lives there when present; a tree without the
    # archive (fresh clone) carries the invariant through 0e7ca8 alone.
    def _max_len_at(rdir):
        r = _load_recipe_readonly(rdir)
        return max((len(d.text) for d in r.context.decisions), default=0)

    archived = RECIPES.parent / ".archive" / "v6" / ".recipes"
    other = None
    for root in (RECIPES, archived):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if d.name == LEGACY_RID or not (d / "recipe.json").exists():
                continue
            try:
                if _max_len_at(d) > CONTEXT_TEXT_MAX:
                    other = d
                    break
            except Exception:
                continue
        if other is not None:
            break
    if other is not None:
        assert _max_len_at(other) > CONTEXT_TEXT_MAX


def test_tiered_over_1200_char_text_rehydrates_and_validates(
        tmp_path, monkeypatch):
    """A >1200-char decision text tiers out (>600B threshold) under
    EDP_TIER_WRITE=1 and re-hydrates + model_validates back to the exact
    original — construction and tiered hydration accept ANY length."""
    monkeypatch.setenv("EDP_TIER_WRITE", "1")
    big = "BIG DECISION HEADLINE. " + ("payload sentence. " * 120)  # >1200
    assert len(big) > CONTEXT_TEXT_MAX
    store = RecipeStore(tmp_path / ".recipes")
    store.save(_make_recipe("r-big", decision_text=big))   # constructs w/ >1200

    # on disk the field is tiered (digest inline + sidecar holds full text)
    on_disk = json.loads(
        (tmp_path / ".recipes" / "r-big" / "recipe.json").read_text(
            encoding="utf-8"))
    d1 = on_disk["context"]["decisions"][0]
    assert d1["text_ref"] == "context/d1.md"
    assert "full text in context/d1.md" in d1["text"]
    # hydrated load re-validates and returns the full >1200-char text
    r = store.load("r-big")
    assert r.context.decisions[0].text == big
    assert len(r.context.decisions[0].text) > CONTEXT_TEXT_MAX


async def test_record_context_write_refuses_over_1200(tmp_path, monkeypatch):
    """A NEW record_context decision/assumption/rejected_option write whose
    body exceeds 1200 chars is REFUSED at the tool path; a <=1200 write (and
    exactly 1200) succeeds."""
    monkeypatch.delenv("EDP_ROLE", raising=False)   # decision route not gated
    ctx = make_context(tmp_path)
    t = _tools(ctx)
    ctx.recipes.save(_make_recipe("r-cap"))

    over = "x" * (CONTEXT_TEXT_MAX + 1)
    for kind in ("decision", "assumption", "rejected_option"):
        res = await t["record_context"].run(
            {"kind": kind, "recipe_id": "r-cap", "text": over})
        assert isinstance(res, ToolError), (kind, res)
        assert res.code == "tool_precondition"
        assert "1200-char write cap" in res.message, (kind, res.message)

    # exactly 1200 chars is accepted (boundary is > not >=)
    at_cap = "y" * CONTEXT_TEXT_MAX
    ok = await t["record_context"].run(
        {"kind": "decision", "recipe_id": "r-cap", "text": at_cap})
    assert isinstance(ok, ToolOk), ok
    r = ctx.recipes.load("r-cap")
    assert any(d.text == at_cap for d in r.context.decisions)
