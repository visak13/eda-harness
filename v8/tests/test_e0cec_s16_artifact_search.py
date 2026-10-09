"""e0cec S16 c-d37f54463d: `GET /v1/artifacts/search`, the one source of the `$` picker in the web composer and
the VS Code extension. Every readable artifact appears, the asked epic's first, each row names its epic, and a
guest sees only its member epics' closure (S5 scope). Private in-memory board, token mode, nothing shared."""

from __future__ import annotations

import io
import json
import os

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient

from edp8 import broker_adapter, guest_scope
from edp8.board import Board
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


def _upload(c, headers, name):
    r = c.post("/v1/artifacts/upload", files={"file": (name, io.BytesIO(PNG), "image/png")}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["value"]["id"]


def _epic(c, title):
    epic = _post(c, "/v1/tickets", {"kind": "epic", "work_type": "feature", "title": title}, OWNER)["id"]
    story = _post(c, "/v1/tickets", {"kind": "story", "work_type": "feature", "title": f"{title} story",
                                     "parent_id": epic}, ARCH)["id"]
    shot = _upload(c, ARCH, f"{title.lower()}-shot.png")
    _post(c, "/v1/artifacts/finalize", {"artifact_ids": [shot], "ticket_id": story}, ARCH)
    url = _post(c, "/v1/artifacts", {"form": "url", "uri": f"https://example.test/{title.lower()}/report",
                                     "note": f"{title} report page", "ticket_id": story}, ARCH)["id"]
    return {"epic": epic, "story": story, "shot": shot, "url": url}


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
    a, b = _epic(c, "Alpha"), _epic(c, "Bravo")
    staged = _upload(c, ARCH, "never-finalised.png")  # staged: invisible to everyone
    orphan = _post(c, "/v1/artifacts", {"form": "url", "uri": "https://example.test/loose", "note": "loose link"}, ARCH)["id"]
    _post(c, f"/v1/epics/{a['epic']}/members", {"members": ["gina"]}, OWNER, method="PUT")
    return {"c": c, "board": board, "A": a, "B": b, "staged": staged, "orphan": orphan}


def _rows(c, headers, **params):
    r = c.get("/v1/artifacts/search", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["value"]


def test_every_readable_artifact_appears_current_epic_first_and_each_row_names_its_epic(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    rows = _rows(c, OWNER, q="", epic_id=b["epic"])
    ids = [r["id"] for r in rows]
    assert set(ids) == {a["shot"], a["url"], b["shot"], b["url"], rig["orphan"]}, ids  # staged one is not readable
    assert rig["staged"] not in ids
    first = rows[:2]
    assert {r["id"] for r in first} == {b["shot"], b["url"]} and all(r["group"] == "scope" for r in first)
    assert all(r["group"] == "board" for r in rows[2:])
    by = {r["id"]: r for r in rows}
    assert by[b["shot"]]["epic_id"] == b["epic"] and by[b["shot"]]["epic_title"] == "Bravo"
    assert by[a["url"]]["epic_id"] == a["epic"] and by[a["url"]]["epic_title"] == "Alpha"
    assert by[rig["orphan"]]["epic_id"] is None and by[rig["orphan"]]["epic_title"] is None
    assert by[b["shot"]]["title"] == "bravo-shot.png" and by[b["url"]]["title"] == "Bravo report page"
    assert by[b["shot"]]["form"] == "image" and by[b["url"]]["form"] == "url"


def test_the_asked_epic_decides_the_order_and_q_matches_title_id_and_epic(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    assert [r["id"] for r in _rows(c, OWNER, q="", epic_id=a["epic"])[:2]] and \
        {r["id"] for r in _rows(c, OWNER, q="", epic_id=a["epic"])[:2]} == {a["shot"], a["url"]}
    assert [r["id"] for r in _rows(c, OWNER, q="bravo-shot")] == [b["shot"]]  # title prefix
    assert [r["id"] for r in _rows(c, OWNER, q="loose")] == [rig["orphan"]]  # note first line
    assert {r["id"] for r in _rows(c, OWNER, q="alpha")} == {a["shot"], a["url"]}  # epic title
    assert _rows(c, OWNER, q=b["shot"][:10])[0]["id"] == b["shot"]  # id prefix ranks first
    assert _rows(c, OWNER, q="zzzzz-nothing") == []
    assert len(_rows(c, OWNER, q="", limit=2)) == 2


def test_a_guest_sees_only_its_member_epics_artifacts_and_a_foreign_epic_is_a_404(rig):
    c, a, b = rig["c"], rig["A"], rig["B"]
    rows = _rows(c, GUEST, q="", epic_id=a["epic"])
    assert {r["id"] for r in rows} == {a["shot"], a["url"]}, rows
    assert all(r["epic_id"] == a["epic"] for r in rows)
    text = json.dumps(rows)
    assert b["epic"] not in text and b["shot"] not in text and rig["orphan"] not in text and "Bravo" not in text
    r = c.get("/v1/artifacts/search", params={"q": "", "epic_id": b["epic"]}, headers=GUEST)
    assert r.status_code == 404 and not r.json()["ok"]  # same answer as a missing id: no existence oracle
    assert {r["id"] for r in _rows(c, GUEST, q="bravo")} == set()


def test_the_route_is_in_the_guest_policy_and_does_not_shadow_the_id_route(rig):
    c, a = rig["c"], rig["A"]
    assert guest_scope.treatment("GET", "/v1/artifacts/search")[0] == "scoped"
    r = c.get(f"/v1/artifacts/{a['shot']}", headers=OWNER)
    assert r.status_code == 200 and r.json()["value"]["id"] == a["shot"]  # {id_} still serves ids
    assert c.get("/v1/artifacts/search", headers={"X-Participant": "nobody"}).status_code in (401, 403)


def test_a_guest_never_sees_a_foreign_epic_through_an_artifact_both_epics_link(rig):
    """review m-1775486e17 #1: an artifact produced on Bravo's story and also linked as evidence on guest-visible
    Alpha comes back naming Alpha only, and Bravo's title is not an oracle through q."""
    c, a, b = rig["c"], rig["A"], rig["B"]
    _post(c, "/v1/links", {"from_id": a["story"], "to_id": b["shot"], "relation": "evidence_for"}, ARCH)
    rows = _rows(c, GUEST, q="", epic_id=a["epic"])
    shared = next(r for r in rows if r["id"] == b["shot"])
    assert shared["epic_id"] == a["epic"] and shared["epic_title"] == "Alpha" and shared["ticket_id"] == a["story"]
    text = json.dumps(rows)
    assert b["epic"] not in text and b["story"] not in text and "Bravo" not in text and "bravo" not in text.lower().replace("bravo-shot", "")
    by_name = _rows(c, GUEST, q="Bravo")  # only the shared file's own name matches, still filed under Alpha
    assert [(r["id"], r["epic_title"]) for r in by_name] == [(b["shot"], "Alpha")]
    assert _rows(c, GUEST, q="bravo story") == [] and _rows(c, GUEST, q="Bravo report page") == []  # foreign titles
    assert [r["id"] for r in _rows(c, GUEST, q="alpha")] and b["shot"] in {r["id"] for r in _rows(c, GUEST, q="alpha")}
    # the owner still sees the oldest link win: the artifact belongs to Bravo
    assert next(r for r in _rows(c, OWNER, q="") if r["id"] == b["shot"])["epic_id"] == b["epic"]


def test_only_a_real_epic_is_named_a_quick_task_or_topic_is_not(rig):
    c = rig["c"]
    topic = _post(c, "/v1/topics", {"title": "Skills research"}, OWNER)["topic"]["id"]
    shot = _upload(c, OWNER, "topic-note.png")
    _post(c, "/v1/artifacts/finalize", {"artifact_ids": [shot], "ticket_id": topic}, OWNER)
    row = next(r for r in _rows(c, OWNER, q="topic-note"))
    assert row["id"] == shot and row["epic_id"] is None and row["epic_title"] is None and row["ticket_id"] == topic


def test_the_search_reads_a_bounded_window_never_the_whole_board(rig, monkeypatch):
    c, board = rig["c"], rig["board"]
    from edp8 import artifact_search
    real, limits = board.store.query, []

    def spy(type_, filters=None, **kw):
        if type_ == "artifact":
            limits.append(kw.get("limit", 500))
        return real(type_, filters, **kw)

    monkeypatch.setattr(board.store, "query", spy)
    monkeypatch.setattr(artifact_search, "WINDOW", 3)
    rows = _rows(c, OWNER, q="")
    assert limits and max(limits) <= 3 and 0 < len(rows) <= 3
    assert len(_rows(c, OWNER, q="shot")) <= 3 + 3  # body matches + the asked epic's, each capped
    limits.clear()
    _rows(c, GUEST, q="")
    assert not limits  # a guest's candidates are its scope's ids, fetched by id


def test_a_guest_with_a_foreign_or_missing_epic_id_gets_a_404(rig):
    c, b = rig["c"], rig["B"]
    for epic in (b["epic"], "epic-0000000000"):
        r = c.get("/v1/artifacts/search", params={"q": "", "epic_id": epic}, headers=GUEST)
        assert r.status_code == 404 and not r.json()["ok"], (epic, r.text)
