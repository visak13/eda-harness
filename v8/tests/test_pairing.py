"""S22 §24 rule 3: the board pairs the checker itself. A story reaching in_review spawns
reviewer.<story> (only when review_required), skipping a live seat; under the RAM floor it queues
with one feed note and retries; new evidence after the reviewer closed re-pairs; the acceptance
gate spawns qa.<epic> once. A stub pool records the spawn calls — no real shell, no real RAM."""

from __future__ import annotations

import pytest

from edp8.board import Board
from edp8.schemas import (
    Check,
    DocType,
    Gate,
    Role,
    SessionState,
    TicketKind,
    TicketStatus,
    WorkType,
)
from edp8.store import Store


class StubPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []

    def spawn(self, role, participant_id, **kw):
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def pool():
    return StubPool()


def make_board(pool, free_mb=4096):
    return Board(Store(":memory:"), pool=pool, free_mb=lambda: free_mb)


def rig(board):
    roles = {"owner": Role.owner, "coordinator": Role.coordinator, "architect": Role.architect,
             "engineer": Role.engineer, "reviewer": Role.reviewer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def review_story_to_in_review(board, r, epic, tags=("review_required",)):
    """Walk a review_required story to evidence-complete in_review (auto-advances)."""
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="S", parent_id=epic.id, tags=list(tags))
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], story.id, design_ref=d.id)
    crit = board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)
    board.ticket_update(r["coordinator"], story.id, status=TicketStatus.ready)
    board.ticket_update(r["coordinator"], story.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_progress)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)  # auto → in_review
    return story, crit


def test_in_review_enqueues_and_drain_spawns_reviewer(pool):
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = review_story_to_in_review(board, r, epic)
    assert board.ticket(story.id).status == TicketStatus.in_review
    assert f"reviewer.{story.id}" in board._pending_pairings  # enqueued, not yet spawned
    assert pool.spawns == []
    out = board.run_pending_pairings()
    assert out["spawned"] == [f"reviewer.{story.id}"]
    assert (Role.reviewer.value, f"reviewer.{story.id}") in pool.spawns
    # the seat participant exists and the assignee is untouched (a checker is not the doer)
    assert board.store.get("participant", f"reviewer.{story.id}") is not None
    assert board.ticket(story.id).assignee == r["engineer"].id
    # draining again does not re-spawn (the queue was drained)
    assert board.run_pending_pairings()["spawned"] == []


def test_plain_story_pairs_no_reviewer(pool):
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = review_story_to_in_review(board, r, epic, tags=())  # not review_required → qa checks
    assert board.ticket(story.id).status == TicketStatus.in_review
    assert board._pending_pairings == {}
    assert board.run_pending_pairings()["spawned"] == []


def test_live_reviewer_seat_skips_the_spawn(pool):
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    # pre-register a LIVE reviewer seat for the story-to-be; the story id is not known yet, so drive
    # the story first, then simulate a live seat and re-trigger via new evidence
    story, crit = review_story_to_in_review(board, r, epic)
    board.run_pending_pairings()  # spawns once
    pool.spawns.clear()
    seat = f"reviewer.{story.id}"
    board.session_upsert(id_="sess-live", participant_id=seat, ticket_id=story.id, pool_id="p",
                         state=SessionState.alive)
    # new evidence lands while the reviewer seat is live → no re-enqueue, no re-spawn
    ev2 = board.doc_create(r["engineer"], doc_type=DocType.report, title="e2", body_md="ok2", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev2.id)
    assert seat not in board._pending_pairings
    assert board.run_pending_pairings()["spawned"] == []
    assert pool.spawns == []


def test_re_pairs_when_evidence_lands_after_reviewer_closed(pool):
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, crit = review_story_to_in_review(board, r, epic)
    board.run_pending_pairings()
    seat = f"reviewer.{story.id}"
    board.session_upsert(id_="sess-dead", participant_id=seat, ticket_id=story.id, pool_id="p",
                         state=SessionState.dead, reason="closed by self")
    pool.spawns.clear()
    ev2 = board.doc_create(r["engineer"], doc_type=DocType.report, title="e2", body_md="ok2", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev2.id)  # new evidence, seat closed
    assert seat in board._pending_pairings
    assert board.run_pending_pairings()["spawned"] == [seat]


def test_under_ram_floor_queues_with_one_feed_note(pool):
    board = make_board(pool, free_mb=300)  # below the 500 MB seat floor
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = review_story_to_in_review(board, r, epic)
    seat = f"reviewer.{story.id}"
    out = board.run_pending_pairings()
    assert out["queued"] == [seat] and out["spawned"] == []
    assert pool.spawns == []
    notes = [m for m in board.store.query("message", {"ticket_id": story.id})
             if m.created_by == "board" and "queued" in m.text]
    assert len(notes) == 1 and "300 MB free" in notes[0].text
    # a second tick still under the floor does NOT post a second note (retry is quiet)
    board.run_pending_pairings()
    notes = [m for m in board.store.query("message", {"ticket_id": story.id})
             if m.created_by == "board" and "queued" in m.text]
    assert len(notes) == 1
    # RAM frees up → the queued seat spawns on the next tick
    board._free_mb = lambda: 4096
    assert board.run_pending_pairings()["spawned"] == [seat]


def test_acceptance_gate_spawns_single_qa(pool):
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.gate_open(epic.id, Gate.acceptance)
    assert f"qa.{epic.id}" in board._pending_pairings
    board.run_pending_pairings()
    assert pool.spawns.count((Role.qa.value, f"qa.{epic.id}")) == 1
    # opening the (idempotent) gate again enqueues nothing new; still a single qa spawn
    board.gate_open(epic.id, Gate.acceptance)
    board.run_pending_pairings()
    assert pool.spawns.count((Role.qa.value, f"qa.{epic.id}")) == 1
