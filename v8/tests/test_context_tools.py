"""Context tools that fit the work (2026-09-06): fat ticket_read, ticket description/tags/epic_id,
ticket_query filters + q, message since_seq/message_read, find over criteria with epic scoping."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import Link, Relation, Ticket, TicketKind, WorkType
from edp8.search import Index, make_embedder
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
H = {"X-Participant": "owner"}


@pytest.fixture
def board():
    return Board(Store(":memory:"), Index(embedder=make_embedder()))


@pytest.fixture
def client(board):
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"), ("eng", "engineer", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid}, headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Space game site",
                                            "description": "showcase site for the galaxy game", "tags": ["web"]},
                       headers=H).json()["value"]
    s1 = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "S10 ship selection sheet",
                                          "parent_id": epic["id"], "description": "build the selection sheet from Astra concepts",
                                          "tags": ["assets", "astra"]}, headers={"X-Participant": "arch"}).json()["value"]
    t1 = client.post("/v1/tickets", json={"kind": "task", "work_type": "feature", "title": "T1 capture renders",
                                          "parent_id": s1["id"], "assignee": "eng"}, headers={"X-Participant": "arch"}).json()["value"]
    c = client.post("/v1/criteria", json={"ticket_id": s1["id"], "text": "the selection sheet renders four ships",
                                          "check": "look", "checked_by": "reviewer"}, headers={"X-Participant": "arch"}).json()["value"]
    d = client.post("/v1/docs", json={"doc_type": "note", "title": "ship ledger", "body_md": "kestrel pilgrim",
                                      "scope": epic["id"]}, headers={"X-Participant": "arch"}).json()["value"]
    client.post("/v1/links", json={"from_id": s1["id"], "to_id": d["id"], "relation": "evidence_for"},
                headers={"X-Participant": "arch"})
    return {"epic": epic, "s1": s1, "t1": t1, "crit": c, "doc": d}


def test_ticket_has_description_tags_and_epic_id(rig):
    assert rig["epic"]["epic_id"] == rig["epic"]["id"] and rig["epic"]["tags"] == ["web"]
    assert rig["s1"]["epic_id"] == rig["epic"]["id"] and rig["t1"]["epic_id"] == rig["epic"]["id"]
    assert rig["s1"]["description"].startswith("build the selection sheet")


def test_fat_ticket_read_has_every_section(client, rig):
    client.post("/v1/messages", json={"ticket_id": rig["s1"]["id"], "kind": "note", "text": "first"}, headers=H)
    v = client.get(f"/v1/tickets/{rig['s1']['id']}", headers=H).json()["value"]
    assert v["title"].startswith("S10") and v["epic_id"] == rig["epic"]["id"]
    assert [c["id"] for c in v["chain"]] == [rig["s1"]["id"], rig["epic"]["id"]]
    assert v["criteria"][0]["id"] == rig["crit"]["id"]
    assert v["docs"][0]["id"] == rig["doc"]["id"] and v["docs"][0]["relation"] == "evidence_for"
    kid = v["children"][0]
    assert kid["id"] == rig["t1"]["id"] and kid["assignee"] == "eng" and kid["assignee_role"] == "engineer"
    assert kid["criteria"] == "0/0"
    assert v["open_gates"] == [] and v["blockers"] == []
    assert v["thread"][0]["text"] == "first" and v["thread_seq"] == v["thread"][0]["seq"] and v["thread_total"] == 1
    assert any(lk["relation"] == "evidence_for" for lk in v["links"])
    narrow = client.get(f"/v1/tickets/{rig['s1']['id']}", params={"include": "children"}, headers=H).json()["value"]
    assert "children" in narrow and "thread" not in narrow


def test_ticket_query_filters_and_word_search(client, rig):
    q = lambda **p: [t["id"] for t in client.get("/v1/tickets", params=p, headers=H).json()["value"]]
    assert set(q(epic_id=rig["epic"]["id"])) == {rig["epic"]["id"], rig["s1"]["id"], rig["t1"]["id"]}
    assert q(tag="astra") == [rig["s1"]["id"]]
    assert q(created_by="owner") == [rig["epic"]["id"]]
    assert q(q="selection sheet") == [rig["s1"]["id"]]
    assert q(q="galaxy") == [rig["epic"]["id"]]
    assert q(kind="task", epic_id=rig["epic"]["id"]) == [rig["t1"]["id"]]


def test_message_since_seq_and_message_read(client, rig):
    sid = rig["s1"]["id"]
    m1 = client.post("/v1/messages", json={"ticket_id": sid, "kind": "question", "to": "eng", "text": "q1"}, headers=H).json()["value"]
    r = client.get("/v1/messages", params={"ticket_id": sid}, headers=H).json()
    seq1 = r["value"][-1]["seq"]
    assert "last_seq=" in r["hint"] and r["value"][-1]["id"] == m1["id"]
    m2 = client.post("/v1/messages", json={"ticket_id": sid, "kind": "answer", "to": "owner", "reply_to": m1["id"],
                                           "text": "a1"}, headers={"X-Participant": "eng"}).json()["value"]
    newer = client.get("/v1/messages", params={"ticket_id": sid, "since_seq": seq1}, headers=H).json()["value"]
    assert [m["id"] for m in newer] == [m2["id"]]
    one = client.get(f"/v1/messages/{m1['id']}", headers=H).json()["value"]
    assert one["seq"] == seq1 and [x["id"] for x in one["replies"]] == [m2["id"]]
    assert client.get(f"/v1/messages/{m2['id']}", headers=H).json()["value"]["in_reply_to"]["id"] == m1["id"]
    by = client.get("/v1/messages", params={"ticket_id": sid, "created_by": "eng"}, headers=H).json()["value"]
    assert [m["id"] for m in by] == [m2["id"]]


def test_find_covers_criteria_and_scopes_to_epic(client, rig):
    hits = client.get("/v1/find", params={"q": "selection sheet"}, headers=H).json()["value"]
    kinds = {(h["type"], h["id"]) for h in hits}
    assert ("ticket", rig["s1"]["id"]) in kinds and ("criterion", rig["crit"]["id"]) in kinds
    crit_hit = next(h for h in hits if h["type"] == "criterion")
    assert crit_hit["ticket_id"] == rig["s1"]["id"] and crit_hit["epic_id"] == rig["epic"]["id"]
    tk_hit = next(h for h in hits if h["type"] == "ticket")
    assert tk_hit["title"].startswith("S10") and tk_hit["status"] == "drafted"
    other = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "selection sheet elsewhere"},
                        headers=H).json()["value"]
    scoped = client.get("/v1/find", params={"q": "selection sheet", "epic_id": rig["epic"]["id"]}, headers=H).json()["value"]
    assert all(h["epic_id"] == rig["epic"]["id"] for h in scoped) and other["id"] not in {h["id"] for h in scoped}


def test_tool_layer_accepts_ticket_id_alias_and_describe_lists_tools(client, rig):
    set_client(BoardClient(participant="owner", admin_token="t", client=client))
    t = ALL_TOOLS["ticket_read"]
    out = t.handler(t.args_model(ticket_id=rig["s1"]["id"]))  # the misfire agents typed most
    assert out["ok"] and out["value"]["id"] == rig["s1"]["id"]
    d = ALL_TOOLS["describe"]
    out = d.handler(d.args_model(type="ticket"))
    assert "ticket_read" in out["value"]["tools"] and "find" in out["value"]["tools"]


def test_old_board_migrates_columns_and_fts(tmp_path):
    """A board file from before 2026-09-06 gains created_by/epic_id/checked_by columns, epic_id
    values, and a populated FTS table on first open."""
    import sqlite3, json
    db = tmp_path / "old.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE ticket (id TEXT PRIMARY KEY, seq INTEGER, created_at TEXT, body TEXT NOT NULL, "
                "kind TEXT, work_type TEXT, parent_id TEXT, status TEXT, assignee TEXT)")
    con.execute("CREATE TABLE seq (name TEXT PRIMARY KEY, n INTEGER)")
    e = Ticket(id="epic-old", kind=TicketKind.epic, work_type=WorkType.feature, title="old epic words", created_by="owner")
    s = Ticket(id="s-old", kind=TicketKind.story, work_type=WorkType.feature, title="old story", parent_id="epic-old",
               created_by="arch")
    for n, t in enumerate((e, s), start=1):
        con.execute("INSERT INTO ticket VALUES (?,?,?,?,?,?,?,?,?)",
                    (t.id, n, t.created_at.isoformat(), t.model_dump_json(exclude={"description", "tags", "epic_id"}),
                     t.kind, t.work_type, t.parent_id, t.status, t.assignee))
    con.execute("INSERT INTO seq VALUES ('global', 2)")
    con.commit(); con.close()
    store = Store(db)
    cols = {r[1] for r in store._conn.execute("PRAGMA table_info(ticket)")}
    assert {"created_by", "epic_id"} <= cols
    assert store.query("ticket", {"created_by": "arch"})[0].id == "s-old"
    b = Board(store)
    assert b.ensure_epic_ids() == 2 and b.ticket("s-old").epic_id == "epic-old"
    assert [h["id"] for h in store.fts_search("words")] == ["epic-old"]
