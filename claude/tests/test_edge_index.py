"""Edge-index (graph overlay) tests — v7 WS3 §2.1b/§2.5b. Fixture stores are
raw JSON on a tmp agent home; no model load, no live stack."""

import json

import pytest

from edp_claude.store import edge_index as ei


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A minimal agent home: one recipe (2 outcomes, 3 steps, 1 decision with
    affects), one plan (3 actions with deps/serves/spec)."""
    monkeypatch.delenv("EDP_GRAPH_DB", raising=False)
    rid, pid = "recipe-x", "plan-x-s2"
    rdir = tmp_path / ".recipes" / rid
    rdir.mkdir(parents=True)
    (rdir / "recipe.json").write_text(json.dumps({
        "recipe_id": rid, "state": "executing",
        "comprehension": {"expected_outcomes": [
            {"id": "o1", "met": False}, {"id": "o2", "met": True}]},
        "steps": [
            {"step_id": "s1", "status": "done", "serves": ["o1"]},
            {"step_id": "s2", "status": "in_progress", "serves": ["o1"],
             "depends_on": ["s1"], "plan_ref": pid},
            {"step_id": "s3", "status": "pending"},          # orphan (legacy)
        ],
        "context": {"decisions": [
            {"id": "d12", "status": "active", "affects": ["s2"]},
        ]},
    }), encoding="utf-8")
    pdir = tmp_path / ".plans"
    pdir.mkdir()
    (pdir / f"{pid}.json").write_text(json.dumps({
        "plan_id": pid, "recipe_id": rid, "recipe_step_id": "s2",
        "state": "dispatching",
        "actions": [
            {"action_id": "a1", "status": "done", "serves": ["o1"],
             "spec_ids": ["spec-universal"]},
            {"action_id": "a2", "status": "in_progress",
             "depends_on": ["a1"], "serves": ["o1"]},
            {"action_id": "a3", "status": "pending", "depends_on": ["a2"]},
        ],
    }), encoding="utf-8")
    ei.rebuild(tmp_path)
    return tmp_path


def test_rebuild_counts_and_qualified_ids(home):
    stats = ei.rebuild(home)          # idempotent
    assert stats["nodes"] >= 10 and stats["edges"] >= 10


def test_impacted_by_decision_is_transitive_through_dependents(home):
    got = ei.impacted_by(home, "decision:recipe-x:d12")
    # d12 affects s2; s2's plan-side dependents ride depends_on transitively
    assert "step:recipe-x:s2" in got
    # nothing upstream leaks in
    assert "step:recipe-x:s1" not in got


def test_impacted_by_action_dependents(home):
    got = ei.impacted_by(home, "action:plan-x-s2:a1")
    # a1 serves o1; a2 depends on a1 → impacted; a3 depends on a2 → impacted
    assert "outcome:recipe-x:o1" in got
    assert "action:plan-x-s2:a2" in got
    assert "action:plan-x-s2:a3" in got


def test_neighborhood_selects_not_dumps(home):
    edges = ei.neighborhood(home, "action:plan-x-s2:a2", depth=1)
    nodes = {e[0] for e in edges} | {e[2] for e in edges}
    assert "action:plan-x-s2:a1" in nodes
    # depth-1 must not pull the whole graph
    assert "step:recipe-x:s1" not in nodes


def test_orphan_steps_reports_legacy_unlinked(home):
    assert ei.orphan_steps(home) == ["step:recipe-x:s3"]


def test_test_lineage_refuses_false_security_and_survives_rebuild(home):
    with pytest.raises(ValueError, match="verifies nothing"):
        ei.record_test(home, test_id="t/spa.spec.ts::empty",
                       verifies=[], covers=["src/app.ts"])
    ei.record_test(home, test_id="t/api.spec.ts::auth",
                   verifies=["outcome:recipe-x:o1"], covers=["src/api.ts"])
    ei.rebuild(home)                  # registered lineage must survive
    assert ei.tests_covering(home, ["src/api.ts"]) == ["test:t/api.spec.ts::auth"]
    assert ei.tests_covering(home, ["src/other.ts"]) == []
    assert ei.dead_tests(home) == []


def test_dead_tests_surface_retired_targets(home):
    ei.record_test(home, test_id="t/old.spec.ts::gone",
                   verifies=["outcome:recipe-x:o9"], covers=["src/old.ts"])
    dead = ei.dead_tests(home)
    assert dead == [("test:t/old.spec.ts::gone", "outcome:recipe-x:o9")]
