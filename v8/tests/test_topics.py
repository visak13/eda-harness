"""S-SME-SURFACE (s-698224fca8): Library topics — their own record in the Library with tags (sme sets,
owner edits, one list), docs, a thread, named human experts and one resident sme seat.

The expert scope test comes first (steer m-2e63bf793e rule 7): an expert's token is minted like the
owner's but reaches ONE topic — its page, its docs and its thread — and nothing else."""

from __future__ import annotations

import json
import os
import socket

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8.board import Board
from edp8.store import Store
from edp8.service import create_app

ADMIN = {"X-Admin": "t"}
OWNER_SECRET = "owner-secret"
OWNER = {"X-Participant": "owner", "X-Token": OWNER_SECRET}


class FakePool:
    """Records spawns; the board's pairing path calls spawn(role, pid, env=, model=, effort=)."""

    def __init__(self):
        self.spawned: list[tuple[str, str, dict | None]] = []
        self.closed: list[str] = []

    def spawn(self, role, participant_id, env=None, model=None, effort=None, **_):
        self.spawned.append((role, participant_id, env))
        return {"ok": True}

    def close(self, participant_id, reason="", **_):
        self.closed.append(participant_id)
        return {"ok": True}

    def reap(self, participant_id, **_):
        self.closed.append(participant_id)
        return {"ok": True}


# t-3e246b5e32 (c): seed and research hosts are resolved before use; tests never hit real DNS
PUBLIC_DNS = {"docs.pytest.org": ["104.21.0.1"], "skills.sh": ["76.76.21.21"], "www.skills.sh": ["76.76.21.21"],
              "github.com": ["140.82.112.3"], "raw.githubusercontent.com": ["185.199.108.133"],
              "evil.example.com": ["93.184.216.34"]}


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    from edp8 import topics
    table = dict(PUBLIC_DNS)

    def resolve(host):
        if host not in table:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return table[host]
    monkeypatch.setattr(topics, "RESOLVE", resolve, raising=False)
    return table


@pytest.fixture
def tokens(tmp_path, monkeypatch):
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(f))
    return f


@pytest.fixture
def pool():
    return FakePool()


@pytest.fixture
def board(pool):
    return Board(Store(":memory:"), pool=pool, free_mb=lambda: 8000)


@pytest.fixture
def client(board, tokens):
    c = TestClient(create_app(board, admin_token="t"))
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent")]:
        assert c.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                      headers=ADMIN).json()["ok"]
    return c


def _agent(tokens, pid):
    """The seat's minted secret (the board mints it into tokens.json's agents map at spawn)."""
    return {"X-Participant": pid, "X-Token": json.loads(tokens.read_text(encoding="utf-8"))["agents"][pid]}


def _topic(client, title="Python testing", **kw):
    r = client.post("/v1/topics", json={"title": title, **kw}, headers=OWNER).json()
    assert r["ok"], r
    return r["value"]


def _expert(client, topic_id, handle="dana"):
    r = client.post(f"/v1/topics/{topic_id}/experts", json={"handle": handle, "name": "Dana QA"},
                    headers=OWNER).json()
    assert r["ok"], r
    v = r["value"]
    return v, {"X-Participant": handle, "X-Token": v["token"]}


# ----------------------------------------------------------------------------- scope (written first)
def test_expert_reads_and_posts_its_own_topic(client):
    t = _topic(client)["topic"]
    _, dana = _expert(client, t["id"])
    page = client.get(f"/v1/topics/{t['id']}", headers=dana).json()
    assert page["ok"], page
    assert page["value"]["topic"]["id"] == t["id"]
    m = client.post(f"/v1/topics/{t['id']}/messages", json={"text": "fixtures belong in conftest"},
                    headers=dana).json()
    assert m["ok"], m
    assert m["value"]["created_by"] == "dana" and m["value"]["ticket_id"] == t["id"]
    thread = client.get(f"/v1/topics/{t['id']}", headers=dana).json()["value"]["thread"]
    assert any(x["text"] == "fixtures belong in conftest" for x in thread)


@pytest.mark.parametrize("method,path", [
    ("get", "/v1/whoami"), ("get", "/v1/context"), ("get", "/v1/inbox"), ("get", "/v1/knowledge"),
    ("get", "/v1/tickets"), ("get", "/v1/topics"), ("get", "/v1/participants"), ("get", "/v1/docs"),
    ("get", "/v1/find?q=x"), ("get", "/v1/feed"), ("get", "/v1/models"), ("get", "/v1/sessions"),
    ("post", "/v1/messages"), ("post", "/v1/tickets"), ("post", "/v1/docs"), ("post", "/v1/topics"),
    ("post", "/v1/library/import"), ("post", "/v1/links"),
])
def test_expert_is_refused_everywhere_else(client, method, path):
    t = _topic(client)["topic"]
    _, dana = _expert(client, t["id"])
    body = {"ticket_id": t["id"], "kind": "note", "text": "x"} if method == "post" else None
    r = getattr(client, method)(path, headers=dana, **({"json": body} if body is not None else {}))
    assert r.status_code == 403, (path, r.status_code, r.text[:200])


def test_expert_cannot_touch_another_topic_or_owner_actions(client):
    a = _topic(client, "A")["topic"]
    b = _topic(client, "B")["topic"]
    _, dana = _expert(client, a["id"])
    assert client.get(f"/v1/topics/{b['id']}", headers=dana).status_code == 403
    assert client.post(f"/v1/topics/{b['id']}/messages", json={"text": "x"}, headers=dana).status_code == 403
    # owner-only actions on its own topic are refused too
    assert client.patch(f"/v1/topics/{a['id']}/tags", json={"tags": ["x"]}, headers=dana).status_code == 403
    assert client.post(f"/v1/topics/{a['id']}/experts", json={"handle": "eve"}, headers=dana).status_code == 403
    assert client.post(f"/v1/topics/{a['id']}/close", headers=dana).status_code == 403
    # a doc that is not this topic's is not readable through the topic route
    other = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "x", "body_md": "b",
                                          "scope": "global"}, headers=OWNER).json()["value"]
    assert client.get(f"/v1/topics/{a['id']}/docs/{other['id']}", headers=dana).status_code == 404


def test_expert_needs_its_token(client):
    t = _topic(client)["topic"]
    _expert(client, t["id"])
    assert client.get(f"/v1/topics/{t['id']}", headers={"X-Participant": "dana"}).status_code == 401
    assert client.get(f"/v1/topics/{t['id']}", headers={"X-Participant": "dana", "X-Token": "nope"}).status_code == 401


def test_removed_expert_loses_access(client, tokens):
    t = _topic(client)["topic"]
    v, dana = _expert(client, t["id"])
    r = client.delete(f"/v1/topics/{t['id']}/experts/{v['expert']['id']}", headers=OWNER).json()
    assert r["ok"], r
    assert "dana" not in json.loads(tokens.read_text(encoding="utf-8"))
    assert client.get(f"/v1/topics/{t['id']}", headers=dana).status_code == 401
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["experts"] == []


def test_expert_add_list_remove_and_token_shown_once(client, tokens):
    t = _topic(client)["topic"]
    v, _ = _expert(client, t["id"])
    e = v["expert"]
    assert e["type"] == "human" and e["role"] == "expert" and e["handle"] == "dana"
    assert json.loads(tokens.read_text(encoding="utf-8"))["dana"] == v["token"]  # minted like the owner's
    assert v["token"] in v["link"] and t["id"] in v["link"]
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert [x["handle"] for x in page["experts"]] == ["dana"]
    assert v["token"] not in json.dumps(page)  # never shown again
    # the same handle twice is a conflict; only the owner adds
    assert not client.post(f"/v1/topics/{t['id']}/experts", json={"handle": "dana"}, headers=OWNER).json()["ok"]
    assert client.post(f"/v1/topics/{t['id']}/experts", json={"handle": "eve"},
                       headers={"X-Participant": "eng"}).status_code == 403


def test_expert_needs_token_mode(board, monkeypatch, tmp_path):
    monkeypatch.setenv("EDP8_TOKENS", str(tmp_path / "absent.json"))
    c = TestClient(create_app(board, admin_token="t"))
    c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, headers=ADMIN)
    t = c.post("/v1/topics", json={"title": "x"}, headers={"X-Participant": "owner"}).json()["value"]["topic"]
    r = c.post(f"/v1/topics/{t['id']}/experts", json={"handle": "dana"}, headers={"X-Participant": "owner"}).json()
    assert not r["ok"] and "token" in r["error"]["message"]


# ----------------------------------------------------------------------------- incident m-c31573e1a2
def test_app_keeps_writing_its_own_tokens_file_after_the_env_is_unset(board, pool, tmp_path, monkeypatch):
    """An app built with EDP8_TOKENS=tmp mints into tmp for its whole life — a thread outliving the test's
    env (the pool watcher did) never falls back to the cwd's tokens.json, the fleet file."""
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(f))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    fleet = cwd / "tokens.json"
    fleet.write_text(json.dumps({"owner": "fleet", "agents": {"x": "y"}}), encoding="utf-8")
    monkeypatch.chdir(cwd)
    monkeypatch.delenv("EDP8_HOME", raising=False)
    c = TestClient(create_app(board, admin_token="t"))
    c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, headers=ADMIN)
    t = c.post("/v1/topics", json={"title": "x"}, headers=OWNER).json()["value"]["topic"]
    monkeypatch.delenv("EDP8_TOKENS")  # the test's env is gone; the app (and its threads) are not
    assert board.run_pending_pairings()["spawned"] == [f"sme.{t['id']}"]
    assert f"sme.{t['id']}" in json.loads(f.read_text(encoding="utf-8"))["agents"]
    assert json.loads(fleet.read_text(encoding="utf-8")) == {"owner": "fleet", "agents": {"x": "y"}}


def test_mint_never_rewrites_a_tokens_file_it_cannot_read(board, pool, tmp_path, monkeypatch):
    f = tmp_path / "tokens.json"
    f.write_text(json.dumps({"owner": OWNER_SECRET, "agents": {}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(f))
    c = TestClient(create_app(board, admin_token="t"))
    c.post("/v1/participants", json={"type": "human", "role": "owner", "handle": "owner", "id": "owner"}, headers=ADMIN)
    c.post("/v1/topics", json={"title": "x"}, headers=OWNER)
    f.write_text("{not json", encoding="utf-8")  # a torn read (another writer mid-replace)
    assert board.run_pending_pairings()["failed"]  # kept queued for the retry
    assert f.read_text(encoding="utf-8") == "{not json"  # never clobbered with {}


# ----------------------------------------------------------------------------- record, tags, seat
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _seat(client, tokens, t):
    return _agent(tokens, f"sme.{t['id']}")


def _alive(board, pid, ticket_id, state="alive"):
    board.session_upsert(id_=f"sess-{pid}", participant_id=pid, ticket_id=ticket_id, pool_id="pool", state=state)


def test_topic_is_its_own_record_listed_in_the_library(client, board):
    v = _topic(client, "Python testing", tags=["Python", "testing"], seed_url="https://docs.pytest.org/en/stable/")
    t = v["topic"]
    assert t["kind"] == "topic" and t["parent_id"] is None and t["epic_id"] == t["id"] and t["status"] == "in_progress"
    assert t["id"].startswith("topic-") and t["assignee"] == f"sme.{t['id']}"
    rows = client.get("/v1/topics", headers=OWNER).json()["value"]
    assert [r["id"] for r in rows] == [t["id"]] and rows[0]["status"] == "open"
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["seed_url"] == "https://docs.pytest.org/en/stable/"
    assert page["tags_set_by"]["by"] == "owner" and page["topic"]["tags"] == ["python", "testing"]
    assert t["id"] not in [e["id"] for e in client.get("/v1/tickets?kind=epic", headers=OWNER).json()["value"]]
    # only the owner opens one; a topic never moves through the delivery walk
    assert client.post("/v1/topics", json={"title": "x"}, headers={"X-Participant": "eng"}).status_code in (400, 403)
    r = client.patch(f"/v1/tickets/{t['id']}", json={"status": "in_review"}, headers=OWNER).json()
    assert not r["ok"] and "closed by the owner" in r["error"]["message"] + r["hint"]


def test_seat_spawned_through_the_pairing_queue(client, board, pool, tokens):
    t = _topic(client)["topic"]
    assert client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]["seat"]["state"] == "queued"
    assert board.run_pending_pairings()["spawned"] == [f"sme.{t['id']}"]
    role, pid, env = pool.spawned[-1]
    assert role == "sme" and pid == f"sme.{t['id']}" and env and env["EDP8_TOKEN"]
    # before the pool mirrors a session the page says spawned, never "not spawned"
    assert client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]["seat"]["state"] == "spawned"


def test_tags_one_list_last_write_wins_with_who(client, board, tokens):
    t = _topic(client, tags=["python"])["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    r = client.patch(f"/v1/tickets/{t['id']}", json={"tags": ["python", "pytest"]}, headers=sme).json()
    assert r["ok"], r
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["topic"]["tags"] == ["python", "pytest"] and page["tags_set_by"]["by"] == f"sme.{t['id']}"
    r = client.patch(f"/v1/topics/{t['id']}/tags", json={"tags": ["pytest", "fixtures"]}, headers=OWNER).json()
    assert r["ok"], r
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["topic"]["tags"] == ["pytest", "fixtures"] and page["tags_set_by"]["by"] == "owner"
    assert client.patch(f"/v1/topics/{t['id']}/tags", json={"tags": ["x"]},
                        headers={"X-Participant": "eng"}).status_code == 403


def test_sme_wakes_on_every_owner_and_expert_message(client, board, tokens):
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    _, dana = _expert(client, t["id"])
    sme = board.participant(f"sme.{t['id']}")
    since = board.store.max_seq()
    client.post(f"/v1/topics/{t['id']}/messages", json={"text": "a plain note"}, headers=dana)
    client.post(f"/v1/topics/{t['id']}/messages", json={"text": "to the owner", "to": "owner"}, headers=dana)
    client.post(f"/v1/topics/{t['id']}/messages", json={"text": "@dana what do you use?", "kind": "question",
                                                        "to": "dana"}, headers=OWNER)
    woken = [e for _, e in board.replay(sme, since) if e.kind == "message_sent"]
    assert [e.data["text"] for e in woken] == ["a plain note", "to the owner", "@dana what do you use?"]
    assert all(board.why(e, sme) for e in woken)
    before = board.store.max_seq()  # the seat's own answer does not wake itself
    client.post("/v1/messages", json={"ticket_id": t["id"], "kind": "answer", "text": "fixtures in conftest"},
                headers=_seat(client, tokens, t))
    assert not [e for _, e in board.replay(sme, before) if e.kind == "message_sent"]


def test_message_on_open_topic_requeues_a_dead_seat(client, board, pool, tokens):
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    pid = f"sme.{t['id']}"
    _alive(board, pid, t["id"])
    client.post(f"/v1/topics/{t['id']}/messages", json={"text": "hi"}, headers=OWNER)
    assert board.run_pending_pairings()["spawned"] == []  # alive: nothing to do
    _alive(board, pid, t["id"], state="dead")
    client.post(f"/v1/topics/{t['id']}/messages", json={"text": "still there?"}, headers=OWNER)
    assert board.run_pending_pairings()["spawned"] == [pid]


def test_resident_seat_cannot_close_itself_until_the_owner_closes(client, board, pool, tokens):
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    chk = client.get("/v1/close_check", headers=sme).json()["value"]
    assert "stays until the owner closes" in chk["resident"]
    r = client.post(f"/v1/topics/{t['id']}/close", headers=OWNER).json()
    assert r["ok"] and r["value"]["status"] == "done"
    assert pool.closed == [f"sme.{t['id']}"]
    assert "resident" not in client.get("/v1/close_check", headers=sme).json()["value"]
    assert not client.post(f"/v1/topics/{t['id']}/messages", json={"text": "late"}, headers=OWNER).json()["ok"]
    assert board.run_pending_pairings()["spawned"] == []  # a closed topic never re-queues its seat


def test_close_self_refuses_while_resident(monkeypatch):
    from edp8 import bundles

    class C:
        participant = "sme.topic-x"

        def close_check(self):
            return {"ok": True, "value": {"inbox": [], "status": {"status": "done"},
                                         "resident": "topic-x is open: its sme stays until the owner closes the topic"}}
    monkeypatch.setattr(bundles, "get_client", lambda: C())
    out = bundles._close_self(bundles.CloseSelfArgs())
    assert not out["ok"] and "stays until the owner closes" in out["error"]["message"]


# ----------------------------------------------------------------------------- research -> proposal (recorded pages)
@pytest.fixture
def recorded(monkeypatch):
    from edp8 import topics
    with open(os.path.join(FIX, "skills_sh_python_testing_patterns.html"), "rb") as f:
        page = f.read()
    with open(os.path.join(FIX, "skills_sh_search_python_testing.json"), "rb") as f:
        search = f.read()
    calls: list[str] = []

    def fake(url):
        calls.append(url)
        if url.startswith("https://skills.sh/"):  # the live site redirects the bare host to www
            return 308, b"", url.replace("https://skills.sh/", "https://www.skills.sh/")
        if url.startswith("https://www.skills.sh/api/search"):
            return 200, search, None
        if url == "https://www.skills.sh/wshobson/agents/python-testing-patterns":
            return 200, page, None
        if url.startswith("https://docs.pytest.org/"):
            return 302, b"", "https://evil.example.com/steal"
        return 404, b"", None
    monkeypatch.setattr(topics, "FETCH", fake)
    return calls


def test_research_search_then_page_then_proposal(client, board, tokens, recorded):
    t = _topic(client, tags=["python"])["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    s = client.post(f"/v1/topics/{t['id']}/research", json={"query": "python testing"}, headers=sme).json()
    assert s["ok"], s
    assert s["value"]["results"][0]["page"] == "https://www.skills.sh/wshobson/agents/python-testing-patterns"
    p = client.post(f"/v1/topics/{t['id']}/research",
                    json={"url": "https://skills.sh/wshobson/agents/python-testing-patterns"}, headers=sme).json()
    assert p["ok"], p
    assert "Arrange, Act, Assert" in p["value"]["text"] and "<div" not in p["value"]["text"]
    rec = p["value"]["receipt"]
    assert rec["url"] == "https://www.skills.sh/wshobson/agents/python-testing-patterns" and rec["status"] == 200
    d = client.post(f"/v1/topics/{t['id']}/proposals", json={
        "title": "Python testing: AAA + fixtures", "body_md": "- [required] tests follow Arrange-Act-Assert",
        "source_url": "https://skills.sh/wshobson/agents/python-testing-patterns"}, headers=sme).json()
    assert d["ok"], d
    doc = d["value"]["doc"]
    assert doc["status"] == "proposed" and doc["source"]["ticket"] == t["id"]
    head = doc["body_md"].splitlines()[0]
    assert head.startswith("> Source: https://www.skills.sh/wshobson/agents/python-testing-patterns · fetched-at ")
    assert rec["fetched_at"] in head and doc["source_url"] == rec["url"] and "python" in doc["tags"]
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert [x["id"] for x in page["docs"]] == [doc["id"]] and page["fetches"][0]["url"] == rec["url"]
    _, dana = _expert(client, t["id"])  # an expert reads the topic's doc through the topic route
    assert client.get(f"/v1/topics/{t['id']}/docs/{doc['id']}", headers=dana).json()["value"]["id"] == doc["id"]


def test_research_stays_inside_the_hosts(client, board, tokens, recorded):
    t = _topic(client, seed_url="https://docs.pytest.org/en/stable/")["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    r = client.post(f"/v1/topics/{t['id']}/research", json={"url": "https://evil.example.com/x"}, headers=sme)
    assert r.status_code == 403
    # the seed host is allowed, but a redirect off it is not followed
    r = client.post(f"/v1/topics/{t['id']}/research", json={"url": "https://docs.pytest.org/en/stable/"}, headers=sme)
    assert r.status_code == 403 and "evil.example.com" in r.text
    assert all("evil" not in c for c in recorded)
    r = client.post(f"/v1/topics/{t['id']}/research", json={"url": "http://www.skills.sh/x"}, headers=sme)
    assert r.status_code == 403
    assert client.post(f"/v1/topics/{t['id']}/research", json={"query": "x"},
                       headers={"X-Participant": "eng"}).status_code == 403


def test_proposal_needs_a_fetched_source_and_never_activates(client, board, tokens, recorded):
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    r = client.post(f"/v1/topics/{t['id']}/proposals", json={
        "title": "x", "body_md": "y", "source_url": "https://www.skills.sh/a/b/c"}, headers=sme).json()
    assert not r["ok"] and "was not fetched" in r["error"]["message"]
    r = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "x", "body_md": "b", "scope": "global"},
                    headers=sme).json()
    assert not r["ok"] and "proposed" in r["error"]["message"]
    active = client.post("/v1/docs", json={"doc_type": "strategy_hl", "title": "a", "body_md": "b",
                                           "scope": "global"}, headers=OWNER).json()["value"]
    r = client.patch(f"/v1/docs/{active['id']}", json={"body_md": "changed"}, headers=sme).json()
    assert not r["ok"] and "proposes its next version" in r["error"]["message"]
    client.post(f"/v1/topics/{t['id']}/research",
                json={"url": "https://www.skills.sh/wshobson/agents/python-testing-patterns"}, headers=sme)
    d = client.post(f"/v1/topics/{t['id']}/proposals", json={
        "title": "a v2", "body_md": "better", "proposes": active["id"],
        "source_url": "https://www.skills.sh/wshobson/agents/python-testing-patterns"},
        headers=sme).json()["value"]["doc"]
    assert d["proposes"] == active["id"]
    assert not client.post(f"/v1/docs/{d['id']}/approve", headers=sme).json()["ok"]
    assert client.post(f"/v1/docs/{d['id']}/approve", headers=OWNER).json()["ok"]


# ----------------------------------------------------------------------------- adversary 09-23 (qa, epic-6a8a6020fd)
def test_reserved_expert_handles_are_refused(client, tokens):
    """#2: an expert named `agents` replaced tokens.json's agents map with a string."""
    t = _topic(client)["topic"]
    for handle in ("agents", "owner"):
        r = client.post(f"/v1/topics/{t['id']}/experts", json={"handle": handle}, headers=OWNER).json()
        assert not r["ok"], handle
    assert isinstance(json.loads(tokens.read_text(encoding="utf-8"))["agents"], dict)


def test_generic_ticket_route_keeps_topic_seat_and_tags(client):
    """#5/#7: PATCH /v1/tickets let an engineer take the assignment (and research) and an architect set tags."""
    t = _topic(client)["topic"]
    r = client.patch(f"/v1/tickets/{t['id']}", json={"assignee": "eng"}, headers={"X-Participant": "eng"}).json()
    assert not r["ok"] and "resident" in r["error"]["message"]
    r = client.patch(f"/v1/tickets/{t['id']}", json={"assignee": "arch"}, headers={"X-Participant": "arch"}).json()
    assert not r["ok"]
    r = client.patch(f"/v1/tickets/{t['id']}", json={"tags": ["outsider"]}, headers={"X-Participant": "arch"}).json()
    assert not r["ok"] and "tags" in r["error"]["message"]
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["seat"]["participant"] == f"sme.{t['id']}" and page["topic"]["tags"] == []
    assert client.get(f"/v1/tickets/{t['id']}", headers=OWNER).json()["value"]["assignee"] == f"sme.{t['id']}"
    # the owner and the sme still write the one list through the generic route too
    assert client.patch(f"/v1/tickets/{t['id']}", json={"tags": ["kept"]}, headers=OWNER).json()["ok"]


def test_seed_url_refuses_local_and_private_hosts(client):
    """#9: the seed host joins the research allowlist, so a loopback/metadata/private seed made the seat an SSRF."""
    for bad in ("https://127.0.0.1/private", "https://169.254.169.254/latest", "https://localhost/x",
                "https://10.0.0.5/x", "https://[::1]/x", "https://box.local/x"):
        r = client.post("/v1/topics", json={"title": "loop", "seed_url": bad}, headers=OWNER).json()
        assert not r["ok"] and "private" in r["error"]["message"], bad
    assert client.post("/v1/topics", json={"title": "ok", "seed_url": "https://docs.pytest.org/"}, headers=OWNER).json()["ok"]


def test_seed_host_is_checked_after_resolution(client, dns):
    """t-3e246b5e32 (c): a public-looking NAME that resolves to loopback/private/metadata is refused, even
    from the owner; so is one that does not resolve."""
    dns.update({"loop.example.com": ["127.0.0.1"], "lan.example.com": ["93.184.216.34", "10.1.2.3"],
                "meta.example.com": ["169.254.169.254"], "v6.example.com": ["::ffff:127.0.0.1"],
                "cgnat.example.com": ["100.100.100.200"]})
    for host in ("loop", "lan", "meta", "v6", "cgnat"):
        r = client.post("/v1/topics", json={"title": "x", "seed_url": f"https://{host}.example.com/p"},
                        headers=OWNER).json()
        assert not r["ok"] and "resolves to a local or private address" in r["error"]["message"], (host, r)
    r = client.post("/v1/topics", json={"title": "x", "seed_url": "https://nowhere.example.com/"}, headers=OWNER).json()
    assert not r["ok"] and "does not resolve" in r["error"]["message"]


def test_research_refuses_a_host_that_turned_private(client, board, tokens, recorded, dns):
    """t-3e246b5e32 (c): the seed resolved public at create, then re-pointed at 127.0.0.1 — the research
    fetch re-checks every hop after resolution and never calls FETCH."""
    t = _topic(client, seed_url="https://docs.pytest.org/en/stable/")["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    dns["docs.pytest.org"] = ["127.0.0.1"]
    r = client.post(f"/v1/topics/{t['id']}/research", json={"url": "https://docs.pytest.org/en/stable/"}, headers=sme)
    assert r.status_code == 403 and "private" in r.text
    assert not any("docs.pytest.org" in c for c in recorded)


def test_topic_config_lives_on_the_record(client, board):
    """t-3e246b5e32 (d): seed_url, the research allowlist and tags_set_by are the record's — 500 tag writes
    and then deleting every ticket_updated event on the topic lose none of them."""
    from edp8 import topics
    t = _topic(client, seed_url="https://docs.pytest.org/en/stable/")["topic"]
    for i in range(500):
        assert client.patch(f"/v1/topics/{t['id']}/tags", json={"tags": [f"t{i}"]}, headers=OWNER).json()["ok"]
    for ev in board.store.query("event", {"subject_id": t["id"], "kind": "ticket_updated"}, limit=-1):
        board.store.delete("event", ev.id)
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["seed_url"] == "https://docs.pytest.org/en/stable/"
    assert page["tags_set_by"]["by"] == "owner" and page["topic"]["tags"] == ["t499"]
    assert "docs.pytest.org" in topics.allowed_hosts(board, t["id"])
    rec = board.ticket(t["id"])
    assert rec.topic_config["seed_url"] == "https://docs.pytest.org/en/stable/"
    assert rec.topic_config["allowlist"] == ["docs.pytest.org"]


def test_legacy_topic_config_is_backfilled_once(client, board):
    """A topic opened before the record field keeps its seed: read once from its receipts, then from the record."""
    t = _topic(client, seed_url="https://docs.pytest.org/en/stable/")["topic"]
    rec = board.ticket(t["id"]); rec.topic_config = None; board.store.put("ticket", rec)
    assert client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]["seed_url"] == "https://docs.pytest.org/en/stable/"
    assert board.ticket(t["id"]).topic_config["allowlist"] == ["docs.pytest.org"]


def test_tags_set_by_names_the_writer_whose_tags_won(client, board, tokens):
    """t-3e246b5e32 (b): two tag writes race on the generic ticket route (owner and sme); the owner's write is
    held between its put and its receipt. Unlocked, the sme's tags won but the page named the owner."""
    import threading
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    sme = _seat(client, tokens, t)
    sme_done, owner_in = threading.Event(), threading.Event()
    real_index = board._index

    def slow_index(kind, id_, text):  # runs between ticket_update's put and its ticket_updated receipt
        if "from-owner" in text:  # the owner's write (the handler runs on a server worker thread)
            owner_in.set()
            sme_done.wait(1.0)  # pre-fix the sme finishes inside this window; post-fix it waits on the lock
        return real_index(kind, id_, text)
    board._index = slow_index
    out = {}

    def write(name, hdr, tags):
        out[name] = client.patch(f"/v1/tickets/{t['id']}", json={"tags": tags}, headers=hdr).json()
        if name == "sme-w":
            sme_done.set()
    ow = threading.Thread(target=write, args=("owner-w", OWNER, ["from-owner"]), name="owner-w")
    ow.start(); owner_in.wait(2.0)
    sw = threading.Thread(target=write, args=("sme-w", sme, ["from-sme"]), name="sme-w")
    sw.start(); ow.join(5); sw.join(5)
    assert out["owner-w"]["ok"] and out["sme-w"]["ok"], out
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    winner = {"from-owner": "owner", "from-sme": f"sme.{t['id']}"}[page["topic"]["tags"][0]]
    assert page["tags_set_by"]["by"] == winner, (page["topic"]["tags"], page["tags_set_by"])


def test_seed_url_outlives_many_tag_writes(client):
    """#10: the seed was read from the newest 200 ticket_updated events, so 200 tag writes lost it."""
    t = _topic(client, seed_url="https://docs.pytest.org/en/stable/")["topic"]
    for i in range(205):
        assert client.patch(f"/v1/topics/{t['id']}/tags", json={"tags": [f"t{i}"]}, headers=OWNER).json()["ok"]
    page = client.get(f"/v1/topics/{t['id']}", headers=OWNER).json()["value"]
    assert page["seed_url"] == "https://docs.pytest.org/en/stable/"


def test_topic_seat_cannot_edit_its_proposal(client, board, tokens, recorded):
    """#6: the seat could PATCH a proposed doc and forge the board-stamped Source · fetched-at header."""
    t = _topic(client)["topic"]
    board.run_pending_pairings()
    sme = _agent(tokens, f"sme.{t['id']}")
    url = "https://www.skills.sh/wshobson/agents/python-testing-patterns"
    assert client.post(f"/v1/topics/{t['id']}/research", json={"url": url}, headers=sme).json()["ok"]
    d = client.post(f"/v1/topics/{t['id']}/proposals", json={"title": "x", "body_md": "## Enforced\n- a [required]\n",
                                                              "source_url": url}, headers=sme).json()["value"]["doc"]
    forged = "> Source: https://never-fetched.example/ · fetched-at 2099-01-01\n\nfabricated"
    r = client.patch(f"/v1/docs/{d['id']}", json={"body_md": forged}, headers=sme).json()
    assert not r["ok"] and "stamped" in r["error"]["message"]
    r = client.post(f"/v1/docs/{d['id']}/edit", json={"edits": [{"op": "replace", "old": "a [required]", "new": "b"}]},
                    headers=sme)
    assert r.status_code != 200 or not r.json().get("ok")
    body = client.get(f"/v1/docs/{d['id']}", headers=OWNER).json()["value"]["body_md"]
    assert body.startswith("> Source: https://www.skills.sh/")
