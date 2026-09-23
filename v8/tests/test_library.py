"""S-LIBRARY (s-decb4f7511, design-34bf11cc07 §4.3–4.4): knowledge docs with tags and status,
proposed → approve/reject with a diff, owner authoring, doc_query filters, the knowledge view,
link/unlink reflected in assemble_ruleset, and Import from skills.sh with a stubbed fetch."""

from __future__ import annotations

import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import library
from edp8.board import Board
from edp8.bundles import ALL_TOOLS, set_client
from edp8.client import BoardClient
from edp8.schemas import DocType
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWNER = {"X-Participant": "owner"}
ENG = {"X-Participant": "eng"}


@pytest.fixture
def board():
    return Board(Store(":memory:"))


@pytest.fixture
def client(board):
    return TestClient(create_app(board, admin_token="t"))


@pytest.fixture
def rig(client):
    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent"),
                           ("eng", "engineer", "agent"), ("craft", "sme", "agent")]:
        assert client.post("/v1/participants", json={"type": typ, "role": role, "handle": pid, "id": pid},
                           headers=ADMIN).json()["ok"]
    epic = client.post("/v1/tickets", json={"kind": "epic", "work_type": "feature", "title": "w"},
                       headers=OWNER).json()["value"]["id"]
    story = client.post("/v1/tickets", json={"kind": "story", "work_type": "feature", "title": "s",
                                             "parent_id": epic}, headers={"X-Participant": "arch"}).json()
    return {"epic": epic, "story": story["value"]["id"] if story["ok"] else None}


def _doc(client, who, **kw):
    body = {"doc_type": "strategy_hl", "title": "craft", "body_md": "- rule one\n- [ ] bar [required]",
            "scope": "global", **kw}
    return client.post("/v1/docs", json=body, headers=who).json()


# ----------------------------------------------------------------------------- c-fb59539911
def test_doc_defaults_active_untagged_and_tags_normalized(client, rig):
    d = _doc(client, OWNER)["value"]
    assert d["status"] == "active" and d["tags"] == [] and d["source"] is None
    t = _doc(client, OWNER, tags=["Python", " web ", "python", ""])["value"]
    assert t["tags"] == ["python", "web"]


@pytest.mark.parametrize("doc_type", ["strategy_hl", "strategy_ll", "domain"])
def test_owner_authors_knowledge_docs(client, rig, doc_type):
    r = _doc(client, OWNER, doc_type=doc_type)
    assert r["ok"], r
    # and edits them: a new version
    u = client.patch(f"/v1/docs/{r['value']['id']}", json={"body_md": "- v2", "tags": ["x"]}, headers=OWNER).json()
    assert u["ok"] and u["value"]["version"] == 2 and u["value"]["tags"] == ["x"]


def test_owner_records_lessons(client, rig):
    r = client.post("/v1/lessons", json={"domain": "operations", "topic": "restart", "text": "restart by pid"},
                    headers=OWNER).json()
    assert r["ok"], r


def test_engineer_cannot_author_active_strategy_but_may_propose(client, rig):
    bad = _doc(client, ENG)
    assert not bad["ok"] and "status=proposed" in bad["hint"]
    p = _doc(client, ENG, status="proposed", ticket_id=rig["epic"])
    assert p["ok"], p
    v = p["value"]
    assert v["status"] == "proposed" and v["source"] == {"participant": "eng", "ticket": rig["epic"]}


def test_proposal_for_active_doc_diff_and_approve_makes_next_version(client, rig):
    base = _doc(client, OWNER, tags=["python"])["value"]
    p = _doc(client, ENG, status="proposed", proposes=base["id"], body_md="- rule one\n- rule two",
             tags=["testing"])["value"]
    diff = client.get(f"/v1/docs/{p['id']}/diff", headers=OWNER).json()["value"]
    assert diff["base_id"] == base["id"] and diff["base_version"] == 1
    assert "+- rule two" in diff["diff"] and "-- [ ] bar [required]" in diff["diff"]
    # only the owner rules
    assert not client.post(f"/v1/docs/{p['id']}/approve", headers=ENG).json()["ok"]
    r = client.post(f"/v1/docs/{p['id']}/approve", headers=OWNER).json()
    assert r["ok"], r
    tgt = client.get(f"/v1/docs/{base['id']}", headers=OWNER).json()["value"]
    assert tgt["version"] == 2 and tgt["body_md"] == "- rule one\n- rule two" and tgt["status"] == "active"
    assert tgt["tags"] == ["python", "testing"] and tgt["versions"] == [1, 2]
    prop = client.get(f"/v1/docs/{p['id']}", headers=OWNER).json()["value"]
    assert prop["status"] == "retired" and prop["resolution"] == f"approved -> {base['id']} v2"
    # a resolved proposal cannot be ruled again
    assert not client.post(f"/v1/docs/{p['id']}/reject", headers=OWNER).json()["ok"]


def test_free_standing_proposal_approve_becomes_active_reject_retires(client, rig):
    a = _doc(client, ENG, status="proposed")["value"]
    b = _doc(client, ENG, status="proposed")["value"]
    diff = client.get(f"/v1/docs/{a['id']}/diff", headers=OWNER).json()["value"]
    assert diff["base_id"] is None and "+- rule one" in diff["diff"]
    assert client.post(f"/v1/docs/{a['id']}/approve", headers=OWNER).json()["value"]["doc"]["status"] == "active"
    rb = client.post(f"/v1/docs/{b['id']}/reject", headers=OWNER).json()["value"]["doc"]
    assert rb["status"] == "retired" and rb["resolution"] == "rejected"


def test_proposal_guards(client, rig):
    base = _doc(client, OWNER)["value"]
    assert not _doc(client, ENG, status="proposed", proposes=base["id"], doc_type="domain")["ok"]  # type mismatch
    assert not _doc(client, OWNER, proposes=base["id"])["ok"]  # proposes needs status=proposed
    assert not _doc(client, OWNER, status="retired")["ok"]


def test_doc_query_filters_by_tag_and_status(client, rig):
    a = _doc(client, OWNER, tags=["python"])["value"]
    _doc(client, OWNER, tags=["web"])
    p = _doc(client, ENG, status="proposed", tags=["python"])["value"]
    ids = lambda q: [d["id"] for d in client.get(f"/v1/docs?{q}", headers=OWNER).json()["value"]]  # noqa: E731
    assert ids("tag=python") == [a["id"], p["id"]]
    assert ids("tag=Python&status=active") == [a["id"]]
    assert ids("status=proposed") == [p["id"]]
    assert ids("doc_type=strategy_hl&status=retired") == []
    # the MCP tool carries the filters too
    set_client(BoardClient(participant="owner", client=client))
    out = ALL_TOOLS["doc_query"].handler(ALL_TOOLS["doc_query"].args_model(tag="python", status="proposed"))
    assert [d["id"] for d in out["value"]] == [p["id"]]


def test_legacy_doc_rows_read_as_active(board, client, rig):
    """A doc stored before the fields existed (no tags/status keys in its JSON) reads as active."""
    import json
    d = _doc(client, OWNER)["value"]
    raw = json.loads(board.store._conn.execute("SELECT body FROM doc WHERE id=?", (d["id"],)).fetchone()["body"])
    for k in ("tags", "status", "proposes", "source", "source_url", "resolution"):
        raw.pop(k)
    with board.store._conn:
        board.store._conn.execute("UPDATE doc SET body=? WHERE id=?", (json.dumps(raw), d["id"]))
    assert [x["id"] for x in client.get("/v1/docs?status=active", headers=OWNER).json()["value"]] == [d["id"]]


# ----------------------------------------------------------------------------- knowledge view + links
def test_knowledge_view_lists_docs_lessons_and_linked_epics(client, rig):
    d = _doc(client, OWNER, tags=["python"])["value"]
    _doc(client, OWNER, doc_type="report")  # not knowledge: not listed
    lk = client.post("/v1/links", json={"from_id": rig["epic"], "to_id": d["id"], "relation": "uses_strategy"},
                     headers=OWNER).json()["value"]
    client.post("/v1/lessons", json={"domain": "ops", "topic": "t", "text": "a lesson"}, headers=OWNER)
    v = client.get("/v1/knowledge", headers=OWNER).json()["value"]
    assert [x["id"] for x in v["docs"]] == [d["id"]]
    assert v["docs"][0]["linked"] == [{"link_id": lk["id"], "ticket_id": rig["epic"], "kind": "epic", "title": "w",
                                       "relation": "uses_strategy"}]
    assert v["tags"] == ["python"] and v["lessons"][0]["text"] == "a lesson"
    assert rig["epic"] in [e["id"] for e in v["epics"]]


def test_link_unlink_epic_is_reflected_in_next_ruleset_and_epic_page(client, rig):
    set_client(BoardClient(participant="owner", client=client))
    d = _doc(client, OWNER, title="py craft", tags=["python"])["value"]
    tool = ALL_TOOLS["assemble_ruleset"]
    story = rig["story"]
    assert story, "story creation failed"
    assert not tool.handler(tool.args_model(ticket_id=story))["ok"]  # nothing linked yet
    lk = client.post("/v1/links", json={"from_id": rig["epic"], "to_id": d["id"], "relation": "uses_strategy"},
                     headers=OWNER).json()["value"]
    page = client.get(f"/v1/epics/{rig['epic']}/page", headers=OWNER).json()["value"]
    assert [(k["id"], k["link_id"], k["relation"]) for k in page["knowledge"]] == [(d["id"], lk["id"], "uses_strategy")]
    out = tool.handler(tool.args_model(ticket_id=story))
    assert out["ok"] and [x["id"] for x in out["value"]["index"]] == [d["id"]]
    assert "constructive" not in out["value"] and out["value"]["enforced"][0]["text"] == "- [ ] bar [required]"
    assert client.delete(f"/v1/links/{lk['id']}", headers=OWNER).json()["value"]["deleted"]
    assert not tool.handler(tool.args_model(ticket_id=story))["ok"]
    assert client.get(f"/v1/epics/{rig['epic']}/page", headers=OWNER).json()["value"]["knowledge"] == []


def test_retired_doc_is_skipped_from_the_brief(client, rig):
    set_client(BoardClient(participant="owner", client=client))
    keep = _doc(client, OWNER)["value"]
    gone = _doc(client, ENG, status="proposed")["value"]
    client.post(f"/v1/docs/{gone['id']}/reject", headers=OWNER)
    for x in (keep, gone):
        client.post("/v1/links", json={"from_id": rig["epic"], "to_id": x["id"], "relation": "uses_strategy"},
                    headers=OWNER)
    tool = ALL_TOOLS["assemble_ruleset"]
    out = tool.handler(tool.args_model(ticket_id=rig["epic"]))
    assert [x["id"] for x in out["value"]["index"]] == [keep["id"]] and out["value"]["skipped_layers"] == [gone["id"]]


# ----------------------------------------------------------------------------- c-e30967d7ab import
SKILL = """---
name: frontend-design
description: Distinctive visual design for new UI.
license: see LICENSE
metadata:
  tags: [design, ui]
---

# Frontend Design

- pick a direction before code
"""


@pytest.fixture
def fetch(monkeypatch):
    calls: list[str] = []
    pages: dict[str, bytes] = {}

    def stub(url):
        calls.append(url)
        return (200, pages[url]) if url in pages else (404, b"")

    monkeypatch.setattr(library, "FETCH", stub)
    return calls, pages


def test_candidate_urls_and_host_allowlist():
    assert library.candidate_urls("https://skills.sh/anthropics/skills/frontend-design") == [
        "https://raw.githubusercontent.com/anthropics/skills/HEAD/skills/frontend-design/SKILL.md",
        "https://raw.githubusercontent.com/anthropics/skills/HEAD/frontend-design/SKILL.md",
        "https://raw.githubusercontent.com/anthropics/skills/HEAD/SKILL.md"]
    assert library.candidate_urls("https://github.com/o/r/blob/main/skills/x/SKILL.md") == [
        "https://raw.githubusercontent.com/o/r/main/skills/x/SKILL.md"]
    for bad in ("http://skills.sh/a/b/c", "https://evil.example/SKILL.md", "https://skills.sh/a/b",
                "https://raw.githubusercontent.com/o/r/HEAD/x.txt", "https://127.0.0.1/SKILL.md"):
        with pytest.raises(library.BoardError):
            library.candidate_urls(bad)


def test_parse_frontmatter_nested_and_block_lists():
    f, body = library.parse_frontmatter(SKILL)
    assert f["name"] == "frontend-design" and f["tags"] == ["design", "ui"] and body.startswith("\n# Frontend")
    f2, _ = library.parse_frontmatter("---\nname: 'x'\ntags:\n  - A\n  - b\n---\nbody")
    assert f2 == {"name": "x", "tags": ["A", "b"]}
    assert library.parse_frontmatter("no frontmatter") == ({}, "no frontmatter")


def test_import_creates_strategy_doc_then_reimport_is_a_new_version(client, rig, fetch):
    calls, pages = fetch
    url = "https://skills.sh/anthropics/skills/frontend-design"
    pages["https://raw.githubusercontent.com/anthropics/skills/HEAD/skills/frontend-design/SKILL.md"] = SKILL.encode()
    r = client.post("/v1/library/import", json={"url": url}, headers=OWNER).json()
    assert r["ok"], r
    d = r["value"]["doc"]
    assert r["value"]["created"] and d["doc_type"] == "strategy_hl" and d["title"] == "skill: frontend-design"
    assert d["tags"] == ["design", "ui", "skills-sh"] and d["source_url"] == url and d["status"] == "active"
    assert "- pick a direction before code" in d["body_md"] and "Distinctive visual design" in d["body_md"]
    assert len(calls) == 1  # the first candidate hit: one fetch
    r2 = client.post("/v1/library/import", json={"url": url + "/"}, headers=OWNER).json()  # same URL, normalized
    assert r2["ok"] and not r2["value"]["created"]
    assert r2["value"]["doc"]["id"] == d["id"] and r2["value"]["doc"]["version"] == 2
    assert len([x for x in client.get("/v1/docs?tag=skills-sh", headers=OWNER).json()["value"]]) == 1


def test_import_falls_back_through_candidates_and_reports_misses(client, rig, fetch):
    calls, pages = fetch
    pages["https://raw.githubusercontent.com/o/r/HEAD/SKILL.md"] = b"# bare skill\n- one"
    r = client.post("/v1/library/import", json={"url": "https://skills.sh/o/r/bare"}, headers=OWNER).json()
    assert r["ok"] and len(calls) == 3 and r["value"]["doc"]["title"] == "skill: bare"
    miss = client.post("/v1/library/import", json={"url": "https://skills.sh/o/other/none"}, headers=OWNER).json()
    assert not miss["ok"] and "tried:" in miss["hint"]


def test_import_needs_a_knowledge_author(client, rig, fetch):
    _, pages = fetch
    pages["https://raw.githubusercontent.com/o/r/HEAD/skills/s/SKILL.md"] = SKILL.encode()
    assert not client.post("/v1/library/import", json={"url": "https://skills.sh/o/r/s"}, headers=ENG).json()["ok"]


def test_http_get_caps_size(monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(200, content=b"x" * (library.MAX_BYTES + 10))

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(library.BoardError, match="larger than"):
        library.http_get("https://raw.githubusercontent.com/o/r/HEAD/SKILL.md")


# ----------------------------------------------------------------------------- second_opinion fixes
def test_proposed_doc_linked_to_an_epic_stays_out_of_the_brief(client, rig):
    set_client(BoardClient(participant="owner", client=client))
    keep = _doc(client, OWNER, body_md="- plain")["value"]
    p = _doc(client, ENG, status="proposed")["value"]  # carries "- [ ] bar [required]"
    for x in (keep, p):
        client.post("/v1/links", json={"from_id": rig["epic"], "to_id": x["id"], "relation": "uses_strategy"},
                    headers={"X-Participant": "arch"})
    tool = ALL_TOOLS["assemble_ruleset"]
    out = tool.handler(tool.args_model(ticket_id=rig["epic"]))["value"]
    assert [x["id"] for x in out["index"]] == [keep["id"]] and out["skipped_layers"] == [p["id"]]
    assert not any("bar" in str(line) for line in out["enforced"])


def test_approved_free_standing_proposal_is_owner_authored_not_the_proposers_role(client, rig):
    p = _doc(client, ENG, status="proposed")["value"]
    d = client.post(f"/v1/docs/{p['id']}/approve", headers=OWNER).json()["value"]["doc"]
    assert d["owner_role"] == "owner"
    assert not client.patch(f"/v1/docs/{p['id']}", json={"body_md": "- mine"}, headers=ENG).json()["ok"]
    assert client.patch(f"/v1/docs/{p['id']}", json={"body_md": "- v2"}, headers=OWNER).json()["ok"]


def test_filters_and_import_identity_see_past_the_row_limit(board, client, rig, fetch):
    owner = board.store.get("participant", "owner")
    for i in range(501):
        board.doc_create(owner, doc_type=DocType.strategy_hl, title=f"d{i}", body_md="- x", scope="global")
    last = board.doc_create(owner, doc_type=DocType.strategy_hl, title="rare", body_md="- x", scope="global", tags=["rare"])
    assert [d.id for d in board.docs_query(tag="rare")] == [last.id]
    assert len(board.docs_query(status="active", limit=10)) == 10
    _, pages = fetch
    pages["https://raw.githubusercontent.com/o/r/HEAD/skills/s/SKILL.md"] = SKILL.encode()
    first = client.post("/v1/library/import", json={"url": "https://skills.sh/o/r/s"}, headers=OWNER).json()["value"]
    again = client.post("/v1/library/import", json={"url": "https://skills.sh/o/r/s"}, headers=OWNER).json()["value"]
    assert not again["created"] and again["doc"]["id"] == first["doc"]["id"] and again["doc"]["version"] == 2


def test_concurrent_imports_of_one_url_make_one_doc(board, rig, monkeypatch):
    import threading
    owner = board.store.get("participant", "owner")
    both_fetched = threading.Barrier(2, timeout=10)

    def stub(url):  # both requests are past the fetch before either looks for an existing doc
        both_fetched.wait()
        return 200, SKILL.encode()

    monkeypatch.setattr(library, "FETCH", stub)
    out: list[dict] = []
    ts = [threading.Thread(target=lambda: out.append(library.import_skill(board, owner, url="https://skills.sh/o/r/s",
                                                                          scope="global", tags=None))) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert sorted(x["created"] for x in out) == [False, True] and len({x["doc"].id for x in out}) == 1


def test_http_get_enforces_a_total_deadline(monkeypatch):
    import httpx
    clock = iter(range(0, 1000, 4))  # each monotonic() read is 4 s later: a slow drip under the read timeout
    monkeypatch.setattr(library.time, "monotonic", lambda: next(clock))

    def handler(request):
        return httpx.Response(200, content=iter([b"a" * 10] * 20))

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(httpx.ReadTimeout, match="longer than 10 s"):
        library.http_get("https://raw.githubusercontent.com/o/r/HEAD/SKILL.md")


def test_diff_of_bodies_without_a_trailing_newline_keeps_lines_apart(client, rig):
    base = _doc(client, OWNER, body_md="old")["value"]
    p = _doc(client, ENG, status="proposed", proposes=base["id"], body_md="new", title="craft 2")["value"]
    d = client.get(f"/v1/docs/{p['id']}/diff", headers=OWNER).json()["value"]
    assert d["diff"].splitlines()[-2:] == ["-old", "+new"]
    assert d["title_changed"] and d["base_title"] == "craft" and d["title"] == "craft 2"
