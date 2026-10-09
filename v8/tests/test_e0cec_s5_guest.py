"""e0cec S5 guest sharing (design-b6a55eed13 §4.B; S1 spike report-f1bc7d34da): role, per-epic membership,
scoped reads, authority refusals, secret screen.

Rig: a private in-memory board in token mode. `gina` is a guest member of epic A (owner PUT
/v1/epics/A/members); epic B shares the searchable word "zebra" and a cross-epic link from A's story. Nothing
touches the fleet (EDP* env cleared by the runner; tmp data dir and tokens file)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, guest_scope
from edp8.board import Board
from edp8.schemas import StatusValue
from edp8.service import create_app
from edp8.store import Store

OWNER_T, GINA_T, ARCH_T = "owner-secret-0001", "gina-secret-0002", "arch-secret-0003"
ADMIN = {"X-Admin": "machine-admin-t"}
OWNER = {"X-Participant": "owner", "X-Token": OWNER_T}
ARCH = {"X-Participant": "arch", "X-Token": ARCH_T}
GUEST = {"X-Participant": "gina", "X-Token": GINA_T}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _post(c, path, body, headers, method="POST"):
    r = c.request(method, path, json=body, headers=headers)
    j = r.json()
    assert r.status_code < 300 and j["ok"], (path, r.status_code, j)
    return j["value"]


def _upload(c, headers, data=PNG, name="x.png", ctype="image/png"):
    r = c.post("/v1/artifacts/upload", files={"file": (name, io.BytesIO(data), ctype)}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["value"]["id"]


def _epic(c, title, word):
    """An epic with a design doc (design_ref), a story, a linked global note, an attached image, a criterion
    and a thread note."""
    epic = _post(c, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": title}, OWNER)["id"]
    design = _post(c, "/v1/docs", {"doc_type": "design", "title": f"design {title}",
                                   "body_md": f"# {word} design", "scope": epic}, ARCH)["id"]
    board = c.app_board
    t = board.store.get("ticket", epic)
    board.store.put("ticket", t.model_copy(update={"design_ref": design}))
    story = _post(c, "/v1/tickets", {"kind": "story", "work_type": "feature", "title": f"{word} story",
                                     "parent_id": epic, "description": f"{word} slice"}, ARCH)["id"]
    note = _post(c, "/v1/docs", {"doc_type": "note", "title": f"{word} note", "body_md": f"{word} evidence",
                                 "scope": "global"}, ARCH)["id"]
    _post(c, "/v1/links", {"from_id": story, "to_id": note, "relation": "evidence_for"}, ARCH)
    image = _upload(c, ARCH)
    _post(c, "/v1/artifacts/finalize", {"artifact_ids": [image], "ticket_id": story}, ARCH)
    crit = _post(c, "/v1/criteria", {"ticket_id": story, "text": f"{word} works", "check": "look"}, ARCH)["id"]
    msg = _post(c, "/v1/messages", {"ticket_id": story, "kind": "note", "text": f"{word} thread note"}, ARCH)["id"]
    return {"epic": epic, "design": design, "story": story, "note": note, "image": image, "crit": crit,
            "msg": msg}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"owner": OWNER_T, "gina": GINA_T, "agents": {"arch": ARCH_T}}), encoding="utf-8")
    monkeypatch.setenv("EDP8_TOKENS", str(tokens))
    monkeypatch.setenv("EDP8_OWNER", "owner")
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    board = Board(Store(":memory:"))
    c = TestClient(create_app(board, admin_token=ADMIN["X-Admin"]))
    c.app_board = board
    for pid, role, typ in [("owner", "owner", "human"), ("gina", "guest", "human"), ("arch", "architect", "agent")]:
        _post(c, "/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    a = _epic(c, "Alpha", "zebra")
    b = _epic(c, "Bravo", "zebra")  # the same searchable word on both sides
    # a cross-epic link from A's story to B's note: the guest reads A's story but never learns B's ids
    _post(c, "/v1/links", {"from_id": a["story"], "to_id": b["note"], "relation": "evidence_for"}, ARCH)
    _post(c, f"/v1/epics/{a['epic']}/members", {"members": ["gina"]}, OWNER, method="PUT")
    return {"c": c, "board": board, "A": a, "B": b}


def _b_ids(b):
    return [b[k] for k in ("epic", "story", "design", "image", "crit", "msg")]  # B's note is one hop from A


def _no_b(text, b):
    leaked = [x for x in _b_ids(b) if x in text]
    assert not leaked, leaked


# ------------------------------------------------------------------ the scope

def test_scope_for_is_none_for_non_guests_and_the_one_hop_closure_for_a_guest(rig):
    board, a, b = rig["board"], rig["A"], rig["B"]
    assert guest_scope.scope_for(board, board.participant("owner")) is None
    assert guest_scope.scope_for(board, board.participant("arch")) is None
    s = guest_scope.scope_for(board, board.participant("gina"))
    assert s.epics == {a["epic"]}
    assert {a["epic"], a["story"]} <= s.tickets and not ({b["epic"], b["story"]} & s.tickets)
    assert {a["design"], a["note"]} <= s.docs and b["design"] not in s.docs
    # one hop: B's note is linked FROM A's story, so the doc itself is readable (R2) — its own links are not
    assert b["note"] in s.docs
    assert a["image"] in s.artifacts and b["image"] not in s.artifacts
    assert {"gina", "owner"} <= s.people


def test_membership_is_the_epic_members_field_and_only_the_owner_edits_it(rig):
    c, a = rig["c"], rig["A"]
    got = c.get(f"/v1/epics/{a['epic']}/members", headers=OWNER).json()["value"]["members"]
    assert [(m["id"], m["display"], m["role"]) for m in got] == [("gina", "ext:gina", "guest")]
    for who in (GUEST, ARCH):
        r = c.put(f"/v1/epics/{a['epic']}/members", json={"members": []}, headers=who)
        assert r.status_code == 403, r.text
    r = c.put(f"/v1/epics/{a['story']}/members", json={"members": ["gina"]}, headers=OWNER)
    assert r.status_code == 400 and "not an epic" in r.text
    r = c.put(f"/v1/epics/{a['epic']}/members", json={"members": ["arch"]}, headers=OWNER)
    assert r.status_code == 400 and "seat" in r.text


# ------------------------------------------------------------------ reads inside the scope

def test_guest_reads_its_epic_tree(rig):
    c, a = rig["c"], rig["A"]
    for path in (f"/v1/tickets/{a['story']}", f"/v1/tickets/{a['epic']}", f"/v1/docs/{a['design']}",
                 f"/v1/docs/{a['note']}", f"/v1/artifacts/{a['image']}", f"/v1/epics/{a['epic']}/page",
                 f"/v1/tickets/{a['story']}/page", f"/v1/tickets/{a['story']}/thread",
                 f"/v1/board/{a['epic']}", f"/v1/gates/{a['story']}", f"/v1/messages/{a['msg']}",
                 f"/v1/docs/{a['design']}/html", f"/v1/epics/{a['epic']}/members",
                 f"/v1/tickets/{a['story']}/transitions"):
        r = c.get(path, headers=GUEST)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
    r = c.get(f"/v1/artifacts/{a['image']}/content", headers=GUEST)
    assert r.status_code == 200 and r.content == PNG


def test_views_of_member_objects_never_name_the_other_epic(rig):
    """The cross-epic link A.story → B.note: the note itself is readable (one hop), but no section of any
    view names B's tickets, design, image, criterion or message."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    b_ids = [x for x in _b_ids(b) if x != b["note"]]
    for path in (f"/v1/tickets/{a['story']}", f"/v1/tickets/{a['story']}/page", f"/v1/epics/{a['epic']}/page",
                 f"/v1/board/{a['epic']}", f"/v1/docs/{b['note']}"):
        r = c.get(path, headers=GUEST)
        assert r.status_code == 200, (path, r.text[:300])
        leaked = [x for x in b_ids if x in r.text]
        assert not leaked, (path, leaked)
    # B's note's OTHER link (to B's story) is redacted
    links = c.get("/v1/links", params={"to_id": b["note"]}, headers=GUEST).json()["value"]
    assert {(lk["from_id"], lk["to_id"]) for lk in links} == {(a["story"], b["note"])}


def test_lists_and_personal_views_carry_nothing_of_the_other_epic(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    owner_text = c.get("/v1/tickets", headers=OWNER).text
    assert b["story"] in owner_text  # B exists: the filter is what hides it
    for path, params in (("/v1/tickets", None), ("/v1/docs", None), ("/v1/criteria", {"ticket_id": a["story"]}),
                         ("/v1/links", None), ("/v1/messages", {"ticket_id": a["story"]}),
                         ("/v1/participants", None), ("/v1/me/people", None), ("/v1/epics/summary", None),
                         ("/v1/tickets/table", None), ("/v1/seats", None), ("/v1/me/attention", None),
                         ("/v1/me/notifications", None), ("/v1/me/conversations", None), ("/v1/me/replies", None),
                         ("/v1/me/summary", None), ("/v1/context", None), ("/v1/inbox", None),
                         ("/v1/lookup", {"scope": a["epic"], "question": "zebra"}),
                         ("/v1/events", {"since": 0, "watch": True, "limit": 1000})):
        r = c.get(path, params=params, headers=GUEST)
        assert r.status_code == 200, (path, r.status_code, r.text[:300])
        _no_b(r.text, b)
    tickets = {t["id"] for t in c.get("/v1/tickets", headers=GUEST).json()["value"]}
    assert {a["epic"], a["story"]} <= tickets
    people = {p["id"] for p in c.get("/v1/participants", headers=GUEST).json()["value"]}
    assert people <= {"owner", "gina", "arch"} and "gina" in people


# ------------------------------------------------------------------ 404 outside the scope, no existence oracle

def _fill(path, ids):
    """A scoped route template with each path parameter set to an id of the right kind."""
    def sub(m):
        name = m.group(1)
        if name in ("doc_id",) or (name == "id_" and path.startswith("/v1/docs/")):
            return ids["design"]
        if name == "id_" and path.startswith("/v1/artifacts/"):
            return ids["image"]
        if name == "id_" and path.startswith("/v1/messages/"):
            return ids["msg"]
        if name == "epic_id":
            return ids["epic"]
        if name == "id_" and path.startswith("/v1/participants/"):
            return "arch-b-only"
        return ids["story"]
    return re.sub(r"\{(\w+)\}", sub, path)


def test_every_scoped_read_answers_404_for_the_other_epic(rig):
    """Every scoped GET with a path parameter, aimed at B's objects: 404, while the owner reads them."""
    c, b = rig["c"], rig["B"]
    rig["board"].participant_create("agent", "engineer", "arch-b-only", id_="arch-b-only")  # works only on B
    checked = 0
    for (method, path) in guest_scope.SCOPED:
        if method != "GET" or "{" not in path:
            continue
        url = _fill(path, b)
        r = c.get(url, headers=GUEST)
        assert r.status_code == 404, (url, r.status_code, r.text[:200])
        checked += 1
    assert checked >= 15
    for path, params in (("/v1/lookup", {"scope": b["epic"], "question": "zebra"}),
                         ("/v1/context", {"ticket_id": b["story"]}),
                         ("/v1/messages", {"ticket_id": b["story"]}),
                         ("/v1/criteria", {"ticket_id": b["story"]}),
                         ("/v1/events", {"subject_id": b["story"]})):
        r = c.get(path, params=params, headers=GUEST)
        assert r.status_code == 404, (path, r.status_code, r.text[:200])
    assert c.get(f"/v1/docs/{b['design']}", headers=OWNER).status_code == 200  # non-guests unchanged


def test_not_a_member_and_missing_answer_the_same_404_body(rig):
    c, b = rig["c"], rig["B"]
    fake = "s-0123456789"
    foreign = c.get(f"/v1/tickets/{b['story']}", headers=GUEST)
    missing = c.get(f"/v1/tickets/{fake}", headers=GUEST)
    owner_missing = c.get(f"/v1/tickets/{fake}", headers=OWNER)
    assert foreign.status_code == missing.status_code == owner_missing.status_code == 404
    assert foreign.json() == json.loads(missing.text.replace(fake, b["story"]))
    assert missing.json() == owner_missing.json()  # board-wide: not_found is 404 for everyone


# ------------------------------------------------------------------ search

def test_find_never_ranks_the_other_epic_and_still_fills_k(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    owner_ids = {h["id"] for h in c.get("/v1/find", params={"q": "zebra", "k": 50}, headers=OWNER).json()["value"]}
    assert b["story"] in owner_ids
    hits = c.get("/v1/find", params={"q": "zebra", "k": 50}, headers=GUEST).json()["value"]
    assert a["story"] in {h["id"] for h in hits}
    _no_b(json.dumps(hits), b)
    # retrieval is restricted, not post-filtered: k=1 still answers with an A hit
    one = c.get("/v1/find", params={"q": "zebra", "k": 1}, headers=GUEST).json()["value"]
    assert len(one) == 1 and guest_scope.scope_for(rig["board"], rig["board"].participant("gina")).has(one[0]["id"])


# ------------------------------------------------------------------ events and the SSE feed

def test_events_replay_carries_no_event_of_the_other_epic(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    owner = c.get("/v1/events", params={"since": 0, "watch": True, "limit": 1000}, headers=OWNER).json()["value"]
    assert any(e["subject_id"] in _b_ids(b) for e in owner)
    got = c.get("/v1/events", params={"since": 0, "watch": True, "limit": 1000}, headers=GUEST).json()["value"]
    assert got and not any(e["subject_id"] in _b_ids(b) for e in got)
    assert any(e["subject_id"] in {a["epic"], a["story"]} for e in got)


async def _frames(resp, stop_after_ready: bool, n: int | None = None):
    out = []
    async for chunk in resp.body_iterator:
        f = chunk.decode() if isinstance(chunk, bytes) else chunk
        if f.startswith(": ping"):
            continue
        out.append(f)
        if (stop_after_ready and f.startswith(": ready")) or (n is not None and len(out) >= n):
            break
    return out


def _data(frames):
    return [json.loads(f[len("data: "):]) for f in frames if f.startswith("data: ")]


def _feed(c):
    return next(r.endpoint for r in c.app.routes if getattr(r, "path", "") == "/v1/feed")


def test_sse_feed_is_scoped_replay_and_live_and_sees_new_member_tickets(rig):
    """watch=true (the whole-board view feed) for a guest: replay and live carry only A; a story created in A
    after the stream opened arrives (the scope is recomputed on ticket_created)."""
    c, board, a, b = rig["c"], rig["board"], rig["A"], rig["B"]
    gina = board.participant("gina")

    async def run():
        resp = await _feed(c)(since=0, watch=True, a=gina)
        replay = _data(await _frames(resp, stop_after_ready=True))
        assert replay and not any(f["subject_id"] in _b_ids(b) for f in replay)
        _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": "late B note"}, ARCH)
        new = _post(c, "/v1/tickets", {"kind": "story", "work_type": "feature", "title": "late A story",
                                       "parent_id": a["epic"]}, ARCH)["id"]
        _post(c, "/v1/messages", {"ticket_id": new, "kind": "note", "text": "on the late story"}, ARCH)
        live = _data(await asyncio.wait_for(_frames(resp, stop_after_ready=False, n=2), timeout=10))
        assert [f["subject_id"] for f in live] == [new, new], live
        await resp.body_iterator.aclose()

    asyncio.run(run())


def test_sse_feed_ends_with_a_resync_when_the_membership_is_revoked(rig):
    c, board, a = rig["c"], rig["board"], rig["A"]
    gina = board.participant("gina")

    async def run():
        resp = await _feed(c)(since=-1, watch=True, a=gina)
        await _frames(resp, stop_after_ready=True)
        _post(c, f"/v1/epics/{a['epic']}/members", {"members": []}, OWNER, method="PUT")
        tail = await asyncio.wait_for(_frames(resp, stop_after_ready=False, n=1), timeout=10)
        assert tail and tail[0].startswith(": resync"), tail
        await resp.body_iterator.aclose()

    asyncio.run(run())
    assert c.get(f"/v1/tickets/{a['story']}", headers=GUEST).status_code == 404  # the next read is refused


# ------------------------------------------------------------------ authority

def test_guest_is_refused_every_authority_route(rig):
    """c-ed7a7fb009: gate answers, criterion verdicts, spawn/reap/resume (REST /v1/sessions/*), status
    transitions, admin, models, settings, the Code tab and chat, workflows: 403 for a guest."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    _post(c, f"/v1/gates/{a['story']}/scope/open", {"note": "look?"}, ARCH)
    probes = [
        ("POST", f"/v1/gates/{a['story']}/scope/answer", {"answer": "approved"}),
        ("PATCH", f"/v1/criteria/{a['crit']}", {"verdict": "pass"}),
        ("POST", "/v1/me/verdict", {"criterion_id": a["crit"], "verdict": "pass"}),
        ("POST", "/v1/sessions/spawn", {"participant_id": "x", "role": "engineer", "ticket_id": a["story"]}),
        ("POST", "/v1/sessions/reap", {"participant_id": "arch"}),
        ("POST", "/v1/sessions/resume", {"participant_id": "arch"}),
        ("PATCH", f"/v1/tickets/{a['story']}", {"status": "dropped"}),
        ("PATCH", f"/v1/tickets/{a['story']}", {"status": "blocked"}),
        ("POST", "/v1/tickets", {"kind": "story", "work_type": "feature", "title": "g", "parent_id": a["epic"]}),
        ("POST", "/v1/docs", {"doc_type": "note", "title": "g", "body_md": "g", "scope": a["epic"]}),
        ("POST", "/v1/links", {"from_id": a["story"], "to_id": b["note"], "relation": "evidence_for"}),
        ("PUT", f"/v1/epics/{a['epic']}/members", {"members": ["gina"]}),
        ("GET", "/v1/admin/settings", None), ("GET", "/v1/admin/teammates", None),
        ("GET", "/v1/models", None), ("GET", "/v1/workflows", None), ("GET", "/v1/pool/capabilities", None),
        ("GET", "/v1/code", None), ("POST", "/v1/code/session", {}), ("GET", "/v1/code/faq", None),
        ("GET", "/v1/harvest/cost", None), ("GET", "/v1/me/usage", None), ("GET", "/v1/library", None),
        ("GET", "/v1/activity", None), ("GET", "/v1/recall", {"q": "zebra"}),
        ("POST", "/v1/messages/resolve", {"ticket_id": a["story"], "to": "owner"}),
    ]
    for method, path, body in probes:
        kw = {"params": body} if method == "GET" and body else ({"json": body} if body is not None else {})
        r = c.request(method, path, headers=GUEST, **kw)
        assert r.status_code == 403, (method, path, r.status_code, r.text[:200])
    assert rig["board"].store.get("ticket", a["story"]).status != "dropped"
    # board-side half: the same writes made straight on the board (an MCP/bridge path) are refused too
    from edp8.board import BoardError
    board = rig["board"]
    gina = board.participant("gina")
    for call in (lambda: board.ticket_update(gina, a["story"], status="dropped"),
                 lambda: board.link_create(gina, from_id=a["story"], to_id=a["note"], relation="evidence_for"),
                 lambda: board.doc_create(gina, doc_type="note", title="g", body_md="g", scope=a["epic"])):
        with pytest.raises(BoardError) as e:
            call()
        assert e.value.code == "forbidden"


def test_guest_may_read_post_a_question_or_note_and_upload_on_member_epics_only(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    for kind in ("question", "note"):
        body = {"ticket_id": a["story"], "kind": kind, "text": f"a {kind} from gina"}
        if kind == "question":
            body["to"] = "arch"
        assert _post(c, "/v1/messages", body, GUEST)["created_by"] == "gina"
    for kind in ("answer", "steer", "status", "finding", "deviation"):
        r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": kind, "text": "x"}, headers=GUEST)
        assert r.status_code == 403, (kind, r.status_code, r.text[:200])
    r = c.post("/v1/messages", json={"ticket_id": b["story"], "kind": "note", "text": "hi"}, headers=GUEST)
    assert r.status_code == 404, r.text
    art = _upload(c, GUEST, data=b"plain notes from gina\n", name="notes.txt", ctype="text/plain")
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "file attached",
                              "artifacts": [art]}, GUEST)
    assert c.get(f"/v1/artifacts/{art}", headers=GUEST).status_code == 200
    art2 = _upload(c, GUEST)
    r = c.post("/v1/artifacts/finalize", json={"artifact_ids": [art2], "ticket_id": b["story"]}, headers=GUEST)
    assert r.status_code == 404, r.text
    _post(c, "/v1/artifacts/finalize", {"artifact_ids": [art2], "ticket_id": a["story"]}, GUEST)


def _matrix():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / "guest_route_matrix.py"
    spec = importlib.util.spec_from_file_location("guest_route_matrix", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_route_table_classifies_every_route_and_tool_and_is_what_runs(rig):
    """c-3aed3de618: every operation in app.openapi() AND every route in app.routes (REST + SSE + hidden) has a
    guest treatment; every MCP tool in bundles.ALL_TOOLS is in the tool table and agrees with the REST routes
    it calls. The table is the runtime gate, so each refused op is then CALLED as the guest and must fail
    (403, or the route's own credential gate on actor-less routes), never succeed."""
    from edp8 import bundles
    m = _matrix()
    c = rig["c"]
    app = c.app
    ops = {(meth.upper(), p) for p, d in app.openapi()["paths"].items() for meth in d if meth in m.METHODS}
    routes = {(meth, r.path) for r in app.routes for meth in (getattr(r, "methods", None) or ["GET"])
              if getattr(r, "path", None) and meth != "HEAD"}
    unclassified = [o for o in ops | routes if guest_scope.treatment(*o)[0] == "unclassified"]
    assert not unclassified, sorted(unclassified)
    rest = m.rest_rows(app)
    tools = m.tool_rows(rest)
    assert {t["tool"] for t in tools} == set(bundles.ALL_TOOLS)
    disagree = [(t["tool"], t["guest"], t["derived"]) for t in tools
                if t["guest"] != t["derived"] and t["tool"] not in guest_scope.TOOLS_LOCAL]
    assert not disagree, disagree
    landed = []
    for meth, p in sorted(ops):
        if guest_scope.treatment(meth, p)[0] != "refused":
            continue
        url = re.sub(r"\{[^}]+\}", "x", p)
        # the legacy renderer authenticates by ?as=&token= (its forms), not by headers
        params = {"as": "gina", "token": GINA_T} if p.startswith("/ui") else None
        r = c.request(meth, url, headers=GUEST, params=params, **({} if meth == "GET" else {"json": {}}))
        if r.status_code < 400 or r.status_code >= 500:
            landed.append((meth, p, r.status_code))
    assert not landed, landed


def test_a_guest_subscribe_resets_only_its_own_read_ledger(rig):
    """bb2515da: subscribe clears the caller's already-read record (POST /v1/docs/reads/reset); a guest's subscribe
    is allowed, so the route is too: it touches the caller's own ledger and returns no doc data."""
    from edp8 import guest_scope
    assert guest_scope.treatment("POST", "/v1/docs/reads/reset")[0] == "allowed"
    r = rig["c"].post("/v1/docs/reads/reset", headers=GUEST, json={})
    assert r.status_code == 200 and r.json()["value"] == {"cleared": True}


# ------------------------------------------------------------------ identity

def test_invites_default_to_guest_and_a_guest_is_never_admin(rig):
    from edp8.admin.auth import is_admin
    from edp8.admin.teammates import TeammateIn
    assert TeammateIn(handle="x").role == "guest"
    assert TeammateIn(handle="x", role="owner").role == "owner"  # owner access is an explicit grant
    assert not is_admin(rig["board"].participant("gina").model_copy(update={"admin": True}))
    c = rig["c"]
    r = c.post("/v1/admin/teammates", json={"handle": "newbie"}, headers=OWNER)
    assert r.status_code == 200, r.text
    assert rig["board"].participant("newbie").role == "guest"
    r = c.post("/v1/admin/teammates", json={"handle": "boss", "admin": True}, headers=OWNER)
    assert r.status_code == 400 and "guest cannot be an admin" in r.text
    assert c.put("/v1/admin/teammates/gina", json={"admin": True}, headers=OWNER).status_code == 400


def test_existing_teammates_keep_their_role_and_old_epics_load_without_members(tmp_path, monkeypatch):
    """No migration rewrites a row: a board reopened over a DB written before S5 keeps every human's role,
    and an epic stored without `members` loads with []."""
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    db = str(tmp_path / "b.db")
    board = Board(Store(db))
    board.participant_create("human", "owner", "olive", id_="olive")
    board.participant_create("human", "owner", "bob", id_="bob")
    board.store.put("participant", board.participant("bob").model_copy(update={"admin": True}))
    from edp8.schemas import TicketKind, WorkType
    epic = board.ticket_create(board.participant("olive"), kind=TicketKind.epic, work_type=WorkType.feature,
                               title="old")
    body = json.loads(board.store._conn.execute("SELECT body FROM ticket WHERE id=?", (epic.id,)).fetchone()["body"])
    body.pop("members", None)
    with board.store.transaction():
        board.store._conn.execute("UPDATE ticket SET body=? WHERE id=?", (json.dumps(body), epic.id))
    board.store._conn.close()
    again = Board(Store(db))
    create_app(again, admin_token="t")
    rows = sorted(again.store.query("participant", {}), key=lambda p: p.id)
    assert [(p.id, p.role, p.admin) for p in rows] == [("bob", "owner", True), ("olive", "owner", False)]
    assert again.ticket(epic.id).members == []


def test_seat_contexts_name_a_guest_ext_handle(rig):
    c, board, a = rig["c"], rig["board"], rig["A"]
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "question", "to": "arch", "text": "why zebra?"}, GUEST)
    ev = [e for e in board.store.query("event", {"kind": "message_sent"}, limit=1000)
          if e.data.get("from") == "gina"][-1]
    assert ev.data["from_role"] == "guest" and ev.data["from_handle"] == "ext:gina"
    asks = c.get("/v1/inbox", headers=ARCH).json()["value"]
    row = next(r for r in asks if r["created_by"] == "gina")
    assert row["from_handle"] == "ext:gina" and row["from_role"] == "guest"
    assert guest_scope.display_handle(board.participant("owner")) == "owner"


# ------------------------------------------------------------------ secret screen

KEYS = {  # one fabricated sample per pattern class (none is a real credential)
    "private-key": "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAA\n-----END OPENSSH PRIVATE KEY-----",
    "anthropic-key": "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0" * 3,
    "openai-key": "sk-proj-" + "Zz9Yy8Xx7Ww6Vv5Uu4Tt3Ss2Rr1Qq0Pp",
    "github-token": "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
    "aws-access-key": "AKIA" + "ABCDEFGHIJKLMNOP",
    "aws-secret-key": "aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "token-assignment": "EDP8_ADMIN_TOKEN=" + "f00dfeedcafe1234beef",
}


def _screen_refused(r, cls):
    assert r.status_code == 422, (cls, r.status_code, r.text[:300])
    err = r.json()["error"]
    assert err["code"] == "secret" and f"({cls})" in err["message"], err


def test_secret_screen_refuses_every_key_class_on_a_guest_epic(rig):
    """c-8ec8f7dd35: on an epic with guest members, message_send / doc_create / doc_edit / artifact finalise
    carrying a key, a live token, a secrets-file value or a .env value is refused, the class named."""
    c, a = rig["c"], rig["A"]
    for cls, key in KEYS.items():
        r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": f"here: {key}"},
                   headers=ARCH)
        _screen_refused(r, cls)
    # a live token from tokens.json (the guest's own included)
    r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": f"use {ARCH_T} for it"},
               headers=ARCH)
    _screen_refused(r, "live-token")
    # doc_create, doc_update and doc_edit
    r = c.post("/v1/docs", json={"doc_type": "note", "title": "creds", "body_md": KEYS["github-token"],
                                 "scope": a["story"]}, headers=ARCH)
    _screen_refused(r, "github-token")
    note = _post(c, "/v1/docs", {"doc_type": "note", "title": "clean", "body_md": "nothing here",
                                 "scope": a["story"]}, ARCH)
    r = c.patch(f"/v1/docs/{note['id']}", json={"body_md": KEYS["aws-access-key"]}, headers=ARCH)
    _screen_refused(r, "aws-access-key")
    r = c.post(f"/v1/docs/{note['id']}/edit", json={"expected_version": note["version"], "edits": [
        {"old_text": "nothing here", "new_text": KEYS["anthropic-key"]}]}, headers=ARCH)
    _screen_refused(r, "anthropic-key")
    # artifact finalise: a text upload's bytes are read before it becomes visible
    art = _upload(c, ARCH, data=("config\n" + KEYS["openai-key"] + "\n").encode(), name="cfg.txt",
                  ctype="text/plain")
    r = c.post("/v1/artifacts/finalize", json={"artifact_ids": [art], "ticket_id": a["story"]}, headers=ARCH)
    _screen_refused(r, "openai-key")
    assert rig["board"].store.get("artifact", art).staged  # refused, never attached


def test_secret_screen_reads_secrets_files_and_env_values(rig, tmp_path, monkeypatch):
    from edp8 import secret_screen
    home = tmp_path / "home"
    (home / "secrets").mkdir(parents=True)
    (home / "secrets" / "slack.json").write_text(json.dumps({"bot": "slack-bot-value-123456"}), encoding="utf-8")
    monkeypatch.setenv("EDP_CONFIG_DIR", str(home))
    envf = tmp_path / ".env"
    envf.write_text("# local\nDB_PASSWORD=hunter2hunter2hunter2\nEDP8_OWNER=olive-the-owner\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    vals = secret_screen.live_values()
    assert vals.get("slack-bot-value-123456") == "secrets-file"
    assert vals.get("hunter2hunter2hunter2") == "env-value"
    assert "olive-the-owner" not in vals  # review #7: only secret-shaped keys are screened
    c, a = rig["c"], rig["A"]
    r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": "pw hunter2hunter2hunter2"},
               headers=ARCH)
    _screen_refused(r, "env-value")
    r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": "slack-bot-value-123456"},
               headers=ARCH)
    _screen_refused(r, "secrets-file")


def test_secret_screen_runs_only_where_a_guest_can_read(rig):
    """B has no guest member: the same content lands there (the screen is for shared epics, not a global
    content filter); and clean text lands on A."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": KEYS["github-token"]}, ARCH)
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "the build is green"}, ARCH)


def test_shared_host_rules_carries_the_untrusted_sender_line():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "guides" / "shared-host-rules.md").read_text(encoding="utf-8")
    assert "from_role" in text and "untrusted" in text and "never send secrets" in text


# ------------------------------------------------------------------ review round 2 (architect m-33154269a9)

def test_r2_1_context_delta_never_streams_a_blocked_foreign_ticket(rig):
    """BLOCKER 1: an A story `blocks` a B story. The guest's context_delta used to build its refs from the
    unredacted ticket_view and kept change rows (no id key), so B's thread text streamed to the guest."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    _post(c, "/v1/links", {"from_id": a["story"], "to_id": b["story"], "relation": "blocks"}, ARCH)
    cur = c.get("/v1/context", params={"ticket_id": a["story"]}, headers=GUEST).json()["value"]["cursor"]
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": "BRAVO-ONLY-TEXT"}, ARCH)
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "question", "to": "gina",
                              "text": "BRAVO-ONLY-ASK @gina"}, ARCH)
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "alpha visible"}, ARCH)
    r = c.get("/v1/context_delta", params={"cursor": cur, "ticket_id": a["story"]}, headers=GUEST)
    assert r.status_code == 200, r.text
    assert "BRAVO-ONLY" not in r.text
    _no_b(r.text, b)
    assert b["story"] not in r.text
    assert "alpha visible" in r.text


def test_r2_2_tickets_table_counts_only_the_guests_closure(rig):
    """BLOCKER 2: /v1/tickets/table counted every ticket, so ?q=/assignee=/tag= was a content oracle."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    _post(c, "/v1/tickets", {"kind": "story", "work_type": "feature", "title": "quokka private",
                             "parent_id": b["epic"]}, ARCH)
    for params in ({"q": "quokka"}, {"q": "zebra"}, {"assignee": "arch"}, {"status": "drafted"}, {}):
        v = c.get("/v1/tickets/table", params=params, headers=GUEST).json()["value"]
        assert v["count"] == len(v["rows"]), (params, v["count"], len(v["rows"]))
        assert all(r["epic_id"] in (None, a["epic"]) for r in v["rows"]), params
    assert c.get("/v1/tickets/table", params={"q": "quokka"}, headers=GUEST).json()["value"]["count"] == 0
    assert c.get("/v1/tickets/table", params={"q": "quokka"}, headers=OWNER).json()["value"]["count"] == 1


def test_r2_2_attention_and_summary_counts_are_scoped(rig):
    c, b = rig["c"], rig["B"]
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "question", "to": "gina", "text": "on B?"}, ARCH)
    att = c.get("/v1/me/attention", headers=GUEST).json()["value"]
    assert att["items"] == [] and att["counts"]["total"] == 0, att["counts"]
    s = c.get("/v1/me/summary", headers=GUEST).json()["value"]
    assert s["counts"]["waiting_on_you"] == 0 and s["counts"]["conversations"] == 0 and s["attention"]["total"] == 0
    _no_b(json.dumps(att) + json.dumps(s), b)


def _same_404(foreign, missing, fid, mid):
    assert foreign.status_code == missing.status_code == 404, (foreign.status_code, foreign.text[:200],
                                                               missing.status_code, missing.text[:200])
    assert foreign.json() == json.loads(missing.text.replace(mid, fid)), (foreign.text, missing.text)


def test_r2_3_a_guest_cannot_quote_what_it_cannot_read(rig):
    """SHOULD-FIX 3: quotes.readable was unscoped, so a guest quoting B's message or doc confirmed its text.
    Unreadable gives the same error as missing."""
    c, a, b = rig["c"], rig["A"], rig["B"]

    def send(q):
        return c.post("/v1/messages", headers=GUEST, json={"ticket_id": a["story"], "kind": "question",
                                                           "to": "arch", "text": "see", "quotes": [q]})
    fake = "m-0123456789"
    foreign = send({"source": "message", "id": b["msg"], "text": "zebra thread note"})
    missing = send({"source": "message", "id": fake, "text": "zebra thread note"})
    assert foreign.status_code == missing.status_code and foreign.status_code >= 400, foreign.text
    assert foreign.text.replace(b["msg"], fake) == missing.text, (foreign.text, missing.text)
    r = send({"source": "doc", "id": b["design"], "version": 1, "locator": {"line_start": 1, "line_end": 1},
              "text": "# zebra design"})
    m = send({"source": "doc", "id": "d-0123456789", "version": 1, "locator": {"line_start": 1, "line_end": 1},
              "text": "# zebra design"})
    assert r.status_code >= 400 and r.text.replace(b["design"], "d-0123456789") == m.text, (r.text, m.text)
    mine = send({"source": "message", "id": a["msg"], "text": "zebra thread note"})  # its own epic still quotes
    assert mine.status_code == 200, mine.text


def test_r2_4_every_id_query_param_and_reply_ref_is_scoped(rig):
    """SHOULD-FIX 4: around/source/request/reply_to were not in ID_PARAMS; dict refs (in_reply_to) leaked."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    fake = "m-0123456789"
    for path, key, extra in (("/v1/messages", "around", {}),
                             ("/v1/me/notifications", "request", {}),
                             (f"/v1/docs/{a['design']}/context", "source", {"version": 1})):
        f = c.get(path, params={key: b["msg"], **extra}, headers=GUEST)
        m = c.get(path, params={key: fake, **extra}, headers=GUEST)
        assert f.status_code == 404, (path, f.status_code, f.text[:200])
        _same_404(f, m, b["msg"], fake)
    f = c.post("/v1/messages", headers=GUEST, json={"ticket_id": a["story"], "kind": "note", "text": "re",
                                                    "reply_to": b["msg"]})
    m = c.post("/v1/messages", headers=GUEST, json={"ticket_id": a["story"], "kind": "note", "text": "re",
                                                    "reply_to": fake})
    _same_404(f, m, b["msg"], fake)
    # a teammate's A-thread reply to a B message: the guest reads the reply, never the B parent
    parent = _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": "BRAVO-PARENT"}, ARCH)["id"]
    child = _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "to": "gina", "text": "see that",
                                      "reply_to": parent}, ARCH)["id"]
    r = c.get(f"/v1/messages/{child}", headers=GUEST)
    assert r.status_code == 200 and r.json()["value"].get("in_reply_to") is None, r.text
    for path in (f"/v1/messages/{child}", "/v1/me/replies", "/v1/me/conversations",
                 f"/v1/tickets/{a['story']}/page", "/v1/messages?ticket_id=" + a["story"]):
        t = c.get(path, headers=GUEST).text
        assert "BRAVO-PARENT" not in t and parent not in t, path
    assert "BRAVO-PARENT" in c.get(f"/v1/messages/{child}", headers=OWNER).text  # teammates unchanged


def test_r2_5_a_one_hop_doc_never_names_its_foreign_scope(rig):
    """SHOULD-FIX 5: doc_get/doc_page returned scope=<B ticket> for a doc one link hop from A."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    doc = _post(c, "/v1/docs", {"doc_type": "note", "title": "hop", "body_md": "hop body", "scope": b["story"]},
                ARCH)["id"]
    _post(c, "/v1/links", {"from_id": a["story"], "to_id": doc, "relation": "evidence_for"}, ARCH)
    r = c.get(f"/v1/docs/{doc}", headers=GUEST)
    assert r.status_code == 200 and r.json()["value"]["scope"] is None, r.text
    assert "hop body" in r.text
    _no_b(r.text, b)
    assert b["story"] not in r.text
    for path in (f"/v1/docs/{doc}/html", f"/v1/tickets/{a['story']}/page", f"/v1/docs/{doc}/sources"):
        t = c.get(path, headers=GUEST)
        assert b["story"] not in t.text and b["epic"] not in t.text, (path, t.status_code)
    assert c.get(f"/v1/docs/{doc}", headers=OWNER).json()["value"]["scope"] == b["story"]


def test_r2_6_seats_fail_closed_for_a_guest(rig):
    """SHOULD-FIX 6: /v1/seats listed every seat and each seat's latest_status (B's thread text)."""
    c, board, a, b = rig["c"], rig["board"], rig["A"], rig["B"]
    for pid, tid in (("eng-a", a["story"]), ("eng-b", b["story"])):
        _post(c, "/v1/participants", {"type": "agent", "role": "engineer", "handle": pid, "id": pid}, ADMIN)
        c.put(f"/v1/sessions/sid-{pid}", json={"participant_id": pid, "ticket_id": tid, "pool_id": "local",
                                               "state": "alive"}, headers=ADMIN)
    board.record_status(board.participant("eng-b"), status=StatusValue.blocked, note="BRAVO-SEAT-STATUS", ticket_id=b["story"])
    # eng-a works on A but its LATEST status is about B: the seat shows, the status does not
    board.record_status(board.participant("eng-a"), status=StatusValue.blocked, note="BRAVO-VIA-A-SEAT", ticket_id=b["story"])
    v = c.get("/v1/seats", headers=GUEST).json()["value"]
    ids = {s["id"] for s in v["seats"]}
    assert "eng-b" not in ids and "eng-a" in ids, ids
    assert all(s["ticket_id"] in (a["epic"], a["story"]) for s in v["seats"]), v["seats"]
    t = json.dumps(v)
    assert "BRAVO" not in t and b["story"] not in t, t
    assert v["retired"] == [] and {p["id"] for p in v["people"]} <= {"owner", "gina", "arch"}
    o = c.get("/v1/seats", headers=OWNER).json()["value"]
    assert {"eng-a", "eng-b"} <= {s["id"] for s in o["seats"]}


def test_r2_7_secret_patterns_host_paths_api_key_header_and_pass_values(rig):
    c, a = rig["c"], rig["A"]
    for cls, text in (("host-path", "logs in C:\\Users\\olive\\AppData\\Local\\heronry"),
                      ("host-path", "%LOCALAPPDATA%\\heronry\\data"),
                      ("host-path", "/c/Users/olive/.ssh/id_ed25519"),
                      ("api-key-header", "curl -H 'x-api-key: 0123456789abcdef'"),
                      ("token-assignment", "DB_PASS=hunter&2!hunter"),
                      ("token-assignment", "SMTP_PASSWORD=p&ss!w0rd99"),
                      ("token-assignment", "PRIVATE_KEY=abc!def&ghi")):
        r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": text}, headers=ARCH)
        _screen_refused(r, cls)
    for text in ("see C:\\src\\Learning\\v8", "EDP8_OWNER=olive", "the auth flow is done"):
        _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": text}, ARCH)


def test_r2_7_an_env_value_of_a_plain_key_never_blocks(rig, tmp_path, monkeypatch):
    """FALSE POSITIVE: every .env value was a secret, so EDP8_OWNER=<handle> blocked messages naming the owner."""
    (tmp_path / ".env").write_text("EDP8_OWNER=olive-the-owner\nAPI_TOKEN=tok-abcdef-123456\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    c, a = rig["c"], rig["A"]
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "ask olive-the-owner"}, ARCH)
    r = c.post("/v1/messages", json={"ticket_id": a["story"], "kind": "note", "text": "tok-abcdef-123456"},
               headers=ARCH)
    _screen_refused(r, "env-value")


def test_r2_7_the_read_boundary_withholds_secrets_a_guest_would_read(rig):
    """The screen runs where a guest READS: text no write path screened (status notes, descriptions, criteria)
    and text written before the guest joined is withheld whole, the class named; the guest feed too."""
    c, board, a = rig["c"], rig["board"], rig["A"]
    gh = KEYS["github-token"]
    t = board.store.get("ticket", a["story"])
    board.store.put("ticket", t.model_copy(update={"description": f"deploy with {gh}"}))  # written before
    crit = board.store.get("criterion", a["crit"])
    board.store.put("criterion", crit.model_copy(update={"text": "read C:\\Users\\olive\\secrets\\x.json"}))
    board.record_status(board.participant("arch"), status=StatusValue.blocked, note="x-api-key: 0123456789abcdef",
                        ticket_id=a["story"])
    for path in (f"/v1/tickets/{a['story']}", f"/v1/tickets/{a['story']}/page",
                 f"/v1/criteria?ticket_id={a['story']}", f"/v1/messages?ticket_id={a['story']}",
                 f"/v1/context?ticket_id={a['story']}"):
        r = c.get(path, headers=GUEST)
        assert r.status_code == 200, (path, r.text[:200])
        assert gh not in r.text and "olive" not in r.text and "0123456789abcdef" not in r.text, path
    assert "withheld from a guest: matches a secret (github-token)" in c.get(f"/v1/tickets/{a['story']}",
                                                                            headers=GUEST).text
    assert gh in c.get(f"/v1/tickets/{a['story']}", headers=OWNER).text  # teammates read it as written

    gina = board.participant("gina")

    async def run():
        resp = await _feed(c)(since=0, watch=True, a=gina)
        replay = await _frames(resp, stop_after_ready=True)
        assert "0123456789abcdef" not in "".join(replay)
        board.record_status(board.participant("arch"), status=StatusValue.blocked, note=f"live {gh}", ticket_id=a["story"])
        live = await asyncio.wait_for(_frames(resp, stop_after_ready=False, n=1), timeout=10)
        assert live and gh not in "".join(live), live
        await resp.body_iterator.aclose()

    asyncio.run(run())


def test_r2_nit_deleting_the_link_revokes_the_one_hop_read(rig):
    """NIT: the scope cache keyed on max_seq, and DELETE /v1/links emits no event, so the doc stayed readable."""
    c, a = rig["c"], rig["A"]
    doc = _post(c, "/v1/docs", {"doc_type": "note", "title": "hop2", "body_md": "hop2", "scope": "global"},
                ARCH)["id"]
    link = _post(c, "/v1/links", {"from_id": a["story"], "to_id": doc, "relation": "evidence_for"}, ARCH)["id"]
    assert c.get(f"/v1/docs/{doc}", headers=GUEST).status_code == 200
    assert c.delete(f"/v1/links/{link}", headers=OWNER).json()["value"]["deleted"]
    assert c.get(f"/v1/docs/{doc}", headers=GUEST).status_code == 404


def test_r2_nit_a_guest_addresses_and_mentions_only_its_epic_people(rig):
    """NIT: to= and @mentions reach the epic's people plus the owner; unresolved_mentions does not tell an
    existing out-of-scope handle from a missing one."""
    c, board, a = rig["c"], rig["board"], rig["A"]
    board.participant_create("agent", "engineer", "arch-b-only", id_="arch-b-only")
    f = c.post("/v1/messages", headers=GUEST, json={"ticket_id": a["story"], "kind": "question",
                                                    "to": "arch-b-only", "text": "hi"})
    m = c.post("/v1/messages", headers=GUEST, json={"ticket_id": a["story"], "kind": "question",
                                                    "to": "nobody-zz", "text": "hi"})
    _same_404(f, m, "arch-b-only", "nobody-zz")
    r1 = _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "hi @arch-b-only"}, GUEST)
    r2 = _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "hi @nobody-zz"}, GUEST)
    assert r1["unresolved_mentions"] == ["arch-b-only"] and r2["unresolved_mentions"] == ["nobody-zz"], (r1, r2)
    ev = [e for _s, e in board.store.events_since(0, limit=100000) if r1["id"] in json.dumps(e.model_dump(mode="json"))]
    assert ev and all("arch-b-only" not in (e.data.get("mentions") or []) for e in ev), ev
    assert _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "question", "to": "owner", "text": "hi"},
                 GUEST)["id"]


# ------------------------------------------------------------------ review round 3 (architect m-c94da4bf13)

def test_r3_1_a_text_artifact_is_screened_when_a_guest_reads_its_content(rig):
    """#1: /v1/artifacts/{id}/content served raw bytes, so a text file attached before the guest joined reached it
    unscreened. Text content passes the read-side screen for a guest; binary stays out of scope."""
    c, board, a = rig["c"], rig["board"], rig["A"]
    gh = KEYS["github-token"]
    art = _upload(c, ARCH, data=f"config\n{gh}\n".encode(), name="cfg.txt", ctype="text/plain")
    # attached before the screen applied (the guest-members check runs at finalise): put it on A directly
    board.store.put("artifact", board.store.get("artifact", art).model_copy(update={"staged": False}))
    _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "the cfg"}, ARCH)
    m = board.store.query("message", {"ticket_id": a["story"]}, limit=1, newest_first=True)[0]
    board.store.put("message", m.model_copy(update={"artifacts": [art]}))
    clean = _upload(c, ARCH, data=b"just notes\n", name="notes.md", ctype="text/markdown")
    _post(c, "/v1/artifacts/finalize", {"artifact_ids": [clean], "ticket_id": a["story"]}, ARCH)
    r = c.get(f"/v1/artifacts/{art}/content", headers=GUEST)
    assert r.status_code == 200 and gh not in r.text and "(github-token)" in r.text, r.text[:200]
    assert gh in c.get(f"/v1/artifacts/{art}/content", headers=OWNER).text  # teammates read the bytes
    assert c.get(f"/v1/artifacts/{clean}/content", headers=GUEST).text == "just notes\n"
    assert c.get(f"/v1/artifacts/{a['image']}/content", headers=GUEST).content == PNG  # binary: unchanged


def test_r3_2_hints_are_computed_from_the_guests_rows(rig):
    """#2: hints sit outside `value`, so the redactor missed them: the comment count and last_seq leaked."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    # a B message quoting A's design: a comment on A's doc the guest may not read
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": "see",
                              "quotes": [{"source": "doc", "id": a["design"], "version": 1,
                                          "locator": {"line_start": 1, "line_end": 1}, "text": "# zebra design"}]},
          ARCH)
    j = c.get(f"/v1/docs/{a['design']}/comments", headers=GUEST).json()
    assert j["value"] == [] and j["hint"].startswith("0 comment(s)"), j
    assert c.get(f"/v1/docs/{a['design']}/comments", headers=OWNER).json()["hint"].startswith("1 comment(s)")
    j = c.get("/v1/messages", params={"to": "gina"}, headers=GUEST).json()
    _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "to": "gina", "text": "on B"}, ARCH)
    j2 = c.get("/v1/messages", params={"to": "gina"}, headers=GUEST).json()
    assert j2["hint"] == j["hint"], (j["hint"], j2["hint"])  # a B message moves no guest cursor


def test_r3_3_a_guest_may_address_a_role_even_with_no_seat_for_it(rig):
    """#3 regression: _guest_refs refused to='architect' (every design-review comment) and to='owner' on an epic
    without that seat."""
    c, a = rig["c"], rig["A"]
    r = c.post("/v1/docs/comments", headers=GUEST, json={"ticket_id": a["epic"], "design_ref": a["design"],
                                                         "reviewed_version": 1, "text": "is this right?",
                                                         "idempotency_key": "g-1"})
    assert r.status_code == 200, r.text
    for role in ("architect", "owner"):
        _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "question", "to": role, "text": f"to {role}"},
              GUEST)


def test_r3_4_guest_errors_never_echo_a_foreign_id_or_title(rig):
    """Accepted residual check: a guest's error never names another epic's object it did not itself send."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    titles = ["Bravo", "zebra story", "design Bravo"]
    calls = [("GET", f"/v1/tickets/{b['story']}", None, None),
             ("GET", f"/v1/docs/{b['design']}", None, None),
             ("GET", f"/v1/messages/{b['msg']}", None, None),
             ("GET", "/v1/messages", {"around": b["msg"]}, None),
             ("GET", "/v1/messages", {"around": a["msg"], "ticket_id": b["story"]}, None),
             ("GET", f"/v1/docs/{a['design']}/context", {"source": b["story"], "version": 1}, None),
             ("GET", f"/v1/artifacts/{b['image']}/content", None, None),
             ("POST", "/v1/messages", None, {"ticket_id": b["story"], "kind": "note", "text": "x"}),
             ("POST", "/v1/messages", None, {"ticket_id": a["story"], "kind": "note", "text": "x",
                                             "reply_to": b["msg"]}),
             ("POST", "/v1/messages", None, {"ticket_id": a["story"], "kind": "question", "to": "arch",
                                             "text": "x", "quotes": [{"source": "message", "id": b["msg"],
                                                                      "text": "zebra thread note"}]}),
             ("POST", "/v1/artifacts/finalize", None, {"artifact_ids": [b["image"]], "ticket_id": a["story"]}),
             ("POST", "/v1/docs/comments", None, {"ticket_id": a["epic"], "design_ref": b["design"],
                                                  "reviewed_version": 1, "text": "x", "idempotency_key": "g-2"})]
    for method, path, params, body in calls:
        r = c.request(method, path, params=params, json=body, headers=GUEST)
        assert r.status_code >= 400, (method, path, r.status_code)
        sent = json.dumps([path, params, body])
        named = [x for x in _b_ids(b) + [b["note"]] if x in r.text and x not in sent]
        assert not named and not any(t in r.text for t in titles), (path, r.text[:300])


# ------------------------------------------------------------------ rebase onto S4 (architect m-bce724316f)

def test_rebase_s4_requirements_a_guest_marks_and_reads_only_its_own_and_cannot_link(rig):
    """s-aa76c83998: a guest marks a requirement on a message it can read (a foreign epic's is a 404), reads only its
    own requirements on a member epic, and cannot link one; the owner sees them all."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    owner_m = _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "note", "text": "owner wants zebra stripes"}, OWNER)
    guest_m = _post(c, "/v1/messages", {"ticket_id": a["story"], "kind": "question", "to": "architect",
                                        "text": "gina wants a dark mode"}, GUEST)
    foreign = _post(c, "/v1/messages", {"ticket_id": b["story"], "kind": "note", "text": "owner on bravo"}, OWNER)
    own = _post(c, "/v1/requirements", {"message_id": guest_m["id"], "char_start": 13, "char_end": 22}, GUEST)
    assert own["text"] == "dark mode" and own["epic"] == a["epic"]
    _post(c, "/v1/requirements", {"message_id": owner_m["id"]}, OWNER)
    assert c.post("/v1/requirements", json={"message_id": foreign["id"]}, headers=GUEST).status_code == 404
    j = c.get(f"/v1/epics/{a['epic']}/requirements", headers=GUEST).json()
    assert [r["text"] for r in j["value"]["requirements"]] == ["dark mode"] and j["value"]["digests"] == [], j
    assert "zebra" not in json.dumps(j)
    assert len(c.get(f"/v1/epics/{a['epic']}/requirements", headers=OWNER).json()["value"]["requirements"]) == 2
    assert c.get(f"/v1/epics/{b['epic']}/requirements", headers=GUEST).status_code == 404
    assert c.post(f"/v1/requirements/{own['id']}/link", json={"criterion": "c-x"}, headers=GUEST).status_code == 403
    assert guest_scope.tool_treatment("requirements") == "scoped"
    assert guest_scope.tool_treatment("requirement_link") == "refused"


# ------------------------------------------------------------------ s-aa76 adversary fixes (report-879bc8060e)
def test_f1_a_guest_cannot_mark_a_slice_of_a_source_it_cannot_read(rig, monkeypatch):
    from edp8 import secret_screen
    from edp8.schemas import EventKind, Message, MessageKind
    c, board, a = rig["c"], rig["board"], rig["A"]
    monkeypatch.setattr(secret_screen, "live_values", lambda *args, **kw: {})
    fake = "ghp_" + "A" * 36  # deliberately fake; only the pattern screen is exercised
    m = Message(id="m-aaaaaaaaaa", ticket_id=a["story"], created_by="owner", kind=MessageKind.note, text=fake)
    board.store.put("message", m)  # legacy text present before a guest joined
    board._emit(m.ticket_id, EventKind.message_sent, {"message": m.id})
    whole = c.get(f"/v1/messages/{m.id}", headers=GUEST)
    assert whole.status_code == 200 and "withheld" in whole.text and fake not in whole.text
    for start, end in ((0, 20), (20, 40), (0, 40)):
        got = c.post("/v1/requirements", headers=GUEST, json={"message_id": m.id, "char_start": start, "char_end": end})
        assert got.status_code == 404 and "ghp_" not in got.text, got.text
    assert board.store.query("requirement", {}, limit=10) == []


def test_f3_a_duplicate_mark_is_one_requirement_every_marker_sees(rig):
    c, a = rig["c"], rig["A"]
    msg = c.post("/v1/messages", headers=OWNER, json={"ticket_id": a["story"], "kind": "note", "text": "ship blue"}).json()["value"]
    own = c.post("/v1/requirements", headers=OWNER, json={"message_id": msg["id"]}).json()["value"]
    guest = c.post("/v1/requirements", headers=GUEST, json={"message_id": msg["id"]})
    assert guest.status_code == 200 and guest.json()["value"]["id"] == own["id"]
    seen = c.get(f"/v1/epics/{a['epic']}/requirements", headers=GUEST).json()["value"]["requirements"]
    assert [x["id"] for x in seen] == [own["id"]] and set(seen[0]["marked_by"]) == {"owner", "gina"}
    mine = c.get(f"/v1/epics/{a['epic']}/requirements", headers=OWNER).json()["value"]["requirements"]
    assert [x["id"] for x in mine] == [own["id"]]
    again = c.post("/v1/requirements", headers=GUEST, json={"message_id": msg["id"]}).json()["value"]
    assert again["marked_by"].count("gina") == 1
