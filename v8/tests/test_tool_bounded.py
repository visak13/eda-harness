"""Design §19 rule 4 (criterion c-caafb70c4a): no tool call blocks on an executable or
another service beyond the call cap. spawn/resume/reap/preflight return within the cap with
either the result or {status:'running', poll:...}; the work continues in a background thread
the server owns. The pool is stubbed, so this asserts the BOUNDING wrapper (the tool layer).
"""

from __future__ import annotations

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


def test_spawn_over_cap_returns_running(raw_client, monkeypatch):
    import edp8.bundles as bundles_mod
    monkeypatch.setenv("EDP8_TOOL_CALL_CAP_S", "1")

    def slow_pool(fn_name, kwargs):
        time.sleep(2.0)
        return {"ok": True, "value": {"session_id": "s-late"}}

    monkeypatch.setattr(bundles_mod, "_pool_call", slow_pool)

    # the caller is an owner: since S-ADV finding 2 (eaa2640) the spawn tool refuses every role but the
    # owner and the epic's architect, and this test is about the call cap, not the binding
    owner = _register(raw_client, "owner", "owner-bnd")
    client = BoardClient(participant=owner, admin_token="t", client=raw_client)
    set_client(client)

    t0 = time.monotonic()
    resp = ALL_TOOLS["spawn"].handler(
        ALL_TOOLS["spawn"].args_model(role="engineer", participant_id="eng-late"))
    elapsed = time.monotonic() - t0
    assert elapsed < 1.5, f"spawn blocked {elapsed:.2f}s past the 1s cap"
    assert resp["value"]["status"] == "running"
    assert resp["value"]["poll"] == "session_query"
