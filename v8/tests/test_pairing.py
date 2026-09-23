"""S22 §24 rule 3, as narrowed by S-ROLES (s-a0c67e6aa7, dec-0697863338): the board pairs ONE
checker — qa.<epic> when the acceptance gate opens. A story reaching in_review pairs nothing (reviewer
is no longer a role); under the RAM floor the qa spawn queues with one feed note and retries; a failed
spawn is kept for the retry. A stub pool records the spawn calls — no real shell, no real RAM."""

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


class FlakyPool:
    """Fails the first N spawn attempts (raising, or returning the adapter's {'ok': False}
    envelope), then succeeds — exercises the §24.1(b) keep-and-retry contract."""

    def __init__(self, fails=1, raises=False):
        self.spawns: list[tuple[str, str]] = []
        self.attempts = 0
        self.fails = fails
        self.raises = raises

    def spawn(self, role, participant_id, **kw):
        self.attempts += 1
        if self.attempts <= self.fails:
            if self.raises:
                raise RuntimeError("pool broke")
            return {"ok": False, "error": {"code": "pool", "message": "no capacity"}}
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def pool():
    return StubPool()


def make_board(pool, free_mb=4096):
    return Board(Store(":memory:"), pool=pool, free_mb=lambda: free_mb)


def rig(board):
    roles = {"owner": Role.owner, "coordinator": Role.coordinator, "architect": Role.architect,
             "engineer": Role.engineer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def story_to_in_review(board, r, epic, tags=("review_required",)):
    """Walk a (formerly review_required) story to evidence-complete in_review (explicit handoff). A bare drafted
    HOLDING sibling is created first so the single evidence-complete story does not, on its own,
    release the whole epic and open its acceptance gate (§24 finding 1) — this test isolates the
    story hand-off from the acceptance spawn."""
    board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                        title="hold", parent_id=epic.id)  # drafted → never released → epic stays open
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
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_review)
    return story, crit


def test_story_in_review_pairs_no_checker(pool):
    """S-ROLES: a story reaching in_review (even one still tagged review_required) spawns nothing;
    qa checks every story once, at epic acceptance."""
    board = make_board(pool)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, crit = story_to_in_review(board, r, epic)
    ev2 = board.doc_create(r["engineer"], doc_type=DocType.report, title="e2", body_md="ok2", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev2.id)  # new evidence re-pairs nothing
    assert board.run_pending_pairings()["spawned"] == []
    assert pool.spawns == [] and not board._pending_pairings
    assert crit.checked_by == "qa"


def _acceptance(board):
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.gate_open(epic.id, Gate.acceptance)
    return epic, f"qa.{epic.id}"


def test_under_ram_floor_queues_with_one_feed_note(pool):
    board = make_board(pool, free_mb=300)  # below the 500 MB seat floor
    epic, seat = _acceptance(board)
    out = board.run_pending_pairings()
    assert out["queued"] == [seat] and out["spawned"] == []
    assert pool.spawns == []
    notes = [m for m in board.store.query("message", {"ticket_id": epic.id})
             if m.created_by == "board" and "queued" in m.text]
    assert len(notes) == 1 and "300 MB free" in notes[0].text
    # a second tick still under the floor does NOT post a second note (retry is quiet)
    board.run_pending_pairings()
    notes = [m for m in board.store.query("message", {"ticket_id": epic.id})
             if m.created_by == "board" and "queued" in m.text]
    assert len(notes) == 1
    # RAM frees up → the queued seat spawns on the next tick
    board._free_mb = lambda: 4096
    assert board.run_pending_pairings()["spawned"] == [seat]


@pytest.mark.parametrize("raises", [False, True])
def test_failed_spawn_keeps_the_entry_for_retry_with_one_note(raises):
    """§24.1(b): a spawn that fails (a pool exception, or the adapter's {'ok': False}) leaves the
    seat QUEUED for the next 60 s tick and posts exactly ONE feed note; it never reports a phantom
    pairing. When the pool recovers, the retry spawns it and drains the entry."""
    flaky = FlakyPool(fails=2, raises=raises)  # first two ticks fail, third recovers
    board = Board(Store(":memory:"), pool=flaky, free_mb=lambda: 4096)
    epic, seat = _acceptance(board)
    out = board.run_pending_pairings()  # first attempt fails
    assert out["spawned"] == [] and out["failed"] == [seat]
    assert flaky.spawns == []               # nothing reported as spawned
    assert seat in board._pending_pairings  # kept for the retry
    notes = [m for m in board.store.query("message", {"ticket_id": epic.id})
             if m.created_by == "board" and "spawn failed" in m.text]
    assert len(notes) == 1
    board.run_pending_pairings()  # still noted once (the retry is quiet)
    notes = [m for m in board.store.query("message", {"ticket_id": epic.id})
             if m.created_by == "board" and "spawn failed" in m.text]
    assert len(notes) == 1
    # third tick: the pool has recovered → the seat finally spawns and leaves the queue
    out3 = board.run_pending_pairings()
    assert out3["spawned"] == [seat]
    assert (Role.qa.value, seat) in flaky.spawns
    assert seat not in board._pending_pairings


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
