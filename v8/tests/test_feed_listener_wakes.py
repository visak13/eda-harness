"""s-e60c3d42ad (e0cec): the feed listener wakes a seat once per real event.

c-f085153cf9: a message on both planes prints once; the banner once across a restart; a 10-retry outage two
lines; a message posted while the listener was down prints after the restart from the saved cursors; an
addressed human message prints with its whole text inside the byte budget.
"""
from __future__ import annotations

import json

from edp8 import feed_driver
from edp8.feed_driver import FeedState, Health, Listener, _retry_loop

ME = "engineer.s-1"


def board_ev(seq, msg_id, *, to=ME, frm="architect.e", from_type="agent", text="hello", kind="steer"):
    return {"seq": seq, "subject_id": "s-1", "kind": "message_sent",
            "data": {"message": msg_id, "to": to, "kind": kind, "from": frm, "from_type": from_type,
                     "text": text[:280]}}


def broker_msg(ts, msg_id, *, kind="steer", status=None, text="hello"):
    body = {"ticket_id": "s-1", "text": text, "board_msg_id": msg_id}
    if status:
        body["status"] = status
    return {"msg_id": "u-" + ts, "ts": ts, "from": "architect.e", "to": ME, "kind": kind, "body": body}


def make(path=None, fetch=None):
    lines: list[dict] = []
    state = FeedState(path)
    return Listener(ME, state, emit=lines.append, fetch=fetch), lines, state


def test_message_on_both_planes_prints_once():
    ln, lines, _ = make()
    ln.on_board(board_ev(5, "m-1"))
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-1"))
    assert len(lines) == 1 and "event" in lines[0]


def test_broker_first_then_board_prints_once():
    ln, lines, _ = make()
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-2"))
    ln.on_board(board_ev(6, "m-2"))
    assert len(lines) == 1 and "broker_msg" in lines[0]


def test_distinct_messages_each_print():
    ln, lines, _ = make()
    ln.on_board(board_ev(5, "m-1"))
    ln.on_board(board_ev(6, "m-2"))
    assert len(lines) == 2


def test_status_copy_follows_the_feed_relevance_rule():
    ln, lines, _ = make()
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-3", kind="status", status="in_progress"))
    ln.on_broker(broker_msg("2026-10-09T01:00:01", "m-4", kind="status", status="blocked"))
    assert [m["broker_msg"]["body"]["board_msg_id"] for m in lines] == ["m-4"]


def test_banner_prints_once_across_a_restart(tmp_path):
    path = tmp_path / "s.json"
    assert FeedState(path).mark_banner() is True
    assert FeedState(path).mark_banner() is False


def test_ten_retry_outage_prints_two_lines():
    lines: list[dict] = []
    health = Health(emit=lines.append)
    calls = {"n": 0}

    def step():
        calls["n"] += 1
        if calls["n"] <= 10:
            raise ConnectionError("down")
        health.up("board")

    _retry_loop("board", step, health, sleep=lambda s: None, rounds=12)
    assert [x["feed"] for x in lines] == ["lost", "recovered"]


def test_message_posted_while_down_prints_after_restart(tmp_path):
    path = tmp_path / "s.json"
    ln, lines, state = make(path)
    ln.on_board(board_ev(5, "m-1"))
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-1"))
    # listener dies here; a restart reads the saved cursors
    state2 = FeedState(path)
    assert state2.board_seq == 5 and state2.broker_ts == "2026-10-09T01:00:00"
    lines2: list[dict] = []
    ln2 = Listener(ME, state2, emit=lines2.append)
    # the board replays from seq 5 on: the old message is not reprinted, the one sent during the gap is
    ln2.on_board(board_ev(5, "m-1"))
    ln2.on_board(board_ev(7, "m-9"))
    assert [e["event"]["data"]["message"] for e in lines2] == ["m-9"]
    assert state2.board_seq == 7


def test_addressed_human_message_prints_full_text_within_budget():
    full = "please " + "x" * 600 + " END"

    def fetch(path, params):
        assert path == "/v1/messages/m-h"
        return {"ok": True, "value": {"text": full}}

    ln, lines, _ = make(fetch=fetch)
    ln.on_board(board_ev(8, "m-h", frm="owner", from_type="human", text=full, kind="note"))
    assert lines[0]["msg"]["text"] == full
    out = json.dumps(feed_driver.cap_line(lines[0]))
    assert len(out.encode()) <= feed_driver._event_budget() and "END" in out


def test_human_message_to_someone_else_is_not_expanded():
    calls = []
    ln, lines, _ = make(fetch=lambda p, q: calls.append(p) or {"ok": False})
    ln.on_board(board_ev(9, "m-o", to="architect.e", frm="owner", from_type="human"))
    assert calls == [] and "event" in lines[0]


def test_a_cut_message_to_someone_else_is_expanded_or_flagged():
    # adversary report-b9c60aeff1 Q1: the architect is woken for every question on its epic; a 604-character one
    # addressed to another seat arrived as its first 280 characters with nothing saying more existed
    full = "q" * 600 + " END"
    ln, lines, _ = make(fetch=lambda p, q: {"ok": True, "value": {"text": full}})
    ln.on_board(board_ev(13, "m-q", to="qa.e", text=full, kind="question"))
    assert lines[0]["msg"]["text"] == full
    ln, lines, _ = make(fetch=lambda p, q: {"ok": False})
    ln.on_board(board_ev(14, "m-r", to="qa.e", text=full, kind="question"))
    assert lines[0]["msg"]["truncated"] is True and "m-r" in lines[0]["msg"]["fetch"]


def test_long_agent_message_prints_whole_text_when_only_the_event_arrives():
    full = "a" * 755

    def fetch(path, params):
        assert path == "/v1/messages/m-l"
        return {"ok": True, "value": {"text": full}}

    ln, lines, _ = make(fetch=fetch)
    ln.on_board(board_ev(10, "m-l", text=full))
    assert lines[0]["msg"]["text"] == full and "truncated" not in lines[0]["msg"]
    assert len(json.dumps(feed_driver.cap_line(lines[0])).encode()) <= feed_driver._event_budget()


def test_long_agent_message_prefers_the_broker_copy_when_it_arrives_first():
    full = "b" * 755
    ln, lines, _ = make(fetch=lambda p, q: {"ok": False})
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-b", text=full))
    ln.on_board(board_ev(11, "m-b", text=full))
    assert len(lines) == 1 and lines[0]["broker_msg"]["body"]["text"] == full


def test_long_agent_message_with_failed_fetch_is_flagged_then_completed():
    full = "c" * 755
    ln, lines, _ = make(fetch=lambda p, q: {"ok": False})
    ln.on_board(board_ev(12, "m-c", text=full))
    assert lines[0]["msg"]["truncated"] is True and "message_read" in lines[0]["msg"]["fetch"]
    ln.on_broker(broker_msg("2026-10-09T01:00:01", "m-c", text=full))
    assert lines[1]["msg"]["text"] == full and len(lines) == 2


def test_over_budget_line_carries_truncated_flag_and_fetch_call():
    out = feed_driver.cap_line({"msg": {"id": "m-x", "text": "z" * 5000}})
    assert out["omitted"]["truncated"] is True and "m-x" in out["omitted"]["fetch"]


def test_seat_close_on_both_planes_prints_once():
    ev = {"seq": 20, "subject_id": "s-1", "kind": "shell_dead",
          "data": {"session": "ses-1", "participant": ME, "reason": "closed", "clean": True}}
    fyi = {"msg_id": "u-1", "ts": "2026-10-09T11:47:06", "from": "pool", "to": ME, "kind": "fyi",
           "body": {"participant": ME, "ticket_id": "s-1", "session_id": "ses-1", "state": "dead", "clean": True}}
    for order in ((ev, fyi), (fyi, ev)):
        ln, lines, _ = make()
        for item in order:
            (ln.on_board if "seq" in item else ln.on_broker)(item)
        assert len(lines) == 1
    ln, lines, _ = make()
    ln.on_board(ev)
    ln.on_board({**ev, "seq": 21, "data": {**ev["data"], "session": "ses-2"}})
    assert len(lines) == 2


def test_a_resumed_session_closing_again_is_a_second_wake_on_either_plane():
    # adversary report-b9c60aeff1 F2: close -> resume -> close of ONE session was two board deaths, one wake
    ev = {"seq": 20, "subject_id": "s-1", "kind": "shell_dead",
          "data": {"session": "ses-1", "participant": ME, "reason": "closed", "clean": True, "run": 10}}
    fyi = {"msg_id": "u-1", "ts": "2026-10-09T11:47:06", "from": "pool", "to": ME, "kind": "fyi",
           "body": {"participant": ME, "ticket_id": "s-1", "session_id": "ses-1", "state": "dead", "clean": True,
                    "run": 10}}
    ln, lines, _ = make()
    ln.on_board(ev)
    ln.on_broker(fyi)
    assert len(lines) == 1
    ln.on_broker({**fyi, "msg_id": "u-2", "ts": "2026-10-09T11:50:00", "body": {**fyi["body"], "run": 30}})
    ln.on_board({**ev, "seq": 40, "data": {**ev["data"], "run": 30}})
    assert len(lines) == 2


def crit_ev(seq, *, by, key="by", created_by=None):
    ev = {"seq": seq, "subject_id": "s-1", "kind": "criterion_checked", "data": {key: by}}
    if created_by:
        ev["created_by"] = created_by
    return ev


def test_own_criterion_verdict_is_dropped_but_the_cursor_moves():
    ln, lines, state = make()
    ln.on_board(crit_ev(7, by=ME))
    ln.on_board(crit_ev(8, by="x", key="from", created_by=ME))
    assert lines == []
    assert state.board_seq == 8


def test_own_message_copy_on_the_broker_is_dropped():
    ln, lines, _ = make()
    own = broker_msg("2026-10-09T01:00:00", "m-9")
    own["from"] = ME
    by_me = broker_msg("2026-10-09T01:00:01", "m-10")
    by_me["body"]["by"] = ME
    ln.on_broker(own)
    ln.on_broker(by_me)
    assert lines == []


def test_another_seat_or_human_act_on_my_ticket_is_kept():
    ln, lines, _ = make()
    ln.on_board(crit_ev(7, by="qa.epic-1"))
    ln.on_board(crit_ev(8, by="owner"))
    assert len(lines) == 2


def test_board_hint_is_kept():
    ln, lines, _ = make()
    ln.on_board({"seq": 9, "subject_id": "s-1", "kind": "hint", "data": {"by": "board", "to": ME}})
    assert len(lines) == 1


def test_own_shell_dead_is_kept_as_the_boards_act():
    ln, lines, _ = make()
    ln.on_board({"seq": 10, "subject_id": "s-1", "kind": "shell_dead",
                 "data": {"participant": ME, "session": "ss-1", "by": ME}})
    assert len(lines) == 1


# s-3c858b31b4 (architect m-31d4966307): a message printed into the seat's turn is a read; the listener tells the board.
def make_receipts(path=None, fetch=None, boom=False):
    lines: list[dict] = []
    seen: list[list[str]] = []

    def receipt(ids):
        if boom:
            raise RuntimeError("board unreachable")
        seen.append(list(ids))

    return Listener(ME, FeedState(path), emit=lines.append, fetch=fetch, receipt=receipt), lines, seen


def test_a_printed_board_message_posts_a_receipt_once_even_when_it_also_arrives_on_the_broker():
    ln, lines, seen = make_receipts()
    ln.on_board(board_ev(5, "m-1"))
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-1"))
    assert len(lines) == 1 and seen == [["m-1"]]


def test_a_broker_only_message_and_a_broker_completion_post_receipts():
    ln, lines, seen = make_receipts()
    ln.on_broker(broker_msg("2026-10-09T01:00:00", "m-2"))
    assert seen == [["m-2"]]
    long_text = "x" * 400
    ln2, lines2, seen2 = make_receipts(fetch=lambda path, params: {"ok": False})
    ln2.on_board(board_ev(6, "m-3", text=long_text, frm="human", from_type="human", to=ME))
    ln2.on_broker(broker_msg("2026-10-09T01:00:01", "m-3", text=long_text))
    assert seen2 and all(ids == ["m-3"] for ids in seen2)


def test_no_receipt_for_an_own_act_or_a_non_message_event():
    ln, lines, seen = make_receipts()
    ln.on_board(board_ev(7, "m-4", frm=ME))  # the seat's own post: it knows
    ln.on_board({"seq": 8, "subject_id": "s-1", "kind": "board_hint",
                 "data": {"hint": "closed_seat_message", "message": "m-5", "by": "board", "text": "t"}})
    assert seen == []


def test_a_failing_receipt_never_blocks_the_wake():
    ln, lines, _ = make_receipts(boom=True)
    ln.on_board(board_ev(9, "m-6"))
    assert len(lines) == 1


# qa report-689ceb50f0 (0.10.6 candidate) fails 2 and 3


def test_a_closed_seat_hint_naming_a_message_already_delivered_still_prints():
    """Fail 2: the hint carries data.message = the message the architect already got as message_sent; keying the
    hint on that id deduped it away, so the architect never heard the seat had closed with it unread."""
    ln, lines, _ = make()
    ln.on_board(board_ev(43, "m-7"))
    hint = {"seq": 44, "subject_id": "s-1", "kind": "board_hint",
            "data": {"hint": "closed_seat_message", "by": "board", "seat": "engineer.s-2", "message": "m-7",
                     "messages": ["m-7"], "text": "CLOSED seat engineer.s-2 left 1 unread message (steer m-7)"}}
    ln.on_board(hint)
    assert len(lines) == 2 and lines[1]["event"]["data"]["hint"] == "closed_seat_message"


def test_an_addressed_message_line_keeps_its_whole_text_past_the_event_budget():
    """Fail 3: a 2,184-char owner question reached the seat cut at ~1.4k chars by the 2,000-byte event cap."""
    text = "word " * 437  # 2,185 chars
    full = feed_driver.cap_line({"msg": {"id": "m-9", "text": text}}, feed_driver._budget_for({"msg": {}}))
    assert full["msg"]["text"] == text and "omitted" not in full
    broker = feed_driver.cap_line({"broker_msg": {"body": {"text": text}}}, feed_driver._budget_for({"broker_msg": {}}))
    assert broker["broker_msg"]["body"]["text"] == text
    # any other event is still held to the event budget
    ev = feed_driver.cap_line({"event": {"data": {"text": text}}}, feed_driver._budget_for({"event": {}}))
    assert ev["omitted"]["truncated"] is True
