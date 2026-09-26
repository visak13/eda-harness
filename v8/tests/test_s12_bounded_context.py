"""S12 (qa finding 18, m-95ca1a69d6): context() for a multi-ticket checking seat overflowed the
MCP client cap (~120k chars). It is shaped in the tool layer (bundles.py); board.py
_context_snapshot / ticket_view and context_delta are left untouched.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}


def _bytes(obj) -> int:
    return len(json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))


@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def five_ticket_seat(client):
    """A 5-story epic assigned to one seat, every story carrying a long thread and a fat doc —
    the shape that overflowed the client cap. Returns the seat's participant id."""
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    A = {"X-Participant": "arch"}
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "big epic",
                                            "description": "an epic with five loud stories"},
                       headers={"X-Participant": "owner"}).json()["value"]
    long_body = ("lorem ipsum dolor sit amet " * 400).strip()   # ~10 KB of doc body
    for i in range(5):
        s = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature",
                                             "title": f"S{i} loud story", "parent_id": epic["id"],
                                             "assignee": "eng"}, headers=A).json()["value"]
        client.post("/v1/criteria", json={"ticket_id": s["id"], "text": f"criterion {i} passes",
                                          "check": "command", "checked_by": "qa"}, headers=A)
        d = client.post("/v1/docs", json={"doc_type": "note", "title": f"doc {i}", "body_md": long_body,
                                          "scope": s["id"]}, headers=A).json()["value"]
        client.post("/v1/links", json={"from_id": s["id"], "to_id": d["id"], "relation": "evidence_for"},
                    headers=A)
        for j in range(30):                                     # 30 long messages per story
            client.post("/v1/messages", json={"ticket_id": s["id"], "kind": "note",
                                              "text": f"[{i}.{j}] " + ("chatter " * 60)}, headers=A)
    return "eng"


def test_context_default_is_bounded_and_names_the_fetch(client, five_ticket_seat):
    set_client(BoardClient(participant=five_ticket_seat, admin_token="t", client=client))
    ctx = ALL_TOOLS["context"]

    full = ctx.handler(ctx.args_model(verbose=True))["value"]
    resp = ctx.handler(ctx.args_model())
    bounded = resp["value"]

    # the full snapshot is the problem the finding reported: well over the client cap
    assert _bytes(full) > 40_000, "fixture must reproduce the oversized snapshot"

    # bounded default fits the budget with margin
    assert _bytes(bounded) <= 40_000, f"bounded snapshot is {_bytes(bounded)} bytes"
    assert len(bounded["tickets"]) == 5

    # per-ticket summaries survive: record, chain, criteria, cursor and asks are intact
    assert "cursor" in bounded and isinstance(bounded["cursor"], str) and bounded["cursor"]
    for tv in bounded["tickets"]:
        assert tv["ticket"]["id"] and tv["criteria"], "criteria are a summary field, kept whole"
        assert tv["thread_total"] == 30, "thread_total is preserved for paging"
        assert len(tv["thread"]) <= 3, "thread bodies are clipped to the newest few"

    # the receipt names what was omitted AND the exact call to fetch it
    om = bounded["omitted"]
    assert "verbose=True" in om["thread_bodies"] and "message_query" in om["thread_bodies"]
    assert "doc_read" in om["doc_summaries"]
    assert om["full_snapshot"] == "context(verbose=True)"


def test_context_verbose_matches_unbounded(client, five_ticket_seat):
    set_client(BoardClient(participant=five_ticket_seat, admin_token="t", client=client))
    ctx = ALL_TOOLS["context"]
    full = ctx.handler(ctx.args_model(verbose=True))["value"]
    # verbose carries full threads and no omission receipt
    assert "omitted" not in full
    assert any(len(tv["thread"]) == 20 for tv in full["tickets"]), "full snapshot keeps ticket_view's thread window"


def test_context_budget_env_override(client, five_ticket_seat, monkeypatch):
    # a tighter budget forces a tighter pass; the irreducible floor is the 5 ticket records
    # themselves (criteria/chain are summary fields, never dropped), so 12 KB is achievable.
    monkeypatch.setenv("EDP8_CONTEXT_BUDGET_B", "12000")
    set_client(BoardClient(participant=five_ticket_seat, admin_token="t", client=client))
    ctx = ALL_TOOLS["context"]
    bounded = ctx.handler(ctx.args_model())["value"]
    assert _bytes(bounded) <= 12000, f"tighter budget not honoured: {_bytes(bounded)} bytes"
    assert "12000" in bounded["omitted"]["why"]
