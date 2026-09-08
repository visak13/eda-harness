"""Epic phase is machine-carried, never seat-remembered (c-c80f7cd8f0, root cause m-77af6e8145).

The board advances an epic's phase from facts — design_ref set -> designed, design_signoff
answered -> signed_off, a child story starting -> in_progress — and every read stamps a one-line
provenance header on the epic's verbatim words, so a fresh story seat never reads pre-design
(drafted) words as the live instruction. Board + Store(':memory:') directly.
"""
from __future__ import annotations

import pytest

from edp8.board import Board
from edp8.schemas import Check, DocType, Gate, Role, TicketKind, TicketStatus, WorkType
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    roles = {"owner": Role.owner, "coordinator": Role.coordinator, "architect": Role.architect,
             "engineer": Role.engineer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def _epic(board, rig):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature,
                               title="first I want concepts before any planning")


def _design(board, rig, scope):
    return board.doc_create(rig["architect"], doc_type=DocType.design, title="design",
                            body_md="# words", scope=scope)


def _criterion(board, rig, ticket_id, checked_by="qa"):
    return board.criterion_create(rig["architect"], ticket_id=ticket_id, text="does the thing",
                                  check=Check.command, checked_by=checked_by)


# ---- (1) transitions carried from facts -----------------------------------------------------

def test_design_ref_set_advances_epic_to_designed(board, rig):
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    assert board.ticket(epic.id).status == TicketStatus.drafted  # no architect ticket_update yet
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    assert board.ticket(epic.id).status == TicketStatus.designed  # carried by the board


def test_design_ref_without_a_criterion_does_not_advance(board, rig):
    """`designed` means checkable — the machine phase keeps the guard's own precondition."""
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    assert board.ticket(epic.id).status == TicketStatus.drafted


def test_design_signoff_answer_advances_epic_to_signed_off(board, rig):
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)  # -> designed
    board.gate_open(epic.id, Gate.design_signoff, by=rig["architect"].id, note="please")
    assert board.ticket(epic.id).status == TicketStatus.designed
    board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "signed")
    assert board.ticket(epic.id).status == TicketStatus.signed_off  # no architect ticket_update


def test_child_story_start_advances_epic_to_in_progress(board, rig):
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    board.ticket_update(rig["owner"], epic.id, status=TicketStatus.signed_off)
    story = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="a slice", parent_id=epic.id)
    _criterion(board, rig, story.id, checked_by="qa")
    board.ticket_update(rig["architect"], story.id, design_ref=d.id, status=TicketStatus.designed)
    board.ticket_update(rig["owner"], story.id, status=TicketStatus.signed_off)  # -> ready (no gate)
    board.ticket_update(rig["coordinator"], story.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # carried by the board


def test_child_start_advances_epic_from_designed_not_only_signed_off(board, rig):
    """finding 4 (second-opinion 2026-09-08): a child can start while the epic is still `designed`
    (never signed_off) — an evidence-complete story auto-advances ready->in_review directly. The
    board must still machine-carry the epic to in_progress."""
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)  # -> designed (NOT signed_off)
    assert board.ticket(epic.id).status == TicketStatus.designed
    story = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="a slice", parent_id=epic.id)
    _criterion(board, rig, story.id, checked_by="qa")
    board.ticket_update(rig["architect"], story.id, design_ref=d.id, status=TicketStatus.designed)
    board.ticket_update(rig["owner"], story.id, status=TicketStatus.signed_off)  # -> ready (no epic gate)
    board.ticket_update(rig["coordinator"], story.id, assignee=rig["engineer"].id)
    assert board.ticket(epic.id).status == TicketStatus.designed  # epic still designed, not signed off
    board.ticket_update(rig["engineer"], story.id, status=TicketStatus.in_progress)
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # carried from `designed`


def test_design_signoff_refused_on_a_story(board, rig):
    """finding 5: design_signoff is answered on the EPIC itself, never a child story."""
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    story = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="a slice", parent_id=epic.id)
    board.gate_open(story.id, Gate.design_signoff, by=rig["architect"].id, note="please")
    with pytest.raises(Exception) as ei:
        board.gate_answer(rig["owner"], story.id, Gate.design_signoff, "signed")
    assert "epic" in str(ei.value)
    assert board.ticket(epic.id).status == TicketStatus.designed  # untouched


def test_design_signoff_refused_on_an_undesigned_epic(board, rig):
    """finding 5: an unprepared (drafted, design-less, criterion-less) epic cannot be signed off —
    it would skip `designed`. The reproduced bug (m-4ec93f8271)."""
    epic = _epic(board, rig)
    assert board.ticket(epic.id).status == TicketStatus.drafted
    board.gate_open(epic.id, Gate.design_signoff, by=rig["architect"].id, note="please")
    with pytest.raises(Exception) as ei:
        board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "signed")
    assert "designed" in str(ei.value)
    assert board.ticket(epic.id).status == TicketStatus.drafted  # NOT signed_off


def test_phase_is_monotonic_never_walks_backward(board, rig):
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    board.ticket_update(rig["owner"], epic.id, status=TicketStatus.signed_off)
    d2 = _design(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d2.id)  # re-point the design
    assert board.ticket(epic.id).status == TicketStatus.signed_off  # NOT back to designed


# ---- (2) the provenance header --------------------------------------------------------------

def test_context_and_ticket_view_carry_the_phase_header(board, rig):
    epic = _epic(board, rig)
    d = _design(board, rig, epic.id)
    _criterion(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    story = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="a slice", parent_id=epic.id)
    # a fresh story seat's context() leads with the epic's words AND their provenance
    view = board.context(rig["architect"], ticket_id=story.id)["tickets"][0]
    hdr = view["words_header"]
    assert view["words"] == epic.title
    assert hdr.startswith("words recorded ")
    assert "phase: designed" in hdr          # the machine phase, not the pre-design 'drafted'
    assert f"governed by {d.id} v1" in hdr
    # ticket_read (the fat single read) carries the same header
    assert board.ticket_view(story.id)["words_header"] == hdr


def test_header_shows_no_design_and_current_phase_before_design(board, rig):
    epic = _epic(board, rig)
    hdr = board.ticket_view(epic.id)["words_header"]
    assert "phase: drafted" in hdr
    assert "governed by (no design yet)" in hdr
