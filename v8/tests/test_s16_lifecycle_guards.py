"""S16 (s-ca39f10643, design-e963c656f5 §4.16, pain p-77ab1bf1): the lifecycle guards, so the /epic and
/ticket skills never depend on a seat's memory.

- an epic lands in `designed` once it has a design_ref AND a criterion, whichever lands last;
- gate_open(design_signoff) refuses what the owner's answer would refuse, naming the missing piece;
- Needs you (Decisions home, the summary count, notifications) never lists a gate the owner cannot answer;
- a quick standalone ticket walks owner → engineer design note → sign-off → build → checker → done.
Board + Store(':memory:') directly.
"""
from __future__ import annotations

import pytest

from edp8 import views
from edp8.board import Board, BoardError
from edp8.schemas import Check, DocType, EventKind, Gate, Role, TicketKind, TicketStatus, WorkType
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def ps(board):
    return {
        "owner": board.participant_create("human", Role.owner, "owner", id_="owner"),
        "arch": board.participant_create("agent", Role.architect, "arch", id_="arch"),
        "eng": board.participant_create("agent", Role.engineer, "eng", id_="eng"),
        "qa": board.participant_create("agent", Role.qa, "qa", id_="qa"),
    }


def _epic(board, ps):
    return board.ticket_create(ps["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")


def _design(board, ps, scope):
    return board.doc_create(ps["arch"], doc_type=DocType.design, title="d", body_md="# d", scope=scope)


def _crit(board, ps, tid):
    return board.criterion_create(ps["arch"], ticket_id=tid, text="ships", check=Check.command)


# ---- (1) drafted → designed, either order ----------------------------------------------------

def test_design_ref_first_then_criteria_lands_designed(board, ps):
    """The order that stuck epic-7f3d64e6de in `drafted`."""
    epic = _epic(board, ps)
    board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    assert board.ticket(epic.id).status == TicketStatus.drafted  # no criterion yet
    _crit(board, ps, epic.id)
    assert board.ticket(epic.id).status == TicketStatus.designed  # no manual ticket_update


def test_criteria_first_then_design_ref_lands_designed(board, ps):
    epic = _epic(board, ps)
    _crit(board, ps, epic.id)
    assert board.ticket(epic.id).status == TicketStatus.drafted
    board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    assert board.ticket(epic.id).status == TicketStatus.designed


def test_a_story_criterion_never_carries_its_epic(board, ps):
    epic = _epic(board, ps)
    board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    _crit(board, ps, s.id)
    assert board.ticket(epic.id).status == TicketStatus.drafted


# ---- (2) gate_open(design_signoff) refuses what the answer would refuse -----------------------

@pytest.mark.parametrize("have_design,have_crit,missing", [
    (False, False, "it has no design_ref and no acceptance criteria"),
    (True, False, "it has no acceptance criteria"),
    (False, True, "it has no design_ref"),
])
def test_gate_open_refuses_an_unsignable_epic_naming_the_missing_piece(board, ps, have_design, have_crit, missing):
    epic = _epic(board, ps)
    if have_design:
        board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    if have_crit:
        _crit(board, ps, epic.id)
    with pytest.raises(BoardError) as ei:
        board.gate_open(epic.id, Gate.design_signoff, by="arch")
    assert ei.value.code == "transition" and missing in ei.value.message
    assert not board.open_gates(epic.id, Gate.design_signoff)


def test_gate_open_carries_a_legacy_drafted_epic_that_has_both_pieces(board, ps):
    """An epic stuck in `drafted` before S16 (both pieces set, no carry) is carried, then opened."""
    epic = _epic(board, ps)
    _crit(board, ps, epic.id)
    t = board.ticket(epic.id)
    t.design_ref = _design(board, ps, epic.id).id
    board.store.put("ticket", t)  # the pre-S16 state: design_ref written with no carry
    assert board.ticket(epic.id).status == TicketStatus.drafted
    board.gate_open(epic.id, Gate.design_signoff, by="arch")
    assert board.ticket(epic.id).status == TicketStatus.designed
    board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "Approved")
    assert board.ticket(epic.id).status == TicketStatus.signed_off


def test_gate_open_refuses_a_story_and_a_quick_task_without_a_note(board, ps):
    epic = _epic(board, ps)
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    with pytest.raises(BoardError, match="answered on the epic"):
        board.gate_open(s.id, Gate.design_signoff, by="arch")
    q = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="w", tags=["quick"], assignee="eng")
    with pytest.raises(BoardError, match="no design note"):
        board.gate_open(q.id, Gate.design_signoff, by="eng")


def test_gate_open_refuses_a_lint_offender_with_the_answer_s_words(board, ps):
    epic = _epic(board, ps)
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    board.criterion_create(ps["owner"], ticket_id=s.id, text="look", check=Check.look,
                           checked_by="owner", override_reason="offender")
    board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    _crit(board, ps, epic.id)
    with pytest.raises(BoardError) as ei:
        board.gate_open(epic.id, Gate.design_signoff, by="arch")
    assert s.id in ei.value.message and "owner" in ei.value.message


# ---- (3) Needs you lists only answerable gates ------------------------------------------------

def _answerable_now(board, ps):
    """Every gate the owner's views offer is one the board accepts the owner's answer on."""
    listed = views.decisions_for(board, ps["owner"])["gates"]
    for g in listed:
        assert board.gate_answer_refusal(ps["owner"], g["ticket_id"], Gate(g["gate"])) is None, g
    return listed


def test_needs_you_hides_a_gate_the_board_would_refuse(board, ps):
    epic = _epic(board, ps)
    board.ticket_update(ps["arch"], epic.id, design_ref=_design(board, ps, epic.id).id)
    _crit(board, ps, epic.id)
    board.gate_open(epic.id, Gate.design_signoff, by="arch")
    assert [g["ticket_id"] for g in _answerable_now(board, ps)] == [epic.id]
    assert views.summary_for(board, ps["owner"])["counts"]["open_gates"] == 1
    # an offence lands after the gate opened (a blocks cycle): the answer would be refused, so it leaves the list
    a = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="A", parent_id=epic.id)
    b = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="B", parent_id=epic.id)
    from edp8.schemas import Relation
    board.link_create(ps["arch"], from_id=a.id, to_id=b.id, relation=Relation.blocks)
    board.link_create(ps["arch"], from_id=b.id, to_id=a.id, relation=Relation.blocks)
    with pytest.raises(BoardError, match="cycle"):
        board.gate_answer(ps["owner"], epic.id, Gate.design_signoff, "go")
    assert _answerable_now(board, ps) == []
    assert views.summary_for(board, ps["owner"])["counts"]["open_gates"] == 0


def test_needs_you_hides_a_legacy_gate_on_a_story(board, ps):
    """A design_signoff opened on a child story before S16 (raw event) cannot be answered there."""
    epic = _epic(board, ps)
    s = board.ticket_create(ps["arch"], kind=TicketKind.story, work_type=WorkType.feature, title="S", parent_id=epic.id)
    board._emit(s.id, EventKind.gate_opened, {"gate": Gate.design_signoff, "by": "arch", "note": ""})
    board.gate_open(epic.id, Gate.scope, by="arch")  # answerable: stays listed
    assert [(g["ticket_id"], g["gate"]) for g in _answerable_now(board, ps)] == [(epic.id, "scope")]


# ---- (4) the quick standalone ticket walk -----------------------------------------------------

def test_quick_standalone_ticket_walks_owner_note_signoff_checker_done(board, ps):
    # owner creates it: parentless, tagged quick, starts ready
    q = board.ticket_create(ps["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="Q",
                            words="rename the tab", tags=["quick"], assignee="eng")
    assert q.parent_id is None and q.status == TicketStatus.ready
    # no edit before the owner signs the engineer's design note
    with pytest.raises(BoardError, match="design sign-off"):
        board.ticket_update(ps["eng"], q.id, status=TicketStatus.in_progress)
    note = board.doc_create(ps["eng"], doc_type=DocType.note, title="Design", body_md="what/how", scope=q.id)
    board.ticket_update(ps["eng"], q.id, design_ref=note.id)
    board.gate_open(q.id, Gate.design_signoff, by="eng", note="please review")
    assert [g["ticket_id"] for g in _answerable_now(board, ps)] == [q.id]
    board.gate_answer(ps["owner"], q.id, Gate.design_signoff, "go")
    board.ticket_update(ps["eng"], q.id, status=TicketStatus.in_progress)
    c = board.criterion_create(ps["eng"], ticket_id=q.id, text="tab reads Seats", check=Check.verdict)
    rep = board.doc_create(ps["eng"], doc_type=DocType.report, title="R", body_md="done", scope=q.id)
    board.criterion_update(ps["eng"], c.id, evidence_ref=rep.id)
    board.ticket_update(ps["eng"], q.id, status=TicketStatus.in_review)
    # the board-derived checker verdicts (on a quick task: the owner, from Needs you)
    assert c.checked_by == board.checker_for(board.ticket(q.id)) == "owner"
    views.record_verdict(board, ps["owner"], criterion_id=c.id, verdict="pass", evidence_version=1)
    assert board.ticket(q.id).status == TicketStatus.done
