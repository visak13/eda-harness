"""Astra's review of s-e60c3d42ad (report-dc4f9c3c8a): one regression per finding F1-F6, on its fixtures."""
from __future__ import annotations

import json
import os
import time

import pytest

from edp8.feed_driver import FeedState, Health, Listener, Readiness, _retry_loop, _stream_usable, listener_ready

ME = "engineer.s-probe"
FULL = "x" * 600 + " END"


def human_ev():
    return {"seq": 5, "kind": "message_sent", "subject_id": "s-probe",
            "data": {"message": "m-probe", "to": ME, "from": "owner", "from_type": "human", "kind": "steer",
                     "text": FULL[:280], "artifacts": ["art-probe"], "quoted": "REQUIRED quoted specification"}}


HUMAN_BROKER = {"ts": "2026-10-09T01:00:00Z", "from": "owner", "to": ME, "kind": "steer",
                "body": {"board_msg_id": "m-probe", "ticket_id": "s-probe", "text": FULL, "artifacts": ["art-probe"]}}


def make(path=None, fetch=None):
    lines: list[dict] = []
    state = FeedState(path)
    return Listener(ME, state, emit=lines.append, fetch=fetch), lines, state


def test_f2_a_failed_emit_leaves_the_message_replayable(tmp_path):
    path = tmp_path / "s.json"

    def broken(_line):
        raise BrokenPipeError

    ln = Listener(ME, FeedState(path), emit=broken)
    with pytest.raises(BrokenPipeError):
        ln.on_board(human_ev())
    state = FeedState(path)
    assert "m-probe" not in state.seen and state.board_seq is None   # neither delivered nor skipped
    lines: list[dict] = []
    Listener(ME, state, emit=lines.append).on_board(human_ev())
    assert len(lines) == 1 and "m-probe" in FeedState(path).seen


def test_f2_an_in_flight_message_still_dedupes_across_planes():
    state = FeedState()
    assert state.reserve("m-1") is True
    assert state.reserve("m-1") is False      # the other plane sees the reservation before the commit
    state.release("m-1")
    assert state.reserve("m-1") is True


def test_f3_the_compact_message_keeps_attachments_quotes_and_guest_marker():
    ev = human_ev()
    ev["data"].update({"from_handle": "ext:guest-probe", "from_role": "guest"})
    ln, lines, _ = make(fetch=lambda *a: {"ok": True, "value": {"text": FULL}})
    ln.on_board(ev)
    msg = lines[0]["msg"]
    assert msg["text"] == FULL and msg["artifacts"] == ["art-probe"]
    assert msg["quoted"] == "REQUIRED quoted specification"
    assert msg["from_handle"] == "ext:guest-probe" and msg["from_role"] == "guest"


def test_f4_a_failed_fetch_is_not_passed_off_as_full_text_and_the_broker_copy_completes_it(tmp_path):
    path = tmp_path / "s.json"
    ln, lines, state = make(path, fetch=lambda *a: {"ok": False, "error": {"code": "unreachable"}})
    ln.on_board(human_ev())
    first = lines[0]["msg"]
    assert first["truncated"] is True and first["fetch"] == "message_read(id='m-probe')"
    assert len(first["text"]) == 280
    assert state.is_partial("m-probe") and FeedState(path).is_partial("m-probe")   # survives a restart
    ln.on_broker(HUMAN_BROKER)
    assert lines[1]["msg"]["text"] == FULL and lines[1]["msg"]["completes"] is True
    assert not state.is_partial("m-probe")
    ln.on_broker(HUMAN_BROKER)                  # a second copy adds nothing
    assert len(lines) == 2


def test_f4_a_short_message_needs_no_fetch_receipt():
    ln, lines, _ = make(fetch=lambda *a: {"ok": False})
    ev = human_ev()
    ev["data"]["text"] = "short"
    ln.on_board(ev)
    assert lines[0]["msg"]["text"] == "short" and "truncated" not in lines[0]["msg"]


def test_f6_recovery_waits_for_a_usable_frame_not_http_headers():
    lines: list[dict] = []
    health = Health(emit=lines.append)

    def step():                      # headers succeed, the body never delivers a frame
        raise TimeoutError("SSE headers succeed but body never arrives")

    _retry_loop("board", step, health, sleep=lambda _: None, rounds=10)
    _stream_usable("board", health)  # the first ready/data frame of the stream that finally works
    assert [x["feed"] for x in lines] == ["lost", "recovered"]


def test_f1_readiness_needs_a_fresh_file_and_a_live_pid(tmp_path):
    ready = tmp_path / "p.ready.json"
    assert listener_ready(ME, path=ready) is False                       # no file
    Readiness(ME, ready).write()
    assert listener_ready(ME, path=ready) is True
    ready.write_text(json.dumps({"pid": os.getpid(), "ts": time.time() - 3600}), encoding="utf-8")
    assert listener_ready(ME, path=ready) is False                       # stale
    ready.write_text(json.dumps({"pid": 2_000_000_000, "ts": time.time()}), encoding="utf-8")
    assert listener_ready(ME, path=ready) is False                       # nobody alive at that pid
