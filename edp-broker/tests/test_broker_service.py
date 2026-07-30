"""TESTPLAN BRK-S service-level + HttpBroker round-trip."""

import asyncio
from datetime import datetime, timezone

import pytest
from edp_contracts import BrokerMessage
from fastapi.testclient import TestClient

from edp_broker.service import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path))


def _msg(to="neuron:r1", kind="done"):
    return BrokerMessage(
        msg_id="m1", ts=datetime.now(timezone.utc),
        **{"from": "p:1"}, to=to, kind=kind, body={},
    ).model_dump(mode="json", by_alias=True)


def test_brk_s_7_health_conforms(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status", "version", "detail", "deps"}
    assert r.json()["status"] == "ready"


def test_publish_then_inbox(client):
    assert client.post("/v1/publish", json=_msg()).status_code == 200
    got = client.get("/v1/inbox/neuron:r1").json()
    assert len(got) == 1 and got[0]["from"] == "p:1"


def test_brk_s_get_message_by_id(client):
    """Team-architecture Phase 2 (2026-05-21): supports the reply()
    MCP tool which routes answers by msg_id."""
    assert client.post("/v1/publish", json=_msg()).status_code == 200
    r = client.get("/v1/message/m1")
    assert r.status_code == 200
    assert r.json()["msg_id"] == "m1"
    assert r.json()["from"] == "p:1"


def test_brk_s_get_message_unknown_is_404(client):
    r = client.get("/v1/message/does-not-exist")
    assert r.status_code == 404


def test_brk_s_2_unregistered_kind_is_envelope(client):
    # Hand-built raw dict — BrokerMessage would reject 'frobnicate' at
    # construction, so we must bypass the client-side model to exercise the
    # SERVER's envelope-error path.
    bad = {
        "msg_id": "m1", "ts": datetime.now(timezone.utc).isoformat(),
        "from": "p:1", "to": "neuron:r1", "kind": "frobnicate", "body": {},
    }
    r = client.post("/v1/publish", json=bad)
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert body["source"] == "edp-broker"
    assert body["code"] == "broker_unregistered_kind"


def test_brk_s_6_bad_recipient_route_error(client):
    r = client.get("/v1/inbox/..%2Fetc")
    assert r.status_code in (404, 409)  # never a path escape / 500


def test_brk_s_8_sse_replays_backlog(client):
    client.post("/v1/publish", json=_msg())
    # max_seconds=0 → drain backlog once and close (bounded for the
    # sync TestClient; an unbounded stream would hang it).
    r = client.get("/v1/events",
                   params={"recipient": "neuron:r1", "max_seconds": 0})
    assert r.status_code == 200
    assert "data:" in r.text


def test_brk_s_events_bad_recipient_is_envelope(client):
    r = client.get("/v1/events",
                   params={"recipient": "..%2Fetc", "max_seconds": 0})
    assert r.status_code in (404, 409)  # never a path escape / 500


async def test_brk_s_events_live_push():
    """The live stream PUSHES a message published AFTER the stream opened
    — proving it holds the connection open and the StreamHub wakes it
    (not a one-shot drain)."""
    import tempfile

    import httpx

    with tempfile.TemporaryDirectory() as d:
        application = create_app(d)
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://b"
        ) as c:
            got: list[str] = []

            async def _consume():
                async with c.stream(
                    "GET", "/v1/events",
                    params={"recipient": "neuron:r1", "max_seconds": 2},
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            got.append(line)
                            return  # got our message; stop

            consumer = asyncio.ensure_future(_consume())
            await asyncio.sleep(0.2)  # ensure the stream is live + waiting
            await c.post("/v1/publish", json=_msg(kind="done"))
            await asyncio.wait_for(consumer, timeout=3)
            assert got and '"from":"p:1"' in got[0].replace(" ", "")


def test_alias_then_publish(client):
    client.post("/v1/alias", json={
        "owner_session": "neuron:r1", "alias": "my-planner",
        "target": "planner:p7"})
    client.post("/v1/publish", json=_msg(to="neuron:r1/my-planner"))
    assert len(client.get("/v1/inbox/planner:p7").json()) == 1


def test_brk_s16_absolute_alias_colon_handle_delivers(client):
    """s16: POST /v1/alias with owner_session '*' registers an ABSOLUTE
    colon→dash bridge; a publish to the visible colon handle is then
    delivered to the dash inbox the planner reads (end-to-end over HTTP)."""
    r = client.post("/v1/alias", json={
        "owner_session": "*", "alias": "rec-s6:s1", "target": "rec-s6-s1"})
    assert r.status_code == 200
    assert client.post(
        "/v1/publish", json=_msg(to="rec-s6:s1")).status_code == 200
    # visible on the dash inbox (rx.broker / check_inbox read here)
    assert len(client.get("/v1/inbox/rec-s6-s1").json()) == 1


def test_brk_s16_absolute_alias_sse_wakes_dash_stream(client):
    """s16: the live SSE stream on the DASH inbox replays a colon-addressed
    message (the StreamHub notifies the resolved dash target)."""
    client.post("/v1/alias", json={
        "owner_session": "*", "alias": "rec-s7:s1", "target": "rec-s7-s1"})
    client.post("/v1/publish", json=_msg(to="rec-s7:s1"))
    r = client.get("/v1/events",
                   params={"recipient": "rec-s7-s1", "max_seconds": 0})
    assert r.status_code == 200 and "data:" in r.text

def _msg2(msg_id, to, sender, kind="done"):
    return BrokerMessage(
        msg_id=msg_id, ts=datetime.now(timezone.utc),
        **{"from": sender}, to=to, kind=kind, body={},
    ).model_dump(mode="json", by_alias=True)


def test_messages_cross_inbox_no_filter(client):
    """OBJECT-MODEL inc3: GET /v1/messages with no `to` scans every
    inbox (the wide inspect lens)."""
    client.post("/v1/publish", json=_msg2("a", "neuron:r1", "p:1"))
    client.post("/v1/publish", json=_msg2("b", "planner:p7", "neuron:r1"))
    got = client.get("/v1/messages").json()
    assert {m["msg_id"] for m in got} == {"a", "b"}


def test_messages_filter_by_from_and_kind(client):
    client.post("/v1/publish",
                json=_msg2("a", "neuron:r1", "p:1", kind="done"))
    client.post("/v1/publish",
                json=_msg2("b", "neuron:r1", "p:2", kind="question"))
    by_from = client.get("/v1/messages", params={"from": "p:2"}).json()
    assert [m["msg_id"] for m in by_from] == ["b"]
    by_kind = client.get("/v1/messages", params={"kind": "done"}).json()
    assert [m["msg_id"] for m in by_kind] == ["a"]


def test_messages_filter_by_to(client):
    client.post("/v1/publish", json=_msg2("a", "neuron:r1", "p:1"))
    client.post("/v1/publish", json=_msg2("b", "planner:p7", "p:1"))
    got = client.get("/v1/messages", params={"to": "planner:p7"}).json()
    assert [m["msg_id"] for m in got] == ["b"]


# HttpBroker (the edp-claude consumer port impl) is exercised against a
# live broker at the INTEGRATION milestone (#9), not here — keeping #3's
# suite free of an edp_claude dependency (deploy independence, audit #13).
