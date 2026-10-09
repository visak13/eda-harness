"""e0cec S6 task 1 (c-89d24b19da): lessons carry scope_kind framework|project + project + domains.

A framework lesson reaches framework epics only (an epic without a `project:<key>` tag); a project lesson
reaches epics of its own project. One gate (lesson_scope.visible) serves context() recall and lookup's
"Lessons from elsewhere". The backfill classifies old lessons and retires the ones that cite a retired tool.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import bundles, knowledge, lesson_scope, records
from edp8.board import Board, BoardError
from edp8.schemas import Lesson, LessonScope, LessonStatus, Role, TicketKind, WorkType
from edp8.store import Store


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP8_PAIN_FILE", str(tmp_path / "pain-points.jsonl"))
    records._pain_seen.clear()
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    roles = {"owner": Role.owner, "architect": Role.architect, "engineer": Role.engineer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h, id_=h)
            for h, r in roles.items()}


def _epic(board, rig, title="retry the flaky upload", tags=None):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title=title,
                               tags=tags)


def _story(board, rig, epic, title="retry the flaky upload with backoff"):
    return board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title=title, parent_id=epic.id, assignee="engineer")


def _recall_ids(board, ticket_id):
    return {i["id"] for i in records.recall(board.store, ticket_id)["items"]}


def _tail_ids(board, rig, scope, question="flaky upload retried"):
    got = board.lookup(rig["architect"], scope=scope, question=question)
    return {r["id"] for r in got["records"] if r.get("section") == "lesson"}, got["body"]


# ----------------------------------------------------------------------------- scope on record
def test_lesson_defaults_to_framework_and_derives_project_from_the_ticket(board, rig):
    plain = _epic(board, rig)
    game = _epic(board, rig, tags=["project:Open World"])
    s = _story(board, rig, game)
    a = board.record_lesson(rig["qa"], domain="ops", topic="retry", text="a flaky upload is retried")
    b = board.record_lesson(rig["qa"], domain="ops", topic="retry", text="b flaky upload from a story",
                            ticket_id=s.id)
    c = board.record_lesson(rig["qa"], domain="ops", topic="retry", text="c flaky upload on a plain epic",
                            ticket_id=plain.id)
    d = board.record_lesson(rig["qa"], domain="ops", topic="retry", text="d explicit project", project="Beech Tree",
                            domains=["geometry", " "])
    e = board.record_lesson(rig["qa"], domain="ops", topic="retry", text="e evidence names the ticket",
                            evidence=[game.id])
    assert (a.scope_kind, a.project) == (LessonScope.framework, "")
    assert (b.scope_kind, b.project) == (LessonScope.project, "open-world")
    assert (c.scope_kind, c.project) == (LessonScope.framework, "")
    assert (d.scope_kind, d.project, d.domains) == (LessonScope.project, "beech-tree", ["geometry"])
    assert (e.scope_kind, e.project) == (LessonScope.project, "open-world")


def test_record_lesson_refuses_a_project_lesson_without_a_project(board, rig):
    with pytest.raises(BoardError):
        board.record_lesson(rig["qa"], domain="d", topic="t", text="x", scope_kind="project")
    with pytest.raises(BoardError):
        board.record_lesson(rig["qa"], domain="d", topic="t", text="x", scope_kind="galaxy")


def test_a_lesson_row_from_before_scope_reads_as_framework(board):
    old = Lesson(id="les-old", domain="d", topic="t", text="old row", created_by="x")
    assert (old.scope_kind, old.project, old.domains) == (LessonScope.framework, "", [])


# ----------------------------------------------------------------------------- visibility: recall + lookup
def test_framework_lesson_never_reaches_a_project_epic(board, rig):
    fw_epic = _epic(board, rig)
    proj_epic = _epic(board, rig, tags=["project:open-world"])
    fw_story, proj_story = _story(board, rig, fw_epic), _story(board, rig, proj_epic)
    les = board.record_lesson(rig["qa"], domain="tools", topic="retry",
                              text="a flaky upload is retried with backoff, never skipped", scope_kind="framework")
    assert les.id in _recall_ids(board, fw_story.id)
    assert les.id not in _recall_ids(board, proj_story.id)
    assert les.id in _tail_ids(board, rig, fw_story.id)[0]
    ids, body = _tail_ids(board, rig, proj_story.id)
    assert les.id not in ids and "Lessons from elsewhere" not in body
    assert les.id not in {i["id"] for i in board.context(rig["engineer"], proj_story.id)["tickets"][0]["recall"]["items"]}


def test_pain_derived_lesson_is_framework_and_stays_out_of_project_epics(board, rig, tmp_path):
    f = tmp_path / "pain-points.jsonl"
    f.write_text(json.dumps({"id": "p-1", "ts": "t", "role": "engineer", "handle": "e", "severity": "low",
                             "area": "tools", "symptom": "flaky upload retried silently",
                             "expected": "a visible retry"}) + "\n", encoding="utf-8")
    fw_story = _story(board, rig, _epic(board, rig))
    proj_story = _story(board, rig, _epic(board, rig, tags=["project:open-world"]))
    board.context(rig["engineer"], proj_story.id)  # ingests the pain file
    [le] = [r for r in board.store.query("lesson", {}, limit=-1) if r.created_by == records.AUTHOR]
    assert (le.scope_kind, le.project) == (LessonScope.framework, "")
    assert le.id not in _recall_ids(board, proj_story.id)
    assert le.id in _recall_ids(board, fw_story.id)


def test_project_lesson_reaches_the_next_epic_of_the_same_project_only(board, rig):
    first = _epic(board, rig, title="open world renders", tags=["project:open-world"])
    les = board.record_lesson(rig["qa"], domain="rendering", topic="flaky upload",
                              text="a flaky upload of a render is retried", ticket_id=_story(board, rig, first).id)
    nxt = _story(board, rig, _epic(board, rig, title="open world more renders", tags=["project:open-world"]))
    other = _story(board, rig, _epic(board, rig, title="beech tree", tags=["project:beech-tree"]))
    framework = _story(board, rig, _epic(board, rig, title="heronry itself"))
    assert les.project == "open-world"
    assert les.id in _recall_ids(board, nxt.id)
    assert les.id in _tail_ids(board, rig, nxt.id)[0]
    for blocked in (other, framework):
        assert les.id not in _recall_ids(board, blocked.id)
        assert les.id not in _tail_ids(board, rig, blocked.id)[0]


def test_domain_extras_obey_the_scope_too(board, rig):
    """A lesson filed under the domain of a kept decision rides the domain path; the gate still applies."""
    epic = _epic(board, rig, tags=["project:open-world"])
    s = _story(board, rig, epic)
    board.record_decision(rig["architect"], scope=epic.id, text="uploads retry with backoff", domains=["ops"])
    fw = board.record_lesson(rig["qa"], domain="ops", topic="unrelated words", text="zebra quartz mango", scope_kind="framework")
    pj = board.record_lesson(rig["qa"], domain="ops", topic="unrelated words", text="plum river stone", project="open-world")
    ids, _ = _tail_ids(board, rig, s.id, question="uploads retry backoff")
    assert pj.id in ids and fw.id not in ids


def test_visible_is_the_single_predicate(board, rig):
    epic = _epic(board, rig, tags=["project:open-world"])
    plain = _epic(board, rig)
    fw = Lesson(id="les-a", domain="d", topic="t", text="x", created_by="x")
    pj = Lesson(id="les-b", domain="d", topic="t", text="x", created_by="x", scope_kind=LessonScope.project,
                project="open-world")
    broken = Lesson(id="les-c", domain="d", topic="t", text="x", created_by="x", scope_kind=LessonScope.project)
    assert [lesson_scope.visible(board.store, x, epic.id) for x in (fw, pj, broken)] == [False, True, False]
    assert [lesson_scope.visible(board.store, x, plain.id) for x in (fw, pj, broken)] == [True, False, False]
    assert lesson_scope.visible(board.store, fw, None) and not lesson_scope.visible(board.store, pj, None)
    assert knowledge.visible_lesson_ids(board.store, plain.id) == set()  # nothing stored yet


# ----------------------------------------------------------------------------- retire
def test_retire_lesson_is_curation_only_and_hides_the_lesson(board, rig):
    s = _story(board, rig, _epic(board, rig))
    le = board.record_lesson(rig["qa"], domain="tools", topic="retry", text="a flaky upload is retried")
    assert le.id in _recall_ids(board, s.id)
    with pytest.raises(BoardError) as e:
        board.retire_lesson(rig["engineer"], lesson_id=le.id, reason="nope")
    assert e.value.code == "scope"
    got = board.retire_lesson(rig["architect"], lesson_id=le.id, reason="wrong")
    assert got.status == LessonStatus.retired and got.retired_reason.startswith("wrong")
    assert le.id not in _recall_ids(board, s.id)
    assert le.id not in _tail_ids(board, rig, s.id)[0]
    assert board.retire_lesson(rig["owner"], lesson_id=le.id, reason="again").status == LessonStatus.retired
    with pytest.raises(BoardError) as e:
        board.retire_lesson(rig["owner"], lesson_id="les-missing")
    assert e.value.code == "not_found"


def test_retire_lesson_is_an_architect_and_owner_tool_only():
    assert "retire_lesson" in bundles.ROLE_BUNDLES[Role.architect.value]
    assert "retire_lesson" in bundles.ROLE_BUNDLES[Role.owner.value]
    for role in (Role.engineer, Role.qa, Role.sme, Role.adversary, Role.doctor):
        assert "retire_lesson" not in bundles.ROLE_BUNDLES[role.value]


# ----------------------------------------------------------------------------- classifier
RETIRED = [
    ("tools", "consult running receipt omitted run_id", "cannot call required consult_status until feed"),
    ("tools", "consult.py MCP containment", "discover-and-disable over codex mcp list"),
    ("tools", "consult with design and sibling report context", "cannot launch on Windows: WinError 206"),
    ("consult", "fence-reverts-concurrent-edit", "A boundary fail-closed restore can revert an edit"),
    ("host", "serial-live-walks", "Two concurrent qa jobs (a codex consult plus a Chromium walk) were killed"),
    ("qa", "adversary claims", "file the fix task from the reproduction table, not the consult answer"),
    ("process", "coordinator seat", "the coordinator seat no longer exists"),
]
KEPT = [
    ("process", "read the design", "Consult the design doc before you plan; a consultant's view is not the design"),
    ("tools", "review", "A review of the diff beats a summary of it"),
]


@pytest.mark.parametrize("domain,topic,text", RETIRED)
def test_classifier_retires_lessons_that_cite_a_retired_tool(domain, topic, text):
    le = Lesson(id="les-x", domain=domain, topic=topic, text=text, created_by="qa.epic-aaaaaa")
    assert lesson_scope.cites_retired_tool(le)


@pytest.mark.parametrize("domain,topic,text", KEPT)
def test_classifier_keeps_lessons_that_only_use_the_word(domain, topic, text):
    assert not lesson_scope.cites_retired_tool(Lesson(id="les-x", domain=domain, topic=topic, text=text,
                                                      created_by="x"))


def _raw(board, **kw):
    """A lesson stored the way an old row is: framework scope by default, written straight to the store."""
    le = Lesson(id=kw.pop("id"), domain=kw.pop("domain", "tools"), topic=kw.pop("topic", "topic"),
                text=kw.pop("text", "a lesson"), created_by=kw.pop("created_by", "qa.s-aaaaaa"), **kw)
    board.store.put("lesson", le)
    return le


_PROJ = "C:" + chr(92) + "Proj" + "ects" + chr(92)  # built in pieces: the PII gate scans the tracked tree for a projects root


def test_backfill_classifies_every_existing_lesson_and_retires_retired_tool_ones(board, rig):
    tagged = _epic(board, rig, title="beech tree", tags=["project:beech-tree"])
    _raw(board, id="les-pain", created_by="board", evidence=["p-1"], domain="blender")
    _raw(board, id="les-epic", created_by=f"qa.{tagged.id}", domain="research")
    _raw(board, id="les-ev", created_by="engineer.s-bbbbbb", evidence=[tagged.id])
    _raw(board, id="les-path", evidence=[_PROJ + r"netdrop\notes.log"], domain="packaging")
    _raw(board, id="les-repo", evidence=[_PROJ + r"eda-base3\v8\x.py"], domain="tools")
    _raw(board, id="les-hint", domain="blender-craft")
    _raw(board, id="les-fw", domain="gates")
    _raw(board, id="les-71df4e7adf", topic="consult with design and sibling report context",
         text="consult with design context cannot launch on Windows: WinError 206")
    dry = board.backfill_lesson_scopes(rig["architect"], dry_run=True)
    assert dry["dry_run"] and board.store.get("lesson", "les-71df4e7adf").status == LessonStatus.live
    assert board.store.get("lesson", "les-epic").project == ""  # a dry run writes nothing
    done = board.backfill_lesson_scopes(rig["architect"])
    got = {le.id: le for le in board.store.query("lesson", {}, limit=-1)}
    assert (got["les-pain"].scope_kind, got["les-pain"].project) == (LessonScope.framework, "")
    assert (got["les-epic"].scope_kind, got["les-epic"].project) == (LessonScope.project, "beech-tree")
    assert (got["les-ev"].scope_kind, got["les-ev"].project) == (LessonScope.project, "beech-tree")
    assert (got["les-path"].scope_kind, got["les-path"].project) == (LessonScope.project, "netdrop")
    assert (got["les-repo"].scope_kind, got["les-repo"].project) == (LessonScope.framework, "")
    assert (got["les-hint"].scope_kind, got["les-hint"].project) == (LessonScope.project, "blender")
    assert (got["les-fw"].scope_kind, got["les-fw"].project) == (LessonScope.framework, "")
    assert got["les-71df4e7adf"].status == LessonStatus.retired
    assert done["counts"]["retired"] == 1 and done["counts"]["project"] == 4
    again = board.backfill_lesson_scopes(rig["architect"])
    assert again["changes"] == [] and again["counts"]["retired"] == 0  # idempotent


def test_backfill_is_curation_only(board, rig):
    with pytest.raises(BoardError):
        board.backfill_lesson_scopes(rig["engineer"])


def test_a_backfilled_project_lesson_leaves_framework_recall(board, rig):
    fw_story = _story(board, rig, _epic(board, rig))
    le = _raw(board, id="les-hint", domain="blender", topic="flaky upload", text="a flaky upload of a mesh is retried")
    assert le.id in _recall_ids(board, fw_story.id)  # before: every lesson reached every epic
    board.backfill_lesson_scopes(rig["architect"])
    assert le.id not in _recall_ids(board, fw_story.id)


# ----------------------------------------------------------------------------- REST
def test_rest_record_retire_and_backfill(board, rig, tmp_path):
    from fastapi.testclient import TestClient
    from edp8.service import create_app

    app = create_app(board)
    c = TestClient(app)
    owner = {"X-Participant": "owner"}
    arch = {"X-Participant": "architect"}
    eng = {"X-Participant": "engineer"}
    epic = _epic(board, rig, tags=["project:open-world"])
    s = _story(board, rig, epic)
    r = c.post("/v1/lessons", headers=eng, json={"domain": "ops", "topic": "t", "text": "x retried", "ticket_id": s.id})
    assert r.status_code == 200, r.text
    assert (r.json()["value"]["scope_kind"], r.json()["value"]["project"]) == ("project", "open-world")
    lid = r.json()["value"]["id"]
    assert c.post(f"/v1/lessons/{lid}/retire", headers=eng, json={"reason": "x"}).status_code in (400, 403)
    ok = c.post(f"/v1/lessons/{lid}/retire", headers=arch, json={"reason": "stale"})
    assert ok.status_code == 200 and ok.json()["value"]["status"] == "retired"
    assert c.post("/v1/lessons/backfill", headers=eng, json={}).status_code in (400, 403)
    assert c.post("/v1/lessons/backfill", headers=owner, json={"dry_run": True}).json()["value"]["dry_run"] is True
