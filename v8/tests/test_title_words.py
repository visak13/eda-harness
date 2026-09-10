"""Human ruling #32 (2026-09-10, "Title ≠ words").

An epic's `words` are the owner's request verbatim and immutable (design §1); its `title` is a short
human title (<= 80 chars) the board derives from the words' first clause when the request runs long.
ticket_update(title=) lets the architect or the owner rename an epic or a story; a task's title is
fixed; the words never change. Board + Store(':memory:') directly, plus the REST surface.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board, BoardError
from edp8.schemas import EventKind, Role, TicketKind, WorkType
from edp8.service import create_app
from edp8.store import Store

LONG = ("First I want concepts before any planning, because the last three epics went straight to code "
        "and every one of them had to be redone once the owner saw the shape. Then a design doc with the "
        "chosen concept, then stories under it, then the engineers build; nothing is signed off until I "
        "have seen a walkthrough of the concept myself and said yes in writing.")
assert len(LONG) > 300


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def rig(board):
    roles = {"owner": Role.owner, "architect": Role.architect, "engineer": Role.engineer}
    return {h: board.participant_create("human" if h == "owner" else "agent", r, h) for h, r in roles.items()}


def _epic(board, rig, title=LONG, **kw):
    return board.ticket_create(rig["owner"], kind=TicketKind.epic, work_type=WorkType.feature, title=title, **kw)


def _story(board, rig, epic):
    return board.ticket_create(rig["architect"], kind=TicketKind.story, work_type=WorkType.feature,
                               title="the concept story", parent_id=epic.id)


# ---- create: words verbatim, title derived ---------------------------------------------------

def test_long_request_keeps_words_verbatim_and_derives_a_short_title(board, rig):
    e = _epic(board, rig)
    assert e.words == LONG
    assert len(e.title) <= 80
    assert e.title == "First I want concepts before any planning, because the last three epics went…"
    # the stored record agrees with the returned one
    t = board.ticket(e.id)
    assert (t.words, t.title) == (LONG, e.title)


def test_first_clause_shorter_than_80_is_the_title(board, rig):
    words = "Ship the hello CLI. " + "x" * 200
    e = _epic(board, rig, title=words)
    assert e.words == words
    assert e.title == "Ship the hello CLI"


def test_short_request_title_equals_words(board, rig):
    e = _epic(board, rig, title="Build a hello CLI")
    assert e.title == "Build a hello CLI"
    assert e.words == "Build a hello CLI"


def test_explicit_words_kwarg_keeps_both(board, rig):
    e = _epic(board, rig, title="Hello CLI", words=LONG)
    assert e.title == "Hello CLI"
    assert e.words == LONG


def test_story_and_task_carry_no_words(board, rig):
    e = _epic(board, rig)
    s = _story(board, rig, e)
    assert s.words is None
    t = board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                            title="one task", parent_id=s.id)
    assert t.words is None


def test_words_stay_searchable_after_title_is_shortened(board, rig):
    e = _epic(board, rig)
    assert "walkthrough" not in e.title
    assert e.id in [h["id"] for h in board.store.fts_search("walkthrough", types={"ticket"})]


# ---- update: title settable by architect/owner on epic and story, words immutable ----------

def test_architect_sets_epic_title(board, rig):
    e = _epic(board, rig)
    out = board.ticket_update(rig["architect"], e.id, title="Concepts before planning")
    assert out.title == "Concepts before planning"
    assert board.ticket(e.id).title == "Concepts before planning"
    assert board.ticket(e.id).words == LONG  # unchanged
    evs = [ev for _, ev in board.store.events_since(0, limit=500)
           if ev.kind == EventKind.ticket_updated and ev.subject_id == e.id]
    assert evs and "title" in evs[-1].data["changed"]


def test_owner_sets_story_title(board, rig):
    e = _epic(board, rig)
    s = _story(board, rig, e)
    assert board.ticket_update(rig["owner"], s.id, title="Concept story, renamed").title == "Concept story, renamed"


def test_engineer_may_not_set_title(board, rig):
    e = _epic(board, rig)
    s = _story(board, rig, e)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["engineer"], s.id, title="nope")
    assert ei.value.code == "scope"


def test_title_over_80_is_refused(board, rig):
    e = _epic(board, rig)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["architect"], e.id, title="t" * 81)
    assert ei.value.code == "scope"
    assert "80" in ei.value.message
    assert board.ticket(e.id).title == e.title


def test_task_title_is_fixed(board, rig):
    e = _epic(board, rig)
    s = _story(board, rig, e)
    t = board.ticket_create(rig["engineer"], kind=TicketKind.task, work_type=WorkType.feature,
                            title="one task", parent_id=s.id)
    with pytest.raises(BoardError) as ei:
        board.ticket_update(rig["architect"], t.id, title="renamed task")
    assert ei.value.code == "scope"


def test_ticket_update_has_no_words_argument(board, rig):
    e = _epic(board, rig)
    with pytest.raises(TypeError):
        board.ticket_update(rig["owner"], e.id, words="rewritten")  # type: ignore[call-arg]
    assert board.ticket(e.id).words == LONG


# ---- reads: the epic page / board read return the words verbatim ----------------------------

def test_board_and_ticket_view_return_words_verbatim(board, rig):
    e = _epic(board, rig)
    s = _story(board, rig, e)
    board.ticket_update(rig["architect"], e.id, title="Concepts before planning")
    assert board.board(e.id)["words"] == LONG
    assert board.ticket_view(e.id)["words"] == LONG
    assert board.ticket_view(s.id)["words"] == LONG
    assert board.ticket_view(e.id)["ticket"]["title"] == "Concepts before planning"


# ---- REST: TicketIn.words, TicketPatch.title, Ticket.words in the JSON ----------------------

@pytest.fixture
def client():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


@pytest.fixture
def http(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent")]:
        r = client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                        headers={"X-Admin": "t"})
        assert r.json()["ok"], r.text
    return {pid: {"X-Participant": pid} for pid in ("owner", "arch")}


def test_rest_epic_json_carries_words_and_patch_title(client, http):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": LONG}, headers=http["owner"])
    v = r.json()["value"]
    assert v["words"] == LONG and len(v["title"]) <= 80
    r = client.patch(f"/v1/tickets/{v['id']}", json={"title": "Concepts before planning"}, headers=http["arch"])
    assert r.json()["ok"], r.text
    assert r.json()["value"]["title"] == "Concepts before planning"
    assert r.json()["value"]["words"] == LONG
    r = client.get(f"/v1/tickets/{v['id']}", headers=http["arch"])
    assert r.json()["value"]["words"] == LONG


def test_epic_page_carries_words_title_and_description(board, rig):
    """Human #33: the epic page returns the architect's brief (`description`) and the short `title`
    at the top level, next to the verbatim `words`."""
    from edp8 import views
    e = _epic(board, rig)
    board.ticket_update(rig["architect"], e.id, title="Concepts before planning",
                        description="Brief: concept first, then design, then stories.")
    page = views.epic_page(board, e.id)
    assert page["words"] == LONG
    assert page["title"] == "Concepts before planning"
    assert page["description"] == "Brief: concept first, then design, then stories."


def test_rest_epic_page_carries_words_title_and_description(client, http):
    r = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": LONG,
                                         "description": "the brief"}, headers=http["owner"])
    eid = r.json()["value"]["id"]
    r = client.get(f"/v1/epics/{eid}/page", headers=http["arch"])
    assert r.json()["ok"], r.text
    v = r.json()["value"]
    assert v["words"] == LONG and v["description"] == "the brief" and len(v["title"]) <= 80
