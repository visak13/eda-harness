"""Tests for edp8.board: scope, transitions, readiness, derivation, context(),
feed relevance, sessions, doc versioning. Uses Board + Store(':memory:') directly.
"""

from __future__ import annotations

import pytest

from edp8.board import Board, BoardError
from edp8.schemas import (
    Check,
    DocType,
    EventKind,
    Gate,
    MessageKind,
    Relation,
    Role,
    SessionState,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)
from edp8.store import Store


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    """All eight roles registered as participants, keyed by role name."""
    roles = {
        "owner": Role.owner,
        "coordinator": Role.coordinator,
        "architect": Role.architect,
        "sme": Role.sme,
        "engineer": Role.engineer,
        "reviewer": Role.reviewer,
        "qa": Role.qa,
        "consultant": Role.consultant,
    }
    out = {}
    for handle, role in roles.items():
        out[handle] = board.participant_create("agent" if handle != "owner" else "human", role, handle)
    return out


def make_epic(board, rig, actor_key="owner"):
    return board.ticket_create(rig[actor_key], kind=TicketKind.epic, work_type=WorkType.feature,
                                title="Build a hello CLI")


def make_story(board, rig, epic, actor_key="architect"):
    return board.ticket_create(rig[actor_key], kind=TicketKind.story, work_type=WorkType.feature,
                                title="CLI skeleton", parent_id=epic.id)


def design_doc(board, rig, scope, actor_key="architect"):
    return board.doc_create(rig[actor_key], doc_type=DocType.design, title="design",
                             body_md="# words\nBuild a hello CLI", scope=scope)


def advance_to_designed(board, rig, ticket, doc, checked_by="qa"):
    board.ticket_update(rig["architect"], ticket.id, design_ref=doc.id)
    board.criterion_create(rig["architect"], ticket_id=ticket.id, text="does the thing",
                            check=Check.command, checked_by=checked_by)
    return board.ticket_update(rig["architect"], ticket.id, status=TicketStatus.designed)


def advance_to_signed_off(board, rig, ticket, actor_key="owner"):
    return board.ticket_update(rig[actor_key], ticket.id, status=TicketStatus.signed_off)


# ------------------------------------------------------------------ scope

def test_engineer_cannot_create_story(board, rig):
    epic = make_epic(board, rig)
    with pytest.raises(BoardError) as ei:
        board.ticket_create(rig["engineer"], kind=TicketKind.story, work_type=WorkType.feature,
                             title="x", parent_id=epic.id)
    assert ei.value.code == "scope"


def test_architect_can_create_story(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    assert story.kind == TicketKind.story
    assert story.parent_id == epic.id


def test_owner_can_create_epic(board, rig):
    epic = make_epic(board, rig, actor_key="owner")
    assert epic.kind == TicketKind.epic


def test_sme_cannot_write_design_doc(board, rig):
    epic = make_epic(board, rig)
    with pytest.raises(BoardError) as ei:
        board.doc_create(rig["sme"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    assert ei.value.code == "scope"


def test_engineer_can_write_report(board, rig):
    epic = make_epic(board, rig)
    d = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence",
                          body_md="ran it -> ok", scope=epic.id)
    assert d.doc_type == DocType.report


def test_reviewer_cannot_write_criteria(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    with pytest.raises(BoardError) as ei:
        board.criterion_create(rig["reviewer"], ticket_id=story.id, text="x", check=Check.command,
                                checked_by="qa")
    assert ei.value.code == "scope"


def test_doer_cannot_write_criteria_on_its_own_story(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    board.ticket_update(rig["architect"], story.id, assignee=rig["architect"].id)
    with pytest.raises(BoardError) as ei:
        board.criterion_create(rig["architect"], ticket_id=story.id, text="x", check=Check.command,
                                checked_by="qa")
    assert ei.value.code == "scope"
    assert "doer" in ei.value.message


# ------------------------------------------------------------------ transitions

def test_illegal_move_refused_with_hint_listing_legal(board, rig):
    epic = make_epic(board, rig)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["owner"], epic.id, status=TicketStatus.ready)
    assert ei.value.code == "transition"
    assert "legal from drafted" in ei.value.hint
    assert "designed" in ei.value.hint


def test_designed_needs_design_ref(board, rig):
    epic = make_epic(board, rig)
    board.criterion_create(rig["architect"], ticket_id=epic.id, text="x", check=Check.command,
                            checked_by="qa")
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["architect"], epic.id, status=TicketStatus.designed)
    assert "design_ref" in ei.value.message


def test_designed_needs_at_least_one_criterion(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["architect"], epic.id, status=TicketStatus.designed)
    assert "criterion" in ei.value.message


def test_in_review_needs_evidence_on_every_criterion(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d)
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], epic.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_progress)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_review)
    assert ei.value.code == "transition"
    assert "evidence_ref" in ei.value.message


def test_done_needs_all_criteria_passed(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d, checked_by="qa")
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], epic.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_progress)
    crit = board.criteria(epic.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_review)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["qa"], epic.id, status=TicketStatus.done)
    assert "verdict=pass" in ei.value.message


def test_verdict_by_doer_refused(board, rig):
    """A checker who is also the ticket's assignee cannot verdict its own work."""
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d, checked_by="qa")
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], epic.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["qa"].id)
    board.ticket_update(rig["qa"], epic.id, status=TicketStatus.in_progress)
    crit = board.criteria(epic.id)[0]
    ev = board.doc_create(rig["qa"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["qa"], crit.id, evidence_ref=ev.id)
    with pytest.raises(BoardError) as ei:
        board.criterion_update(rig["qa"], crit.id, verdict=Verdict.passed)
    assert ei.value.code == "scope"
    assert "doer" in ei.value.message


def test_verdict_by_wrong_checker_role_refused(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d, checked_by="qa")
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], epic.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_progress)
    crit = board.criteria(epic.id)[0]
    assert crit.checked_by == "qa"
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    with pytest.raises(BoardError) as ei:
        board.criterion_update(rig["reviewer"], crit.id, verdict=Verdict.passed)
    assert ei.value.code == "scope"
    assert "checked_by qa" in ei.value.message


def test_epic_done_requires_qa_checked_criterion(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    # criterion checked_by owner (not qa)
    board.ticket_update(rig["architect"], epic.id, design_ref=d.id)
    board.criterion_create(rig["architect"], ticket_id=epic.id, text="x", check=Check.command,
                            checked_by="owner")
    board.ticket_update(rig["architect"], epic.id, status=TicketStatus.designed)
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], epic.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_progress)
    crit = board.criteria(epic.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    board.criterion_update(rig["owner"], crit.id, verdict=Verdict.passed)
    board.ticket_update(rig["engineer"], epic.id, status=TicketStatus.in_review)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["owner"], epic.id, status=TicketStatus.done)
    assert "checked_by=qa" in ei.value.message


# ------------------------------------------------------------------ readiness

def test_signed_off_stays_when_blocked_by_unfinished_ticket(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, story, d)
    knowledge = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.knowledge,
                                     title="learn the thing", parent_id=epic.id)
    board.link_create(rig["architect"], from_id=knowledge.id, to_id=story.id, relation=Relation.blocks)
    board.ticket_update(rig["owner"], story.id, status=TicketStatus.signed_off)
    story = board.ticket(story.id)
    assert story.status == TicketStatus.signed_off


def test_story_auto_promotes_to_ready_when_blocker_done(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, story, d)
    knowledge = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.knowledge,
                                     title="learn the thing", parent_id=epic.id)
    kd = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, knowledge, kd)
    board.link_create(rig["architect"], from_id=knowledge.id, to_id=story.id, relation=Relation.blocks)
    board.ticket_update(rig["owner"], story.id, status=TicketStatus.signed_off)
    # finish the knowledge ticket
    board.ticket_update(rig["owner"], knowledge.id, status=TicketStatus.signed_off)
    board.ticket_update(rig["coordinator"], knowledge.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], knowledge.id, status=TicketStatus.in_progress)
    kcrit = board.criteria(knowledge.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["engineer"], kcrit.id, evidence_ref=ev.id)
    board.ticket_update(rig["engineer"], knowledge.id, status=TicketStatus.in_review)
    board.criterion_update(rig["qa"], kcrit.id, verdict=Verdict.passed)
    board.ticket_update(rig["qa"], knowledge.id, status=TicketStatus.done)

    story = board.ticket(story.id)
    assert story.status == TicketStatus.ready
    evs = board.store.query("event", {"subject_id": story.id, "kind": EventKind.status_changed})
    promo = [e for e in evs if e.data.get("to") == "ready"]
    assert promo and promo[-1].data["by"] == "board"


def test_epic_never_auto_ready(board, rig):
    epic = make_epic(board, rig)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d)
    board.ticket_update(rig["owner"], epic.id, status=TicketStatus.signed_off)
    epic = board.ticket(epic.id)
    # epics have no auto-ready path (readiness rule excludes kind == epic)
    assert epic.status == TicketStatus.signed_off


# ------------------------------------------------------------------ derivation

def test_child_in_progress_promotes_parent_epic_to_in_progress(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, story, d)
    advance_to_signed_off(board, rig, story)
    ed = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, ed)
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], story.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], story.id, status=TicketStatus.in_progress)
    epic = board.ticket(epic.id)
    assert epic.status == TicketStatus.in_progress


def test_all_stories_done_opens_acceptance_gate_on_epic(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, story, d, checked_by="qa")
    advance_to_signed_off(board, rig, story)
    ed = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, ed, checked_by="qa")
    advance_to_signed_off(board, rig, epic)
    board.ticket_update(rig["coordinator"], story.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], story.id, status=TicketStatus.in_progress)
    crit = board.criteria(story.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="evidence", body_md="ok",
                           scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    board.ticket_update(rig["engineer"], story.id, status=TicketStatus.in_review)
    board.criterion_update(rig["qa"], crit.id, verdict=Verdict.passed)
    board.ticket_update(rig["qa"], story.id, status=TicketStatus.done)

    gates = board.open_gates(epic.id, Gate.acceptance)
    assert len(gates) == 1


def test_gate_open_is_idempotent(board, rig):
    epic = make_epic(board, rig)
    e1 = board.gate_open(epic.id, Gate.acceptance)
    e2 = board.gate_open(epic.id, Gate.acceptance)
    assert e1.id == e2.id
    assert len(board.open_gates(epic.id, Gate.acceptance)) == 1


def test_gate_answer_by_owner_only(board, rig):
    epic = make_epic(board, rig)
    board.gate_open(epic.id, Gate.acceptance)
    with pytest.raises(BoardError) as ei:
        board.gate_answer(rig["coordinator"], epic.id, Gate.acceptance, "looks good")
    assert ei.value.code == "scope"
    board.gate_answer(rig["owner"], epic.id, Gate.acceptance, "approved")


def test_open_gates_empties_after_answer(board, rig):
    epic = make_epic(board, rig)
    board.gate_open(epic.id, Gate.acceptance)
    assert len(board.open_gates(epic.id, Gate.acceptance)) == 1
    board.gate_answer(rig["owner"], epic.id, Gate.acceptance, "approved")
    assert board.open_gates(epic.id, Gate.acceptance) == []


# ------------------------------------------------------------------ context()

def test_context_engineer_sees_words_chain_criteria_docs_thread(board, rig):
    epic = make_epic(board, rig)
    ed = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, ed)
    story = make_story(board, rig, epic)
    sd = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, story, sd)
    board.ticket_update(rig["coordinator"], story.id, assignee=rig["engineer"].id)
    board.message_send(rig["architect"], ticket_id=story.id, to=None, kind=MessageKind.note, text="fyi")

    ctx = board.context(rig["engineer"], story.id)
    assert len(ctx["tickets"]) == 1
    node = ctx["tickets"][0]
    assert node["words"] == "Build a hello CLI"
    chain_ids = [c["id"] for c in node["chain"]]
    assert chain_ids == [story.id, epic.id]
    assert len(node["criteria"]) == 1
    doc_ids = {d["id"] for d in node["docs"]}
    assert sd.id in doc_ids
    assert ed.id in doc_ids  # epic design doc included
    assert any(m["text"] == "fyi" for m in node["thread"])


def test_context_asks_for_me_shows_unanswered_hides_answered(board, rig):
    epic = make_epic(board, rig)
    q1 = board.message_send(rig["engineer"], ticket_id=epic.id, to="owner", kind=MessageKind.question,
                             text="ship as pip package?")
    q2 = board.message_send(rig["engineer"], ticket_id=epic.id, to="owner", kind=MessageKind.question,
                             text="what license?")
    board.message_send(rig["owner"], ticket_id=epic.id, to="engineer", kind=MessageKind.answer,
                        text="yes", reply_to=q1.id)

    ctx = board.context(rig["owner"], epic.id)
    ask_ids = {a["id"] for a in ctx["asks_for_me"]}
    assert q2.id in ask_ids
    assert q1.id not in ask_ids


# ------------------------------------------------------------------ feed relevance

def test_owner_relevance(board, rig):
    epic = make_epic(board, rig)
    owner = rig["owner"]
    gate_ev = board.gate_open(epic.id, Gate.acceptance)
    assert board.relevant(gate_ev, owner) is True

    msg_to_owner = board.message_send(rig["engineer"], ticket_id=epic.id, to="owner",
                                       kind=MessageKind.note, text="hi")
    ev_to_owner = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.message_sent})[-1]
    assert board.relevant(ev_to_owner, owner) is True

    status_note = board.message_send(rig["engineer"], ticket_id=epic.id, to=None,
                                      kind=MessageKind.status, text="progressing")
    ev_status_note = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.message_sent})[-1]
    assert board.relevant(ev_status_note, owner) is True

    # status_changed is NOT relevant to owner
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    status_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.assigned})[-1]
    assert board.relevant(status_ev, owner) is False


def test_coordinator_relevance(board, rig):
    epic = make_epic(board, rig)
    coord = rig["coordinator"]
    created_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.ticket_created})[0]
    assert board.relevant(created_ev, coord) is True

    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)
    assigned_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.assigned})[-1]
    assert board.relevant(assigned_ev, coord) is True

    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d)
    board.ticket_update(rig["owner"], epic.id, status=TicketStatus.signed_off)
    status_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.status_changed})[-1]
    assert board.relevant(status_ev, coord) is True

    sess = board.session_upsert(id_="sess-1", participant_id=rig["engineer"].id, ticket_id=epic.id,
                                 pool_id="pool-1", state=SessionState.dead)
    dead_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.shell_dead})[0]
    assert board.relevant(dead_ev, coord) is True


def test_engineer_relevance_messages_and_own_ticket_status(board, rig):
    epic = make_epic(board, rig)
    engineer = rig["engineer"]
    board.ticket_update(rig["coordinator"], epic.id, assignee=engineer.id)

    board.message_send(rig["architect"], ticket_id=epic.id, to="engineer", kind=MessageKind.note, text="hi")
    msg_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.message_sent})[-1]
    assert board.relevant(msg_ev, engineer) is True

    d = design_doc(board, rig, epic.id)
    advance_to_designed(board, rig, epic, d)
    board.ticket_update(rig["owner"], epic.id, status=TicketStatus.signed_off)
    status_ev = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.status_changed})[-1]
    assert board.relevant(status_ev, engineer) is True

    # not on the ticket -> not relevant
    other_epic = board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature,
                                      title="unrelated")
    board.ticket_update(rig["coordinator"], other_epic.id, assignee=rig["reviewer"].id)
    unrelated_ev = board.store.query("event", {"subject_id": other_epic.id, "kind": EventKind.assigned})[-1]
    assert board.relevant(unrelated_ev, engineer) is False


def test_replay_respects_relevance(board, rig):
    epic = make_epic(board, rig)
    start = board.store.max_seq()
    board.message_send(rig["engineer"], ticket_id=epic.id, to="owner", kind=MessageKind.note, text="a")
    board.ticket_update(rig["coordinator"], epic.id, assignee=rig["engineer"].id)

    owner_events = board.replay(rig["owner"], start)
    kinds = [e.kind for _, e in owner_events]
    assert EventKind.message_sent in kinds
    assert EventKind.assigned not in kinds

    coord_events = board.replay(rig["coordinator"], start)
    coord_kinds = [e.kind for _, e in coord_events]
    assert EventKind.assigned in coord_kinds


# ------------------------------------------------------------------ sessions

def test_session_upsert_dead_emits_shell_dead_once(board, rig):
    epic = make_epic(board, rig)
    board.session_upsert(id_="sess-1", participant_id=rig["engineer"].id, ticket_id=epic.id,
                          pool_id="pool-1", state=SessionState.alive)
    board.session_upsert(id_="sess-1", participant_id=rig["engineer"].id, ticket_id=epic.id,
                          pool_id="pool-1", state=SessionState.dead)
    board.session_upsert(id_="sess-1", participant_id=rig["engineer"].id, ticket_id=epic.id,
                          pool_id="pool-1", state=SessionState.dead)
    dead_events = board.store.query("event", {"subject_id": epic.id, "kind": EventKind.shell_dead})
    assert len(dead_events) == 1


# ------------------------------------------------------------------ doc versioning

def test_doc_update_bumps_version_old_readable(board, rig):
    d = board.doc_create(rig["architect"], doc_type=DocType.design, title="v1", body_md="body v1",
                          scope="global")
    assert d.version == 1
    updated = board.doc_update(rig["architect"], d.id, body_md="body v2", title="v2")
    assert updated.version == 2
    latest = board.doc(d.id)
    assert latest.version == 2
    assert latest.body_md == "body v2"
    old = board.doc(d.id, version=1)
    assert old.body_md == "body v1"
    assert old.title == "v1"
