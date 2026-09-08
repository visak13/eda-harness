"""S20 T0 — pool_adapter.sync_sessions: no false deaths, no port flood (criterion c-1a82925acb).

A live host incident (2026-09-07 14:55–15:00) had the mirror poll GET /v1/liveness for every
one of 116 session rows (most long closed) and re-list sessions per dead-without-reason row —
40k pool requests in ten minutes, ephemeral ports exhausted — then map each failed liveness
answer to dead, announcing healthy seats dead. These tests pin the fix.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import httpx

from edp8 import pool_adapter
from edp8.board import Board
from edp8.schemas import EventKind, SessionState
from edp8.store import Store


class _Resp:
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data
        self.content = b"{}" if data is not None else b""
        self.text = text

    def json(self):
        return self._data


class _FakeClient:
    """Records every GET/PUT and answers liveness from a canned reply (or raises)."""

    def __init__(self, *, live=None, get_raises=False, get_status=200, gets=None, puts=None):
        self.live = live if live is not None else {"state": "active"}
        self.get_raises = get_raises
        self.get_status = get_status
        self.gets = gets if gets is not None else []
        self.puts = puts if puts is not None else []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url):
        self.gets.append(url)
        if self.get_raises:
            raise httpx.ConnectError("refused")
        return _Resp(self.get_status, self.live)

    def put(self, url, json=None, headers=None):
        self.puts.append({"url": url, "body": json})
        return _Resp(200, {"ok": True})


def _rows(closed=0, live=0, live_state="active"):
    rows = []
    for i in range(live):
        rows.append({"session_id": f"L{i}", "handle": f"engineer.s-live{i}", "state": live_state})
    for i in range(closed):
        rows.append({"session_id": f"C{i}", "handle": f"engineer.s-closed{i}", "state": "done",
                     "dead_reason": "closed by self: done"})
    return rows


def _install(monkeypatch, rows, **client_kw):
    sess_calls = {"n": 0}

    def fake_sessions():
        sess_calls["n"] += 1
        return {"ok": True, "value": rows}

    monkeypatch.setattr(pool_adapter, "sessions", fake_sessions)
    gets, puts = [], []
    monkeypatch.setattr(pool_adapter.httpx, "Client",
                        lambda *a, **k: _FakeClient(gets=gets, puts=puts, **client_kw))
    return sess_calls, gets, puts


# ------------------------------------------------------ (a)(b) no port flood

def test_closed_rows_are_not_probed_and_sweep_is_bounded(monkeypatch):
    sess, gets, puts = _install(monkeypatch, _rows(closed=100, live=5))
    out = pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    assert out["ok"]
    # exactly one session list + one liveness per LIVE row (closed rows never probed)
    assert sess["n"] == 1
    assert len(gets) == 5
    assert sess["n"] + len(gets) <= 6  # ≤ 6 pool requests over 100 closed + 5 live
    assert out["value"]["mirrored"] == 105  # every row still mirrored (via PUTs, one client)


def test_one_keep_alive_client_for_the_whole_sweep(monkeypatch):
    made = {"n": 0}
    real_rows = _rows(closed=2, live=2)
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": True, "value": real_rows})

    def client_factory(*a, **k):
        made["n"] += 1
        return _FakeClient()

    monkeypatch.setattr(pool_adapter.httpx, "Client", client_factory)
    pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    assert made["n"] == 1  # one client instance carried the whole sweep


# ------------------------------------------------------ (c)(d) state mapping

def test_active_maps_to_alive(monkeypatch):
    _, _, puts = _install(monkeypatch, _rows(live=1), live={"state": "active"})
    pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    assert puts[0]["body"]["state"] == SessionState.alive.value
    assert not puts[0]["body"].get("presence_stale")


def test_dead_answer_carries_reason_and_no_stale(monkeypatch):
    _, _, puts = _install(monkeypatch, _rows(live=1), live={"state": "dead", "dead_reason": "process gone"})
    pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    body = puts[0]["body"]
    assert body["state"] == SessionState.dead.value and body["reason"] == "process gone"
    assert not body.get("presence_stale")


def test_liveness_timeout_keeps_prev_via_presence_stale(monkeypatch):
    _, gets, puts = _install(monkeypatch, _rows(live=1, live_state="active"), get_raises=True)
    out = pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    body = puts[0]["body"]
    assert body.get("presence_stale") is True  # non-answer → keep prev, stamp stale
    assert body["state"] == SessionState.alive.value  # fallback to the pool's own live state, never dead
    assert out["value"]["stale"] == 1


def test_unknown_answer_is_a_nonanswer(monkeypatch):
    _, _, puts = _install(monkeypatch, _rows(live=1, live_state="parked"), live={"state": "unknown"})
    pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    body = puts[0]["body"]
    assert body.get("presence_stale") is True
    assert body["state"] == SessionState.parked.value  # parked pool row stays parked, not dead


def test_terminal_row_mirrored_dead_with_reason_without_probe(monkeypatch):
    _, gets, puts = _install(monkeypatch, _rows(closed=1))
    pool_adapter.sync_sessions(board_url="http://board", admin_token="t")
    assert gets == []  # a done row is never probed
    assert puts[0]["body"]["state"] == SessionState.dead.value
    assert "closed by self" in puts[0]["body"]["reason"]


# ------------------------------------------------------ board side: no false death, one event

def test_presence_stale_upsert_keeps_state_and_emits_no_event():
    board = Board(Store(":memory:"))
    tid = "s-x"

    def dead_events():
        return [e for e in board.store.query("event", {"subject_id": tid})
                if e.kind == EventKind.shell_dead]

    board.session_upsert(id_="sess1", participant_id="engineer.s-x", ticket_id=tid, pool_id="local",
                         state=SessionState.alive)
    assert len(dead_events()) == 0
    # a missed probe arrives as presence_stale — must NOT flip the seat to dead or emit
    s = board.session_upsert(id_="sess1", participant_id="engineer.s-x", ticket_id=tid, pool_id="local",
                             state=SessionState.dead, reason="timeout", presence_stale=True)
    assert s.state == SessionState.alive  # previous state kept
    assert s.presence_stale_since is not None
    assert len(dead_events()) == 0  # silence is never rendered as Closed
    # a genuine dead answer flips it and emits exactly one event
    s = board.session_upsert(id_="sess1", participant_id="engineer.s-x", ticket_id=tid, pool_id="local",
                             state=SessionState.dead, reason="closed by self: done")
    assert s.state == SessionState.dead
    assert s.presence_stale_since is None  # cleared on a positive answer
    assert len(dead_events()) == 1


def test_positive_answer_after_stale_clears_the_stamp():
    board = Board(Store(":memory:"))
    board.session_upsert(id_="s2", participant_id="engineer.s-y", ticket_id="s-y", pool_id="local",
                         state=SessionState.alive)
    board.session_upsert(id_="s2", participant_id="engineer.s-y", ticket_id="s-y", pool_id="local",
                         state=SessionState.alive, presence_stale=True)
    s = board.session_upsert(id_="s2", participant_id="engineer.s-y", ticket_id="s-y", pool_id="local",
                             state=SessionState.alive)
    assert s.presence_stale_since is None
