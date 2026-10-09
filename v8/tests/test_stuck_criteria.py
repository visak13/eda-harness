"""e0cec S3 (owner R3, dec-49f1f6a911, design-b6a55eed13 §4.A): a pending criterion no seat can clear, for ANY reason,
falls to a requeued checker of its role, then to the epic's resident architect (with its reason recorded). Only a
criterion the owner set to checked_by=owner ever reaches the owner. Pains p-892b786f, p-3eba4926, p-c3c5d460."""
from __future__ import annotations

import pytest

from asks_support import serve
from edp8.board import Board, BoardError
from edp8.schemas import (
    Check,
    DocType,
    EventKind,
    Gate,
    Role,
    SessionState,
    StatusValue,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)
from edp8.store import Store


class StubPool:
    def __init__(self):
        self.spawns: list[tuple[str, str]] = []
        self.resumes: list[str] = []

    def resume(self, participant_id):
        self.resumes.append(participant_id)
        return {"ok": True, "resumed": True}

    def spawn(self, role, participant_id, **kw):
        self.spawns.append((role, participant_id))
        return {"ok": True, "participant_id": participant_id}


@pytest.fixture
def b():
    return Board(Store(":memory:"), pool=StubPool(), free_mb=lambda: 4096)


@pytest.fixture
def r(b):
    out = {"owner": b.participant_create("human", Role.owner, "owner", id_="owner"),
           "engineer": b.participant_create("agent", Role.engineer, "engineer.story", id_="engineer.story"),
           "qa": b.participant_create("agent", Role.qa, "qa.x", id_="qa.x")}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    out["architect"] = b.participant_create("agent", Role.architect, f"architect.{out['epic'].id}",
                                            id_=f"architect.{out['epic'].id}")
    return out


def alive(b, pid, ticket_id, sid=None, state=SessionState.alive):
    b.session_upsert(id_=sid or f"s-{pid}", participant_id=pid, ticket_id=ticket_id, pool_id="pool", state=state)


def die(b, pid, ticket_id, sid=None, reason=""):
    b.session_upsert(id_=sid or f"s-{pid}", participant_id=pid, ticket_id=ticket_id, pool_id="pool",
                     state=SessionState.dead, reason=reason)


def hold(b, r):
    """A drafted sibling, so no single in_review story releases the whole epic and opens its acceptance gate."""
    b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="hold",
                    parent_id=r["epic"].id)


def to_in_review(b, r, ticket, doer, *, check=Check.command, checked_by=None, evidence=True, assignee=True):
    """Walk a ticket (with one criterion) to a handed-over in_review."""
    epic = r["epic"]
    if checked_by:  # the owner's override (e0cec S6: a Standard knowledge line is the sme's unless the owner keeps it)
        crit = b.criterion_create(r["owner"], ticket_id=ticket.id, text="c", check=check, checked_by=checked_by,
                                  override_reason="the owner keeps this line")
    else:
        crit = b.criterion_create(r["architect"] if ticket.kind != TicketKind.task else r["engineer"], ticket_id=ticket.id,
                                  text="c", check=check)
    d = b.doc_create(r["architect"], doc_type=DocType.design, title="d", body_md="b", scope=epic.id)
    if ticket.kind != TicketKind.task:
        b.ticket_update(r["architect"], ticket.id, design_ref=d.id)
    b.ticket_update(r["architect"], ticket.id, status=TicketStatus.designed)
    b.ticket_update(r["owner"], ticket.id, status=TicketStatus.signed_off)
    b.ticket_update(r["architect"], ticket.id, status=TicketStatus.ready)
    if assignee:
        b.ticket_update(r["architect"], ticket.id, assignee=doer.id)
    b.ticket_update(doer, ticket.id, status=TicketStatus.in_progress)
    if evidence:
        ev = b.doc_create(doer, doc_type=DocType.report, title="e", body_md="ok", scope=epic.id)
        b.criterion_update(doer, crit.id, evidence_ref=ev.id)
    b.ticket_update(doer, ticket.id, status=TicketStatus.in_review)
    return b.criterion_update(doer, crit.id) if False else b.store.get("criterion", crit.id)


def story_and_task(b, r):
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    task = b.ticket_create(r["engineer"], kind=TicketKind.task, work_type=WorkType.feature, title="T",
                           parent_id=story.id, serves=serve(b, story.id))
    return story, task


def task_in_review(b, r, *, assignee=True):
    hold(b, r)
    story, task = story_and_task(b, r)
    if assignee:
        alive(b, r["engineer"].id, story.id)  # the doer's seat is up while it hands over
    c = to_in_review(b, r, task, r["engineer"], assignee=assignee)
    return story, task, c


# ------------------------------------------------------------------ the causes


def test_a_task_line_is_not_stuck_while_its_engineer_is_alive(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    assert c.checked_by == "engineer" and b.stuck_cause(c) is None


def test_checker_dead_when_the_engineer_closes(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)  # p-3eba4926 / p-c3c5d460: the engineer closed with the line pending
    assert b.stuck_cause(c) == "checker_dead"


def test_a_dead_engineer_gets_a_fresh_checker_queued_event_only(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    assert not b._pending_pairings
    die(b, r["engineer"].id, story.id)  # the death event queues it
    assert list(b._pending_pairings) == [f"engineer.{task.id}"]
    assert b._pending_pairings[f"engineer.{task.id}"]["ticket"] == task.id
    out = b.run_pending_pairings()
    assert out["spawned"] == [f"engineer.{task.id}"] and b._pool.spawns == [("engineer", f"engineer.{task.id}")]
    ev = [e for e in b.store.query("event", {"subject_id": task.id, "kind": EventKind.checker_requeued})]
    assert len(ev) == 1 and ev[0].data["criteria"] == [c.id] and ev[0].data["cause"] == "checker_dead"


def test_the_fresh_engineer_checker_can_clear_the_line_and_the_task_finishes(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    b.run_pending_pairings()
    fresh = b.store.get("participant", f"engineer.{task.id}")
    alive(b, fresh.id, task.id)
    assert b.stuck_cause(c) is None  # a live checker exists again
    b.criterion_update(fresh, c.id, verdict=Verdict.passed, note="re-ran the command: green")
    assert b.ticket(task.id).status == TicketStatus.done


def test_no_requeue_at_boot(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    b._pending_pairings.clear()
    reopened = Board(b.store, pool=b._pool, free_mb=lambda: 4096)  # S14: a boot derives nothing for a stuck line
    assert reopened._pending_pairings == {}


def test_handoff_queues_a_checker_when_none_is_alive(b, r):
    hold(b, r)
    story, task = story_and_task(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)  # the engineer's seat is already gone when the task is handed over
    to_in_review(b, r, task, r["engineer"])
    assert f"engineer.{task.id}" in b._pending_pairings


def test_placeholder_doer(b, r):
    story, task, c = task_in_review(b, r, assignee=False)  # nobody was ever assigned or spawned for the task
    assert b.stuck_cause(c) == "placeholder_doer"
    assert f"engineer.{task.id}" in b._pending_pairings or b.requeue_checkers(b.ticket(task.id))


def test_doer_guard_when_the_only_checker_is_the_doer(b, r):
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    c = to_in_review(b, r, story, r["engineer"])
    b.store.put("ticket", b.ticket(story.id).model_copy(update={"assignee": r["qa"].id}))  # qa became its doer
    alive(b, r["qa"].id, r["epic"].id)
    b.gate_open(r["epic"].id, Gate.acceptance)  # qa_ready: the epic is at acceptance
    b._pending_pairings.clear()
    assert b.stuck_cause(c) == "doer_guard"
    assert b.requeue_checkers(b.ticket(story.id)) == [f"qa.{r['epic'].id}"]  # a different qa seat is queued


def test_qa_line_is_waiting_not_stuck_before_the_epic_is_ready(b, r):
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    c = to_in_review(b, r, story, r["engineer"])
    assert c.checked_by == "qa" and b.stuck_cause(c) is None and not b._pending_pairings


def test_qa_dead_at_acceptance_is_requeued_once_ready(b, r):
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    c = to_in_review(b, r, story, r["engineer"])
    for k in b.children(r["epic"].id):  # S4 C1: qa is ready only once every story is handed over, so the hold goes
        if k.title == "hold":
            b.ticket_update(r["architect"], k.id, status=TicketStatus.dropped)
    qa = f"qa.{r['epic'].id}"
    b.participant_create("agent", Role.qa, qa, id_=qa)
    b._pending_pairings.clear()
    alive(b, qa, r["epic"].id)
    assert b.stuck_cause(c) is None
    die(b, qa, r["epic"].id)  # qa closed with a line pending
    # c-4ecf4e135a: stuck, but the board queues no replacement; the architect gets ONE hint naming seat + criteria
    assert b.stuck_cause(c) == "checker_dead" and not b._pending_pairings
    hints = _qa_dead_hints(b, story.id)
    assert len(hints) == 1 and hints[0].data["seat"] == qa and c.id in hints[0].data["criteria"]
    assert qa in hints[0].data["text"] and c.id in hints[0].data["text"]
    b.requeue_checkers(b.ticket(story.id))  # a repeat of the same pending set adds no second hint
    assert len(_qa_dead_hints(b, story.id)) == 1 and not b._pending_pairings


@pytest.mark.parametrize("reason", ["closed by self: deferred", "reaped by owner", "interrupted: the pool stopped"])
def test_a_parked_qa_is_not_requeued(b, r, reason):
    # owner m-b0c290f469: a qa told to hold closed itself deferred and the board spawned a new one each time
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    c = to_in_review(b, r, story, r["engineer"])
    for k in b.children(r["epic"].id):
        if k.title == "hold":
            b.ticket_update(r["architect"], k.id, status=TicketStatus.dropped)
    qa = f"qa.{r['epic'].id}"
    b.participant_create("agent", Role.qa, qa, id_=qa)
    b._pending_pairings.clear()
    alive(b, qa, r["epic"].id)
    die(b, qa, r["epic"].id, reason=reason)
    assert b.stuck_cause(c) == "checker_dead" and not b._pending_pairings


def _qa_dead_hints(b, ticket_id):
    return [e for e in b.store.query("event", {"subject_id": ticket_id, "kind": EventKind.board_hint}, limit=50)
            if e.data.get("hint") == "qa_checker_dead"]


def test_a_dead_qa_is_neither_resumed_nor_spawned_by_the_board(b, r):
    # c-4ecf4e135a (was owner m-3b722c0a38): the board no longer resumes or spawns qa; the architect decides
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    to_in_review(b, r, story, r["engineer"])
    for k in b.children(r["epic"].id):
        if k.title == "hold":
            b.ticket_update(r["architect"], k.id, status=TicketStatus.dropped)
    qa = f"qa.{r['epic'].id}"
    b.participant_create("agent", Role.qa, qa, id_=qa)
    b._pending_pairings.clear()
    alive(b, qa, r["epic"].id)
    die(b, qa, r["epic"].id, reason="crashed")
    pool = b._pool
    pool.spawns.clear()
    b.run_pending_pairings()
    assert pool.resumes == [] and (Role.qa.value, qa) not in pool.spawns
    assert len(_qa_dead_hints(b, story.id)) == 1


def test_a_checker_that_never_ran_is_not_resumed(b, r):
    qa = f"qa.{r['epic'].id}"
    assert b._resume_saved_seat(qa) is False and b._pool.resumes == []  # no saved session: the caller spawns fresh


def test_cannot_clear_is_recorded_when_the_right_role_is_refused(b, r):
    hold(b, r)
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    c = to_in_review(b, r, story, r["engineer"])
    b.gate_open(r["epic"].id, Gate.acceptance)
    alive(b, r["qa"].id, r["epic"].id)
    assert b.stuck_cause(c) is None
    b.store.put("ticket", b.ticket(story.id).model_copy(update={"assignee": r["qa"].id}))  # the guard will refuse qa
    with pytest.raises(BoardError):
        b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)
    assert b.stuck_cause(c) == "doer_guard" or b.stuck_cause(c) == "cannot_clear"
    assert b.store.query("event", {"subject_id": c.id, "kind": EventKind.criterion_verdict_refused})


def test_a_wrong_role_refusal_is_not_cannot_clear(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    with pytest.raises(BoardError):
        b.criterion_update(r["qa"], c.id, verdict=Verdict.passed)  # qa is not the checker of a task line
    assert b.stuck_cause(c) is None
    assert not b.store.query("event", {"subject_id": c.id, "kind": EventKind.criterion_verdict_refused})


# ------------------------------------------------------------------ the architect, the last link


def test_the_resident_architect_clears_a_stuck_line_with_its_reason(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    out = b.criterion_update(r["architect"], c.id, verdict=Verdict.passed, note="qa proved it in report-x")
    assert out.verdict == Verdict.passed and b.ticket(task.id).status == TicketStatus.done
    ev = [e for e in b.store.query("event", {"subject_id": task.id, "kind": EventKind.criterion_checked})][-1]
    assert ev.data["fallback"] == "architect" and ev.data["cause"] == "checker_dead"
    assert ev.data["reason"] == "qa proved it in report-x" and ev.data["by"] == r["architect"].id


def test_the_architect_without_a_reason_is_advised_and_the_verdict_stands(b, r):
    from edp8 import advice
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    advice.take()
    b.criterion_update(r["architect"], c.id, verdict=Verdict.passed)
    assert any("reason" in said for said in advice.take())
    assert b.store.get("criterion", c.id).verdict == Verdict.passed


def test_the_architect_cannot_clear_a_line_that_is_not_stuck(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)  # the engineer is alive: not stuck
    with pytest.raises(BoardError):
        b.criterion_update(r["architect"], c.id, verdict=Verdict.passed, note="skip the engineer")


def test_another_architect_may_not_use_the_fallback(b, r):
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    other = b.participant_create("agent", Role.architect, "architect.other", id_="architect.other")
    with pytest.raises(BoardError):
        b.criterion_update(other, c.id, verdict=Verdict.passed, note="not my epic")


def test_an_owner_checked_line_never_reroutes(b, r):
    hold(b, r)
    kn = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.knowledge, title="kn",
                         parent_id=r["epic"].id)
    c = to_in_review(b, r, kn, r["engineer"], check=Check.look, checked_by="owner")
    assert c.checked_by == "owner"
    assert b.stuck_cause(c) is None
    assert b.requeue_checkers(b.ticket(kn.id)) == [] and not b._pending_pairings
    with pytest.raises(BoardError):
        b.criterion_update(r["architect"], c.id, verdict=Verdict.passed, note="I will clear it")


def test_a_stuck_line_never_reaches_the_owners_attention(b, r):
    from edp8 import attention
    story, task, c = task_in_review(b, r)
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    assert b.stuck_cause(c) == "checker_dead"
    assert [i for i in attention.items(b, r["owner"]) if i["kind"] in ("signoff",)] == []


def test_requeue_is_capped_per_seat(b, r):
    story, task, c = task_in_review(b, r)
    pid = f"engineer.{task.id}"
    alive(b, r["engineer"].id, story.id)
    die(b, r["engineer"].id, story.id)
    for n in range(5):
        b.run_pending_pairings()
        alive(b, pid, task.id, sid="s-fresh")
        die(b, pid, task.id, sid="s-fresh")
        b.store.put("session", b.store.get("session", "s-fresh").model_copy(update={"state": SessionState.dead}))
    seen = [e for e in b.store.query("event", {"subject_id": task.id, "kind": EventKind.checker_requeued})]
    assert len(seen) == Board.REQUEUE_CAP


# ------------------------------------------------------------------ the receipt (p-892b786f)


def test_the_handoff_receipt_names_the_checker(b, r):
    story, task, c = task_in_review(b, r)
    rows = b.checker_receipt(b.ticket(task.id))
    assert rows[0]["checked_by"] == "engineer" and rows[0]["criteria"] == [c.id]
    assert rows[0]["who"] == r["engineer"].id
    die(b, r["engineer"].id, story.id)
    assert "queued" in b.checker_receipt(b.ticket(task.id))[0]["who"]


def test_a_quick_task_receipt_names_the_owner(b, r):
    quick = b.ticket_create(r["owner"], kind=TicketKind.story, work_type=WorkType.feature, title="quick",
                            tags=["quick"], words="do the small thing")
    crit = b.criterion_create(r["engineer"], ticket_id=quick.id, text="it works", check=Check.look)
    assert crit.checked_by == "owner"
    rows = b.checker_receipt(quick)
    assert rows == [{"checked_by": "owner", "criteria": [crit.id], "who": "the owner, on the ticket page"}]


# ------------------------------------------------------------------ record_status honours the inbox (S3 task 5)


def test_record_status_done_with_a_message_waiting_records_and_names_it(b, r):
    from edp8 import advice
    story, task, c = task_in_review(b, r)
    b.message_send(r["architect"], to=r["engineer"].id, kind="steer", text="change the plan", ticket_id=story.id)
    advice.take()
    b.record_status(r["engineer"], status=StatusValue.done, ticket_id=story.id, note="finished")
    [said] = advice.take()
    assert "1 message(s) still await you" in said and "change the plan" in said and "inbox()" in said
    b.record_status(r["engineer"], status=StatusValue.handed_off, ticket_id=story.id, note="over")
    assert advice.take()


def test_record_status_done_passes_with_an_empty_inbox(b, r):
    story, task, c = task_in_review(b, r)
    assert b.inbox(r["engineer"]) == [] or not b.inbox(r["engineer"])
    b.record_status(r["engineer"], status=StatusValue.done, ticket_id=story.id, note="finished")


# ------------------------------------------------------------------ Needs you is owner-only, each row says why


def _owner_rows(b, r):
    from edp8 import attention
    return attention.items(b, r["owner"])


def test_an_ask_to_the_owner_is_listed_but_not_one_to_a_seat(b, r):
    story, task, c = task_in_review(b, r)
    to_owner = b.message_send(r["architect"], ticket_id=story.id, to=r["owner"].id, kind="question", text="pick one?")
    to_seat = b.message_send(r["engineer"], ticket_id=story.id, to=r["architect"].id, kind="question", text="ok?")
    asks = [i for i in _owner_rows(b, r) if i["kind"] == "ask"]
    assert [i["id"] for i in asks] == [to_owner.id]
    assert "work does not wait on it" in asks[0]["why"]
    from edp8 import contextual_work
    shown = contextual_work.contextual_work(b, story.id)["unresolved_asks"]
    assert [a["id"] for a in shown] == [to_owner.id] and shown[0]["why"]
    assert to_seat.id not in [a["id"] for a in shown]


def test_every_attention_row_has_a_why(b, r):
    hold(b, r)
    kn = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.knowledge, title="kn",
                         parent_id=r["epic"].id)
    to_in_review(b, r, kn, r["engineer"], check=Check.look, checked_by="owner")
    b.message_send(r["architect"], ticket_id=kn.id, to=r["owner"].id, kind="steer", text="look here")
    rows = _owner_rows(b, r)
    assert {i["kind"] for i in rows} == {"ask"} and all(i["why"] for i in rows)


def test_a_resumed_checker_gets_the_seats_current_token(b, r):
    # p-451a2390: the resumed shell must authenticate with the secret the board holds now, not the one its pool
    # row stored at the first spawn (a stale token gave the revived qa an MCP server with no tools)
    calls = []

    class TokenPool(StubPool):
        def resume(self, participant_id, env=None):
            calls.append((participant_id, env))
            return {"ok": True, "resumed": True}

    b._pool = TokenPool()
    b._mint_token = lambda handle: "tok-current"
    seat = r["engineer"].id
    alive(b, seat, r["epic"].id)
    die(b, seat, r["epic"].id, reason="crashed")
    assert b._spawn_seat(Role.engineer.value, seat, r["epic"].id) is True
    assert calls == [(seat, {"EDP8_TOKEN": "tok-current"})] and b._pool.spawns == []
