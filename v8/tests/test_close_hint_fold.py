"""s-3c858b31b4 (architect m-65df772509): one seat close gives the epic architect ONE hint. A qa close once cost 14
architect turns: a shell_dead, 2 qa_checker_dead and 10 closed_seat_message, almost all for messages qa had acted on.
The close now emits one `closed_seat_message` that lists the unread messages and carries the dead-qa criteria; a message
the seat read (message_read or the inbox), answered, or that was posted before its run began is left out.
c-a7059e9d27 overlap (adversary report-171c63dc8f): a message landing inside the close race window is named by exactly
one hint, whichever of the send path and the close path gets there."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.schemas import EventKind, Role, TicketKind, TicketStatus, WorkType
from edp8.service import create_app
from edp8.store import Store
from test_stuck_criteria import StubPool, alive, die, hold, to_in_review


@pytest.fixture
def b(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    return Board(Store(":memory:"), pool=StubPool(), free_mb=lambda: 4096)


@pytest.fixture
def r(b):
    out = {"owner": b.participant_create("human", Role.owner, "owner", id_="owner"),
           "engineer": b.participant_create("agent", Role.engineer, "engineer.story", id_="engineer.story")}
    out["epic"] = b.ticket_create(out["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E")
    out["architect"] = b.participant_create("agent", Role.architect, f"architect.{out['epic'].id}",
                                            id_=f"architect.{out['epic'].id}")
    out["qa"] = b.participant_create("agent", Role.qa, f"qa.{out['epic'].id}", id_=f"qa.{out['epic'].id}")
    return out


def _hints(b, *kinds):
    return [e for e in b.store.query("event", {"kind": EventKind.board_hint}, limit=500)
            if e.data.get("hint") in (kinds or ("closed_seat_message", "qa_checker_dead"))]


def _steer(b, r, ticket_id, to, text="go", sender="architect"):
    return b.message_send(r[sender], ticket_id=ticket_id, to=to.id, kind="steer", text=text).id


def _two_stories_in_review(b, r):
    """Two handed-over stories with a qa-checked line each, the epic held open so nothing else fires."""
    hold(b, r)
    stories = [b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title=f"S{i}",
                               parent_id=r["epic"].id) for i in range(2)]
    crits = [to_in_review(b, r, s, r["engineer"]) for s in stories]
    for k in b.children(r["epic"].id):
        if k.title == "hold":
            b.ticket_update(r["architect"], k.id, status=TicketStatus.dropped)
    return stories, crits


def test_the_qa_close_flood_is_one_hint(b, r):
    """Replay of the 12:06:33Z qa close: 12 messages to the seat and two stories' qa lines pending -> ONE hint."""
    stories, crits = _two_stories_in_review(b, r)
    qa, epic = r["qa"], r["epic"]
    before = [_steer(b, r, epic.id, qa, f"spawn steer {i}") for i in range(2)]  # posted before the run: the seat has them
    b._pending_pairings.clear()
    alive(b, qa.id, epic.id)
    seen = [_steer(b, r, stories[0].id, qa, f"seen {i}") for i in range(4)]
    answered = [_steer(b, r, stories[1].id, qa, f"answered {i}") for i in range(3)]
    unread = [_steer(b, r, epic.id, qa, f"unread {i}") for i in range(3)]
    b.note_seen(qa, seen)
    for m in answered:
        b.message_send(qa, ticket_id=stories[1].id, to=r["architect"].id, kind="answer", text="done", reply_to=m)
    die(b, qa.id, epic.id)
    [hint] = _hints(b)
    assert hint.data["hint"] == "closed_seat_message" and hint.data["seat"] == qa.id
    assert sorted(hint.data["messages"]) == sorted(unread)
    assert not set(hint.data["messages"]) & {*before, *seen, *answered}
    assert sorted(hint.data["criteria"]) == sorted(c.id for c in crits)  # the dead-qa lines are folded in
    assert qa.id in hint.data["text"] and all(c.id in hint.data["text"] for c in crits)
    assert not _hints(b, "qa_checker_dead")


def test_a_close_with_nothing_unread_keeps_one_qa_checker_dead_hint(b, r):
    stories, crits = _two_stories_in_review(b, r)
    b._pending_pairings.clear()
    alive(b, r["qa"].id, r["epic"].id)
    die(b, r["qa"].id, r["epic"].id)
    [hint] = _hints(b)  # two stories, one close: one hint, not one per ticket
    assert hint.data["hint"] == "qa_checker_dead" and hint.data["seat"] == r["qa"].id
    assert sorted(hint.data["criteria"]) == sorted(c.id for c in crits)


def test_messages_the_seat_read_or_that_predate_its_run_or_whose_phase_moved_are_left_out(b, r):
    eng, epic = r["engineer"], r["epic"]
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=epic.id)
    before = _steer(b, r, story.id, eng, "spawn steer")
    alive(b, eng.id, story.id)
    read = _steer(b, r, story.id, eng, "read via message_read")
    listed = _steer(b, r, story.id, eng, "listed in the inbox")
    # the real read paths, through the API: message_read and the inbox (it receipts every ask it lists)
    import os
    os.environ.setdefault("EDP8_EMBEDDER", "none")
    client = TestClient(create_app(b, admin_token="t"))
    h = {"X-Participant": eng.id}
    assert client.get(f"/v1/messages/{read}", headers=h).json()["ok"]
    assert client.get("/v1/inbox", headers=h).json()["ok"]
    moved = _steer(b, r, story.id, eng, "asked while drafted")  # after the inbox call: no receipt
    assert b.store.get("message", moved).ask_phase == "drafted"
    t = b.store.get("ticket", story.id)  # the ticket moves past the phase it was asked in (set directly: the walk needs a design)
    t.status = TicketStatus.designed
    b.store.put("ticket", t)
    unread = _steer(b, r, story.id, eng, "nobody read this")
    die(b, eng.id, story.id)
    [hint] = _hints(b)
    assert hint.data["messages"] == [unread]
    assert not {before, read, listed, moved} & set(hint.data["messages"])


def test_overlap_a_message_inside_the_close_race_window_is_named_by_exactly_one_hint(b, r):
    """c-a7059e9d27 / report-171c63dc8f: the message is sent while the seat is alive (so the send path says nothing),
    the close lands, then the send path's own check runs again: one hint names it, never two, never none."""
    eng = r["engineer"]
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    alive(b, eng.id, story.id)
    mid = _steer(b, r, story.id, eng, "lands in the window")
    assert not _hints(b, "closed_seat_message")  # alive: the send path stays quiet
    die(b, eng.id, story.id, reason="closed by owner")
    named = lambda: [e for e in _hints(b, "closed_seat_message")  # noqa: E731
                     if mid in (e.data.get("messages") or []) or e.data.get("message") == mid]
    assert len(named()) == 1
    # the send path's own check, run after the close (the race): deduped against the per-close hint
    assert b.hint_closed_seat_message(b.store.get("message", mid), eng.id) is False
    # and the close sweep again (a repeat mirror, or the pool replaying the death): still one
    b._hint_messages_lost_to_close(eng.id, b.store.get("session", f"s-{eng.id}").started_seq)
    assert len(named()) == 1
    # the other order: the send path got there first (the seat was already closing), then the close lands
    story2 = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S2",
                             parent_id=r["epic"].id)
    alive(b, eng.id, story2.id, sid="s-two")
    mid2 = _steer(b, r, story2.id, eng, "send path first")
    assert b.hint_closed_seat_message(b.store.get("message", mid2), eng.id) is True
    die(b, eng.id, story2.id, sid="s-two", reason="closed by owner")
    again = [e for e in _hints(b, "closed_seat_message") if mid2 in (e.data.get("messages") or []) or e.data.get("message") == mid2]
    assert len(again) == 1


def _second_epic(b, r):
    """A second epic with its own architect, qa seat and a handed-over story."""
    epic = b.ticket_create(r["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title="E2")
    arch = b.participant_create("agent", Role.architect, f"architect.{epic.id}", id_=f"architect.{epic.id}")
    qa = b.participant_create("agent", Role.qa, f"qa.{epic.id}", id_=f"qa.{epic.id}")
    eng = b.participant_create("agent", Role.engineer, "engineer.story2", id_="engineer.story2")
    r2 = {"owner": r["owner"], "architect": arch, "engineer": eng, "qa": qa, "epic": epic}
    hold(b, r2)
    story = b.ticket_create(arch, kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=epic.id)
    crit = to_in_review(b, r2, story, eng)
    for k in b.children(epic.id):
        if k.title == "hold":
            b.ticket_update(arch, k.id, status=TicketStatus.dropped)
    return r2, story, crit


def test_two_closes_at_once_on_two_epics_each_hint_carries_only_its_own(b, r, tmp_path):
    """The fold is per close (a ContextVar), not Board state: with request handlers in a threadpool, a close on another
    epic running at the same moment must neither join this close's hint nor lose its own criteria."""
    import threading
    stories, crits = _two_stories_in_review(b, r)
    r2, story2, crit2 = _second_epic(b, r)
    qa1, qa2 = r["qa"], r2["qa"]
    b._pending_pairings.clear()
    alive(b, qa1.id, r["epic"].id)
    alive(b, qa2.id, r2["epic"].id)
    m1 = _steer(b, r, r["epic"].id, qa1, "for qa one")
    m2 = _steer(b, r2, r2["epic"].id, qa2, "for qa two", sender="architect")
    barrier = threading.Barrier(2)
    real = b._hint_messages_lost_to_close

    def meet(participant_id, started_seq):  # both closes are inside their fold here, at the same moment
        barrier.wait(timeout=10)
        real(participant_id, started_seq)

    b._hint_messages_lost_to_close = meet
    errors: list[BaseException] = []

    def close(seat, epic_id):
        try:
            die(b, seat.id, epic_id)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=close, args=(qa1, r["epic"].id)),
               threading.Thread(target=close, args=(qa2, r2["epic"].id))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not errors, errors
    by_seat = {h.data["seat"]: h for h in _hints(b)}
    assert set(by_seat) == {qa1.id, qa2.id}
    assert by_seat[qa1.id].data["messages"] == [m1] and sorted(by_seat[qa1.id].data["criteria"]) == sorted(c.id for c in crits)
    assert by_seat[qa2.id].data["messages"] == [m2] and by_seat[qa2.id].data["criteria"] == [crit2.id]


def _listener_receipt(b, client, eng, mid, *, age_s=0):
    """What the feed listener does after it prints a message: POST /v1/messages/seen as the seat. `age_s` backdates the
    receipt, as if it had been printed that long before."""
    from datetime import timedelta
    r1 = client.post("/v1/messages/seen", json={"ids": [mid]}, headers={"X-Participant": eng.id}).json()
    assert r1["ok"], r1
    for e in b.store.query("event", {"subject_id": mid, "kind": EventKind.message_seen}, limit=5):
        assert e.data == {"by": eng.id, "via": "listener"}
        if age_s:
            b.store.put("event", e.model_copy(update={"created_at": e.created_at - timedelta(seconds=age_s)}))


def _listener_rig(b, r):
    import os
    os.environ.setdefault("EDP8_EMBEDDER", "none")
    eng = r["engineer"]
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    alive(b, eng.id, story.id)
    return eng, story, TestClient(create_app(b, admin_token="t"))


def test_a_message_printed_5s_before_death_is_still_hinted(b, r):
    """c-a7059e9d27: a listener receipt means PRINTED, not acted on. Printed, then the seat dies 5 s later: not lost."""
    eng, story, client = _listener_rig(b, r)
    printed = b.message_send(r["architect"], ticket_id=story.id, to=eng.id, kind="note", text="printed, then death").id
    _listener_receipt(b, client, eng, printed, age_s=5)
    die(b, eng.id, story.id)
    [hint] = _hints(b)
    assert hint.data["messages"] == [printed]


def test_a_message_printed_10_min_before_death_with_no_reply_is_not_hinted(b, r):
    eng, story, client = _listener_rig(b, r)
    printed = b.message_send(r["architect"], ticket_id=story.id, to=eng.id, kind="note", text="FYI, acted on").id
    unseen = b.message_send(r["architect"], ticket_id=story.id, to=eng.id, kind="note", text="never printed").id
    _listener_receipt(b, client, eng, printed, age_s=600)
    die(b, eng.id, story.id)
    [hint] = _hints(b)
    assert hint.data["messages"] == [unseen]  # the old printed one is out, the never-printed one is in


def test_a_message_printed_seconds_ago_is_not_hinted_when_the_seat_posted_after_it(b, r):
    eng, story, client = _listener_rig(b, r)
    printed = b.message_send(r["architect"], ticket_id=story.id, to=eng.id, kind="note", text="acted on").id
    _listener_receipt(b, client, eng, printed, age_s=5)
    b.message_send(eng, ticket_id=story.id, to=r["architect"].id, kind="note", text="working on it")
    die(b, eng.id, story.id)
    assert _hints(b) == []


def test_a_read_receipt_counts_at_once_whatever_its_age(b, r):
    eng, story, client = _listener_rig(b, r)
    read = b.message_send(r["architect"], ticket_id=story.id, to=eng.id, kind="note", text="read just now").id
    assert client.get(f"/v1/messages/{read}", headers={"X-Participant": eng.id}).json()["ok"]
    die(b, eng.id, story.id)
    assert _hints(b) == []


def test_context_asks_for_me_writes_the_read_receipt(b, r):
    eng = r["engineer"]
    story = b.ticket_create(r["architect"], kind=TicketKind.story, work_type=WorkType.feature, title="S",
                            parent_id=r["epic"].id)
    b.ticket_update(r["architect"], story.id, assignee=eng.id)
    alive(b, eng.id, story.id)
    ask = _steer(b, r, story.id, eng, "listed by context()")
    out = b.context(eng)
    assert [a["id"] for a in out["asks_for_me"]] == [ask] and b.was_seen(ask, eng.id)
