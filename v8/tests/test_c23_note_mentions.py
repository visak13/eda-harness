"""epic-52edacd059 C23 (s-93ddb7fd1a): an @handle in a quote's note notifies like one in the text.

message_send resolves @mentions from the text AND every quote's note: the message_sent event's
`mentions`, the broker mirror (delivery.after_message) and `unresolved_mentions` all read both, with
the same exclusions (sender, `to`) and the same unknown-handle-is-prose rule, one entry per person.
"""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import delivery
from edp8.board import Board
from edp8.schemas import EventKind
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
ARCH = {"X-Participant": "arch"}


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def client(board):
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def published(monkeypatch):
    got: list[tuple[str, str]] = []
    monkeypatch.setattr(delivery.broker_adapter, "publish",
                        lambda frm, to, kind, body: got.append((to, body.get("board_msg_id"))))
    return got


@pytest.fixture
def env(client):
    for pid, role, typ in [("owner", "owner", "human"), ("vishal", "owner", "human"),
                           ("arch", "architect", "agent"), ("eng", "engineer", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "c23"},
                       headers=OWNER).json()["value"]
    story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "C23",
                                             "parent_id": epic["id"], "assignee": "eng"},
                        headers=ARCH).json()["value"]["id"]
    src = client.post("/v1/messages", headers=ARCH, json={"ticket_id": story, "kind": "note",
                                                          "text": "The quoted passage."}).json()["value"]["id"]
    return {"story": story, "src": src}


def send(client, env, *, text="see this", note=None, to="eng", who=OWNER):
    q = {"source": "message", "id": env["src"], "text": "The quoted passage."}
    if note is not None:
        q["note"] = note
    r = client.post("/v1/messages", headers=who, json={"ticket_id": env["story"], "to": to,
                                                       "kind": "question", "text": text, "quotes": [q]})
    assert r.status_code == 200 and r.json()["ok"], r.text
    return r.json()["value"]


def event_mentions(board, mid):
    evs = [e for e in board.store.query("event", {"kind": EventKind.message_sent}, limit=500)
           if e.data.get("message") == mid]
    assert len(evs) == 1
    return evs[0].data["mentions"]


def test_a_mention_only_in_a_note_is_notified_and_listed(board, client, env, published):
    m = send(client, env, text="no handles here", note="@vishal can you rule on this?")
    assert event_mentions(board, m["id"]) == ["vishal"]
    assert ("vishal", m["id"]) in published       # the broker inbox mirror wakes the person
    assert m["unresolved_mentions"] == []


def test_a_handle_in_text_and_note_is_listed_once(board, client, env, published):
    m = send(client, env, text="@vishal look", note="@vishal and this line")
    assert event_mentions(board, m["id"]) == ["vishal"]
    assert [to for to, mid in published if mid == m["id"]].count("vishal") == 1


def test_sender_and_to_are_excluded_in_notes(board, client, env, published):
    m = send(client, env, text="x", note="@owner @eng @vishal", to="eng", who=OWNER)
    assert event_mentions(board, m["id"]) == ["vishal"]
    assert [to for to, mid in published if mid == m["id"]] == ["eng", "vishal"]  # eng once, as `to`


def test_an_unknown_handle_in_a_note_is_prose_like_in_text(board, client, env, published):
    in_text = send(client, env, text="@nobody here", note=None)
    in_note = send(client, env, text="x", note="@nobody here")
    for m in (in_text, in_note):
        assert event_mentions(board, m["id"]) == []
        assert m["unresolved_mentions"] == ["nobody"]
        assert [to for to, mid in published if mid == m["id"]] == ["eng"]


def test_an_open_fence_in_the_text_does_not_swallow_a_note_mention(board, client, env, published):
    m = send(client, env, text="```\nunclosed", note="@vishal")
    assert event_mentions(board, m["id"]) == ["vishal"]


def test_mentions_in_several_notes_keep_order(board, client, env, published):
    qs = [{"source": "message", "id": env["src"], "text": "The quoted passage.", "note": "@arch first"},
          {"source": "message", "id": env["src"], "text": "The quoted passage.", "note": "@vishal @arch"}]
    r = client.post("/v1/messages", headers=OWNER, json={"ticket_id": env["story"], "to": "eng",
                                                         "kind": "question", "text": "x", "quotes": qs})
    assert event_mentions(board, r.json()["value"]["id"]) == ["arch", "vishal"]
