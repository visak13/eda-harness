"""S13 (s-461403ebd1, design-e963c656f5 §4.14(b)): the workflow definition, its lint and its store.

- the built-in presets (Standard, Lean, Solo) validate with no error;
- validate names each problem: unreachable status, kind without checker, role without spawner, unknown hook,
  a gate with no precondition;
- a published version is immutable; duplicate makes a draft; publish refuses an invalid draft.
"""
from __future__ import annotations

import pytest

from edp8 import workflow as wf
from edp8.store import Store


def _errors(d) -> set[str]:
    return {p["code"] for p in wf.validate(d) if p["severity"] == "error"}


@pytest.mark.parametrize("build", [wf.build_standard, wf.build_lean, wf.build_solo])
def test_builtin_presets_validate(build):
    d = build()
    assert d.published and d.builtin
    assert _errors(d) == set()


def test_standard_is_built_from_the_old_tables():
    """Standard's source is the constants it replaced: the same edges, creators, authors, checkers, caps."""
    from edp8 import schemas as S
    from edp8.board import CRITERIA_CAP, STORY_CAP, TASK_CAP
    w = wf.Workflow(wf.build_standard())
    for frm, to in S.TRANSITIONS.items():
        assert w.legal(frm.value) == {x.value for x in to}
    for kind, who in S.TICKET_CREATORS.items():
        assert w.creators(kind.value) == {r.value for r in who}
    assert w.criterion_authors == {r.value for r in S.CRITERION_AUTHORS}
    assert w.criterion_checkers == {r.value for r in S.CRITERION_CHECKERS}
    for dt, who in S.DOC_AUTHORS.items():
        assert w.doc_authors(dt.value) == {r.value for r in who}
    assert (w.cap("stories_per_epic"), w.cap("tasks_per_story"), w.cap("criteria_per_story")) == \
        (STORY_CAP, TASK_CAP, CRITERIA_CAP)


def _broken():
    return wf.dump(wf.build_standard()) | {"id": "broken"}


def test_lint_unreachable_status():
    d = _broken()
    d["transitions"] = [t for t in d["transitions"] if t["to"] != "partial"]
    probs = wf.validate(d)
    assert any(p["code"] == "unreachable_status" and "'partial'" in p["message"] for p in probs)


def test_lint_kind_without_checker():
    d = _broken()
    d["checkers"] = [{"when": {"kinds": ["task"]}, "role": "engineer"}]
    probs = wf.validate(d)
    assert {p["message"] for p in probs if p["code"] == "kind_without_checker"} == {
        "kind 'epic' has no checker rule", "kind 'story' has no checker rule"}


def test_lint_role_without_spawner():
    d = _broken()
    for r in d["roles"]:
        r["may_spawn"] = [x for x in r["may_spawn"] if x != "qa"]
    assert any(p["code"] == "role_without_spawner" and "'qa'" in p["message"] for p in wf.validate(d))


def test_lint_unknown_hook_and_param():
    d = _broken()
    d["hooks"]["run_my_script"] = {"on": True, "params": {}}
    d["hooks"]["acceptance_pairs_checker"]["params"]["shell"] = "rm -rf"
    codes = _errors(d)
    assert {"unknown_hook", "hook_param"} <= codes


def test_lint_gate_without_precondition():
    d = _broken()
    d["gates"].append({"id": "budget2", "answerers": ["owner"], "requires": []})
    assert any(p["code"] == "gate_without_precondition" and "'budget2'" in p["message"] for p in wf.validate(d))


def test_lint_unknown_predicate_is_no_code():
    d = _broken()
    d["transitions"][0]["requires"].append({"check": "python:os.system", "params": {}})
    assert "unknown_predicate" in _errors(d)


def test_registry_publish_is_immutable_and_duplicate_makes_a_draft():
    reg = wf.WorkflowRegistry(Store(":memory:"))
    with pytest.raises(wf.WorkflowError) as e:
        reg.save(wf.dump(wf.build_standard()), by="owner")
    assert e.value.code == "immutable"
    d = reg.duplicate("standard@1", new_id="team", by="owner")
    assert (d.id, d.version, d.published) == ("team", 1, False)
    body = wf.dump(d)
    body["caps"]["stories_per_epic"] = 3
    reg.save(body, by="owner")  # a draft may change
    pub = reg.publish("team", 1, by="owner")
    assert pub.published and reg.resolve("team@1").cap("stories_per_epic") == 3
    body["caps"]["stories_per_epic"] = 4
    with pytest.raises(wf.WorkflowError) as e:
        reg.save(body, by="owner")  # PUT on a published version
    assert e.value.code == "immutable"
    nxt = reg.duplicate("team@1", by="owner")
    assert (nxt.id, nxt.version, nxt.published) == ("team", 2, False)
    assert reg.resolve("team@1").cap("stories_per_epic") == 3  # the published version never moved


def test_registry_publish_refuses_an_invalid_draft():
    reg = wf.WorkflowRegistry(Store(":memory:"))
    d = wf.dump(reg.duplicate("standard@1", new_id="bad", by="owner"))
    d["hooks"]["nope"] = {"on": True, "params": {}}
    reg.save(d, by="owner")
    with pytest.raises(wf.WorkflowError) as e:
        reg.publish("bad", 1, by="owner")
    assert e.value.code == "invalid" and any(p["code"] == "unknown_hook" for p in e.value.problems)


def test_pins_migrate_idempotently():
    reg = wf.WorkflowRegistry(Store(":memory:"))
    reg.pin("epic-b", "lean@1")
    assert reg.migrate_pins(["epic-a", "epic-b"]) == 1
    assert reg.migrate_pins(["epic-a", "epic-b"]) == 0
    assert (reg.pin_of("epic-a"), reg.pin_of("epic-b")) == ("standard@1", "lean@1")
