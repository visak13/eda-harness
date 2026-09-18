"""Owner-requested evidence-is-not-completion lifecycle regression."""
import pytest
from edp8.board import BoardError
from test_board import board, rig
from edp8.schemas import TicketKind, TicketStatus, WorkType, Check, DocType, MessageKind


def setup_story(board, rig):
    epic = board.ticket_create(rig['owner'], kind=TicketKind.epic, work_type=WorkType.feature, title='handoff proof')
    story = board.ticket_create(rig['architect'], kind=TicketKind.story, work_type=WorkType.feature,
                               title='partial capability proof', parent_id=epic.id, assignee=rig['engineer'].id)
    criterion = board.criterion_create(rig['architect'], ticket_id=story.id, text='actual proof', check=Check.command)
    design = board.doc_create(rig['architect'], doc_type=DocType.design, title='d', body_md='contract', scope=epic.id)
    board.ticket_update(rig['architect'], story.id, design_ref=design.id, status=TicketStatus.designed)
    board.ticket_update(rig['owner'], story.id, status=TicketStatus.signed_off)
    board.ticket_update(rig['engineer'], story.id, status=TicketStatus.in_progress)
    evidence = board.doc_create(rig['engineer'], doc_type=DocType.report, title='partial', body_md='not yet proven', scope=epic.id)
    return story, criterion, evidence


def test_partial_evidence_is_not_handoff_and_explicit_handoff_preserves_completion(board, rig):
    story, criterion, evidence = setup_story(board, rig)
    with pytest.raises(BoardError, match='evidence_ref'):
        board.ticket_update(rig['engineer'], story.id, status=TicketStatus.in_review)
    board.criterion_update(rig['engineer'], criterion.id, evidence_ref=evidence.id)
    assert board.ticket(story.id).status == TicketStatus.in_progress
    board.doc_update(rig['engineer'], evidence.id, body_md='still incomplete')
    board.ticket_update(rig['engineer'], story.id, description='work remains')
    board.message_send(rig['engineer'], ticket_id=story.id, to=None, kind=MessageKind.note, text='still building')
    assert board.ticket(story.id).status == TicketStatus.in_progress
    with pytest.raises(BoardError, match='assignee'):
        board.ticket_update(rig['architect'], story.id, status=TicketStatus.in_review)
    board.ticket_update(rig['engineer'], story.id, status=TicketStatus.in_review)
    assert board.ticket(story.id).status == TicketStatus.in_review
    board.ticket_update(rig['engineer'], story.id, status=TicketStatus.in_progress)
    board.message_send(rig['engineer'], ticket_id=story.id, to=None, kind=MessageKind.status, text='returned work')
    assert board.ticket(story.id).status == TicketStatus.in_progress
    board.ticket_update(rig['engineer'], story.id, status=TicketStatus.in_review)
    from edp8.schemas import Verdict
    board.criterion_update(rig['qa'], criterion.id, verdict=Verdict.passed)
    assert board.ticket(story.id).status == TicketStatus.done
