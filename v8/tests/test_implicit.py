"""S-IMPLICIT (s-b461950144, design-34bf11cc07 §4.5, owner m-5b3db5cb0d "recursive self-improvement
needs to be implicit"): the board reads and records by itself.

  c-530bb59136 read   — context(ticket) and assemble_ruleset carry a capped `recall` section
  c-1e8f2edd8e record — verdict+note → claim, accepted deviation → decision, gate answer → decision,
                        pain filed → lesson; dedup by text, per-epic cap, withdraw as undo
  c-a9984af463 link   — design_signoff / quick-task create link tagged Library docs + one note
Board + Store(':memory:') directly; the REST/MCP halves go through the TestClient.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8 import records
from edp8.board import Board
from edp8.schemas import (Check, ClaimBasis, DecisionStatus, DocStatus, DocType, Gate, MessageKind, Relation,
                          Role, TicketKind, TicketStatus, Verdict, WorkType)
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


def _epic(board, rig, tags=None):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature,
                               title="retry the flaky upload", tags=tags)


def _story(board, rig, epic, title="retry the flaky upload with backoff"):
    return board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title=title, parent_id=epic.id, assignee="engineer")


def _signed_off_epic(board, rig, tags=None):
    epic = _epic(board, rig, tags=tags)
    d = board.doc_create(rig["architect"], doc_type=DocType.design, title="design", body_md="# d", scope=epic.id)
    board.criterion_create(rig["architect"], ticket_id=epic.id, text="it works", check=Check.command)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    board.gate_open(epic.id, Gate.design_signoff, by="architect", note="please")
    board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "go")
    return epic


def _auto(board, typ):
    return [r for r in board.store.query(typ, {}, limit=-1) if r.created_by == records.AUTHOR]


# ============================================================================ c-530bb59136 read

def test_context_carries_recall_with_ids_and_one_line_text(board, rig):
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    d = board.record_decision(rig["architect"], scope=epic.id, text="uploads retry with exponential backoff")
    c = board.record_claim(rig["qa"], scope=epic.id, text="the flaky upload fails one run in ten",
                           basis=ClaimBasis.measured, evidence=["x"])
    le = board.record_lesson(rig["qa"], domain="operations", topic="retry",
                             text="a flaky upload is retried, never skipped")
    ctx = board.context(rig["engineer"], s.id)
    rec = ctx["tickets"][0]["recall"]
    ids = {i["id"] for i in rec["items"]}
    assert {d.id, c.id, le.id} <= ids
    for i in rec["items"]:
        assert set(i) == {"id", "type", "text"} and "\n" not in i["text"] and len(i["text"]) <= records.RECALL_TEXT
    assert rec["receipt"]["cap"] == records.RECALL_MAX


def test_recall_is_capped_and_other_epics_stay_out(board, rig):
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    for i in range(records.RECALL_MAX + 4):
        board.record_decision(rig["architect"], scope=epic.id, text=f"upload retry rule {i} with backoff")
    other = board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="other")
    foreign = board.record_decision(rig["architect"], scope=other.id, text="upload retry rule from elsewhere")
    rec = records.recall(board.store, s.id)
    assert len(rec["items"]) == records.RECALL_MAX
    assert foreign.id not in {i["id"] for i in rec["items"]}


def test_recall_never_calls_a_model_or_the_index(board, rig, monkeypatch):
    """recall passes index=None to wired_lookup: no dense leg, so no embedder (and no LLM) runs."""
    seen = {}
    real = records.knowledge.wired_lookup

    def spy(store, index, scope, **kw):
        seen["index"] = index
        return real(store, index, scope, **kw)

    monkeypatch.setattr(records.knowledge, "wired_lookup", spy)
    epic = _epic(board, rig)
    records.recall(board.store, _story(board, rig, epic).id)
    assert seen == {"index": None}


def test_context_without_ticket_limits_recall_to_few_tickets(board, rig):
    epic = _epic(board, rig)
    stories = [_story(board, rig, epic, title=f"slice {i}") for i in range(5)]
    ctx = board.context(rig["engineer"])
    assert len(ctx["tickets"]) == 5 and all("recall" not in t for t in ctx["tickets"])
    assert "recall" in board.context(rig["engineer"], stories[0].id)["tickets"][0]


# ============================================================================ c-1e8f2edd8e record

def _checked(board, rig, check=Check.command, checked_by="qa"):
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    c = board.criterion_create(rig["architect"], ticket_id=s.id, text="retries pass", check=check,
                               checked_by=checked_by)
    rep = board.doc_create(rig["engineer"], doc_type=DocType.report, title="R", body_md="ok", scope=s.id)
    board.criterion_update(rig["engineer"], c.id, evidence_ref=rep.id)
    return epic, s, c, rep


def test_qa_verdict_with_note_records_a_measured_claim(board, rig):
    epic, s, c, rep = _checked(board, rig)
    board.criterion_update(rig["qa"], c.id, verdict=Verdict.passed, note="re-ran pytest cold: 12 passed")
    [cl] = _auto(board, "claim")
    assert cl.basis == ClaimBasis.measured and cl.scope == s.id
    assert cl.text == f"{c.id} pass: re-ran pytest cold: 12 passed"
    assert set(cl.evidence) == {rep.id, c.id}
    assert cl.id in {i["id"] for i in board.context(rig["engineer"], s.id)["tickets"][0]["recall"]["items"]}


def test_owner_judgment_verdict_records_a_ruled_claim(board, rig):
    epic, s, c, rep = _checked(board, rig, check=Check.look, checked_by="owner")
    board.criterion_update(rig["owner"], c.id, verdict=Verdict.failed, note="the tab still says Sessions")
    [cl] = _auto(board, "claim")
    assert cl.basis == ClaimBasis.ruled and " fail: " in cl.text


def test_verdict_without_note_records_nothing(board, rig):
    epic, s, c, rep = _checked(board, rig)
    board.criterion_update(rig["qa"], c.id, verdict=Verdict.passed)
    assert _auto(board, "claim") == []


def test_record_verdict_view_passes_the_note(board, rig):
    from edp8 import views
    epic, s, c, rep = _checked(board, rig)
    views.record_verdict(board, rig["qa"], criterion_id=c.id, verdict="pass", note="looked: fine",
                         ticket_id=s.id)
    assert [x.text for x in _auto(board, "claim")] == [f"{c.id} pass: looked: fine"]


def _deviation(board, rig):
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    dev = board.message_send(rig["engineer"], ticket_id=s.id, to="architect", kind=MessageKind.deviation,
                             text="Design says poll every 5 s; the API rate-limits at 10/min, so poll every 30 s.")
    return epic, s, dev


def test_accepted_deviation_records_a_decision(board, rig):
    epic, s, dev = _deviation(board, rig)
    ans = board.message_send(rig["architect"], ticket_id=s.id, to="engineer", kind=MessageKind.answer,
                             text="Accepted — 30 s it is.", reply_to=dev.id)
    [d] = _auto(board, "decision")
    assert d.text.startswith("Deviation accepted: Design says poll every 5 s") and d.scope == s.id
    assert d.source == ans.id and not d.binding and "architect accepted" in d.detail


@pytest.mark.parametrize("who,text", [("architect", "No — keep 5 s and batch."),
                                      ("engineer", "accepted"),
                                      ("architect", "going with it later")])
def test_rejected_or_non_accepter_answer_records_nothing(board, rig, who, text):
    epic, s, dev = _deviation(board, rig)
    board.message_send(rig[who], ticket_id=s.id, to=None, kind=MessageKind.answer, text=text, reply_to=dev.id)
    assert _auto(board, "decision") == []


def test_answer_to_a_question_is_not_a_decision(board, rig):
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    q = board.message_send(rig["engineer"], ticket_id=s.id, to="architect", kind=MessageKind.question, text="?")
    board.message_send(rig["architect"], ticket_id=s.id, to="engineer", kind=MessageKind.answer, text="yes",
                       reply_to=q.id)
    assert _auto(board, "decision") == []


def test_gate_answer_records_a_decision_sourced_from_the_answer(board, rig):
    epic = _signed_off_epic(board, rig)
    [d] = _auto(board, "decision")
    assert d.text == f"design_signoff gate on {epic.id} answered by owner: go"
    src = board.store.get("message", d.source)
    assert src is not None and src.text == "[design_signoff] go"


def _pain(path, **kw):
    rec = {"id": "p-1", "ts": "t", "role": "engineer", "handle": "e", "severity": "low", "area": "tools",
           "symptom": "link_delete silently drops unknown ids", "expected": "a not_found error", **kw}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def test_pain_filed_becomes_a_lesson_once(board, rig, tmp_path):
    f = tmp_path / "pain-points.jsonl"
    _pain(f)
    _pain(f, id="p-2", dup_of="p-1", symptom="same again")
    _pain(f, id="p-3", symptom="fixed already")
    with open(f, "a", encoding="utf-8") as h:
        h.write(json.dumps({"id": "p-3", "resolves": True, "status": "fixed"}) + "\n")
    board.context(rig["engineer"])
    [le] = _auto(board, "lesson")
    assert (le.domain, le.evidence) == ("tools", ["p-1"])
    assert le.text == "link_delete silently drops unknown ids — expected: a not_found error"
    records._pain_seen.clear()  # a re-read (file touched / new process) never duplicates
    board.context(rig["engineer"])
    assert len(_auto(board, "lesson")) == 1


def test_duplicate_text_is_recorded_once_per_epic(board, rig):
    epic, s, c, rep = _checked(board, rig)
    board.criterion_update(rig["qa"], c.id, verdict=Verdict.failed, note="Retries   flake.")
    board.criterion_update(rig["qa"], c.id, verdict=Verdict.failed, note="retries flake")
    assert len(_auto(board, "claim")) == 1


def test_per_epic_cap_stops_auto_records(board, rig, monkeypatch):
    monkeypatch.setenv("EDP8_AUTO_RECORD_CAP", "2")
    epic, s, c, rep = _checked(board, rig)
    for i in range(4):
        board.criterion_update(rig["qa"], c.id, verdict=Verdict.failed, note=f"attempt {i} flaked")
    assert len(_auto(board, "claim")) == 2
    other_s = _story(board, rig, _epic(board, rig), title="another epic")  # a different epic has its own budget
    c2 = board.criterion_create(rig["architect"], ticket_id=other_s.id, text="x", check=Check.command)
    board.criterion_update(rig["engineer"], c2.id, evidence_ref=rep.id)
    board.criterion_update(rig["qa"], c2.id, verdict=Verdict.passed, note="fine here")
    assert len(_auto(board, "claim")) == 3


def test_withdraw_is_the_undo(board, rig):
    epic, s, dev = _deviation(board, rig)
    board.message_send(rig["owner"], ticket_id=s.id, to=None, kind=MessageKind.answer, text="yes, go",
                       reply_to=dev.id)
    [d] = _auto(board, "decision")
    board.withdraw_decision(rig["owner"], decision_id=d.id, reason="auto-record noise")
    assert board.store.get("decision", d.id).status == DecisionStatus.withdrawn
    assert d.id not in {i["id"] for i in records.recall(board.store, s.id)["items"]}


def test_a_failing_hook_never_breaks_the_event(board, rig, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")

    monkeypatch.setattr(records, "claim_from_verdict", boom)
    epic, s, c, rep = _checked(board, rig)
    got = board.criterion_update(rig["qa"], c.id, verdict=Verdict.passed, note="n")
    assert got.verdict == Verdict.passed


# ============================================================================ c-a9984af463 auto-link

def _lib(board, rig, dtype, tags, status=None, title=None):
    d = board.doc_create(rig["owner"], doc_type=dtype, title=title or f"{dtype.value} {tags}", body_md="- rule",
                         scope="global", tags=tags)
    if status:
        d.status = status
        board.store.put("doc", d)
    return d


def test_design_signoff_links_tagged_library_docs_and_notes_it(board, rig):
    py = _lib(board, rig, DocType.strategy_ll, ["python", "testing"])
    dom = _lib(board, rig, DocType.domain, ["uploads"])
    _lib(board, rig, DocType.strategy_hl, ["rust"])  # no tag match
    _lib(board, rig, DocType.strategy_hl, ["python"], status=DocStatus.retired)  # not active
    epic = _signed_off_epic(board, rig, tags=["python", "uploads", "model:engineer=claude-opus-5-5"])
    links = {(lk.to_id, lk.relation) for lk in board.store.query("link", {"from_id": epic.id}, limit=-1)
             if lk.relation in (Relation.uses_strategy, Relation.uses_domain)}
    assert links == {(py.id, Relation.uses_strategy), (dom.id, Relation.uses_domain)}
    notes = [m for m in board.thread(epic.id) if m.created_by == "board" and "Library auto-link" in m.text]
    assert len(notes) == 1 and py.id in notes[0].text and dom.id in notes[0].text and "link_delete" in notes[0].text


def test_unlink_after_autolink(board, rig):
    py = _lib(board, rig, DocType.strategy_ll, ["python"])
    epic = _signed_off_epic(board, rig, tags=["python"])
    [lk] = board.store.query("link", {"from_id": epic.id, "to_id": py.id}, limit=-1)
    assert board.store.delete("link", lk.id)  # DELETE /v1/links/{id} (architect/owner unlink)
    assert board.store.query("link", {"from_id": epic.id, "to_id": py.id}, limit=-1) == []


def test_untagged_epic_links_nothing_and_posts_no_note(board, rig):
    _lib(board, rig, DocType.strategy_ll, ["python"])
    epic = _signed_off_epic(board, rig)
    assert not [m for m in board.thread(epic.id) if "Library auto-link" in m.text]


def test_quick_task_create_autolinks_by_its_tags(board, rig):
    py = _lib(board, rig, DocType.strategy_ll, ["python"])
    q = board.ticket_create(rig["owner"], kind=TicketKind.story, work_type=WorkType.chore, title="fix it",
                            words="fix the python thing", tags=["quick", "python"])
    assert [lk.to_id for lk in board.store.query("link", {"from_id": q.id, "relation": Relation.uses_strategy},
                                                 limit=-1)] == [py.id]
    assert q.status == TicketStatus.ready


def test_plain_tags_drop_config_tags():
    from edp8.library import plain_tags
    assert plain_tags(["Python", "model:qa=gpt-6-astra", "seat-model:x", "quick", "a=b"]) == {"python"}


# ============================================================================ REST + MCP halves

def test_rest_recall_and_criterion_note(board, rig):
    from fastapi.testclient import TestClient
    from edp8.service import create_app
    epic, s, c, rep = _checked(board, rig)
    app = create_app(board)
    cl = TestClient(app)
    h = {"X-Participant": "qa"}
    r = cl.patch(f"/v1/criteria/{c.id}", json={"verdict": "pass", "note": "cold re-run green"}, headers=h)
    assert r.status_code == 200, r.text
    r = cl.get("/v1/recall", params={"ticket_id": s.id}, headers=h)
    assert r.status_code == 200
    assert any(i["type"] == "claim" and "cold re-run green" in i["text"] for i in r.json()["value"]["items"])


def test_assemble_ruleset_appends_recall(board, rig):
    """The MCP brief (bundles._assemble_ruleset via the REST client) carries value.recall."""
    from fastapi.testclient import TestClient
    from edp8.bundles import ALL_TOOLS, set_client
    from edp8.client import BoardClient
    from edp8.service import create_app
    epic = _epic(board, rig)
    s = _story(board, rig, epic)
    doc = _lib(board, rig, DocType.strategy_ll, ["python"])
    board.link_create(rig["architect"], from_id=epic.id, to_id=doc.id, relation=Relation.uses_strategy)
    d = board.record_decision(rig["architect"], scope=epic.id, text="uploads retry with exponential backoff")
    set_client(BoardClient(participant="engineer", client=TestClient(create_app(board))))
    tool = ALL_TOOLS["assemble_ruleset"]
    out = tool.handler(tool.args_model(ticket_id=s.id))
    assert out["ok"] and d.id in {i["id"] for i in out["value"]["recall"]["items"]}

def test_the_same_pain_id_twice_in_one_file_makes_one_lesson(board, rig, tmp_path):
    """S-ADV finding 8: a pain re-filed under its own id (an edited symptom) is one lesson, not two."""
    f = tmp_path / "pain-points.jsonl"
    _pain(f, id="p-one", symptom="first symptom")
    _pain(f, id="p-one", symptom="updated symptom")
    records._pain_seen.clear()
    made = records.lessons_from_pains(board, f)
    assert len(made) == 1 and made[0].evidence == ["p-one"]
    assert len(_auto(board, "lesson")) == 1
