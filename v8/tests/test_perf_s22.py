"""S22 performance pass: the changed code keeps its answers and gains the measured speed-ups.

- request timing middleware: off by default; on, one JSON line per request with the route TEMPLATE
- gzip: JSON and the SPA are compressed, the SSE feed is excluded
- epics/summary: `id` narrows to one row equal to that row of the full list; the one-query open-gate
  count equals the per-ticket fold it replaced
- store: planner statistics exist after open (sqlite_stat1), and the message(ticket_id, created_by) index
- admin/services: the supervisor's /status omits its table when asked (rows=false); the status read
  is cached briefly and a service action invalidates it
"""
from __future__ import annotations

import json
import os
import sqlite3

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES

from edp8 import broker_adapter, timing, views
from edp8.board import Board
from edp8.schemas import Gate
from edp8.service import create_app
from edp8.store import Store

ADMIN = {"X-Admin": "t"}
OWN = {"X-Participant": "owner"}
ARCH = {"X-Participant": "arch"}


def _rig(client: TestClient) -> dict[str, str]:
    def post(path, body, headers):
        r = client.post(path, json=body, headers=headers).json()
        assert r["ok"], r
        return r["value"]

    for pid, role, typ in [("owner", "owner", "human"), ("arch", "architect", "agent")]:
        post("/v1/participants", {"type": typ, "role": role, "handle": pid, "id": pid}, ADMIN)
    ids = {}
    for n in range(3):
        epic = post("/v1/tickets", {"kind": "epic", "work_type": "feature", "title": f"epic {n}"}, OWN)["id"]
        story = post("/v1/tickets", {"kind": "story", "work_type": "bug", "title": f"story {n}",
                                     "parent_id": epic}, ARCH)["id"]
        post("/v1/criteria", {"ticket_id": story, "text": "works", "check": "command"}, ARCH)
        post("/v1/messages", {"ticket_id": epic, "kind": "question", "to": "owner", "text": f"ok {n}?"}, ARCH)
        ids[f"epic{n}"], ids[f"story{n}"] = epic, story
    return ids


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setattr(broker_adapter, "publish", lambda *a, **k: True)

    def make(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        app = create_app(Board(Store(":memory:")), admin_token="t")
        return app, TestClient(app)
    return make


def test_timing_off_by_default_and_logs_route_templates_when_on(app_client, tmp_path, monkeypatch):
    monkeypatch.setattr(timing, "log_path", lambda: tmp_path / "timing.jsonl")
    _, c = app_client()
    _rig(c)
    assert not (tmp_path / "timing.jsonl").exists()
    _, c = app_client(EDP8_TIMING="1")
    ids = _rig(c)
    c.get(f"/v1/tickets/{ids['story0']}", headers=OWN)
    rows = timing.read(tmp_path / "timing.jsonl")
    routes = {r["route"] for r in rows}
    assert "/v1/tickets/{id_}" in routes and not any(ids["story0"] in r for r in routes)
    one = next(r for r in rows if r["route"] == "/v1/tickets/{id_}")
    assert one["method"] == "GET" and one["status"] == 200 and one["ms"] >= 0 and one["bytes"] > 0
    summary = {(s["method"], s["route"]): s for s in timing.summarise(rows)}
    assert summary[("GET", "/v1/tickets/{id_}")]["n"] == 1


def test_json_is_gzipped_and_the_feed_is_not(app_client):
    _, c = app_client()
    _rig(c)
    r = c.get("/v1/epics/summary", headers={**OWN, "Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip" and r.json()["ok"]
    assert "text/event-stream" in DEFAULT_EXCLUDED_CONTENT_TYPES  # the feed's media type stays a plain stream


def test_summary_id_filter_is_that_row_of_the_full_list(app_client):
    _, c = app_client()
    ids = _rig(c)
    full = {r["id"]: r for r in c.get("/v1/epics/summary", headers=OWN).json()["value"]}
    one = c.get("/v1/epics/summary", params={"id": ids["epic1"]}, headers=OWN).json()["value"]
    assert [r["id"] for r in one] == [ids["epic1"]] and one[0] == full[ids["epic1"]]
    assert c.get("/v1/epics/summary", params={"id": "epic-nope"}, headers=OWN).json()["value"] == []


def test_open_gate_count_matches_the_per_ticket_fold(app_client):
    app, c = app_client()
    ids = _rig(c)
    board = app.state.board
    for t in (ids["epic0"], ids["story0"]):
        board.gate_open(t, Gate.scope, by="arch", note="x")
    tree = [ids["epic0"], ids["story0"], ids["epic1"]]
    assert views._open_gate_count(board, tree) == sum(len(board.open_gates(t)) for t in tree)


def test_store_has_planner_stats_and_the_thread_author_index(tmp_path):
    db = tmp_path / "s.db"
    s = Store(db)
    b = Board(s)
    b.participant_create("human", "owner", "owner", id_="owner")
    del s, b
    Store(db)  # a second open runs PRAGMA optimize on a store that holds rows
    con = sqlite3.connect(db)
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master")}
    assert "ix_message_ticket_created" in names
    assert "sqlite_stat1" in names
    plan = " ".join(r[3] for r in con.execute(
        'EXPLAIN QUERY PLAN SELECT body FROM message WHERE "ticket_id"=? AND "created_by"=?', ("t", "o")))
    assert "ix_message_ticket_created" in plan
    plan = " ".join(r[3] for r in con.execute(
        'EXPLAIN QUERY PLAN SELECT body FROM message WHERE "ticket_id"=? AND "to"=? AND "kind"=?', ("t", "o", "q")))
    assert "ix_message_ticket_to" in plan


def test_supervisor_status_without_rows_and_admin_status_cache(monkeypatch):
    from edp8 import launcher, supervisor
    from edp8.admin import services

    calls = {"rows": 0}
    monkeypatch.setattr(launcher, "status_rows", lambda: calls.__setitem__("rows", calls["rows"] + 1) or [])

    class Sup:
        paused, failed, lock = {"pool"}, set(), None
    dispatch = supervisor.make_dispatch(Sup(), lambda *a, **k: None)
    code, out = dispatch("/status", {"rows": False})
    assert code == 200 and "services" not in out and out["paused"] == ["pool"] and calls["rows"] == 0
    code, out = dispatch("/status", {})
    assert "services" in out and calls["rows"] == 1  # an older board (no flag) still gets the table

    monkeypatch.setattr(launcher, "supervisor_running", lambda: False)
    services.invalidate()
    calls["rows"] = 0
    services.status()
    services.status()
    assert calls["rows"] == 1  # the second read within the TTL is the cached answer
    services.invalidate()
    services.status()
    assert calls["rows"] == 2
    services.invalidate()


def test_timing_file_rows_are_json(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"method": "GET", "route": "/x", "status": 200, "ms": 1.0, "bytes": 3}) + "\n")
    assert timing.summarise(timing.read(p))[0]["p95_ms"] == 1.0


def test_one_socket_scan_serves_every_port_from_one_scan(monkeypatch):
    import psutil

    from edp8 import run_state

    class C:
        def __init__(self, port, pid):
            self.status, self.pid = psutil.CONN_LISTEN, pid
            self.laddr = type("A", (), {"port": port})()
    scans = []
    monkeypatch.setattr(psutil, "net_connections", lambda kind="inet": scans.append(kind) or [C(9400, 11), C(9300, 22)])
    with run_state.one_socket_scan():
        assert (run_state.listener_pid(9400), run_state.listener_pid(9300), run_state.listener_pid(1)) == (11, 22, None)
    assert len(scans) == 1  # a status read scans once
    assert run_state.listener_pid(9400) == 11 and len(scans) == 2  # outside the block every call is live
