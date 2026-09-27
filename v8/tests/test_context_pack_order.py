"""Owner ruling m-9f2b933578 (dec-7581ebda87): the context-pack exam's Q2 miss was a message addressed to the
seat buried under newer thread posts. context() carries, per ticket, `for_you` (messages addressed to the seat,
by handle or role, not its own) ahead of the newest-N `thread` window, on every budget pass; the window never
holds the seat's own posts.
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


@pytest.fixture
def seat(client_app):
    c = client_app
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent"), ("eng2", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers=ADMIN).json()["ok"]
    A, E = {"X-Participant": "arch"}, {"X-Participant": "eng"}
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "epic",
                                       "description": "an epic"}, headers={"X-Participant": "owner"}).json()["value"]
    s = c.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "the story",
                                    "parent_id": epic["id"], "assignee": "eng",
                                    "description": "d " * 2000}, headers=A).json()["value"]
    c.post("/v1/criteria", json={"ticket_id": s["id"], "text": "it works", "check": "command",
                                 "checked_by": "qa"}, headers=A)

    def post(h, **kw):
        return c.post("/v1/messages", json={"ticket_id": s["id"], **kw}, headers=h).json()["value"]["id"]

    buried = post(A, kind="finding", to="eng", text="FINDING-FOR-ENG: fix the pack order " + "x " * 300)
    by_role = post(A, kind="note", to="engineer", text="ROLE-NOTE: every engineer reads this")
    post(A, kind="note", to="eng2", text="NOT-FOR-ENG: another seat's note")
    reply = post(E, kind="answer", to="arch", reply_to=by_role, text="ack")
    own = [post(E, kind="note", text=f"OWN-{i} " + "mine " * 40) for i in range(12)]
    chatter = [post(A, kind="note", text=f"CHATTER-{i} " + "noise " * 40) for i in range(12)]
    return {"client": c, "buried": buried, "by_role": by_role, "reply": reply, "own": set(own),
            "chatter": chatter, "story": s["id"]}


@pytest.fixture
def client_app():
    return TestClient(create_app(Board(Store(":memory:")), admin_token="t"))


def _pack(seat, monkeypatch, budget: int) -> dict:
    monkeypatch.setenv("EDP8_CONTEXT_BUDGET_B", str(budget))
    set_client(BoardClient(participant="eng", admin_token="t", client=seat["client"]))
    ctx = ALL_TOOLS["context"]
    return ctx.handler(ctx.args_model())["value"]


@pytest.mark.parametrize("budget", [4000, 8000, 16000, 40000])
def test_addressed_messages_come_first_and_own_posts_never_fill_the_window(seat, monkeypatch, budget):
    pack = _pack(seat, monkeypatch, budget)
    tv = next(t for t in pack["tickets"] if t["ticket"]["id"] == seat["story"])
    keys = list(tv)
    assert keys.index("for_you") < keys.index("thread"), "for_you rides ahead of the newest-N window"
    ids = [m["id"] for m in tv["for_you"]]
    assert ids == [seat["buried"], seat["by_role"]], f"at {budget} B: {ids}"  # handle + role, oldest first
    assert next(m for m in tv["for_you"] if m["id"] == seat["by_role"]).get("answered") is True
    assert "answered" not in tv["for_you"][0]
    window = {m["id"] for m in tv["thread"]}
    assert not window & seat["own"], "the seat's own posts never fill the window"
    assert seat["reply"] not in window
    assert not window & set(ids), "a for_you row is not repeated in the window"
    assert window <= set(seat["chatter"]), "the window is the newest posts by others"
    blob = json.dumps(pack)
    assert "NOT-FOR-ENG" not in json.dumps(tv["for_you"]) and "FINDING-FOR-ENG" in blob


def test_full_snapshot_carries_for_you_too(seat, monkeypatch):
    set_client(BoardClient(participant="eng", admin_token="t", client=seat["client"]))
    ctx = ALL_TOOLS["context"]
    full = ctx.handler(ctx.args_model(verbose=True))["value"]
    tv = next(t for t in full["tickets"] if t["ticket"]["id"] == seat["story"])
    assert [m["id"] for m in tv["for_you"]] == [seat["buried"], seat["by_role"]]
