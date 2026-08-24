"""Tests for edp8.plane_adapter: mirror push (board -> fake Plane) and webhook sink (Plane -> board)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.plane_adapter import PlaneClient, PlaneMirror, webhook_router
from edp8.schemas import (
    DocType,
    EventKind,
    MessageKind,
    Role,
    TicketKind,
    WorkType,
)
from edp8.store import Store


class FakePlane:
    """Records every request; hands back deterministic ids."""

    def __init__(self):
        self.requests: list[tuple[str, str, dict]] = []
        self._issue_seq = 0
        self.fail_next = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append((request.method, str(request.url), body))
        if self.fail_next:
            self.fail_next = False
            return httpx.Response(500, json={"error": "boom"})
        if request.method == "POST" and request.url.path.endswith("/issues/"):
            self._issue_seq += 1
            return httpx.Response(200, json={"id": f"issue-{self._issue_seq}"})
        if request.method == "PATCH":
            return httpx.Response(200, json={"ok": True})
        if request.method == "POST" and "/comments/" in request.url.path:
            return httpx.Response(200, json={"ok": True})
        if request.method == "GET" and request.url.path.endswith("/states/"):
            return httpx.Response(200, json=[
                {"name": "in_progress", "id": "state-inprog"},
                {"name": "done", "id": "state-done"},
            ])
        return httpx.Response(404, json={"error": "unhandled"})


@pytest.fixture
def board():
    b = Board(Store(":memory:"))
    b.participant_create("human", Role.owner, "owner", id_="owner")
    b.participant_create("agent", Role.architect, "arch", id_="arch")
    b.participant_create("agent", Role.engineer, "eng", id_="eng")
    return b


@pytest.fixture
def fake_plane():
    return FakePlane()


@pytest.fixture
def mirror(board, fake_plane):
    http = httpx.Client(transport=httpx.MockTransport(fake_plane.handler))
    client = PlaneClient("http://plane.local", "key", "ws", "proj", http=http)
    return PlaneMirror(board, client)


def test_ticket_created_creates_issue_and_maps(board, mirror, fake_plane):
    owner = board.participant("owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic one")
    for seq, ev in board.store.events_since(0):
        mirror.on_event(ev)

    creates = [r for r in fake_plane.requests if r[0] == "POST" and r[1].endswith("/issues/")]
    assert len(creates) == 1
    assert creates[0][2]["name"] == "Epic one"

    from edp8.plane_adapter import _map_get

    assert _map_get(board, epic.id) == "issue-1"
    assert mirror.errors == []


def test_status_changed_updates_issue_state(board, mirror, fake_plane):
    owner = board.participant("owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic two")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)  # maps epic.id -> issue-1

    # drive a status_changed event directly (full lifecycle transitions are board.py's concern,
    # not the mirror's — the mirror only needs a valid event with a mapped subject_id).
    board._emit(epic.id, EventKind.status_changed, {"from": "drafted", "to": "in_progress", "by": owner.id})

    for s, ev in board.store.events_since(board.store.max_seq() - 1):
        mirror.on_event(ev)

    patches = [r for r in fake_plane.requests if r[0] == "PATCH"]
    assert any(p[2].get("state") == "state-inprog" for p in patches)


def test_message_sent_adds_comment(board, mirror, fake_plane):
    owner = board.participant("owner")
    arch = board.participant("arch")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic three")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)

    board.message_send(arch, ticket_id=epic.id, to=None, kind=MessageKind.note, text="hello plane")
    latest = board.store.events_since(board.store.max_seq() - 1)
    for s, ev in latest:
        mirror.on_event(ev)

    comments = [r for r in fake_plane.requests if r[0] == "POST" and "/comments/" in r[1]]
    assert any("hello plane" in c[2]["comment_html"] for c in comments)


def test_doc_updated_design_doc_comments_with_link(board, mirror, fake_plane):
    owner = board.participant("owner")
    arch = board.participant("arch")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic four")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)

    doc = board.doc_create(arch, doc_type=DocType.design, title="Design", body_md="# hi", scope=epic.id)
    for s, ev in board.store.events_since(board.store.max_seq() - 1):
        mirror.on_event(ev)

    comments = [r for r in fake_plane.requests if r[0] == "POST" and "/comments/" in r[1]]
    assert any(f"[edp8:doc] {doc.id} v1" in c[2]["comment_html"] for c in comments)


def test_mirror_is_best_effort_on_http_error(board, mirror, fake_plane):
    owner = board.participant("owner")
    fake_plane.fail_next = True
    board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Will fail")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)  # must not raise

    assert len(mirror.errors) == 1


def test_webhook_adds_note_message_from_plane(board, mirror, fake_plane):
    owner = board.participant("owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic five")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)  # maps epic.id -> issue-1

    app = FastAPI()
    app.include_router(webhook_router(board))
    tc = TestClient(app)

    payload = {
        "event": "issue_comment",
        "action": "created",
        "data": {"issue": "issue-1", "comment_html": "<p>a human reply on plane</p>"},
    }
    r = tc.post("/v1/plane/webhook", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    msgs = board.thread(epic.id)
    notes = [m for m in msgs if m.created_by == "plane"]
    assert len(notes) == 1
    assert notes[0].kind == MessageKind.note
    assert "a human reply" in notes[0].text


def test_webhook_ignores_our_own_mirrored_comment(board, mirror, fake_plane):
    owner = board.participant("owner")
    epic = board.ticket_create(owner, kind=TicketKind.epic, work_type=WorkType.feature, title="Epic six")
    for s, ev in board.store.events_since(0):
        mirror.on_event(ev)

    app = FastAPI()
    app.include_router(webhook_router(board))
    tc = TestClient(app)

    payload = {
        "event": "issue_comment",
        "action": "created",
        "data": {"issue": "issue-1", "comment_html": "<p>[edp8:note] from arch: mirrored text</p>"},
    }
    tc.post("/v1/plane/webhook", json=payload)

    notes = [m for m in board.thread(epic.id) if m.created_by == "plane"]
    assert notes == []


def test_webhook_ignores_unmapped_issue(board):
    app = FastAPI()
    app.include_router(webhook_router(board))
    tc = TestClient(app)

    payload = {
        "event": "issue_comment",
        "action": "created",
        "data": {"issue": "issue-unknown", "comment_html": "<p>orphan</p>"},
    }
    r = tc.post("/v1/plane/webhook", json=payload)
    assert r.status_code == 200
