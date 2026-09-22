"""edp8.exam — the repeatable recall-exam harness (steer m-3f96079aa8 item 1)."""

import json

import pytest

from edp8 import exam


def _pack(ids, body, history=()):
    recs = [{"id": i, "type": "decision"} for i in ids]
    if history:
        recs[0]["history"] = [{"id": h} for h in history]
    return {"ok": True, "value": {"records": recs, "body": body,
                                  "receipt": {"bytes": len(body), "seed_kind": "fts+dense", "source_excerpts": 0}}}


def test_load_exam_accepts_list_and_wrapper(tmp_path):
    p = tmp_path / "e.json"
    p.write_text(json.dumps({"questions": [{"epic": "epic-a", "question": "q1"}]}))
    qs = exam.load_exam(p)
    assert qs == [{"n": 1, "epic": "epic-a", "question": "q1", "expected": "", "expected_ids": [], "proof_ids": []}]
    p.write_text(json.dumps([{"n": 7, "epic": "epic-a", "question": "q"}, {"n": 7, "epic": "e", "question": "q"}]))
    with pytest.raises(ValueError, match="duplicate"):
        exam.load_exam(p)
    p.write_text(json.dumps([{"question": "no epic"}]))
    with pytest.raises(ValueError, match="epic"):
        exam.load_exam(p)


def test_signals_find_ids_in_records_and_history():
    q = {"expected": "Usage widget sits above Find", "expected_ids": ["dec-1", "dec-old", "dec-x"]}
    sig = exam.pack_signals(q, _pack(["dec-1"], "the usage widget sits above find", history=["dec-old"])["value"])
    assert sig["expected_ids_found"] == ["dec-1", "dec-old"]
    assert sig["expected_ids_missing"] == ["dec-x"]
    assert sig["id_recall"] == pytest.approx(2 / 3)
    assert sig["term_coverage"] == 1.0  # usage, widget, sits, above, find


def test_run_packs_writes_reader_inputs_and_template(tmp_path):
    qs = [{"n": 1, "epic": "epic-a", "question": "where is usage?", "expected": "above find", "expected_ids": ["dec-1"]},
          {"n": 2, "epic": "epic-b", "question": "boom", "expected": "", "expected_ids": []}]
    calls = []

    def fake_lookup(scope, question):
        calls.append((scope, question))
        if scope == "epic-b":
            return {"ok": False, "error": {"code": "not_found"}}
        return _pack(["dec-1"], "DECISION: usage above find")

    m = exam.run_packs(qs, tmp_path, lookup=fake_lookup, rev="abc123")
    assert calls == [("epic-a", "where is usage?"), ("epic-b", "boom")]
    assert m["board_rev"] == "abc123"
    assert m["summary"]["failed_lookups"] == 1 and m["summary"]["mean_id_recall"] == 1.0
    md = (tmp_path / "packs" / "1.md").read_text(encoding="utf-8")
    assert "where is usage?" in md and "usage above find" in md
    assert "lookup failed" in (tmp_path / "packs" / "2.md").read_text(encoding="utf-8")
    grading = json.loads((tmp_path / "grading.json").read_text())
    assert [g["verdict"] for g in grading] == ["", ""]
    assert (tmp_path / "reader_prompt.md").exists()


def test_score_totals_and_baseline_changes():
    graded = [{"n": 1, "epic": "a", "verdict": "right"}, {"n": 2, "epic": "a", "verdict": "half"},
              {"n": 3, "epic": "b", "verdict": "miss"}, {"n": 4, "epic": "b", "verdict": ""}]
    base = [{"n": 1, "verdict": "miss"}, {"n": 2, "verdict": "half"}, {"n": 3, "verdict": "right"}]
    r = exam.score(graded, base)
    assert r["overall"]["graded"] == 3 and r["overall"]["points"] == 1.5 and r["overall"]["pct"] == 50.0
    assert r["by_epic"]["a"]["pct"] == 75.0 and r["by_epic"]["b"]["miss"] == 1
    assert r["ungraded"] == [4]
    assert r["changes"] == [{"n": 1, "was": "miss", "now": "right"}, {"n": 3, "was": "right", "now": "miss"}]


def test_lookup_goes_through_the_tool_layer(monkeypatch):
    seen = {}

    class FakeClient:
        def lookup(self, scope, question=None, id=None, path=None):
            seen["args"] = (scope, question)
            return _pack(["dec-9"], "x")

    from edp8 import bundles
    monkeypatch.setattr(bundles, "_client", FakeClient())
    env = exam._lookup_via_tools("epic-z", "why?")
    assert env["ok"] and seen["args"] == ("epic-z", "why?")


def test_architect_exam_format_and_grade_aliases(tmp_path):
    p = tmp_path / "exam4.json"
    p.write_text(json.dumps([{"n": 1, "epic": "e", "type": "why", "question": "q", "answer": "two positions",
                              "proof_ids": ["m-1", "m-2"], "superseded_note": ""}]))
    q = exam.load_exam(p)[0]
    assert q["expected"] == "two positions" and q["proof_ids"] == ["m-1", "m-2"]
    value = {"records": [{"id": "dec-1", "source": "m-1"}], "body": "two positions", "receipt": {}}
    sig = exam.pack_signals(q, value)
    assert sig["proof_ids_found"] == ["m-1"] and sig["proof_recall"] == 0.5
    r = exam.score([{"n": 1, "epic": "e", "verdict": "CORRECT"}, {"n": 2, "epic": "e", "verdict": "NOT-IN-PACK"},
                    {"n": 3, "epic": "e", "verdict": "PARTIAL"}, {"n": 4, "epic": "e", "verdict": "WRONG"}])
    assert r["overall"] == {"graded": 4, "points": 1.5, "pct": 37.5, "right": 1, "half": 1, "miss": 1, "invented": 1}
