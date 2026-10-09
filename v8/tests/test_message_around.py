"""e0cec S3 (design-b6a55eed13 §4.A "Old discussion"): message_query(around=<id>, window=N) returns N before, the
target whole and N after in seq order (default 5, max 25); ticket_read(before_seq=) pages the thread tail back."""
import pytest

from edp8 import broker_adapter, bundles
from edp8.board import Board
from edp8.service import create_app
from edp8.store import Store

OWN = {"X-Participant": "owner"}
LONG = "x" * 600


@pytest.fixture
def rig(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    c = TestClient(create_app(Board(Store(":memory:")), admin_token="t"))
    assert c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"},
                  headers={"X-Admin": "t"}).json()["ok"]
    epic = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "E"},
                  headers=OWN).json()["value"]["id"]
    other = c.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "Other"},
                   headers=OWN).json()["value"]["id"]
    ids = []
    for n in range(40):
        body = LONG if n == 20 else f"msg {n}"
        ids.append(c.post("/v1/messages", json={"ticket_id": epic, "kind": "note", "text": body},
                          headers=OWN).json()["value"]["id"])
    return c, epic, other, ids


def around(c, mid, **params):
    return c.get("/v1/messages", params={"around": mid, **params}, headers=OWN).json()


def texts(resp):
    return [r["text"] for r in resp["value"]]


def test_around_returns_n_before_the_target_and_n_after_in_seq_order(rig):
    c, epic, other, ids = rig
    resp = around(c, ids[10], window=3)
    assert resp["ok"] and texts(resp) == [f"msg {n}" for n in range(7, 14)]
    seqs = [r["seq"] for r in resp["value"]]
    assert seqs == sorted(seqs)
    assert [r["id"] for r in resp["value"] if r.get("target")] == [ids[10]]


def test_the_default_window_is_five(rig):
    c, epic, other, ids = rig
    assert texts(around(c, ids[10])) == [f"msg {n}" for n in range(5, 16)]


def test_the_window_is_capped_at_25(rig):
    c, epic, other, ids = rig
    resp = around(c, ids[20], window=99)
    assert len(resp["value"]) == 40 and [r["id"] for r in resp["value"]] == ids
    short = around(c, ids[30], window=99)
    assert [r["id"] for r in short["value"]] == ids[5:]  # 25 before, the target, the 9 after it


def test_the_edges_return_what_exists(rig):
    c, epic, other, ids = rig
    assert [r["id"] for r in around(c, ids[0], window=2)["value"]] == ids[:3]
    assert [r["id"] for r in around(c, ids[-1], window=2)["value"]] == ids[-3:]
    assert [r["id"] for r in around(c, ids[7], window=0)["value"]] == [ids[7]]


def test_the_target_text_is_whole_and_neighbours_are_ticket_scoped(rig):
    c, epic, other, ids = rig
    c.post("/v1/messages", json={"ticket_id": other, "kind": "note", "text": "elsewhere"}, headers=OWN)
    resp = around(c, ids[20], window=2)
    target = next(r for r in resp["value"] if r.get("target"))
    assert target["text"] == LONG
    assert {r["ticket_id"] for r in resp["value"]} == {epic}


def test_an_unknown_message_or_a_foreign_ticket_is_refused(rig):
    c, epic, other, ids = rig
    assert around(c, "m-nope")["ok"] is False
    wrong = around(c, ids[3], ticket_id=other)
    assert wrong["ok"] is False and wrong["error"]["code"] == "invalid"


def test_the_mcp_tool_clips_neighbours_but_not_the_target(rig, monkeypatch):
    c, epic, other, ids = rig

    class Client:
        def message_query(self, **kw):
            return c.get("/v1/messages", params={k: v for k, v in kw.items() if v is not None}, headers=OWN).json()

    monkeypatch.setattr(bundles, "get_client", lambda: Client())
    a = bundles.MessageQueryArgs(around=ids[20], window=1)
    out = bundles._message_query(a)["value"]
    assert out["target"] == ids[20] and [i["id"] for i in out["items"]] == ids[19:22]
    target = next(i for i in out["items"] if i.get("target"))
    assert target["text"] == LONG
    long_neighbour = bundles._message_query(bundles.MessageQueryArgs(around=ids[19], window=1))["value"]["items"]
    assert len(next(i for i in long_neighbour if i["id"] == ids[20])["text"]) < 300  # clipped, with its "+N chars" marker


def test_ticket_read_before_seq_pages_the_thread_back(rig):
    c, epic, other, ids = rig

    def read(**p):
        return c.get(f"/v1/tickets/{epic}", params={"include": "thread", **p}, headers=OWN).json()["value"]

    newest = read(thread_limit=10)
    assert [m["id"] for m in newest["thread"]] == ids[-10:] and newest["thread_before_seq"] == newest["thread"][0]["seq"]
    older = read(thread_limit=10, before_seq=newest["thread_before_seq"])
    assert [m["id"] for m in older["thread"]] == ids[-20:-10]
    assert older["thread_seq"] == newest["thread_seq"] and older["thread_total"] == 40
    oldest = read(thread_limit=100, before_seq=older["thread_before_seq"])
    assert [m["id"] for m in oldest["thread"]] == ids[:20] and "thread_before_seq" not in oldest
    assert read(thread_limit=10, before_seq=0)["thread"] == []


def test_ticket_read_before_seq_is_an_mcp_arg_that_reaches_the_client(monkeypatch):
    seen = {}

    class Client:
        def ticket_read(self, id_, include=None, thread_limit=20, before_seq=None):
            seen.update(id_=id_, before_seq=before_seq, thread_limit=thread_limit)
            return {"ok": True, "value": {}}

    monkeypatch.setattr(bundles, "get_client", lambda: Client())
    bundles._ticket_read(bundles.TicketReadArgs(ticket_id="t-1", before_seq=77, thread_limit=5))
    assert seen == {"id_": "t-1", "before_seq": 77, "thread_limit": 5}
