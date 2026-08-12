"""P2 tiered storage — digest inline, full text in sidecars.

THE HARD CONSTRAINT proven here: hydration happens at the store chokepoint
(before model_validate), so the in-memory model always carries full text and
every consumer — worker grounding via _resolve_action_injected, full
read_object, the dispatch stamp — is byte-identical to pre-tiering behavior.
Legacy files (no refs) round-trip unchanged. Adoption is gated by
EDP_TIER_WRITE; once tiered, always tiered.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from edp_contracts import ToolOk

from edp_claude.schemas import Plan, Recipe

FIXTURES = Path(__file__).parent / "fixtures"
BIG = "DECISION BODY LINE. " * 200          # ~4KB
EVIDENCE = "evidence paragraph " * 300      # ~5.7KB


def _ok(res):
    assert isinstance(res, ToolOk), res
    return res.data


BIG_DECISION = "BIG DECISION HEADLINE. " + BIG


@pytest.fixture
def tier_on(monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "1")


@pytest.fixture
def sidecar_writes(monkeypatch):
    """Count REAL sidecar writes as a list of written paths.

    Patching `tiering.write_atomic` (not `atomic.write_atomic`) counts sidecar
    IO ONLY: recipe.json, plan.json and the snapshots import `write_atomic` into
    their own store namespaces, so they never reach this spy.
    """
    from edp_claude.store import tiering
    written: list[str] = []
    orig = tiering.write_atomic

    def spy(path, text):
        written.append(Path(path).name)
        return orig(path, text)

    monkeypatch.setattr(tiering, "write_atomic", spy)
    return written


def _mk_recipe(env, rid="r-tier", state="executing"):
    comprehension = {"branches": [], "expected_outcomes": [
        {"id": "o1", "description": "o", "verification": "v"}]}
    # A PLANNING recipe is dispatchable: next_action stamps its first ready
    # step and SAVES. That needs the P6 signoff gate satisfied.
    step1_status = "in_progress"
    if state == "planning":
        comprehension |= {"user_signoff": True, "signoff_quote": "go"}
        step1_status = "pending"
    env.ctx.recipes.save(Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension=comprehension,
        steps=[{"step_id": "s1", "kind": "k", "description": "short step",
                "status": step1_status, "depends_on": [],
                "execution": "spawn_planner"},
               {"step_id": "s2", "kind": "k", "description": BIG,
                "status": "pending", "depends_on": [],
                "execution": "spawn_planner"}],
        context={"decisions": [
            {"id": "d1", "text": "SHORT DECISION.", "rationale": "r",
             "by": "neuron", "at": datetime.now(timezone.utc).isoformat()},
            {"id": "d2", "text": "BIG DECISION HEADLINE. " + BIG,
             "rationale": "r", "by": "neuron",
             "at": datetime.now(timezone.utc).isoformat(),
             "load_bearing": True}]},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )))
    return rid


def _mk_plan(env, pid="r-tier-s1", actual=None, injected=None):
    fields = dict(
        plan_id=pid, recipe_id="r-tier", recipe_step_id="s1",
        domain="generic", shape="x", goal="g", state="dispatching",
        actions=[{
            "action_id": "a1", "description": "build", "status": "done",
            "depends_on": [], "executor_mode": "subagent",
            "acceptance": {"kind": "artifact", "expected": "e",
                           "actual": actual},
        }],
        context={},
    )
    if injected:
        fields["injected_context"] = injected
    env.ctx.plans.save(Plan.model_validate(fields))
    return pid


# ── recipe round-trip ───────────────────────────────────────────────────────

async def test_recipe_roundtrip_byte_identity(env, tier_on):
    rid = _mk_recipe(env)
    rdir = env.ctx.recipes.root / rid
    raw = json.loads((rdir / "recipe.json").read_text(encoding="utf-8"))
    decs = {d["id"]: d for d in raw["context"]["decisions"]}
    # big decision tiered: digest inline + ref + sidecar holds full text
    assert decs["d2"]["text_ref"] == "context/d2.md"
    assert "full text in context/d2.md" in decs["d2"]["text"]
    assert (rdir / "context" / "d2.md").read_text(
        encoding="utf-8") == "BIG DECISION HEADLINE. " + BIG
    # small decision untouched, no new keys on disk
    assert decs["d1"]["text"] == "SHORT DECISION."
    assert "text_ref" not in decs["d1"] and "status" not in decs["d1"]
    # big step description tiered too
    steps = {s["step_id"]: s for s in raw["steps"]}
    assert steps["s2"]["description_ref"] == "context/step-s2.md"
    assert "description_ref" not in steps["s1"]
    # HYDRATED load returns full text byte-equal
    r = env.ctx.recipes.load(rid)
    assert r.context.decisions[1].text == "BIG DECISION HEADLINE. " + BIG
    assert r.steps[1].description == BIG
    # idempotent re-save: same digest + sidecar, still loads full
    env.ctx.recipes.save(r)
    assert env.ctx.recipes.load(rid).context.decisions[1].text \
        == "BIG DECISION HEADLINE. " + BIG


async def test_snapshot_is_dehydrated(env, tier_on):
    # s18/C1: snapshots are now written only on a transition / every Kth save,
    # so read the snapshot the FIRST save produces — the dehydration path under
    # test runs on every save regardless of cadence.
    rid = _mk_recipe(env)                       # first save → snapshot written
    v = env.ctx.recipes.load(rid).version       # its persisted version
    snap = json.loads((env.ctx.recipes.root / rid / "snapshots" /
                       f"v{v}.json").read_text(encoding="utf-8"))
    d2 = next(d for d in snap["context"]["decisions"] if d["id"] == "d2")
    assert "full text in context/d2.md" in d2["text"]
    assert len(json.dumps(snap)) < len(BIG) * 2  # snapshot stays small


async def test_legacy_recipe_passthrough_no_new_keys(env, monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "0")
    rid = _mk_recipe(env)
    raw = (env.ctx.recipes.root / rid / "recipe.json").read_text(
        encoding="utf-8")
    parsed = json.loads(raw)
    for key in ("text_ref", "description_ref", "superseded_by"):
        assert f'"{key}"' not in raw, key
    # decisions carry no emission-gated keys (steps legitimately have status)
    for d in parsed["context"]["decisions"]:
        assert "status" not in d and "text_ref" not in d, d
    # load + save round-trips with full text inline (flag off = no adoption)
    r = env.ctx.recipes.load(rid)
    assert r.context.decisions[1].text == "BIG DECISION HEADLINE. " + BIG
    env.ctx.recipes.save(r)
    raw2 = (env.ctx.recipes.root / rid / "recipe.json").read_text(
        encoding="utf-8")
    assert "BIG DECISION HEADLINE." in raw2 and '"text_ref"' not in raw2


async def test_missing_sidecar_degrades_not_crashes(env, tier_on):
    rid = _mk_recipe(env)
    rdir = env.ctx.recipes.root / rid
    (rdir / "context" / "d2.md").unlink()
    r = env.ctx.recipes.load(rid)          # must not raise
    assert "full text in context/d2.md" in r.context.decisions[1].text
    events = (rdir / "events.jsonl").read_text(encoding="utf-8")
    assert "tiering_degraded" in events


async def test_golden_geoguessr_recipe_loads_and_tiers(env, tier_on):
    """The real 47KB GeoGuessr recipe v40: loads unchanged, and one
    tiered save shrinks the live JSON while load still returns the full
    decision texts byte-equal."""
    raw = json.loads((FIXTURES / "geoguessr_recipe_v40.json").read_text(
        encoding="utf-8"))
    rid = raw["recipe_id"]
    rdir = env.ctx.recipes.root / rid
    rdir.mkdir(parents=True)
    (rdir / "recipe.json").write_text(json.dumps(raw), encoding="utf-8")
    r = env.ctx.recipes.load(rid)          # legacy hydrate = no-op
    originals = {d.id: d.text for d in r.context.decisions}
    assert originals["d4"].startswith("CORE STRATEGY")
    before = (rdir / "recipe.json").stat().st_size
    env.ctx.recipes.save(r)                # first tiered save migrates
    after = (rdir / "recipe.json").stat().st_size
    assert after < before * 0.55, (before, after)
    r2 = env.ctx.recipes.load(rid)
    assert {d.id: d.text for d in r2.context.decisions} == originals
    assert (rdir / "context" / "d4.md").exists()


# ── plan round-trip + worker grounding ──────────────────────────────────────

async def test_plan_evidence_tiered_and_hydrated(env, tier_on):
    _mk_recipe(env)
    pid = _mk_plan(env, actual=EVIDENCE)
    pdir = env.ctx.plans.root / pid
    raw = json.loads((env.ctx.plans.root / f"{pid}.json").read_text(
        encoding="utf-8"))
    acc = raw["actions"][0]["acceptance"]
    assert acc["actual_ref"] == "evidence/a1-actual.md"
    assert "full text in evidence/a1-actual.md" in acc["actual"]
    assert (pdir / "evidence" / "a1-actual.md").read_text(
        encoding="utf-8") == EVIDENCE
    p = env.ctx.plans.load(pid)
    assert p.actions[0].acceptance.actual == EVIDENCE


async def test_injected_context_markers_and_grounding_identity(env, tier_on):
    """The hard constraint, end to end: tiered injected_context values are
    @file: markers on disk, but the worker-facing resolved grounding is
    byte-identical to the untiered text."""
    _mk_recipe(env)
    big_text = "BIG DECISION HEADLINE. " + BIG
    pid = _mk_plan(env, injected={"d2": big_text})
    raw = json.loads((env.ctx.plans.root / f"{pid}.json").read_text(
        encoding="utf-8"))
    assert raw["injected_context"]["d2"].startswith("@file:context/d2.md")
    assert (env.ctx.plans.root / pid / "context" / "d2.md").read_text(
        encoding="utf-8") == big_text
    # stamp the pointer on the action, then read like a worker would
    p = env.ctx.plans.load(pid)
    assert p.injected_context["d2"] == big_text   # hydrated
    p.actions[0].injected_context_ids = {"load_bearing_decisions": ["d2"]}
    env.ctx.plans.save(p)
    from edp_claude import objects
    view = await objects.read_object(env.ctx, "action", plan_id=pid,
                                     action_id="a1")
    assert view["injected_context"]["load_bearing_decisions"] == [big_text]


async def test_legacy_plan_passthrough(env, monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "0")
    _mk_recipe(env)
    pid = _mk_plan(env, actual=EVIDENCE)
    raw = (env.ctx.plans.root / f"{pid}.json").read_text(encoding="utf-8")
    assert '"actual_ref"' not in raw and "@file:" not in raw
    assert env.ctx.plans.load(pid).actions[0].acceptance.actual == EVIDENCE


# ── s24/B1 content guard: an unchanged sidecar is never rewritten ───────────
#
# Each assertion below was MUTATION-PROVED (d60/B5): the guard was neutralised
# (`_write_sidecar` made unconditional) and the write-count tests went RED; the
# digest substitution was gated on the write (`if not wrote: return`) and the
# digest test went RED. A green suite that survives both mutations would be
# guarding nothing.

def _raw_recipe(env, rid):
    return json.loads((env.ctx.recipes.root / rid / "recipe.json").read_text(
        encoding="utf-8"))


def _decision(raw, did):
    return next(d for d in raw["context"]["decisions"] if d["id"] == did)


async def test_unchanged_text_save_writes_no_sidecar(env, tier_on,
                                                     sidecar_writes):
    """(1) A save whose tiered text is UNCHANGED performs ZERO sidecar writes."""
    rid = _mk_recipe(env)
    # the adoption save tiers both long fields — that write MUST happen.
    assert sorted(sidecar_writes) == ["d2.md", "step-s2.md"], sidecar_writes
    sidecar_writes.clear()

    env.ctx.recipes.save(env.ctx.recipes.load(rid))   # nothing changed
    assert sidecar_writes == [], \
        f"an unchanged save must write NO sidecar; wrote {sidecar_writes}"

    # the invariant still holds: sidecar content == live text, digest inline.
    rdir = env.ctx.recipes.root / rid
    assert (rdir / "context" / "d2.md").read_text(
        encoding="utf-8") == BIG_DECISION
    assert env.ctx.recipes.load(rid).context.decisions[1].text == BIG_DECISION


async def test_changed_text_save_writes_exactly_once(env, tier_on,
                                                     sidecar_writes):
    """(2) A save whose tiered text CHANGED writes exactly once — only the field
    that changed — and the sidecar content matches the new text."""
    rid = _mk_recipe(env)
    sidecar_writes.clear()
    edited = "EDITED HEADLINE. " + BIG

    r = env.ctx.recipes.load(rid)
    r.context.decisions[1].text = edited
    env.ctx.recipes.save(r)

    # exactly one write, and it is the changed field — the untouched step
    # description sidecar is NOT rewritten alongside it.
    assert sidecar_writes == ["d2.md"], sidecar_writes
    rdir = env.ctx.recipes.root / rid
    assert (rdir / "context" / "d2.md").read_text(encoding="utf-8") == edited
    assert env.ctx.recipes.load(rid).context.decisions[1].text == edited


async def test_digest_line_written_inline_whether_or_not_sidecar_is(
        env, tier_on, sidecar_writes):
    """(3) The inline digest is substituted in BOTH cases. The guard belongs on
    the IO, never on the digest: skipping `obj[field] = _digest_line(...)` would
    leave full text inline and silently untier the field."""
    rid = _mk_recipe(env)
    sidecar_writes.clear()

    # (a) unchanged save — no sidecar write, digest still inline.
    env.ctx.recipes.save(env.ctx.recipes.load(rid))
    assert sidecar_writes == []
    d2 = _decision(_raw_recipe(env, rid), "d2")
    assert d2["text_ref"] == "context/d2.md"
    assert "full text in context/d2.md" in d2["text"]
    assert BIG not in d2["text"], "full text leaked inline on a skipped write"

    # (b) changed save — one sidecar write, digest refreshed to the new text.
    edited = "EDITED HEADLINE. " + BIG
    r = env.ctx.recipes.load(rid)
    r.context.decisions[1].text = edited
    env.ctx.recipes.save(r)
    assert sidecar_writes == ["d2.md"], sidecar_writes
    d2 = _decision(_raw_recipe(env, rid), "d2")
    assert d2["text"].startswith("EDITED HEADLINE.")
    assert "full text in context/d2.md" in d2["text"]
    assert BIG not in d2["text"], "full text leaked inline on a real write"


async def test_missing_sidecar_is_rewritten_not_skipped(env, tier_on,
                                                        sidecar_writes):
    """The guard is fail-safe: it skips only on a CONTENT match. A sidecar that
    vanished under us is re-created, never assumed present."""
    rid = _mk_recipe(env)
    rdir = env.ctx.recipes.root / rid
    r = env.ctx.recipes.load(rid)             # full text in memory
    (rdir / "context" / "d2.md").unlink()
    sidecar_writes.clear()

    env.ctx.recipes.save(r)
    assert "d2.md" in sidecar_writes, "a missing sidecar MUST be rewritten"
    assert (rdir / "context" / "d2.md").read_text(
        encoding="utf-8") == BIG_DECISION


async def test_plan_injected_context_unchanged_save_writes_no_sidecar(
        env, tier_on, sidecar_writes):
    """The guard lives in the write helper, so the PLAN payload path (the
    @file: marker branch, which has no `*_ref` field) gets it for free."""
    _mk_recipe(env)
    sidecar_writes.clear()                      # ignore the recipe's own writes
    pid = _mk_plan(env, actual=EVIDENCE, injected={"d2": BIG_DECISION})
    assert sorted(sidecar_writes) == ["a1-actual.md", "d2.md"], sidecar_writes
    sidecar_writes.clear()

    env.ctx.plans.save(env.ctx.plans.load(pid))
    assert sidecar_writes == [], \
        f"an unchanged plan save must write NO sidecar; wrote {sidecar_writes}"
    p = env.ctx.plans.load(pid)
    assert p.injected_context["d2"] == BIG_DECISION
    assert p.actions[0].acceptance.actual == EVIDENCE


async def test_next_action_is_sidecar_io_free(env, tier_on, monkeypatch,
                                              sidecar_writes):
    """EMPIRICAL (not read-from-the-code) IO-freedom: count ACTUAL sidecar
    writes across N successive next_action calls.

    The fixture starts in PLANNING so call #0 is a real DISPATCH tick: it
    stamps s1 in_progress, trips the `_recipe_sig` guard (_tools.py:773) and
    SAVES. That is the discriminating call — pre-fix it rewrote both sidecars
    (measured: ['d2.md', 'step-s2.md']); post-fix it writes none. Calls #1..N-1
    are the idle steady state, where `_recipe_sig` already suppresses the save.

    `saves` is asserted non-zero on purpose: without it, a future FSM change
    that stopped next_action from saving at all would turn every count below
    into a vacuous zero and this test would guard nothing (d60/B5).
    """
    rid = _mk_recipe(env, state="planning")
    store = env.ctx.recipes
    saves: list[str] = []
    orig_save = store.save
    monkeypatch.setattr(
        store, "save",
        lambda r: (saves.append(r.recipe_id), orig_save(r))[1])
    sidecar_writes.clear()

    n = 5
    counts = []
    for _ in range(n):
        res = await env.call("next_action", handle=rid, handle_type="recipe")
        assert isinstance(res, ToolOk), res
        counts.append(len(sidecar_writes))
        sidecar_writes.clear()

    assert saves, ("next_action never saved — the write-count assertions below "
                   "would be vacuously zero")
    assert counts[0] == 0, \
        f"the dispatching next_action tick wrote sidecars: {counts}"
    assert counts[1:] == [0] * (n - 1), \
        f"next_action is not sidecar-IO-free in steady state: {counts}"


# ── supersede_decision ──────────────────────────────────────────────────────

async def test_supersede_decision_archives_from_index_and_stamp(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="OLD DIRECTION: retrieval-first.",
                       load_bearing=True))
    _ok(await env.call("record_context", kind="decision", recipe_id=rid,
                       text="NEW DIRECTION: meta-reasoning core.",
                       load_bearing=True))
    got = _ok(await env.call("supersede_decision", recipe_id=rid,
                             decision_id="d1", replaced_by="d2",
                             note="d4-style strategy pivot"))
    assert got["status"] == "superseded"

    # context push: index shows only the active decision + superseded count
    from edp_claude.fsm import recipe_context
    ctx = recipe_context(env.ctx.recipes.load(rid))
    assert [x["id"] for x in ctx["active_decisions"]["index"]] == ["d2"]
    assert ctx["active_decisions"]["superseded"] == 1

    # dispatch stamp: only the ACTIVE load-bearing decision reaches a worker
    sid = _ok(await env.call("add_step", recipe_id=rid, description="build",
                             execution="spawn_planner", estimate={"hours": 1}))["step_id"]
    pid = _ok(await env.call("create_plan", recipe_id=rid, step_id=sid,
                             shape="poc-iterate-build", goal="g"))["plan_id"]
    _ok(await env.call("add_action", plan_id=pid, action_id="a1",
                       description="work"))
    await env.call("pool_spawn_worker", plan_id=pid, action_id="a1")
    a = next(a for a in env.ctx.plans.load(pid).actions
             if a.action_id == "a1")
    assert a.injected_context_ids["load_bearing_decisions"] == ["d2"]

    # honest history: the full read still contains the superseded decision
    r = env.ctx.recipes.load(rid)
    d1 = next(d for d in r.context.decisions if d.id == "d1")
    assert d1.status == "superseded" and d1.superseded_by == "d2"
    # events trail records it
    events = (env.ctx.recipes.root / rid / "events.jsonl").read_text(
        encoding="utf-8")
    assert "decision_superseded" in events


async def test_supersede_preconditions(env):
    rid = _ok(await env.call("start_recipe", goal="g",
                             domain="api"))["recipe_id"]
    _ok(await env.call("record_context", kind="decision", recipe_id=rid, text="only one"))
    bad = await env.call("supersede_decision", recipe_id=rid,
                         decision_id="d9")
    assert not isinstance(bad, ToolOk)
    bad2 = await env.call("supersede_decision", recipe_id=rid,
                          decision_id="d1", replaced_by="d9")
    assert not isinstance(bad2, ToolOk)
