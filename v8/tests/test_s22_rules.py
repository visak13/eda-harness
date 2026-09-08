"""S22 (design §24/§24.1): the board derives the checker, lints design_signoff, enforces the
story/task/criteria caps, and applies the evidence-complete release rule. Board + Store(':memory:')
directly, so the rules are tested at the board seam the tool layer calls."""

from __future__ import annotations

import pytest

from edp8.board import Board, BoardError
from edp8.schemas import (
    DESCRIBE,
    Check,
    DocType,
    EventKind,
    Gate,
    MessageKind,
    Relation,
    Role,
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
    roles = {"owner": Role.owner, "coordinator": Role.coordinator, "architect": Role.architect,
             "engineer": Role.engineer, "reviewer": Role.reviewer, "qa": Role.qa}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h)
            for h, r in roles.items()}


def make_epic(board, rig):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")


def make_story(board, rig, epic, **kw):
    return board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="S", parent_id=epic.id, **kw)


def design_doc(board, rig, scope):
    return board.doc_create(rig["architect"], doc_type=DocType.design, title="d", body_md="b", scope=scope)


def advance_to_designed(board, rig, ticket, doc, checked_by="qa"):
    board.ticket_update(rig["architect"], ticket.id, design_ref=doc.id)
    board.criterion_create(rig["architect"], ticket_id=ticket.id, text="does the thing",
                           check=Check.command, checked_by=checked_by)
    return board.ticket_update(rig["architect"], ticket.id, status=TicketStatus.designed)


# ------------------------------------------------------------------ §24.1 derivation

def test_checker_derivation_per_ticket_kind(board, rig):
    """qa is the default (plain story/task/review-story/epic); reviewer only for a non-review story
    tagged review_required; owner for a knowledge ticket."""
    epic = make_epic(board, rig)
    assert board.checker_for(epic) == "qa"
    story = make_story(board, rig, epic)
    assert board.criterion_create(rig["architect"], ticket_id=story.id, text="a",
                                  check=Check.command).checked_by == "qa"
    rr = make_story(board, rig, epic, tags=["review_required"])
    assert board.criterion_create(rig["architect"], ticket_id=rr.id, text="a",
                                  check=Check.command).checked_by == "reviewer"
    rv = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.review,
                             title="rv", parent_id=epic.id, tags=["review_required"])
    assert board.criterion_create(rig["architect"], ticket_id=rv.id, text="a",
                                  check=Check.verdict).checked_by == "qa"  # review story → qa even if tagged
    kn = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.knowledge,
                             title="kn", parent_id=epic.id)
    assert board.criterion_create(rig["architect"], ticket_id=kn.id, text="a",
                                  check=Check.look).checked_by == "owner"
    task = board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                               title="t", parent_id=story.id)
    assert board.criterion_create(rig["engineer"], ticket_id=task.id, text="a",
                                  check=Check.command).checked_by == "engineer"  # §24.1(d): task → its doer


def test_task_criterion_is_self_verdicted_by_its_engineer(board, rig):
    """§24.1(d): a task is the doer's own checklist — its engineer records evidence AND the verdict
    (no doer guard, no paired seat), and the task auto-advances to done. A reviewer/qa cannot
    verdict a task criterion (it is not theirs)."""
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    task = board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                               title="t", parent_id=story.id)
    c = board.criterion_create(rig["engineer"], ticket_id=task.id, text="a", check=Check.command)
    assert c.checked_by == "engineer"
    board.ticket_update(rig["architect"], task.id, status=TicketStatus.designed)
    board.ticket_update(rig["owner"], task.id, status=TicketStatus.signed_off)
    board.ticket_update(rig["engineer"], task.id, status=TicketStatus.ready)
    board.ticket_update(rig["engineer"], task.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], task.id, status=TicketStatus.in_progress)
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(rig["engineer"], c.id, evidence_ref=ev.id)  # auto → in_review
    assert board.ticket(task.id).status == TicketStatus.in_review
    with pytest.raises(BoardError) as ei:  # qa is not this task's checker
        board.criterion_update(rig["qa"], c.id, verdict=Verdict.passed)
    assert ei.value.code == "scope"
    board.criterion_update(rig["engineer"], c.id, verdict=Verdict.passed)  # the doer self-verdicts
    assert board.ticket(task.id).status == TicketStatus.done  # auto: a task gates nothing, closes itself


def test_owner_doer_guard_applies_without_override_reason(board, rig):
    """§24.1(d): the doer guard reaches the owner too — an owner writing a criterion is only allowed
    as an explicit override (checked_by + override_reason); without a reason the owner is not a
    criterion author and is refused (it never silently bypasses the guard)."""
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    with pytest.raises(BoardError) as ei:
        board.criterion_create(rig["owner"], ticket_id=story.id, text="x", check=Check.command)
    assert ei.value.code == "scope"


def test_checked_by_argument_ignored_unless_owner_override(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)  # derives qa
    c = board.criterion_create(rig["architect"], ticket_id=story.id, text="x", check=Check.command,
                               checked_by="owner")
    assert c.checked_by == "qa"  # architect's ask ignored
    assert not board.store.query("event", {"subject_id": story.id,
                                           "kind": EventKind.criterion_checker_overridden})
    c2 = board.criterion_create(rig["owner"], ticket_id=story.id, text="y", check=Check.look,
                                checked_by="owner", override_reason="my personal sign-off on this one")
    assert c2.checked_by == "owner"
    ev = board.store.query("event", {"subject_id": story.id, "kind": EventKind.criterion_checker_overridden})
    assert ev and ev[-1].data["from"] == "qa" and ev[-1].data["to"] == "owner"
    assert ev[-1].data["reason"].startswith("my personal") and ev[-1].data["by"] == rig["owner"].id
    with pytest.raises(BoardError) as ei:  # owner but no reason → not an override, and owner is not an author
        board.criterion_create(rig["owner"], ticket_id=story.id, text="z", check=Check.command,
                               checked_by="owner")
    assert ei.value.code == "scope"


def test_describe_criterion_states_derivation():
    d = DESCRIBE["criterion"].lower()
    for token in ("derives", "qa", "review_required", "knowledge", "override_reason"):
        assert token in d, f"describe('criterion') must state derivation; missing {token!r}"


# ------------------------------------------------------------------ §24 design_signoff lint

def _open_signoff(board, epic):
    board.gate_open(epic.id, Gate.design_signoff, by="architect")


def test_signoff_lint_refuses_owner_checked_story_criterion(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    board.criterion_create(rig["owner"], ticket_id=story.id, text="human check", check=Check.look,
                           checked_by="owner", override_reason="force the no-seat-path offender")
    advance_to_designed(board, rig, epic, design_doc(board, rig, epic.id))  # design_signoff needs a designed epic
    _open_signoff(board, epic)
    with pytest.raises(BoardError) as ei:
        board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "go")
    assert ei.value.code == "transition"
    assert story.id in ei.value.message and "owner" in ei.value.message


def test_signoff_lint_refuses_blocks_cycle(board, rig):
    epic = make_epic(board, rig)
    a = make_story(board, rig, epic)
    b = make_story(board, rig, epic)
    board.link_create(rig["architect"], from_id=a.id, to_id=b.id, relation=Relation.blocks)
    board.link_create(rig["architect"], from_id=b.id, to_id=a.id, relation=Relation.blocks)
    advance_to_designed(board, rig, epic, design_doc(board, rig, epic.id))  # design_signoff needs a designed epic
    _open_signoff(board, epic)
    with pytest.raises(BoardError) as ei:
        board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "go")
    assert ei.value.code == "transition" and "cycle" in ei.value.message


def test_signoff_lint_refuses_non_review_behind_review_story(board, rig):
    epic = make_epic(board, rig)
    deliver = make_story(board, rig, epic)
    review = board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.review,
                                 title="rv", parent_id=epic.id)
    board.link_create(rig["architect"], from_id=review.id, to_id=deliver.id, relation=Relation.blocks)
    advance_to_designed(board, rig, epic, design_doc(board, rig, epic.id))  # design_signoff needs a designed epic
    _open_signoff(board, epic)
    with pytest.raises(BoardError) as ei:
        board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "go")
    assert ei.value.code == "transition" and review.id in ei.value.message and deliver.id in ei.value.message


def test_signoff_lint_passes_clean_epic(board, rig):
    epic = make_epic(board, rig)
    make_story(board, rig, epic)  # qa-checked delivery story
    board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.review,
                        title="rv", parent_id=epic.id)  # implicitly waits on the delivery story
    advance_to_designed(board, rig, epic, design_doc(board, rig, epic.id))  # design_signoff needs a designed epic
    _open_signoff(board, epic)
    ev = board.gate_answer(rig["owner"], epic.id, Gate.design_signoff, "go")  # no raise
    assert ev.kind == EventKind.gate_answered


# ------------------------------------------------------------------ §24.1 release rule

def test_qa_fail_does_not_reblock_a_released_successor(board, rig):
    epic = make_epic(board, rig)
    blocker = make_story(board, rig, epic)
    succ = make_story(board, rig, epic)
    advance_to_designed(board, rig, blocker, design_doc(board, rig, epic.id), checked_by="qa")
    board.ticket_update(rig["owner"], blocker.id, status=TicketStatus.signed_off)
    advance_to_designed(board, rig, succ, design_doc(board, rig, epic.id), checked_by="qa")
    board.link_create(rig["architect"], from_id=blocker.id, to_id=succ.id, relation=Relation.blocks)
    board.ticket_update(rig["owner"], succ.id, status=TicketStatus.signed_off)
    board.ticket_update(rig["coordinator"], blocker.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], blocker.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], blocker.id, status=TicketStatus.in_progress)
    assert board.ticket(succ.id).status == TicketStatus.signed_off    # held while blocker unreleased
    crit = board.criteria(blocker.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    assert board.ticket(blocker.id).status == TicketStatus.in_review  # auto: evidence complete
    assert board.ticket(succ.id).status == TicketStatus.ready         # released before any verdict
    board.criterion_update(rig["qa"], crit.id, verdict=Verdict.failed)
    board.ticket_update(rig["qa"], blocker.id, status=TicketStatus.in_progress)
    assert board.ticket(blocker.id).status == TicketStatus.in_progress
    assert board.ticket(succ.id).status == TicketStatus.ready         # NOT re-blocked


def test_successor_not_released_while_a_criterion_lacks_evidence(board, rig):
    epic = make_epic(board, rig)
    blocker = make_story(board, rig, epic)
    succ = make_story(board, rig, epic)
    board.ticket_update(rig["architect"], blocker.id, design_ref=design_doc(board, rig, epic.id).id)
    c1 = board.criterion_create(rig["architect"], ticket_id=blocker.id, text="a", check=Check.command)
    board.criterion_create(rig["architect"], ticket_id=blocker.id, text="b", check=Check.command)  # no evidence
    board.ticket_update(rig["architect"], blocker.id, status=TicketStatus.designed)
    board.ticket_update(rig["owner"], blocker.id, status=TicketStatus.signed_off)
    advance_to_designed(board, rig, succ, design_doc(board, rig, epic.id), checked_by="qa")
    # the blocks link must exist BEFORE succ is signed off, or succ auto-readies with no blocker
    board.link_create(rig["architect"], from_id=blocker.id, to_id=succ.id, relation=Relation.blocks)
    board.ticket_update(rig["owner"], succ.id, status=TicketStatus.signed_off)
    board.ticket_update(rig["coordinator"], blocker.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], blocker.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], blocker.id, status=TicketStatus.in_progress)
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(rig["engineer"], c1.id, evidence_ref=ev.id)  # only one of two
    with pytest.raises(BoardError):
        board.ticket_update(rig["engineer"], blocker.id, status=TicketStatus.in_review)
    assert board.ticket(succ.id).status == TicketStatus.signed_off


# ------------------------------------------------------------------ §24.1 caps

def test_story_cap_ninth_refused_with_scope_code_and_hint(board, rig):
    epic = make_epic(board, rig)
    for _ in range(8):
        make_story(board, rig, epic)
    with pytest.raises(BoardError) as ei:
        make_story(board, rig, epic)
    assert ei.value.code == "scope" and "8 open stories" in ei.value.message
    assert "scope`" in ei.value.hint and "split the epic" in ei.value.hint


def test_task_cap_sixth_refused(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    for i in range(5):
        board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                            title=f"t{i}", parent_id=story.id)
    with pytest.raises(BoardError) as ei:
        board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                            title="t6", parent_id=story.id)
    assert ei.value.code == "scope" and "at most 5 tasks" in ei.value.message


def test_task_without_criterion_cannot_leave_drafted(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    task = board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                               title="t", parent_id=story.id)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["engineer"], task.id, status=TicketStatus.designed)
    assert ei.value.code == "transition" and "criterion" in ei.value.message


def test_criteria_cap_seventh_refused_on_unfolded_story_folded_exempt(board, rig):
    epic = make_epic(board, rig)
    story = make_story(board, rig, epic)
    for i in range(6):
        board.criterion_create(rig["architect"], ticket_id=story.id, text=f"c{i}", check=Check.command)
    with pytest.raises(BoardError) as ei:
        board.criterion_create(rig["architect"], ticket_id=story.id, text="c7", check=Check.command)
    assert ei.value.code == "scope" and "at most 6" in ei.value.message
    folded = make_story(board, rig, epic)
    board.criterion_create(rig["architect"], ticket_id=folded.id, text="(from S1) inherited a",
                           check=Check.command)
    for i in range(8):  # a folded story is exempt from the fresh-criteria cap
        board.criterion_create(rig["architect"], ticket_id=folded.id, text=f"f{i}", check=Check.command)


def test_design_signoff_refused_when_epic_over_story_cap(board, rig):
    epic = make_epic(board, rig)
    for _ in range(8):
        make_story(board, rig, epic)
    board.gate_open(epic.id, Gate.scope, by="architect")
    board.gate_answer(rig["owner"], epic.id, Gate.scope, "raise the cap")
    make_story(board, rig, epic)  # 9th now allowed by the scope raise
    assert len(board._open_stories(epic.id)) == 9
    with pytest.raises(BoardError) as ei:
        board.gate_open(epic.id, Gate.design_signoff, by="architect")
    assert ei.value.code == "scope" and "9 open stories" in ei.value.message

def test_auto_advance_and_release_wait_for_the_doers_consult(board, rig, tmp_path, monkeypatch):
    """A story whose evidence is complete is NOT auto-advanced (and its successor NOT released)
    while the doer's own consult on it is in flight; the consult's thread note re-evaluates."""
    from edp8 import consult as consult_mod
    monkeypatch.setenv("EDP8_SOL_LOG_DIR", str(tmp_path))
    epic = make_epic(board, rig)
    blocker = make_story(board, rig, epic)
    succ = make_story(board, rig, epic)
    advance_to_designed(board, rig, blocker, design_doc(board, rig, epic.id), checked_by="qa")
    board.ticket_update(rig["owner"], blocker.id, status=TicketStatus.signed_off)
    advance_to_designed(board, rig, succ, design_doc(board, rig, epic.id), checked_by="qa")
    board.link_create(rig["architect"], from_id=blocker.id, to_id=succ.id, relation=Relation.blocks)
    board.ticket_update(rig["owner"], succ.id, status=TicketStatus.signed_off)
    board.ticket_update(rig["coordinator"], blocker.id, status=TicketStatus.ready)
    board.ticket_update(rig["coordinator"], blocker.id, assignee=rig["engineer"].id)
    board.ticket_update(rig["engineer"], blocker.id, status=TicketStatus.in_progress)
    consult_mod.inflight_mark(blocker.id, "run-1", rig["engineer"].id)
    crit = board.criteria(blocker.id)[0]
    ev = board.doc_create(rig["engineer"], doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
    board.criterion_update(rig["engineer"], crit.id, evidence_ref=ev.id)
    assert board.ticket(blocker.id).status == TicketStatus.in_progress   # held
    assert board.ticket(succ.id).status == TicketStatus.signed_off       # not released
    consult_mod.inflight_clear(blocker.id)
    board.message_send(rig["engineer"], ticket_id=blocker.id, to=None, kind=MessageKind.note,
                       text="consultant[second_opinion]: fine")
    assert board.ticket(blocker.id).status == TicketStatus.in_review     # advanced on the note
    assert board.ticket(succ.id).status == TicketStatus.ready            # released once


def test_a_foreign_board_never_spawns_on_the_fleet_pool(tmp_path, monkeypatch):
    """A board whose EDP8_HOME is not the pool's agent home (an e2e temp board, a private instance)
    is refused at the one spawn choke point, before any pool call (2026-09-08: an e2e board spawned
    qa.epic-2b3bea99e0 on the fleet pool for an epic that existed only in its temp DB)."""
    from edp8 import pool_adapter
    calls: list[str] = []
    monkeypatch.setattr(pool_adapter, "_post", lambda path, body=None, timeout=90.0: calls.append(path) or {"ok": True})
    monkeypatch.setenv("EDP_POOL_AGENT_HOME", str(tmp_path / "fleet"))
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "e2e-home"))
    out = pool_adapter.spawn("qa", "qa.epic-x")
    assert out["ok"] is False and out["error"]["code"] == "foreign_board"
    assert calls == []
    monkeypatch.setenv("EDP8_HOME", str(tmp_path / "fleet"))
    assert pool_adapter.foreign_board_reason() is None
    assert pool_adapter.spawn("qa", "qa.epic-x")["ok"] is True and calls == ["/v1/spawn"]
    monkeypatch.delenv("EDP_POOL_AGENT_HOME")
    monkeypatch.delenv("EDP_AGENT_HOME", raising=False)
    assert pool_adapter.foreign_board_reason() is None  # no pool home known: the launcher's call

