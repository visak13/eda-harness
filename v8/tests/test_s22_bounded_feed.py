"""S22 c-0615088222 (consult #7): replay applies its limit while streaming instead of materialising
the whole history, and every feed queue is bounded (oldest dropped + a resync marker that ends the
stream so the client reconnects from its last seq and the replay fills the gap).

The measurement test seeds a 20k-event history and prints time + tracemalloc peak for the two
replay paths (/v1/events?limit=200 and the SSE catch-up iteration); the report carries its output."""
from __future__ import annotations

import asyncio
import json
import time
import tracemalloc

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.schemas import EventKind, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

N = 20_000


@pytest.fixture(scope="module")
def seeded():
    board = Board(Store(":memory:"))
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Busy")
    board.ticket_update(owner, epic.id, assignee=owner.id)
    for i in range(N):
        # half page the owner (an @mention), half are notes between seats: the wake feed filters
        board._emit(epic.id, EventKind.message_sent, {"text": f"note {i} " + "x" * 200, "by": "arch",
                                                      "mentions": [owner.id] if i % 2 else []})
    return board, owner


def _measure(fn):
    tracemalloc.start()
    t0 = time.perf_counter()
    out = fn()
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return out, dt, peak


def test_replay_measured_on_20k_history(seeded, capsys):
    board, owner = seeded
    client = TestClient(create_app(board, admin_token="t"))
    h = {"X-Participant": owner.id}
    rows = []
    for watch in (False, True):
        r, dt, peak = _measure(lambda: client.get(
            "/v1/events", params={"since": 0, "limit": 200, "watch": watch}, headers=h).json())
        assert len(r["value"]) == 200 and r["value"][0]["seq"] < r["value"][-1]["seq"]
        rows.append((f"/v1/events limit=200 watch={watch}", dt, peak))
    # SSE catch-up: the service iterates the replay; the first 200 frames are what a client reads
    # before the server has to hold anything more.
    it = getattr(board, "iter_replay", None)
    def first_200():
        src = it(owner, 0, watch=True) if it else iter(board.replay(owner, 0, watch=True))
        return [next(src) for _ in range(200)]
    got, dt, peak = _measure(first_200)
    assert len(got) == 200
    rows.append(("SSE catch-up, first 200 frames", dt, peak))
    with capsys.disabled():
        print(f"\n20k-event history ({'iter_replay' if it else 'replay list'}):")
        for name, dt, peak in rows:
            print(f"  {name:<40} {dt * 1000:8.1f} ms  peak {peak / 1e6:7.2f} MB")


def _rig():
    board = Board(Store(":memory:"))
    owner = board.participant_create("human", Role.owner, "owner", id_="owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Busy")
    return board, owner, epic


def test_iter_replay_stops_at_limit_and_keeps_order():
    board, owner, epic = _rig()
    start = board.store.max_seq()
    for i in range(1200):  # spans three store pages
        board._emit(epic.id, EventKind.message_sent, {"text": f"n{i}", "mentions": [owner.id] if i % 3 == 0 else []})
    full = board.replay(owner, start)
    assert len(full) == 400
    assert list(board.iter_replay(owner, start, limit=250)) == full[:250]
    assert list(board.iter_replay(owner, start, watch=True, limit=700))[-1][0] == start + 700
    assert list(board.iter_replay(owner, start, limit=0)) == []
    assert board.replay_tail(owner, 5) == full[-5:]
    assert board.replay_tail(owner, 10_000)[-400:] == full  # asking for more than exists: all of it


def test_full_queue_drops_oldest_and_marks_resync(monkeypatch):
    import edp8.board as board_mod
    monkeypatch.setattr(board_mod, "FEED_QUEUE_MAX", 3)
    board, owner, epic = _rig()
    q = board.subscribe(owner.id, watch=True)
    evs = [board._emit(epic.id, EventKind.message_sent, {"text": f"n{i}"}) for i in range(5)]
    assert q.maxsize == 3 and q.resync is True
    kept = [q.get_nowait().id for _ in range(q.qsize())]
    assert kept == [e.id for e in evs[-3:]]  # the two oldest were dropped
    board.unsubscribe(owner.id, q)


def _feed_endpoint(app):
    return next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/v1/feed")


async def _frames(resp, stop_after_ready: bool):
    out = []
    async for chunk in resp.body_iterator:
        f = chunk.decode() if isinstance(chunk, bytes) else chunk
        out.append(f)
        if stop_after_ready and f.startswith(": ready"):
            break
    return out


def test_sse_overflow_sends_resync_and_reconnect_replays_the_gap(monkeypatch):
    """A slow reader whose queue overflows gets `: resync <cursor>` and the stream ends; a reconnect
    from that cursor delivers every event, including the dropped ones, in order."""
    import edp8.board as board_mod
    monkeypatch.setattr(board_mod, "FEED_QUEUE_MAX", 3)
    board, owner, epic = _rig()
    feed = _feed_endpoint(create_app(board, admin_token="t"))

    async def run():
        resp = await feed(since=-1, watch=True, a=owner)
        head = await _frames(resp, stop_after_ready=True)
        cursor = int(head[-1].split()[2])
        evs = [board._emit(epic.id, EventKind.message_sent, {"text": f"n{i}"}) for i in range(6)]
        tail = await _frames(resp, stop_after_ready=False)  # ends by itself on resync
        assert tail == [f": resync {cursor}\n\n"]
        again = await feed(since=cursor, watch=True, a=owner)
        body = await _frames(again, stop_after_ready=True)
        ids = [json.loads(f[len("data: "):])["id"] for f in body if f.startswith("data: ")]
        assert ids == [e.id for e in evs]
        await again.body_iterator.aclose()

    asyncio.run(run())
