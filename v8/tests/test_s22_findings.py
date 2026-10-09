"""S22 reopen — the architect's FIRST second-opinion read (12 findings). One test per open
finding from steer m-6ce85aeede: acceptance-gate deadlock (1), authenticated auto-spawn (4),
_released story-only (6), link_create reconciliation (7), pairing survives restart (3), pairing
from persisted criteria + review_required frozen (5), caps under the board lock (11), and the
drafted→dropped docstring case (12). Findings 2/8/9/10 are covered elsewhere (test_pairing,
test_relevance_matrix)."""

from __future__ import annotations

import threading

import pytest

from asks_support import serve
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
    roles = {"owner": Role.owner, "architect": Role.architect,
             "engineer": Role.engineer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def make_board(pool=None, **kw):
    return Board(Store(":memory:"), pool=pool, **kw)


def story_to_in_review(board, r, epic, *, title="S", tags=("review_required",)):
    """Walk a story to evidence-complete in_review (explicit handoff)."""
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title=title, parent_id=epic.id, tags=list(tags))
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], story.id, design_ref=d.id)
    crit = board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], story.id, status=TicketStatus.signed_off)
    board.ticket_update(r["architect"], story.id, status=TicketStatus.ready)
    board.ticket_update(r["architect"], story.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_progress)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_review)
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
def _qa_hints(board, epic_id):
    from edp8.schemas import EventKind
    return [e for e in board.store.query("event", {"subject_id": epic_id, "kind": EventKind.board_hint}, limit=50)
            if e.data.get("hint") == "qa_available"]


def test_finding1_epic_moves_to_in_review_and_hints_the_architect_on_evidence_complete_in_review():
    """Two stories evidence-complete in_review (not `done`) → the epic moves to in_review and the architect gets one
    hint; the board opens no gate and enqueues no qa seat."""
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
    assert board.ticket(epic.id).status != TicketStatus.in_review  # the drafted hold is unreleased → epic stays open
    assert not _qa_hints(board, epic.id)
    board.ticket_update(r["architect"], hold.id, status=TicketStatus.dropped)  # last child clears
    assert board.ticket(epic.id).status == TicketStatus.in_review  # every child released/dropped
    assert len(_qa_hints(board, epic.id)) == 1  # one hint to the architect; no gate, no seat
    assert not board.open_gates(epic.id, Gate.acceptance) and f"qa.{epic.id}" not in board._pending_pairings
    board.run_pending_pairings()
    assert pool.spawns == []


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
    board.criterion_update(r["engineer"], crit.id, evidence_ref=ev.id)
    assert board.ticket(story.id).status == TicketStatus.ready  # evidence no longer implies handoff
    # Reproduce a lagging ready parent with a working child, then explicitly hand off.
    child = board.ticket(story.id)
    child.status = TicketStatus.in_progress
    child.assignee = r["engineer"].id
    board.store.put("ticket", child)
    board.ticket_update(r["engineer"], story.id, status=TicketStatus.in_review)
    assert board.ticket(story.id).status == TicketStatus.in_review
    # the active branch moved it to in_progress, then every story released carried it on to in_review
    # (s-ccdafcb229, owner m-b0a7f9cda9)
    assert board.ticket(epic.id).status == TicketStatus.in_review
    assert len(_qa_hints(board, epic.id)) == 1 and not board.open_gates(epic.id, Gate.acceptance)


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
    story_to_in_review(board, r, epic)
    board._enqueue_pairing(f"qa.{epic.id}", "qa", epic.id)  # the board stages no qa (B); the queue still drains
    board.run_pending_pairings()
    assert minted == [f"qa.{epic.id}"]
    assert pool.envs and pool.envs[0] == {"EDP8_TOKEN": f"secret-qa.{epic.id}"}

    # trusted mode: no minter → env is None (header-only, unchanged)
    pool2 = StubPool()
    board2 = make_board(pool2, free_mb=lambda: 4096)  # mint_token defaults to None
    r2 = rig(board2)
    epic2 = board2.ticket_create(r2["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story_to_in_review(board2, r2, epic2)
    board2._enqueue_pairing(f"qa.{epic2.id}", "qa", epic2.id)
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
    story_to_in_review(board, r, epic)
    board._enqueue_pairing(f"qa.{epic.id}", "qa", epic.id)
    out = board.run_pending_pairings()
    assert pool.spawns == []                       # nothing spawned token-less
    assert out["spawned"] == [] and f"qa.{epic.id}" in out["failed"]
    assert f"qa.{epic.id}" in board._pending_pairings  # kept for the retry


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
                               title="T", parent_id=story.id, serves=serve(board, story.id), assignee=r["engineer"].id)
    tc = board.criterion_create(r["engineer"], ticket_id=task.id, text="tc", check=Check.command)
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.designed)
    board.ticket_update(r["owner"], task.id, status=TicketStatus.signed_off)  # auto-readies (no blocker)
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.in_progress)
    ev = board.doc_create(r["engineer"], doc_type=DocType.report, title="te", body_md="ok", scope=epic.id)
    board.criterion_update(r["engineer"], tc.id, evidence_ref=ev.id)
    board.ticket_update(r["engineer"], task.id, status=TicketStatus.in_review)
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
    board.ticket_update(r["architect"], pred.id, status=TicketStatus.ready)
    board.ticket_update(r["architect"], pred.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], pred.id, status=TicketStatus.in_progress)
    assert board._released(board.ticket(pred.id)) is False
    # successor already ready
    succ = story_to_signed_off(board, r, epic, title="B")
    board.ticket_update(r["architect"], succ.id, status=TicketStatus.ready)
    assert board.ticket(succ.id).status == TicketStatus.ready
    board.link_create(r["architect"], from_id=pred.id, to_id=succ.id, relation=Relation.blocks)
    assert board.ticket(succ.id).status == TicketStatus.signed_off  # walked back behind the blocker


# --------------------------------------------------------------- finding 3: survive a restart
def test_finding3_pending_pairings_rederived_on_new_board():
    """A restart re-derives no qa pairing (B): the board never staffs qa, even for an epic with an acceptance gate
    opened by hand."""
    store = Store(":memory:")
    board = Board(store, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story, _ = story_to_in_review(board, r, epic, title="S")
    board.gate_open(epic.id, Gate.acceptance)  # qa wanted
    # a fresh Board over the SAME store (a restart) starts with an empty queue, then re-derives it
    board2 = Board(store, free_mb=lambda: 4096)
    assert set(board2._pending_pairings) == set()


def test_finding3_rederive_skips_a_live_seat():
    store = Store(":memory:")
    board = Board(store, free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story_to_in_review(board, r, epic, title="S")
    board.gate_open(epic.id, Gate.acceptance)
    board.session_upsert(id_="sess", participant_id=f"qa.{epic.id}", ticket_id=epic.id,
                         pool_id="p", state=SessionState.alive)
    board2 = Board(store, free_mb=lambda: 4096)
    assert f"qa.{epic.id}" not in board2._pending_pairings  # a live seat is not re-paired


# --------------------------------------------------------------- finding 5, retired by S-ROLES
def test_finding5_review_required_is_a_plain_tag_now():
    """S-ROLES: review_required no longer retargets the checker (qa checks every story), so the tag
    freeze is gone — adding it after criteria is allowed and leaves checked_by=qa."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    story = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                                title="S", parent_id=epic.id)
    crit = board.criterion_create(r["architect"], ticket_id=story.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], story.id, tags=["review_required"])
    assert "review_required" in board.ticket(story.id).tags
    assert board.store.get("criterion", crit.id).checked_by == "qa"


# --------------------------------------------------------------- finding 11: caps under the lock
def test_finding11_story_cap_counts_under_the_board_lock():
    """The cap count and the insert run inside the board lock: a probe from another thread cannot
    acquire the lock while the count is happening."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    acquired_during_count: list[bool] = []
    orig = board._enforce_story_cap

    def probing_enforce(epic_id, *rest):
        # this runs INSIDE `with self._lock` — a second thread must not be able to take the lock
        holder: list[bool] = []
        th = threading.Thread(target=lambda: holder.append(board._lock.acquire(blocking=False)))
        th.start()
        th.join()
        got = holder[0]
        if got:
            board._lock.release()
        acquired_during_count.append(got)
        return orig(epic_id, *rest)

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
                               title="T", parent_id=story.id, serves=serve(board, story.id), assignee=r["engineer"].id)
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
    story_to_in_review(board, r, epic, title="S", tags=())  # S4 C1: qa pairs once every story is handed over
    for k in board.children(epic.id):
        if k.title == "hold":
            board.ticket_update(r["architect"], k.id, status=TicketStatus.dropped)
    board._enqueue_pairing(f"qa.{epic.id}", "qa", epic.id)
    assert f"qa.{epic.id}" in board._pending_pairings
    board.store.put("ticket", board.ticket(epic.id).model_copy(update={"status": TicketStatus.dropped}))  # in_review has no drop edge
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


# --------------------------------------------------------------- terminal outcomes release (architect m-23b59aec97)
def _review_story(board, r, epic):
    rv = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.review,
                             title="review", parent_id=epic.id)
    d = board.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    board.ticket_update(r["architect"], rv.id, design_ref=d.id)
    board.criterion_create(r["architect"], ticket_id=rv.id, text="c", check=Check.command)
    board.ticket_update(r["architect"], rv.id, status=TicketStatus.designed)
    return rv


def test_review_story_readies_past_a_dropped_and_a_partial_sibling():
    """s-9148b053a5 was refused `ready` with a dropped and a partial sibling as its open blockers: both are
    terminal outcomes the owner or architect decided, so both release."""
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    gone = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="gone", parent_id=epic.id)
    board.ticket_update(r["architect"], gone.id, status=TicketStatus.dropped)
    half, _ = story_to_in_review(board, r, epic, title="half", tags=())
    board.ticket_update(r["owner"], half.id, status=TicketStatus.partial)
    assert board.ticket(half.id).status == TicketStatus.partial
    rv = _review_story(board, r, epic)
    assert {b.id for b in board.blockers(rv.id)} == {gone.id, half.id}
    board.ticket_update(r["owner"], rv.id, status=TicketStatus.signed_off)
    assert board.ticket(rv.id).status == TicketStatus.ready  # nothing holds it: the board promotes it


def test_dropping_an_explicit_blocker_readies_its_successor():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    pred = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="pred", parent_id=epic.id)
    succ = story_to_signed_off(board, r, epic, title="succ")
    board.link_create(r["architect"], from_id=pred.id, to_id=succ.id, relation=Relation.blocks)
    assert board.ticket(succ.id).status == TicketStatus.signed_off  # the live blocker holds it
    board.ticket_update(r["architect"], pred.id, status=TicketStatus.dropped)
    assert board.ticket(succ.id).status == TicketStatus.ready


def test_an_in_progress_sibling_still_holds_the_review_story():
    board = make_board()
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    gone = board.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="gone", parent_id=epic.id)
    board.ticket_update(r["architect"], gone.id, status=TicketStatus.dropped)
    live = story_to_signed_off(board, r, epic, title="live")
    board.ticket_update(r["architect"], live.id, assignee=r["engineer"].id)
    board.ticket_update(r["engineer"], live.id, status=TicketStatus.in_progress)
    rv = _review_story(board, r, epic)
    board.ticket_update(r["owner"], rv.id, status=TicketStatus.signed_off)
    assert board.ticket(rv.id).status == TicketStatus.signed_off
    with pytest.raises(BoardError) as e:
        board.ticket_update(r["architect"], rv.id, status=TicketStatus.ready)
    assert live.id in str(e.value.hint or e.value.message) and gone.id not in str(e.value.hint or e.value.message)


# --------------------------------------------------------------- 0.10.5: the acceptance gate is retired at startup
def test_startup_closes_every_open_acceptance_gate_once():
    """design-63db8a7d42 row C: a gate the old auto-open left behind is closed with the retirement reason; a second run is a no-op."""
    board = make_board(StubPool(), free_mb=lambda: 4096)
    r = rig(board)
    epic = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    other = board.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="F")
    board.gate_open(epic.id, Gate.acceptance)
    board.gate_open(other.id, Gate.scope)
    assert board.open_gates(epic.id, Gate.acceptance)
    assert board.retire_acceptance_gates() == [epic.id]
    assert board.open_gates(epic.id, Gate.acceptance) == []
    assert board.open_gates(other.id, Gate.scope)  # only acceptance is retired
    closed = [e for e in board.store.query("event", {"subject_id": epic.id, "kind": EventKind.gate_closed})]
    assert [e.data["reason"] for e in closed] == ["retired in 0.10.5: acceptance gate removed (design-63db8a7d42 row C)"]
    assert board.retire_acceptance_gates() == []  # one-time: nothing left to close
