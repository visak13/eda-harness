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

