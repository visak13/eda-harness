"""Regression guard for the motor-nerve advisory executor's BROKER WIRE.

Root cause this protects against (found by the s13:a5 live stall-detector
proof): `make_broker_executor` originally posted a PARTIAL dict
``{to, kind, body, from_}`` with NO ``msg_id``/``ts``. The real broker validates
every publish as a full ``BrokerMessage`` (``msg_id`` + tz-aware ``ts`` required)
and rejected it 409. a4's 10 effect tests all used a STUB executor, so the real
wire was never exercised — the defect shipped green. These deterministic tests
exercise the REAL executor's constructed payload (httpx monkeypatched, NO live
broker) and assert it is a COMPLETE, contract-valid envelope.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from edp_contracts import BrokerMessage

from edp_claude.reactive import driver


class _FakeResponse:
    def __init__(self, captured: list[dict], payload: dict):
        captured.append(payload)
        self._payload = payload

    def raise_for_status(self) -> None:  # a complete envelope never 409s
        return None

    def json(self) -> dict:
        return {"msg_id": self._payload["msg_id"]}


class _FakeClient:
    """Stands in for httpx.Client — captures the posted JSON body."""

    def __init__(self, captured: list[dict], **_kw):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url: str, json: dict):  # noqa: A002 — mirror httpx api
        return _FakeResponse(self._captured, json)


@pytest.fixture
def captured(monkeypatch):
    posted: list[dict] = []
    import httpx
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: _FakeClient(posted, **kw))
    return posted


def test_notify_above_payload_is_a_complete_valid_broker_message(captured):
    ex = driver.make_broker_executor("http://broker.test", parent="parent:inbox")
    ex("notify_above", {"kind": "alert", "body": {"advisory": "stall"}})

    assert len(captured) == 1, "exactly one publish"
    payload = captured[0]
    # the original defect: these two keys were ABSENT -> broker 409.
    assert payload.get("msg_id"), "msg_id must be present (was the 409 cause)"
    assert payload.get("ts"), "ts must be present (was the 409 cause)"
    # ts is tz-aware UTC and parseable.
    parsed = datetime.fromisoformat(payload["ts"])
    assert parsed.tzinfo is not None, "ts must be tz-aware"
    # routed to the parent inbox with the advisory kind.
    assert payload["to"] == "parent:inbox"
    assert payload["kind"] == "alert"
    # and — the real guarantee — it round-trips the REAL contract validator
    # (the same model_validate the broker runs on /v1/publish).
    msg = BrokerMessage.model_validate(payload)
    assert msg.msg_id and msg.from_ == "motor-nerve"


def test_broker_send_observation_payload_is_complete_and_valid(captured):
    ex = driver.make_broker_executor("http://broker.test")
    ex("broker_send", {"to": "topic:x", "kind": "observation",
                       "body": {"note": "hi"}})

    payload = captured[0]
    assert payload.get("msg_id") and payload.get("ts")
    # round-trips the real BrokerMessage contract (no 409 on a live broker).
    msg = BrokerMessage.model_validate(payload)
    assert msg.to == "topic:x" and msg.kind == "observation"


def test_each_publish_gets_a_unique_msg_id(captured):
    """msg_id/ts are per-message — but (see the effect idempotency key) they are
    added INSIDE the executor, AFTER the dispatcher computes the idempotency key,
    so they never enter the idem subset and never break dedupe."""
    ex = driver.make_broker_executor("http://broker.test", parent="p:inbox")
    ex("notify_above", {"kind": "alert", "body": {"a": 1}})
    ex("notify_above", {"kind": "alert", "body": {"a": 1}})
    assert captured[0]["msg_id"] != captured[1]["msg_id"]


def test_unknown_action_still_refused_no_silent_mutation(captured):
    ex = driver.make_broker_executor("http://broker.test")
    with pytest.raises(ValueError, match="refuses action"):
        ex("pool_reap", {"handle": "x"})
    assert not captured, "a refused action must not publish anything"
