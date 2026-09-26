"""s-ccdafcb229 (owner m-b0a7f9cda9): board fixes for open pain records, one test per record."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8.board import Board
from edp8.schemas import Check, DocType, Role, TicketKind, TicketStatus, Verdict, WorkType
from edp8.store import Store


@pytest.fixture
def b():
    board = Board(Store(":memory:"))
    ps = {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "eng": board.participant_create("agent", Role.engineer, "eng", id_="eng"),
        "qa": board.participant_create("agent", Role.qa, "qa", id_="qa"),
    }
    return board, ps


def _quick_worked(board, ps):
    t = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_progress)
    c = board.criterion_create(ps["eng"], ticket_id=t.id, text="x", check=Check.verdict)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=t.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    board.ticket_update(ps["eng"], t.id, status=TicketStatus.in_review)
    return t, c


# ------------------------------------------------------------------ p-334391e9 post-commit failure

def test_a_stored_verdict_is_not_reported_as_an_error_when_a_later_step_fails(b, monkeypatch):
    board, ps = b
    t, c = _quick_worked(board, ps)

    def boom(*a, **k):
        raise RuntimeError("event write failed")
    monkeypatch.setattr(board, "_auto_advance", boom)
    warnings: list[str] = []
    out = board.criterion_update(ps["owner"], c.id, verdict=Verdict.passed, evidence_version=1, warnings=warnings)
    assert out.verdict == Verdict.passed
    assert board.store.get("criterion", c.id).verdict == Verdict.passed
    assert warnings and "event write failed" in warnings[0]


def test_a_validation_error_still_raises_before_anything_is_stored(b):
    board, ps = b
    t, c = _quick_worked(board, ps)
    with pytest.raises(Exception):
        board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)  # qa is not this checker
    assert board.store.get("criterion", c.id).verdict != Verdict.passed


# ------------------------------------------------------------------ p-3fd57a36 sign-off after a start

def _designed_epic_with_story(board, ps):
    from edp8.schemas import Gate
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    d = board.doc_create(ps["arch"], doc_type=DocType.design, title="d", body_md="# d", scope=epic.id)
    board.criterion_create(ps["arch"], ticket_id=epic.id, text="epic works", check=Check.command)
    board.ticket_update(ps["arch"], epic.id, design_ref=d.id)
    story = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                                parent_id=epic.id)
    board.criterion_create(ps["arch"], ticket_id=story.id, text="story works", check=Check.command)
    board.ticket_update(ps["arch"], story.id, design_ref=d.id, status=TicketStatus.designed)
    board.gate_open(epic.id, Gate.design_signoff, by="arch", note="please sign")
    board.ticket_update(ps["arch"], story.id, status=TicketStatus.signed_off)
    return epic, story


def test_design_signoff_stays_answerable_after_a_child_story_started(b):
    from edp8.schemas import Gate
    board, ps = b
    epic, story = _designed_epic_with_story(board, ps)
    board.ticket_update(ps["arch"], story.id, status=TicketStatus.ready)
    board.ticket_update(ps["arch"], story.id, assignee="eng")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # carried forward by the start
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "signed off")
    assert not board.open_gates(epic.id, Gate.design_signoff)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # never moved backward


# ------------------------------------------------------------------ p-b618055b answered scope lifts the cap

def test_an_answered_scope_gate_lifts_the_story_cap_for_design_signoff(b):
    from edp8.board import STORY_CAP, BoardError
    from edp8.schemas import Gate
    board, ps = b
    epic = board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    for i in range(STORY_CAP):
        board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title=f"S{i}",
                            parent_id=epic.id)
    board.gate_open(epic.id, Gate.scope, by="arch", note="need more stories")
    board.gate_answer(ps["owner"], epic.id, Gate.scope, "add as many as you want")
    board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S9", parent_id=epic.id)
    board.gate_open(epic.id, Gate.design_signoff, by="arch", note="sign")  # no longer refused
    assert board.open_gates(epic.id, Gate.design_signoff)



# ------------------------------------------------------------------ epic walk (owner m-b0a7f9cda9)

def _epic_with_evidenced_story(board, ps):
    from edp8.schemas import Gate
    epic, story = _designed_epic_with_story(board, ps)
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "signed off")
    board.ticket_update(ps["arch"], story.id, assignee="eng")
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_progress)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=story.id)
    (c,) = board.criteria(story.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    return epic, story, c


def test_the_board_carries_the_epic_to_in_review_when_every_story_is_released(b):
    from edp8.schemas import Gate
    board, ps = b
    epic, story, _ = _epic_with_evidenced_story(board, ps)
    assert board.ticket(epic.id).status == TicketStatus.in_progress
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    assert board.ticket(epic.id).status == TicketStatus.in_review  # no seat moved it
    assert board.open_gates(epic.id, Gate.acceptance)


def test_a_story_sent_back_reopens_the_epic(b):
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.failed)
    board.ticket_update(ps["qa"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress


def test_qa_verdicts_close_the_story_and_the_epic_without_a_status_call(b):
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)
    assert board.ticket(story.id).status == TicketStatus.done
    rep = board.doc_create(ps["qa"], doc_type=DocType.report, title="QA", body_md="ok", scope=epic.id)
    (ec,) = board.criteria(epic.id)
    board.criterion_update(ps["qa"], ec.id, evidence_ref=rep.id)
    board.criterion_update(ps["qa"], ec.id, verdict=Verdict.passed)
    assert board.ticket(epic.id).status == TicketStatus.done  # in_review was board-carried


def test_the_architect_may_finish_its_epic_but_not_a_story(b):
    from edp8.board import BoardError
    board, ps = b
    epic, story, c = _epic_with_evidenced_story(board, ps)
    board.ticket_update(ps["eng"], story.id, status=TicketStatus.in_review)
    with pytest.raises(BoardError, match="done is set"):
        board.ticket_update(ps["arch"], story.id, status=TicketStatus.done)
    board.criterion_update(ps["qa"], c.id, verdict=Verdict.passed)
    (ec,) = board.criteria(epic.id)
    ec.verdict, ec.evidence_ref = Verdict.passed, "r"
    board.store.put("criterion", ec)  # verdict stored without the auto-advance (e.g. a board restart)
    allowed = {t["to"]: t["allowed"] for t in board.legal_transitions(ps["arch"], epic.id)["transitions"]}
    assert allowed["done"] and allowed["partial"]
    board.ticket_update(ps["arch"], epic.id, status=TicketStatus.done)
    assert board.ticket(epic.id).status == TicketStatus.done
