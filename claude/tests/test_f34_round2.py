"""F34 (2026-08-18) — campaign Round 2 (memory & state layer) fixes.

#1  StoreConflict: concurrent load-modify-save loses no update silently.
#2  rollup crash idempotence: a re-run after a crash between segment
    write and hot rewrite reuses the segment instead of double-archiving.
#3/#4 CAS sidecars: an edit publishes NEW bytes under a NEW name; the
    snapshot's ref keeps hydrating the OLD content.
#5  gate-load-bearing kinds are pinned through rollup.
#8  the jsonl follower survives a rollup truncation (no deafness).
#10 write_doc drains the accepted-amendment overlay.
#13 neuron store: archived is terminal; touch increments atomically.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from edp_claude.schemas import Recipe
from edp_claude.server import make_context
from edp_claude.store.ipc_lock import StoreConflict
from edp_claude.store.recipe_store import rollup_events
from edp_claude.store.atomic import append_jsonl, read_jsonl


def _now():
    return datetime.now(timezone.utc)


def _recipe(rid="r-f34", state="executing"):
    return Recipe.model_validate(dict(
        recipe_id=rid, user_goal_verbatim="g", domain="generic",
        state=state,
        comprehension={"branches": [], "expected_outcomes": [
            {"id": "o1", "description": "d", "verification": "v"}]},
        steps=[{"step_id": "s1", "kind": "k", "description": "d",
                "status": "in_progress", "depends_on": [],
                "execution": "inline"}],
        context={},
        created_at=_now(), updated_at=_now()))


# ── #1 optimistic concurrency ───────────────────────────────────────────────

def test_stale_save_raises_store_conflict(tmp_path):
    ctx = make_context(tmp_path)
    ctx.recipes.save(_recipe())
    a = ctx.recipes.load("r-f34")
    b = ctx.recipes.load("r-f34")
    b.state = "reviewing"
    ctx.recipes.save(b)                      # first writer wins
    a.state = "planning"
    with pytest.raises(StoreConflict):
        ctx.recipes.save(a)                  # stale writer conflicts loudly
    assert ctx.recipes.load("r-f34").state == "reviewing"


def test_fresh_object_overwrite_adopts_disk_version(tmp_path):
    ctx = make_context(tmp_path)
    ctx.recipes.save(_recipe())
    ctx.recipes.save(ctx.recipes.load("r-f34"))       # disk version grows
    v_disk = ctx.recipes.load("r-f34").version
    # a hand-constructed object (version==1, the record_recipe escape
    # hatch / test flows) still overwrites — adopting the disk version.
    ctx.recipes.save(_recipe(state="reviewing"))
    r = ctx.recipes.load("r-f34")
    assert r.state == "reviewing" and r.version == v_disk + 1


# ── #2 rollup crash idempotence ────────────────────────────────────────────

def test_rollup_crash_rerun_does_not_double_archive(tmp_path):
    rdir = tmp_path / "r"
    rdir.mkdir()
    for i in range(30):
        append_jsonl(rdir / "events.jsonl", {"kind": "k", "i": i})
    out1 = rollup_events(rdir, threshold=30, tail_keep=5)
    assert out1 and out1["segment"] == 1
    # simulate the crash: restore the PRE-rollup hot file (segment already
    # written) and run again — the head must not archive twice.
    seg = read_jsonl(rdir / "events.0001.jsonl")
    tail = read_jsonl(rdir / "events.jsonl")
    full = seg + tail
    (rdir / "events.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in full), encoding="utf-8")
    out2 = rollup_events(rdir, threshold=30, tail_keep=5)
    assert out2 and out2.get("resumed_crash") is True
    assert not (rdir / "events.0002.jsonl").exists()
    assert len(read_jsonl(rdir / "events.jsonl")) == 5


# ── #5 pinned gate kinds ───────────────────────────────────────────────────

def test_gate_kinds_survive_rollup(tmp_path):
    rdir = tmp_path / "r"
    rdir.mkdir()
    append_jsonl(rdir / "events.jsonl",
                 {"kind": "acceptance_verdict",
                  "body": {"verdict": "pass"}})
    append_jsonl(rdir / "events.jsonl",
                 {"kind": "user_gate_answer", "gate_target": "G-SKIP:x:y"})
    for i in range(40):
        append_jsonl(rdir / "events.jsonl", {"kind": "noise", "i": i})
    out = rollup_events(rdir, threshold=40, tail_keep=5)
    assert out is not None
    hot_kinds = [r["kind"] for r in read_jsonl(rdir / "events.jsonl")]
    assert "acceptance_verdict" in hot_kinds
    assert "user_gate_answer" in hot_kinds


def test_grounding_echo_pinned_in_plan_worklog(tmp_path):
    rdir = tmp_path / "p"
    rdir.mkdir()
    append_jsonl(rdir / "worklog.jsonl",
                 {"kind": "message_sent", "msg_kind": "grounding",
                  "from_handle": "p:a1"})
    for i in range(40):
        append_jsonl(rdir / "worklog.jsonl", {"kind": "noise", "i": i})
    out = rollup_events(rdir, threshold=40, tail_keep=5,
                        filename="worklog.jsonl")
    assert out is not None
    hot = read_jsonl(rdir / "worklog.jsonl")
    assert any(r.get("msg_kind") == "grounding" for r in hot)


# ── #3/#4 CAS sidecars: snapshots stop lying ───────────────────────────────

def test_snapshot_ref_survives_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_TIER_WRITE", "1")
    ctx = make_context(tmp_path)
    big_old = "OLD DIRECTION. " + ("x " * 600)
    big_new = "NEW DIRECTION. " + ("y " * 600)
    r = _recipe()
    r.context.decisions = []
    ctx.recipes.save(r)
    from edp_claude.schemas.recipe import Decision
    r = ctx.recipes.load("r-f34")
    r.context.decisions.append(Decision.model_validate(
        {"id": "d1", "text": big_old, "rationale": "r",
         "by": "neuron", "at": _now().isoformat()}))
    ctx.recipes.save(r)
    raw1 = json.loads(
        (tmp_path / ".recipes" / "r-f34" / "recipe.json")
        .read_text(encoding="utf-8"))
    ref_old = raw1["context"]["decisions"][0]["text_ref"]
    # edit → new CAS file; the OLD ref's bytes are untouched
    r = ctx.recipes.load("r-f34")
    r.context.decisions[0].text = big_new
    ctx.recipes.save(r)
    raw2 = json.loads(
        (tmp_path / ".recipes" / "r-f34" / "recipe.json")
        .read_text(encoding="utf-8"))
    ref_new = raw2["context"]["decisions"][0]["text_ref"]
    assert ref_new != ref_old
    rdir = tmp_path / ".recipes" / "r-f34"
    assert (rdir / ref_old).read_text(encoding="utf-8") == big_old
    assert (rdir / ref_new).read_text(encoding="utf-8") == big_new


# ── #8 follower survives truncation ────────────────────────────────────────

def test_tail_follower_detects_truncation(tmp_path):
    from edp_claude.reactive.driver import _tail_jsonl
    path = tmp_path / "events.jsonl"
    # a long pre-existing file the follower starts at EOF of
    for i in range(200):
        append_jsonl(path, {"kind": "old", "i": i})
    seen: list[dict] = []

    class Obs:
        def on_next(self, rec):
            seen.append(rec)

    stop = threading.Event()
    t = threading.Thread(target=_tail_jsonl,
                         args=(path, Obs(), stop, 30), daemon=True)
    t.start()
    time.sleep(0.3)
    # rollup-style truncation: rewrite to a SHORT tail, then append news
    path.write_text("", encoding="utf-8")
    time.sleep(0.1)
    append_jsonl(path, {"kind": "blocker", "msg": "after-rollup"})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(r.get("kind") == "blocker" for r in seen):
            break
        time.sleep(0.05)
    stop.set()
    t.join(timeout=2)
    assert any(r.get("kind") == "blocker" for r in seen), (
        "follower went deaf after truncation")


# ── #10 recompile drains the overlay ───────────────────────────────────────

def test_write_doc_drains_promoted_overlay(tmp_path):
    ctx = make_context(tmp_path)
    store = ctx.specs
    sid = "spec-f34"
    store.write_doc(sid, "# base doc\nrule one\n")
    lid = store.append_proposed_learning(sid, rule_text="NEVER frobnicate")
    store.append_learning(sid, {
        "learning_id": lid, "rule_text": "NEVER frobnicate",
        "tag": "[expected]", "overrides": None, "source": None,
        "status": "promoted"})
    assert "Field amendments" in store.read_doc(sid, with_overlay=True)
    # the SME recompiles (folding the rule in) → overlay drains
    store.write_doc(sid, "# base doc v2\nrule one\nNEVER frobnicate\n")
    out = store.read_doc(sid, with_overlay=True)
    assert "Field amendments" not in out
    assert store.accepted_pending_learnings(sid) == []


# ── #13 neuron store ───────────────────────────────────────────────────────

def test_archived_neuron_is_not_resurrected(tmp_path):
    ctx = make_context(tmp_path)
    from edp_claude.store.neuron_store import NeuronRecord
    ctx.neurons.create(NeuronRecord(
        neuron_id="n1", name="N", description="d", category="domain",
        status="stable", created_at=_now(), updated_at=_now()))
    ctx.neurons.set_status("n1", "archived")
    # a stale writer tries to flip it back — conditional UPDATE holds
    got = ctx.neurons.set_status("n1", "pending_review")
    assert got.status == "archived"
    # the explicit escape works
    got2 = ctx.neurons.set_status("n1", "stable", force=True)
    assert got2.status == "stable"


def test_touch_increments_atomically(tmp_path):
    ctx = make_context(tmp_path)
    from edp_claude.store.neuron_store import NeuronRecord
    ctx.neurons.create(NeuronRecord(
        neuron_id="n2", name="N", description="d", category="domain",
        status="stable", created_at=_now(), updated_at=_now()))
    for _ in range(3):
        ctx.neurons.touch("n2")
    assert ctx.neurons.get("n2").use_count == 3
