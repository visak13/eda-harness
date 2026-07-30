"""W3 automated spec flowback — SpecStore primitives (DESIGN-v6 §W3).

Pure-store unit tests for the four store-side deliverables the a2 _tools.py
wiring calls: (1) the structured append-proposed helper, (2) the accepted-
pending query, (3) read_doc(with_overlay=True) overlay compose (incl. the
overrides supersede annotation), and (4) the resolve_spec_learnings accept-
folds-into-entries path. Store-only (no MCP env) so they are fast +
deterministic; conftest's autouse fixture clears EDP_ROLE/EDP_HANDLE (d7/d8).
"""

from datetime import datetime, timezone

from edp_claude.schemas import Specialization
from edp_claude.store.spec_store import SpecStore


def _store(tmp_path):
    return SpecStore(tmp_path / "specs")


def _seed(store, spec_id="spec-x"):
    now = datetime(2026, 7, 8, tzinfo=timezone.utc)
    store.save(Specialization(
        spec_id=spec_id, neuron_id="n-x", name="X", subject="x",
        created_at=now, updated_at=now,
    ))
    return spec_id


# ── (1) append-proposed structured record + legacy still parses ─────────────
def test_append_proposed_structured_record(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    lid = store.append_proposed_learning(
        sid, rule_text="content is raw, never serialized", tag="[required]",
        overrides="SERIALIZE THE CONTENT",
        source={"recipe_id": "r1", "action_id": "a1"})
    assert lid.startswith("learn-")
    rows = store.read_learnings(sid, status="proposed")
    assert len(rows) == 1
    rec = rows[0]
    assert rec["learning_id"] == lid
    assert rec["rule_text"] == "content is raw, never serialized"
    assert rec["tag"] == "[required]"
    assert rec["overrides"] == "SERIALIZE THE CONTENT"
    assert rec["source"] == {"recipe_id": "r1", "action_id": "a1"}
    assert rec["status"] == "proposed"


def test_legacy_freetext_still_parses(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    # a legacy loose record (no learning_id) coexists with a structured one
    store.append_learning(sid, {"note": "free text only"})
    store.append_proposed_learning(sid, rule_text="new structured", tag="[hint]")
    allrows = store.read_learnings(sid)
    assert any(r.get("note") == "free text only" for r in allrows)
    assert any(r.get("rule_text") == "new structured" for r in allrows)


# ── (2) accepted-pending query ──────────────────────────────────────────────
def test_accepted_pending_query_reflects_promotion(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    l1 = store.append_proposed_learning(sid, rule_text="rule one", tag="[expected]")
    l2 = store.append_proposed_learning(sid, rule_text="rule two", tag="[required]")
    assert store.accepted_pending_learnings(sid) == []       # nothing accepted
    store.resolve_spec_learnings(sid, accept=[l1], reject=[l2])
    pend = store.accepted_pending_learnings(sid)
    assert [p["learning_id"] for p in pend] == [l1]
    assert pend[0]["rule_text"] == "rule one"                # content carried fwd
    assert pend[0]["tag"] == "[expected]"
    # accept + reject both drained the proposed queue (last-write-wins)
    assert store.read_learnings(sid, status="proposed") == []


# ── (4) accept folds into entries + bumps version; reject does neither ──────
def test_accept_folds_into_entries_and_bumps_version(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    v0 = store.load(sid).version
    l1 = store.append_proposed_learning(sid, rule_text="always pin deps",
                                        tag="[required]")
    res = store.resolve_spec_learnings(sid, accept=[l1])
    spec = store.load(sid)
    assert res["accepted"] == [l1] and res["rejected"] == []
    assert res["version"] == spec.version == v0 + 1          # exactly one bump
    assert [e.text for e in spec.entries] == ["always pin deps"]
    assert spec.entries[0].adherence == "required"          # tag -> adherence


def test_reject_only_does_not_bump_version(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    v0 = store.load(sid).version
    l1 = store.append_proposed_learning(sid, rule_text="stale", tag="[hint]")
    res = store.resolve_spec_learnings(sid, reject=[l1])
    assert res["rejected"] == [l1] and res["accepted"] == []
    assert res["version"] == v0                              # no accept, no bump
    assert store.load(sid).version == v0
    assert store.load(sid).entries == []
    assert store.read_learnings(sid, status="proposed") == []


# ── (3) read_doc overlay compose ────────────────────────────────────────────
def test_read_doc_default_is_unchanged(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    store.write_doc(sid, "# Spec X\n\nbody\n")
    # a proposed-but-unaccepted learning never touches the live read path
    store.append_proposed_learning(sid, rule_text="proposed only", tag="[required]")
    assert store.read_doc(sid) == "# Spec X\n\nbody\n"
    assert "Field amendments" not in store.read_doc(sid)


def test_read_doc_overlay_compose_and_supersede(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    store.write_doc(sid, "# Spec X\n\nRule A: SERIALIZE THE CONTENT always.\n")
    l1 = store.append_proposed_learning(
        sid, rule_text="content is RAW, never serialized", tag="[required]",
        overrides="SERIALIZE THE CONTENT")
    store.resolve_spec_learnings(sid, accept=[l1])
    overlaid = store.read_doc(sid, with_overlay=True)
    assert "## Field amendments (accepted, pending recompile)" in overlaid
    assert "**amendments override any contradicting rule above**" in overlaid
    assert "- L1 [required] content is RAW, never serialized" in overlaid
    # the matched base fragment is annotated IN PLACE
    assert "> SUPERSEDED by amendment L1: SERIALIZE THE CONTENT" in overlaid


def test_read_doc_overlay_unmatched_override_still_lists(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    store.write_doc(sid, "# Spec X\n\nNo matching fragment here.\n")
    l1 = store.append_proposed_learning(
        sid, rule_text="new rule", tag="[expected]",
        overrides="THIS FRAGMENT IS ABSENT")
    store.resolve_spec_learnings(sid, accept=[l1])
    overlaid = store.read_doc(sid, with_overlay=True)
    assert "- L1 [expected] new rule" in overlaid
    assert "SUPERSEDED" not in overlaid                      # unmatched -> no note


def test_read_doc_overlay_no_doc_and_no_pending(tmp_path):
    store = _store(tmp_path)
    sid = _seed(store)
    assert store.read_doc(sid, with_overlay=True) is None    # no doc -> None
    store.write_doc(sid, "# Spec X\n")
    # doc but no accepted-pending -> base unchanged, no empty section appended
    assert store.read_doc(sid, with_overlay=True) == "# Spec X\n"


def test_legacy_promoted_learning_renders_summary(tmp_path):
    """Migration: a legacy proposed record (text/kind/adherence, no rule_text)
    accepted through the new path renders rule_text=<its summary> in the overlay
    AND folds into entries with the mapped kind + adherence."""
    store = _store(tmp_path)
    sid = _seed(store)
    store.write_doc(sid, "# Spec X\n")
    store.append_learning(sid, {
        "learning_id": "learn-legacy1", "status": "proposed",
        "kind": "anti_pattern", "text": "never useEffect-as-fetch",
        "adherence": "required"})
    store.resolve_spec_learnings(sid, accept=["learn-legacy1"])
    spec = store.load(sid)
    assert spec.entries[-1].text == "never useEffect-as-fetch"
    assert spec.entries[-1].kind == "anti_pattern"           # legacy kind reused
    assert spec.entries[-1].adherence == "required"          # adherence -> tag -> adherence
    overlaid = store.read_doc(sid, with_overlay=True)
    assert "- L1 [required] never useEffect-as-fetch" in overlaid
