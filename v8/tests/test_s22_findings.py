"""S22 reopen — the architect's FIRST second-opinion read (12 findings). One test per open
finding from steer m-6ce85aeede: acceptance-gate deadlock (1), authenticated auto-spawn (4),
_released story-only (6), link_create reconciliation (7), pairing survives restart (3), pairing
from persisted criteria + review_required frozen (5), caps under the board lock (11), and the
drafted→dropped docstring case (12). Findings 2/8/9/10 are covered elsewhere (test_pairing,
test_relevance_matrix)."""

from __future__ import annotations

import threading

import pytest

from edp8.board import Board, BoardError
from edp8.schemas import (
    Check,
    DocType,
    EventKind,
    Gate,
    Relation,
    Role,
    SessionState,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)
from edp8.store import Store


class StubPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []
        self.envs: list[dict | None] = []

    def spawn(self, role, participant_id, *, env=None, **kw):
        self.spawns.append((role, participant_id))
        self.envs.append(env)
        return {"ok": True, "participant_id": participant_id}


def rig(board):
    roles = {"owner": Role.owner, "coordinator": Role.coordinator, "architect": Role.architect,
             "engineer": Role.engineer, "reviewer": Role.reviewer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def make_board(pool=None, **kw):
    return Board(Store(":memory:"), pool=pool, **kw)


def story_to_in_review(board, r, epic, *, title="S", tags=("review_required",)):
    """Walk a story to evidence-complete in_review (auto-advances)."""
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title=title, parent_id=epic.id, tags=list(tags))
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


def story_to_signed_off(board, r, epic, *, title="B"):
    """A story parked at signed_off (past owner sign-off, before ready)."""
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title=title, parent_id=epic.id)
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], story.id, design_ref=d.id)
    board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)
    return story


# --------------------------------------------------------------- finding 1: acceptance deadlock
def test_finding1_epic_opens_acceptance_on_evidence_complete_in_review():
    """Two stories evidence-complete in_review (not `done`) → the epic opens `acceptance` and
    qa.<epic> is enqueued exactly once — the §24.1 release rule no longer deadlocks the gate."""
    pool = StubPool()
    board = make_board(pool, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    hold = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="hold", parent_id=epic.id)  # drafted → never released
    s1, _ = story_to_in_review(board, r, epic, title="S1", tags=())
    s2, _ = story_to_in_review(board, r, epic, title="S2", tags=())
    assert board.ticket(s1.id).status == TicketStatus.in_review
    assert board.ticket(s2.id).status == TicketStatus.in_review
    assert not board.open_gates(epic.id, Gate.acceptance)  # the drafted hold is unreleased → shut
    assert f"qa.{epic.id}" not in board._pending_pairings
    board.ticket_update(r["architect"], hold.id, status=TicketStatus.dropped)  # last child clears
    assert board.open_gates(epic.id, Gate.acceptance)  # every child released/dropped → gate open
    assert f"qa.{epic.id}" in board._pending_pairings
    board.run_pending_pairings()
    assert pool.spawns.count((Role.qa.value, f"qa.{epic.id}")) == 1


def test_finding1_gate_opens_when_child_jumps_ready_to_in_review_under_a_ready_epic():
    """The residual deadlock (second-opinion): a story evidence-completes straight from `ready` to
    `in_review` while its epic is still `ready`. The active branch moves the epic to in_progress; an
    `elif` would skip the release check and the gate would never open. The independent `if` opens it."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="S", parent_id=epic.id)
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], story.id, design_ref=d.id)
    crit = board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)  # auto → ready
    assert board.ticket(story.id).status == TicketStatus.ready
    # force the epic to `ready` so the active branch will fire on the child's in_review transition
    ep = board.ticket(epic.id)
    ep.status = TicketStatus.ready
    board.store.put("ticket", ep)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)  # ready → in_review (no in_progress)
    assert board.ticket(story.id).status == TicketStatus.in_review
    assert board.ticket(epic.id).status == TicketStatus.in_progress  # active branch moved it
    assert board.open_gates(epic.id, Gate.acceptance)  # ...and the gate STILL opened


# --------------------------------------------------------------- finding 4: authenticated spawn
def test_finding4_auto_seat_spawns_with_minted_token():
    """An auto-paired seat spawns through the same path as the service route — its EDP8_TOKEN is
    minted and injected as spawn env; trusted mode (no minter) injects nothing."""
    pool = StubPool()
    minted: list[str] = []

    def mint(handle):
        minted.append(handle)
        return f"secret-{handle}"

    board = make_board(pool, free_mb=lambda: 4096, mint_token=mint)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story_to_in_review(board, r, epic)  # review_required → reviewer paired
    board.run_pending_pairings()
    assert pool.envs and pool.envs[0] == {"EDP8_TOKEN": f"secret-reviewer.{minted[0].split('.', 1)[1]}"}

    # trusted mode: no minter → env is None (header-only, unchanged)
    pool2 = StubPool()
    board2 = make_board(pool2, free_mb=lambda: 4096)  # mint_token defaults to None
    r2 = rig(board2)
    epic2 = board2.ticket_create(r2["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story_to_in_review(board2, r2, epic2)
    board2.run_pending_pairings()
    assert pool2.envs and pool2.envs[0] is None


def test_finding4_minter_exception_fails_closed_keeps_pairing_queued():
    """A configured minter that RAISES must not spawn a token-less seat (it could never authenticate
    in public mode); the pairing stays queued for the retry and nothing is spawned."""
    pool = StubPool()

    def boom(handle):
        raise RuntimeError("mint backend down")

    board = make_board(pool, free_mb=lambda: 4096, mint_token=boom)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = story_to_in_review(board, r, epic)
    out = board.run_pending_pairings()
    assert pool.spawns == []                       # nothing spawned token-less
    assert out["spawned"] == [] and f"reviewer.{story.id}" in out["failed"]
    assert f"reviewer.{story.id}" in board._pending_pairings  # kept for the retry


# --------------------------------------------------------------- finding 6: _released story-only
def test_finding6_released_is_story_only_for_in_review():
    """The early-release-on-in_review branch is story-only: an evidence-complete in_review TASK or
    EPIC is NOT released — both release only when `done`."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = story_to_in_review(board, r, epic, tags=())
    assert board._released(board.ticket(story.id)) is True  # a story does release

    # a task evidence-complete in_review does NOT release
    task = board.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                               title="T", parent_id=story.id, assignee=r["engineer"].id)
    tc = board.criterion_create(r["engineer"], ticket_id=task.id, text="tc", check=Check.command)
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], task.id, status=TicketStatus.signed_off)  # auto-readies (no blocker)
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.in_progress)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="te", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], tc.id, evidence_ref=ev.id)  # auto → in_review
    assert board.ticket(task.id).status == TicketStatus.in_review
    assert board._released(board.ticket(task.id)) is False  # a task releases only when done

    # an epic in_review (synthetic) is likewise not released by evidence
    ep = board.ticket(epic.id)
    ep.status = TicketStatus.in_review
    assert board._released(ep) is False


# --------------------------------------------------------------- finding 7: link reconciliation
def test_finding7_link_from_released_predecessor_readies_successor():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    pred, _ = story_to_in_review(board, r, epic, title="A", tags=())  # released (evidence-complete)
    succ = story_to_signed_off(board, r, epic, title="B")  # no blocker yet → auto-readies
    # force the "stranded signed_off" state the consult described (succ ended up signed_off through
    # some path with no live trigger to re-ready it), then add the link from the released predecessor
    sc = board.ticket(succ.id)
    sc.status = TicketStatus.signed_off
    board.store.put("ticket", sc)
    board.link_create(r["architect"], from_id=pred.id, to_id=succ.id, relation=Relation.blocks)
    assert board.ticket(succ.id).status == TicketStatus.ready  # reconciled: blocker released → ready


def test_finding7_unreleased_blocker_walks_ready_successor_back():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    # predecessor still in progress (unreleased)
    pred = story_to_signed_off(board, r, epic, title="A")
    board.ticket_update(r["coordinator"], pred.id, status=TicketStatus.ready)
    board.ticket_update(r["coordinator"], pred.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], pred.id, status=TicketStatus.in_progress)
    assert board._released(board.ticket(pred.id)) is False
    # successor already ready
    succ = story_to_signed_off(board, r, epic, title="B")
    board.ticket_update(r["coordinator"], succ.id, status=TicketStatus.ready)
    assert board.ticket(succ.id).status == TicketStatus.ready
    board.link_create(r["architect"], from_id=pred.id, to_id=succ.id, relation=Relation.blocks)
    assert board.ticket(succ.id).status == TicketStatus.signed_off  # walked back behind the blocker


# --------------------------------------------------------------- finding 3: survive a restart
def test_finding3_pending_pairings_rederived_on_new_board():
    """A board built on a store that already holds a reviewer-checked in_review story and an epic
    with an open acceptance gate re-derives both pairings — a restart between enqueue and drain
    loses nothing."""
    store = Store(":memory:")
    board = Board(store, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = story_to_in_review(board, r, epic, title="S")  # review_required → reviewer wanted
    board.gate_open(epic.id, Gate.acceptance)  # qa wanted
    # a fresh Board over the SAME store (a restart) starts with an empty queue, then re-derives it
    board2 = Board(store, free_mb=lambda: 4096)
    assert f"reviewer.{story.id}" in board2._pending_pairings
    assert f"qa.{epic.id}" in board2._pending_pairings


def test_finding3_rederive_skips_a_live_seat():
    store = Store(":memory:")
    board = Board(store, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = story_to_in_review(board, r, epic, title="S")
    board.session_upsert(id_="sess", participant_id=f"reviewer.{story.id}", ticket_id=story.id,
                         pool_id="p", state=SessionState.alive)
    board2 = Board(store, free_mb=lambda: 4096)
    assert f"reviewer.{story.id}" not in board2._pending_pairings  # a live seat is not re-paired


# --------------------------------------------------------------- finding 5: criteria drive pairing
def test_finding5_review_required_frozen_once_a_story_has_criteria():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="S", parent_id=epic.id)  # no review_required tag
    board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    with pytest.raises(BoardError) as ei:  # adding the tag now would retarget a derived checker
        board.ticket_update(r["architect"], story.id, tags=["review_required"])
    assert ei.value.code == "scope" and "frozen" in ei.value.message
    # an unrelated tag edit that leaves review_required membership unchanged is still allowed
    board.ticket_update(r["architect"], story.id, tags=["hot"])
    assert "hot" in board.ticket(story.id).tags


def test_finding5_pairing_reads_persisted_criteria_not_tags():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="S", parent_id=epic.id, tags=["review_required"])
    board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    # criterion persisted checked_by=reviewer; now strip the tag out-of-band (as a stale mutation)
    t = board.ticket(story.id)
    t.tags = []
    board.store.put("ticket", t)
    assert board._story_wants_reviewer(board.ticket(story.id)) is True  # criteria win, not tags


# --------------------------------------------------------------- finding 11: caps under the lock
def test_finding11_story_cap_counts_under_the_board_lock():
    """The cap count and the insert run inside the board lock: a probe from another thread cannot
    acquire the lock while the count is happening."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    acquired_during_count: list[bool] = []
    orig = board._enforce_story_cap

    def probing_enforce(epic_id):
        # this runs INSIDE `with self._lock` — a second thread must not be able to take the lock
        holder: list[bool] = []
        th = threading.Thread(target=lambda: holder.append(board._lock.acquire(blocking=False)))
        th.start(); th.join()
        got = holder[0]
        if got:
            board._lock.release()
        acquired_during_count.append(got)
        return orig(epic_id)

    board._enforce_story_cap = probing_enforce
    board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                        title="S", parent_id=epic.id)
    assert acquired_during_count == [False]  # the lock was held throughout the count+insert


# --------------------------------------------------------------- finding 12: drafted → dropped
def test_finding12_drafted_task_may_be_dropped_without_a_criterion():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = story_to_signed_off(board, r, epic, title="S")
    task = board.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                               title="T", parent_id=story.id, assignee=r["engineer"].id)
    assert board.ticket(task.id).status == TicketStatus.drafted
    # forward to `designed` still needs a criterion...
    with pytest.raises(BoardError):
        board.ticket_update(r["engineer"], task.id, status=TicketStatus.designed)
    # ...but cancelling never-started work (drafted → dropped) stays legal
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.dropped)
    assert board.ticket(task.id).status == TicketStatus.dropped


# ============================================================ S22 reopen §24.1(a)/(b)/(c)
# (live failure m-969cb61cfe: a restarted board spawned qa for two DROPPED epics whose acceptance
# gates were left open, and those qa seats then verdicted a LIVE epic's in_review stories.)

# --------------------------------------------------------------- (a) drop closes the epic's gates
def test_reopen_a_drop_closes_the_epics_open_gates():
    board = make_board(StubPool(), free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.gate_open(epic.id, Gate.acceptance)
    assert board.open_gates(epic.id, Gate.acceptance)  # open before the drop
    board.ticket_update(r["owner"], epic.id, status=TicketStatus.dropped)
    assert board.open_gates(epic.id) == []  # the drop retired the gate (gate_closed)
    kinds = [e.kind for e in board.store.query("event", {"subject_id": epic.id})]
    assert EventKind.gate_closed in kinds


def test_reopen_a_dropped_epic_is_not_rederived_after_a_restart():
    """The live failure: a dropped epic must never re-spawn qa on a board restart."""
    store = Store(":memory:")
    board = Board(store, pool=StubPool(), free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.gate_open(epic.id, Gate.acceptance)
    board.ticket_update(r["owner"], epic.id, status=TicketStatus.dropped)
    board2 = Board(store, pool=StubPool(), free_mb=lambda: 4096)  # a restart
    assert f"qa.{epic.id}" not in board2._pending_pairings
    assert board2.run_pending_pairings()["spawned"] == []


def test_reopen_a_sweep_skips_a_pairing_whose_epic_died():
    """A qa pairing already enqueued in memory when its epic is dropped is dropped, not spawned."""
    pool = StubPool()
    board = make_board(pool, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    board.gate_open(epic.id, Gate.acceptance)
    assert f"qa.{epic.id}" in board._pending_pairings
    board.ticket_update(r["owner"], epic.id, status=TicketStatus.dropped)
    out = board.run_pending_pairings()
    assert out["spawned"] == [] and pool.spawns == []
    assert f"qa.{epic.id}" not in board._pending_pairings  # popped as a dead-epic pairing


# --------------------------------------------------------------- (b) qa context scoped to its epic
def test_reopen_b_qa_context_is_scoped_to_its_own_epic():
    """qa.<epicA> sees only epicA's in_review stories and epicA's acceptance gate — never epicB's,
    the exact cross-epic leak that let dropped-epic qa seats verdict a live epic's stories."""
    board = make_board(StubPool(), free_mb=lambda: 4096)
    r = rig(board)
    epic_a = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="A")
    epic_b = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="B")
    sa, _ = story_to_in_review(board, r, epic_a, title="SA", tags=())  # qa-checked (default)
    sb, _ = story_to_in_review(board, r, epic_b, title="SB", tags=())
    qa_a = board.participant_create("agent", Role.qa, f"qa.{epic_a.id}", id_=f"qa.{epic_a.id}")
    ids = {t.id for t in board.my_tickets(qa_a)}
    assert sa.id in ids and epic_a.id in ids       # its own epic's story + epic surface
    assert sb.id not in ids and epic_b.id not in ids  # the sibling epic is invisible
