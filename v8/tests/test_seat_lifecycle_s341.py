"""s-341902c31f (design-63db8a7d42 F and G): the owner's Close is "closed by owner" and never a crash; every pool event
(crashed, stalled, closed, resumed) reaches the epic's architect and none pages the owner; a message that races a
close is delivered or hinted, never lost. Private board, stub pool."""
from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from test_board_hints_closed_seat import _rig, _session

from edp8 import broker_adapter, pool_adapter
from edp8.schemas import EventKind, SessionState


def _hints(board, ticket, hint):
    return [e for e in board.store.query("event", {"subject_id": ticket, "kind": EventKind.board_hint}, limit=100)
            if e.data.get("hint") == hint]


def _arch_owner(board, seats):
    return board.store.get("participant", seats["architect"]), board.store.get("participant", "owner")


def test_every_pool_event_kind_reaches_the_architect_and_none_pages_the_owner(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    arch, owner = _arch_owner(board, seats)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    eng = seats["engineer"]

    def last(kind, ticket):
        return board.store.query("event", {"subject_id": ticket, "kind": kind}, limit=100)[-1]

    def reaches(ev):
        return (board.relevant(ev, arch) and "architect_listener" in [x.value for x in board._reason_for(ev, arch)]
                and not board.relevant(ev, owner))

    _session(client, "s-e1", eng, story, "alive")
    _session(client, "s-e1", eng, story, "stalled", "no output")  # stalled
    assert reaches(last(EventKind.shell_stalled, story))
    _session(client, "s-e1", eng, story, "alive")  # resumed (a stall that cleared)
    assert reaches(_hints(board, story, "seat_resumed")[-1])
    _session(client, "s-e1", eng, story, "dead", "process exited without close_self")  # crashed
    ev = last(EventKind.shell_dead, story)
    assert ev.data["clean"] is False and reaches(ev)
    _session(client, "s-e1", eng, story, "alive")  # resumed after a crash
    assert len(_hints(board, story, "seat_resumed")) == 2
    _session(client, "s-e1", eng, story, "dead", "closed by owner")  # closed
    ev = last(EventKind.shell_dead, story)
    assert ev.data["clean"] is True and reaches(ev)


def test_the_pool_notice_goes_to_the_architect_not_the_owner(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    sent = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")
    _session(client, "s-e2", seats["engineer"], story, "alive")
    _session(client, "s-e2", seats["engineer"], story, "dead", "closed by owner")
    assert [(a[1], a[2]) for a in sent if a[0] == "pool"] == [(seats["architect"], "crashed"),
                                                             (seats["architect"], "fyi")]


def test_each_close_of_one_resumed_session_names_its_own_run_on_both_planes(monkeypatch):
    # adversary report-b9c60aeff1 F2: the listener keys a close on (session, run); both planes must carry the same run
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    sent = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    for _ in range(2):
        _session(client, "s-e1", seats["engineer"], story, "alive")
        _session(client, "s-e1", seats["engineer"], story, "dead", "closed by owner")
    deaths = board.store.query("event", {"subject_id": story, "kind": EventKind.shell_dead}, limit=100)
    runs = [e.data["run"] for e in deaths]
    assert len(runs) == 2 and None not in runs and runs[0] != runs[1]
    assert [a[3]["run"] for a in sent if a[0] == "pool"] == runs


def test_close_by_the_owner_is_recorded_closed_by_owner_and_is_no_crash(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    closed = []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: closed.append((pid, reason)) or
                        {"ok": True, "value": {"closed": True, "reason": reason}})
    sent = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    body = {"participant_id": seats["engineer"], "ticket_id": story}
    r = client.post("/v1/sessions/close", json=body, headers={"X-Participant": "owner"}).json()
    assert r["ok"], r
    assert closed == [(seats["engineer"], "closed by owner")]
    _session(client, "s-e1", seats["engineer"], story, "dead", closed[0][1])  # what the pool then mirrors
    row = board.store.get("session", "s-e1")
    assert row.state == SessionState.dead and row.reason == "closed by owner"
    [dead] = board.store.query("event", {"subject_id": story, "kind": EventKind.shell_dead}, limit=10)
    assert dead.data["clean"] is True
    assert not [a for a in sent if a[2] == "crashed"]  # no crash notice
    assert not board._pending_pairings  # a closed-by-owner seat is parked on purpose: nothing is re-queued


def test_only_the_owner_and_the_architect_may_close(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: {"ok": True, "value": {"closed": True}})
    body = {"participant_id": seats["engineer"], "ticket_id": story}
    assert client.post("/v1/sessions/close", json=body, headers={"X-Participant": seats["engineer"]}).status_code == 403
    assert client.post("/v1/sessions/close", json=body, headers={"X-Participant": seats["architect"]}).json()["ok"]


# ---- c-a7059e9d27: a message sent while its recipient closes is never silently lost -----------------------------

def _send(client, story, seat, sender="owner"):
    r = client.post("/v1/messages", json={"ticket_id": story, "kind": "steer", "to": seat, "text": "go"},
                    headers={"X-Participant": sender}).json()
    assert r["ok"], r
    return r["value"]["id"]


def test_a_send_just_before_the_close_is_hinted_when_the_close_lands(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    mid = _send(client, story, seats["engineer"])  # the liveness check passes: the seat is alive
    assert _hints(board, story, "closed_seat_message") == []
    _session(client, "s-e1", seats["engineer"], story, "dead", "closed by owner")  # the close lands after the send
    [h] = _hints(board, story, "closed_seat_message")
    assert h.data["message"] == mid and h.data["seat"] == seats["engineer"]
    arch = board.store.get("participant", seats["architect"])
    assert board.relevant(h, arch)


def test_a_send_just_after_the_close_is_hinted_once_by_the_send_path(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    _session(client, "s-e1", seats["engineer"], story, "dead", "closed by owner")
    mid = _send(client, story, seats["engineer"])
    [h] = _hints(board, story, "closed_seat_message")
    assert h.data["message"] == mid


def _post(client, story, seat, kind, text, **extra):
    r = client.post("/v1/messages", json={"ticket_id": story, "kind": kind, "text": text, **extra},
                    headers={"X-Participant": seat}).json()
    assert r["ok"], r
    return r["value"]["id"]


def _live_rig(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "alive")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    return board, client, epic, story, seats, pool


def _lost(board, story):
    return sorted(m for h in _hints(board, story, "closed_seat_message") for m in (h.data.get("messages") or [h.data["message"]]))


def test_a_message_the_seat_replied_to_or_resolved_leaves_no_hint_but_a_status_post_does_not_hide_one(monkeypatch):
    """Architect ruling on Astra F2: only reply_to / resolves count as handled; a status post is not a reply."""
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    replied = _send(client, story, eng, sender=seats["architect"])
    resolved = _send(client, story, eng, sender=seats["architect"])
    unread = _send(client, story, eng, sender=seats["architect"])
    _post(client, story, eng, "answer", "done", to=seats["architect"], reply_to=replied)
    _post(client, story, eng, "note", "handled the other one", resolves=[resolved])
    _post(client, story, eng, "status", "Boot is active.")  # not an acknowledgement of `unread`
    _session(client, "s-e1", eng, story, "dead", "closed by self: handed_off")
    assert _lost(board, story) == [unread]


def test_a_message_the_seat_cites_by_id_in_its_closing_status_leaves_no_hint(monkeypatch):
    """Live 14:03Z: the adversary's closing status named m-834842a8dc ("accepts F2..., directs this seat to close"),
    yet its close hinted that message as unread. Naming a message by id in its own post is proof the seat read it."""
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    cited = _send(client, story, eng, sender=seats["architect"])
    unread = _send(client, story, eng, sender=seats["architect"])
    _post(client, story, eng, "status", f"[reviewed] report delivered; {cited} directs this seat to close")
    _session(client, "s-e1", eng, story, "dead", "closed by self: reviewed")
    assert _lost(board, story) == [unread]


def test_a_mention_only_message_is_hinted_on_close(monkeypatch):
    """Astra F3: the close sweep and the send path use the same recipient set, mentions included."""
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    mid = _post(client, story, "owner", "note", f"@{eng} Please stop and read this.")
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == [mid]


def test_the_sweep_has_no_row_cap_and_no_age_cutoff_inside_the_run(monkeypatch):
    """Astra F4: 51 unread messages all get a hint, including one older than the old 180 s window."""
    from datetime import timedelta

    from edp8.schemas import now
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    ids = [_send(client, story, eng) for _ in range(51)]
    m = board.store.get("message", ids[0])
    m.created_at = now() - timedelta(hours=2)  # sent long before the close, still inside the run
    board.store.put("message", m)
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == sorted(ids)


def test_a_resume_starts_a_new_window_and_the_sweep_is_idempotent(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    first = _send(client, story, eng)
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == [first]
    _session(client, "s-e1", eng, story, "alive")  # resumed: `first` belongs to the earlier run
    second = _send(client, story, eng)
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == sorted([first, second])
    board._hint_messages_lost_to_close(eng, board.store.get("session", "s-e1").started_seq)
    assert len(_hints(board, story, "closed_seat_message")) == 2


# ---- Astra F1 / F5 / F6 ------------------------------------------------------------------------------------------

def test_f1_an_architect_cannot_close_another_epics_seat_by_naming_its_own_ticket(monkeypatch):
    from edp8.schemas import Role, TicketKind, WorkType
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    closed = []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: closed.append((pid, reason)) or {"ok": True})
    foreign = board.ticket_create(board.participant("owner"), kind=TicketKind.epic, work_type=WorkType.feature,
                                  title="foreign")
    target = f"engineer.{foreign.id}"
    board.participant_create("agent", Role.engineer, target, id_=target)
    _session(client, "foreign", target, foreign.id, "alive")
    headers = {"X-Participant": seats["architect"]}
    for body in ({"participant_id": target, "ticket_id": foreign.id},
                 {"participant_id": target, "ticket_id": story},
                 {"participant_id": target, "ticket_id": story, "reason": "closed by owner"}):
        assert client.post("/v1/sessions/close", headers=headers, json=body).status_code == 403, body
    assert closed == []
    # the same holds for resume and reap, which share the authorisation
    assert client.post("/v1/sessions/reap", headers=headers,
                       json={"participant_id": target, "ticket_id": story}).status_code == 403


def test_f1_a_forged_attribution_is_refused_and_each_actor_is_recorded_as_itself(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    closed = []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: closed.append((pid, reason)) or {"ok": True})
    eng = seats["engineer"]
    body = {"participant_id": eng, "ticket_id": story}
    arch, owner = {"X-Participant": seats["architect"]}, {"X-Participant": "owner"}
    assert client.post("/v1/sessions/close", headers=arch, json={**body, "reason": "closed by owner"}).status_code in (
        400, 403, 409, 422)
    assert client.post("/v1/sessions/close", headers=owner, json={**body, "reason": "closed by architect"}).status_code in (
        400, 403, 409, 422)
    assert closed == []
    assert client.post("/v1/sessions/close", headers=arch, json=body).json()["ok"]
    assert client.post("/v1/sessions/close", headers=owner, json=body).json()["ok"]
    assert client.post("/v1/sessions/close", headers=arch, json={**body, "reason": "wrapping up"}).json()["ok"]
    assert [r for _, r in closed] == ["closed by architect", "closed by owner", "closed by architect: wrapping up"]


def test_f5_an_architects_close_is_clean_and_requeues_nothing(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    sent, requeues = [], []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, reason: {"ok": True})
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    monkeypatch.setattr(board, "_requeue_epic_checkers", lambda ticket: requeues.append(ticket))
    r = client.post("/v1/sessions/close", headers={"X-Participant": seats["architect"]},
                    json={"participant_id": seats["engineer"], "ticket_id": story}).json()
    assert r["ok"], r
    _session(client, "s-e1", seats["engineer"], story, "dead", "closed by architect")
    [dead] = board.store.query("event", {"subject_id": story, "kind": EventKind.shell_dead}, limit=10)
    assert dead.data["clean"] is True and requeues == []
    assert not [a for a in sent if a[2] == "crashed"]


def test_f6_a_parked_seat_that_resumes_is_a_resume_event_for_the_architect(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    arch = board.store.get("participant", seats["architect"])
    _session(client, "s-e1", seats["engineer"], story, "parked")
    assert _hints(board, story, "seat_resumed") == []
    _session(client, "s-e1", seats["engineer"], story, "alive")
    [h] = _hints(board, story, "seat_resumed")
    assert board.relevant(h, arch)
    _session(client, "s-e1", seats["engineer"], story, "alive")  # a repeat of the same state adds nothing
    assert len(_hints(board, story, "seat_resumed")) == 1


def _owner_chat(board, story):
    return [m for m in board.store.query("message", {"to": "owner", "ticket_id": story}, limit=100)
            if m.created_by == "board"]


def test_q1_with_no_live_architect_the_owner_hears_a_crash_and_a_stall_in_plain_chat(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    sent = []
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: sent.append(a) or True)
    _session(client, "s-arch", seats["architect"], epic, "dead", "crashed")  # nobody left to heal
    _session(client, "s-e1", seats["engineer"], story, "alive")
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")
    assert [(a[1], a[2]) for a in sent if a[0] == "pool"][-1] == ("owner", "crashed")
    [chat] = _owner_chat(board, story)  # R4: a durable board message, not only the broker notice
    assert chat.kind.value == "note" and seats["engineer"] in chat.text and "no live architect" in chat.text
    dead = board.store.query("event", {"subject_id": story, "kind": EventKind.shell_dead})[-1]
    assert not board.relevant(dead, board.store.get("participant", "owner"))  # the message is the page, once
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")  # same state
    assert len(_owner_chat(board, story)) == 1
    _session(client, "s-e2", seats["engineer"], story, "alive")
    _session(client, "s-e2", seats["engineer"], story, "stalled", "no output")
    assert len(_owner_chat(board, story)) == 2  # a stall is its own page


def test_q1_a_clean_close_and_a_live_architect_send_the_owner_nothing(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")  # healable
    assert _owner_chat(board, story) == []
    _session(client, "s-arch", seats["architect"], epic, "dead", "crashed")
    _session(client, "s-e2", seats["engineer"], story, "alive")
    _session(client, "s-e2", seats["engineer"], story, "dead", "closed by owner")  # clean
    assert _owner_chat(board, story) == []


def test_r4_a_resume_after_an_owner_page_tells_the_owner_once_and_a_healed_one_tells_nobody(monkeypatch):
    board, client, epic, story, seats, pool = _rig(monkeypatch)
    _session(client, "s-arch", seats["architect"], epic, "dead", "crashed")
    _session(client, "s-e1", seats["engineer"], story, "alive")
    _session(client, "s-e1", seats["engineer"], story, "parked")  # parked, never paged: a resume says nothing
    _session(client, "s-e1", seats["engineer"], story, "alive")
    assert _owner_chat(board, story) == []
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")
    assert len(_owner_chat(board, story)) == 1
    _session(client, "s-e1", seats["engineer"], story, "alive")  # resumed after the page
    chats = _owner_chat(board, story)
    assert len(chats) == 2 and "is running again" in chats[-1].text
    _session(client, "s-e1", seats["engineer"], story, "alive")
    assert len(_owner_chat(board, story)) == 2
    _session(client, "s-e1", seats["engineer"], story, "dead", "process exited without close_self")  # a second crash
    assert len(_owner_chat(board, story)) == 3


@pytest.mark.parametrize("who", ["owner", "architect"])
@pytest.mark.parametrize("reason", ["closed by owner; closed by architect", "closed by owner: closed by architect",
                                    "CLOSED BY Architect", "wrapping up (closed by self)"])
def test_r1_no_caller_reason_may_contain_closed_by(monkeypatch, who, reason):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    closed = []
    monkeypatch.setattr(pool_adapter, "close", lambda pid, r: closed.append((pid, r)) or {"ok": True})
    actor = "owner" if who == "owner" else seats["architect"]
    r = client.post("/v1/sessions/close", headers={"X-Participant": actor},
                    json={"participant_id": seats["engineer"], "ticket_id": story, "reason": reason})
    assert r.status_code in (400, 403, 409, 422) and closed == []


def test_r2_a_status_post_never_marks_a_message_handled_even_with_reply_to_or_resolves(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    by_reply = _send(client, story, eng, sender=seats["architect"])
    by_resolve = _send(client, story, eng, sender=seats["architect"])
    _post(client, story, eng, "status", "Booting; not acted on.", reply_to=by_reply)
    _post(client, story, eng, "status", "Booting; not acted on.", resolves=[by_resolve])
    _session(client, "s-e1", eng, story, "dead", "closed by self: handed_off")
    assert _lost(board, story) == sorted([by_reply, by_resolve])


def test_r3_a_session_row_from_before_started_seq_gets_a_boundary_on_its_next_mirror(monkeypatch):
    from datetime import timedelta

    from edp8.schemas import now
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    old = board.store.get("session", "s-e1")
    old.started_seq = None  # what a row decoded from before the field looks like
    board.store.put("session", old)
    mid = _send(client, story, eng)
    m = board.store.get("message", mid)
    m.created_at = now() - timedelta(minutes=4)  # older than the 180 s fallback
    board.store.put("message", m)
    _session(client, "s-e1", eng, story, "alive")  # an ordinary mirror backfills the boundary
    assert board.store.get("session", "s-e1").started_seq == board.store.seq_of("session", "s-e1")
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == [mid]


def test_r3_a_legacy_row_resumed_since_uses_its_latest_resume_as_the_boundary(monkeypatch):
    board, client, epic, story, seats, pool = _live_rig(monkeypatch)
    eng = seats["engineer"]
    before = _send(client, story, eng)
    _session(client, "s-e1", eng, story, "parked")
    _session(client, "s-e1", eng, story, "alive")  # a resume event (seat_resumed) after `before`
    during = _send(client, story, eng)
    old = board.store.get("session", "s-e1")
    old.started_seq = None
    board.store.put("session", old)
    _session(client, "s-e1", eng, story, "alive")
    _session(client, "s-e1", eng, story, "dead", "closed by owner")
    assert _lost(board, story) == [during] and before not in _lost(board, story)


