"""Board UI without page reloads (2026-09-06): scoped poll + region swap, recipient picker with
@autocomplete, a cross-epic tickets page with filters, grouped inbox."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
H = {"X-Participant": "owner"}


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def client(board, monkeypatch, ui_prefix):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a: True)
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("ravi", "reviewer", "human"), ("arch", "architect", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    e = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Galaxy site"},
                    headers=H).json()["value"]["id"]
    s = client.post("/v1/tickets", json={"kind": "story", "work_type": "bug", "title": "fix the ship sheet", "parent_id": e,
                                         "tags": ["assets"]}, headers={"X-Participant": "arch"}).json()["value"]["id"]
    seat = f"engineer.{s}"
    client.post("/v1/participants", json={"type": "agent", "role": "engineer", "handle": seat, "id": seat}, headers=ADMIN)
    client.put("/v1/sessions/sid-1", headers=ADMIN,
               json={"participant_id": seat, "ticket_id": s, "pool_id": "local", "state": "alive"})
    return {"epic": e, "story": s, "seat": seat}


def test_no_meta_refresh_anywhere_and_pages_carry_poll_scope(client, rig, ui_prefix):
    for path, params, scope in ((f"{ui_prefix}/me", {"as": "owner"}, "me"),
                                (f"{ui_prefix}/epic/{rig['epic']}", {"as": "owner"}, f"epic:{rig['epic']}"),
                                (f"{ui_prefix}/ticket/{rig['story']}", {"as": "owner"}, f"ticket:{rig['story']}"),
                                (f"{ui_prefix}/activity", {"as": "owner"}, "me"),
                                (f"{ui_prefix}/tickets", {}, "all"),
                                (f"{ui_prefix}", {}, "all")):
        page = client.get(path, params=params).text
        assert "http-equiv" not in page, path
        assert f"data-poll='{scope}'" in page and "data-seq='" in page, path
        assert "id='page-body'" in page and "/ui/poll?since=" in page, path


def test_poll_counts_only_events_in_scope(client, rig):
    seq = client.get("/ui/poll", params={"since": 0, "scope": "all"}).json()["seq"]
    other = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "elsewhere"},
                        headers=H).json()["value"]["id"]
    assert client.get("/ui/poll", params={"since": seq, "scope": f"epic:{rig['epic']}"}).json()["new"] == 0
    assert client.get("/ui/poll", params={"since": seq, "scope": "all"}).json()["new"] >= 1
    client.post("/v1/messages", json={"ticket_id": rig["story"], "kind": "note", "text": "hi"}, headers=H)
    r = client.get("/ui/poll", params={"since": seq, "scope": f"epic:{rig['epic']}"}).json()
    assert r["new"] == 1 and r["seq"] > seq
    assert client.get("/ui/poll", params={"since": r["seq"], "scope": f"ticket:{rig['story']}"}).json()["new"] == 0
    # 'me' scope is the owner's relevance filter
    client.post("/v1/messages", json={"ticket_id": rig["story"], "kind": "question", "to": "owner", "text": "q?"},
                headers={"X-Participant": "ravi"})
    assert client.get("/ui/poll", params={"since": r["seq"], "scope": "me", "as": "owner"}).json()["new"] == 1
    assert other


def test_inbox_has_recipient_picker_people_json_and_grouping(client, rig, ui_prefix):
    client.post("/v1/messages", json={"ticket_id": rig["story"], "kind": "question", "to": "owner", "text": "one?"},
                headers={"X-Participant": "ravi"})
    client.post("/v1/messages", json={"ticket_id": rig["epic"], "kind": "question", "to": "owner", "text": "two?"},
                headers={"X-Participant": "ravi"})
    page = client.get(f"{ui_prefix}/me", params={"as": "owner"}).text
    assert "<select name='to'" in page and f"value='{rig['seat']}'" in page and "value='ravi'" in page
    assert "id='people-json'" in page and '"handle": "ravi"' in page and f'"handle": "{rig["seat"]}"' in page
    assert page.count("class='fold ask-group'") == 2  # one group per ticket
    assert "<optgroup label='Your conversations'>" in page
    assert "type @ to mention" in page


def test_send_with_recipient_and_unresolved_mention_banner(client, rig, ui_prefix):
    r = client.post(f"{ui_prefix}/me/message", data={"as_": "owner", "ticket_id": rig["story"], "to": "ravi", "kind": "question",
                                            "text": "please look @nobody @ravi"}, follow_redirects=False)
    assert r.status_code == 303 and "unresolved=nobody" in r.headers["location"] and "sent=" in r.headers["location"]
    page = client.get(f"{ui_prefix}/me", params={"as": "owner", "sent": rig["story"], "unresolved": "nobody"}).text
    assert "@nobody" in page and "matched nobody" in page
    m = client.get("/v1/messages", params={"ticket_id": rig["story"]}, headers=H).json()["value"][-1]
    assert m["to"] == "ravi"


def test_tickets_page_filters(client, rig, ui_prefix):
    page = client.get(f"{ui_prefix}/tickets").text
    assert rig["story"] in page and "name='q'" in page and "Tickets" in page
    assert rig["story"] in client.get(f"{ui_prefix}/tickets", params={"q": "ship sheet"}).text
    assert rig["story"] not in client.get(f"{ui_prefix}/tickets", params={"q": "nebula"}).text
    assert rig["story"] in client.get(f"{ui_prefix}/tickets", params={"tag": "assets"}).text
    assert rig["story"] not in client.get(f"{ui_prefix}/tickets", params={"work_type": "feature", "epic": rig["epic"]}).text
    assert rig["story"] in client.get(f"{ui_prefix}/tickets", params={"kind": "story", "epic": rig["epic"]}).text


def test_epic_page_filter_bar(client, rig, ui_prefix):
    page = client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "owner"}).text
    assert "class='filter-bar'" in page and rig["story"] in page
    filtered = client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "owner", "work_type": "feature"}).text
    assert rig["story"] not in filtered.split("Epic thread")[0]
    assert rig["story"] in client.get(f"{ui_prefix}/epic/{rig['epic']}", params={"as": "owner", "q": "sheet"}).text
