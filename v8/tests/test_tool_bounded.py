"""Design §19 rule 4 (criterion c-caafb70c4a): no tool call blocks on an executable or
another service beyond the call cap. consult/spawn/resume/reap/preflight return within the
cap with either the result or {status:'running', poll:...}; the work continues in a
background thread the server owns, and consult wakes the caller with a consult_done thread
note when a background run finishes.

The codex executable is never spawned: `edp8.consult.consult` is stubbed with a slow/fast
stand-in, so this asserts the BOUNDING wrapper (the tool layer), exactly as a reviewer/qa
re-runs it. A live consult confirming <30 s is a separate board-time check.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store


@pytest.fixture
def raw_client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


def _register(raw, role, handle):
    admin = BoardClient(participant=None, admin_token="t", client=raw)
    r = admin._request("POST", "/v1/participants", admin=True,
                       json={"type": "agent", "role": role, "handle": handle})
    assert r["ok"], r
    return r["value"]["id"]


def _epic(raw):
    """An epic to hang a thread on, created by an owner (engineers may not create epics)."""
    owner = _register(raw, "owner", f"owner-{time.time_ns()}")
    set_client(BoardClient(participant=owner, admin_token="t", client=raw))
    r = ALL_TOOLS["ticket_create"].handler(
        ALL_TOOLS["ticket_create"].args_model(kind="epic", work_type="chore", title="bounded target"))
    assert r["ok"], r
    return r["value"]["id"]


def test_consult_over_cap_returns_running_with_run_id(raw_client, monkeypatch):
    import edp8.bundles as bundles_mod
    import edp8.consult as consult_mod
    monkeypatch.setenv("EDP8_TOOL_CALL_CAP_S", "1")

    started = threading.Event()

    def slow(purpose, question, on_run_id=None, **kw):
        if on_run_id:
            on_run_id("run-slow-1")
        started.set()
        time.sleep(2.0)
        return {"ok": True, "value": {"answer": "the slow answer", "run_id": "run-slow-1",
                                      "profile": "design"}, "hint": ""}

    monkeypatch.setattr(consult_mod, "consult", slow)

    caller = _register(raw_client, "engineer", "eng-bnd")
    client = BoardClient(participant=caller, admin_token="t", client=raw_client)
    tid = _epic(raw_client)
    set_client(client)

    t0 = time.monotonic()
    resp = ALL_TOOLS["consult"].handler(
        ALL_TOOLS["consult"].args_model(question="q", ticket_id=tid))
    elapsed = time.monotonic() - t0

    assert elapsed < 1.5, f"consult blocked {elapsed:.2f}s — the call cap is 1s"
    assert resp["ok"] is True
    assert resp["value"]["status"] == "running"
    assert resp["value"]["run_id"] == "run-slow-1"
    assert resp["value"]["poll"] == "consult_status"

    # the background run finishes and wakes the caller with a consult_done note on the thread
    deadline = time.monotonic() + 5
    woke = None
    while time.monotonic() < deadline:
        thread = client.message_query(ticket_id=tid)
        msgs = thread["value"] if thread.get("ok") else []
        woke = next((m for m in msgs if "consult_done" in (m.get("text") or "")), None)
        if woke and any("the slow answer" in (m.get("text") or "") for m in msgs):
            break
        time.sleep(0.1)
    assert woke is not None, "no consult_done note reached the caller's thread"
    assert woke["to"] == caller, "consult_done must be addressed to the caller so the feed wakes it"
    texts = [m.get("text") or "" for m in client.message_query(ticket_id=tid)["value"]]
    assert any("the slow answer" in t for t in texts), "the answer must also land on the thread"


def test_consult_within_cap_returns_answer_and_posts_note_synchronously(raw_client, monkeypatch):
    import edp8.consult as consult_mod
    monkeypatch.setenv("EDP8_TOOL_CALL_CAP_S", "5")

    def fast(purpose, question, on_run_id=None, **kw):
        if on_run_id:
            on_run_id("run-fast-1")
        return {"ok": True, "value": {"answer": "quick answer", "run_id": "run-fast-1",
                                      "profile": "design"}, "hint": ""}

    monkeypatch.setattr(consult_mod, "consult", fast)

    caller = _register(raw_client, "engineer", "eng-fast")
    client = BoardClient(participant=caller, admin_token="t", client=raw_client)
    tid = _epic(raw_client)
    set_client(client)

    resp = ALL_TOOLS["consult"].handler(
        ALL_TOOLS["consult"].args_model(question="q", ticket_id=tid, purpose="adversary"))
    assert resp["ok"] is True and resp["value"]["answer"] == "quick answer"

    # within the cap the answer note is posted BEFORE the handler returns (no race for a poller)
    texts = [m.get("text") or "" for m in client.message_query(ticket_id=tid)["value"]]
    assert any("consultant[design]: quick answer" in t for t in texts)
    # no consult_done wake needed — the caller already has the answer in hand
    assert not any("consult_done" in t for t in texts)


def test_spawn_over_cap_returns_running(raw_client, monkeypatch):
    import edp8.bundles as bundles_mod
    monkeypatch.setenv("EDP8_TOOL_CALL_CAP_S", "1")

    def slow_pool(fn_name, kwargs):
        time.sleep(2.0)
        return {"ok": True, "value": {"session_id": "s-late"}}

    monkeypatch.setattr(bundles_mod, "_pool_call", slow_pool)

    coord = _register(raw_client, "coordinator", "coord-bnd")
    client = BoardClient(participant=coord, admin_token="t", client=raw_client)
    set_client(client)

    t0 = time.monotonic()
    resp = ALL_TOOLS["spawn"].handler(
        ALL_TOOLS["spawn"].args_model(role="engineer", participant_id="eng-late"))
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"spawn blocked {elapsed:.2f}s past the 1s cap"
    assert resp["value"]["status"] == "running"
    assert resp["value"]["poll"] == "session_query"
