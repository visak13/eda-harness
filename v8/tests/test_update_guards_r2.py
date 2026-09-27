"""Adversary round 2, R2-A and R2-B (t-326566ee13): the update guards fail closed.

R2-A: the pool answering an HTTP error (503 {"detail": ...}) or anything that is not the sessions schema
is "cannot say", never "no seats", so `heronry update` refuses without --force, the supervisor's pool
stop refuses without force, and preflight reports the seat count as unknown. R2-B: the harness-update
guard routes a live seat by the harness its row recorded (row, then spawn_settings), not by today's
model catalog, and a live seat whose harness can't be resolved returns 409. Siblings: starting and
resuming shells are live (the guards counted only `active`), and an unrecognised or missing state
counts as live; parked stays idle (S5). Private temp homes and loopback test servers only.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from admin_support import ADMIN_H
from edp8 import bundles, launcher, pool_adapter, supervisor, updater
from edp8.admin import harnesses as H
from test_admin_harnesses import env, fake  # noqa: F401 — shared fixtures

# ------------------------------------------------------------------------------ a real loopback pool


class _Pool:
    """A loopback HTTP pool whose GET /v1/sessions answers (status, body, content type)."""

    def __init__(self):
        self.answer: tuple[int, bytes, str] = (200, b"[]", "application/json")
        pool = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                code, body, ctype = pool.answer
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


@pytest.fixture
def pool(monkeypatch):
    p = _Pool()
    monkeypatch.setattr(launcher, "owner", lambda svc, **k: ("ours", {}))
    monkeypatch.setattr(launcher, "port", lambda svc: p.port)
    monkeypatch.setattr(launcher, "running", lambda svc: True)
    monkeypatch.setenv("EDP_POOL_URL", f"http://127.0.0.1:{p.port}")
    yield p
    p.close()


UNKNOWN_ANSWERS = {
    "503 json detail": (503, b'{"detail":"pool temporarily unavailable"}', "application/json"),
    "500 empty list": (500, b"[]", "application/json"),
    "200 error object": (200, b'{"detail":"nope"}', "application/json"),
    "200 not json": (200, b"<html>proxy error</html>", "text/html"),
    "200 row not an object": (200, b'["engineer.x"]', "application/json"),
    "200 sessions not a list": (200, b'{"sessions": {"a": 1}}', "application/json"),
}


@pytest.mark.parametrize("answer", list(UNKNOWN_ANSWERS), ids=list(UNKNOWN_ANSWERS))
def test_live_seats_pool_error_or_bad_schema_is_unknown(pool, answer):
    pool.answer = UNKNOWN_ANSWERS[answer]
    assert launcher.live_seats() is None


def test_live_seats_counts_every_live_process_state(pool):
    rows = [{"handle": f"s.{st}", "state": st, "proc": {"pid": i}}
            for i, st in enumerate(["active", "starting", "resuming", "parked", "done", "dead", "weird"])]
    rows.append({"handle": "s.nostate", "proc": {"pid": 9}})
    pool.answer = (200, httpx.Response(200, json=rows).content, "application/json")
    got = launcher.live_seats()
    assert got == ["s.active (pid 0)", "s.starting (pid 1)", "s.resuming (pid 2)", "s.weird (pid 6)",
                   "s.nostate (pid 9)"]
    pool.answer = (200, b'{"sessions": []}', "application/json")
    assert launcher.live_seats() == []


def test_live_seats_parse_sessions_schema():
    assert launcher.parse_sessions([]) == [] and launcher.parse_sessions({"sessions": []}) == []
    for bad in (None, {"detail": "x"}, {"value": []}, "[]", [1], [{"state": "active"}, None]):
        assert launcher.parse_sessions(bad) is None, bad


# ------------------------------------------------------------------------------ R2-A: updater.apply


class ReachedStop(Exception):
    pass


@pytest.fixture
def app_update(monkeypatch):
    monkeypatch.setenv("EDP_DEV", "0")
    monkeypatch.setattr(launcher, "bundled", lambda: False)
    monkeypatch.setattr(updater, "_uv_tool_env", lambda: True)
    monkeypatch.setattr(updater, "current_version", lambda: "1.0.0")
    monkeypatch.setattr(updater, "fetch_release", lambda url, tag=None: updater.Release("2.0.0", {}))
    monkeypatch.setattr(updater, "download", lambda rel: {})
    monkeypatch.setattr(updater, "secure_previous", lambda version, url=None: {"edp8": Path("prev.whl")})
    calls: list[str] = []
    monkeypatch.setattr(updater, "backup_db", lambda db, v: calls.append("backup") or Path("b.db"))

    def stop():
        calls.append("stop")
        raise ReachedStop()
    monkeypatch.setattr(updater, "_stop_all", stop)
    return calls


def test_updater_refuses_when_the_pool_answers_503(pool, app_update):
    pool.answer = UNKNOWN_ANSWERS["503 json detail"]
    with pytest.raises(updater.UpdateError, match="couldn't confirm no seats"):
        updater.apply({})
    assert app_update == []  # refused before the backup and the stop
    with pytest.raises(ReachedStop):
        updater.apply({"force": True})


def test_updater_guard_does_not_trust_a_missing_run_record(pool, app_update, monkeypatch):
    """A pool with no run record can still be this home's pool (owner() proves it by home_id)."""
    monkeypatch.setattr(launcher, "running", lambda svc: False)
    pool.answer = UNKNOWN_ANSWERS["503 json detail"]
    with pytest.raises(updater.UpdateError, match="couldn't confirm no seats"):
        updater.apply({})
    assert app_update == []


def test_updater_proceeds_on_a_well_formed_idle_pool(pool, app_update):
    pool.answer = (200, b'[{"handle": "old", "state": "done"}]', "application/json")
    with pytest.raises(ReachedStop):
        updater.apply({})


# ------------------------------------------------------------------------------ siblings


def test_live_seats_unknown_blocks_the_supervisor_pool_stop(monkeypatch):
    monkeypatch.setattr(supervisor.run_state, "mark_probe", lambda *a, **k: None)
    monkeypatch.setattr(supervisor.run_state, "update", lambda *a, **k: None)
    stopped = []
    monkeypatch.setattr(launcher, "stop", lambda svc, **k: stopped.append(svc) or
                        {"service": svc, "state": "stopped", "killed": [], "survivors": []})
    monkeypatch.setattr(launcher, "live_seats", lambda: None)
    sup = supervisor.Supervisor(["pool"], probe=lambda s: False, alive=lambda s: False,
                                restart=lambda s, r: None, emit=lambda *a: None, threshold=1, clock=lambda: 1.0)
    dispatch = supervisor.make_dispatch(sup, lambda *a: None)
    code, out = dispatch("/services/pool/stop", {})
    assert code == 409 and out["seats"] is None and stopped == []
    code, _ = dispatch("/services/pool/stop", {"force": True})
    assert code == 200 and stopped == ["pool"]


def test_live_seats_pool_adapter_non_json_is_an_error(pool):
    pool.answer = UNKNOWN_ANSWERS["200 not json"]
    got = pool_adapter.sessions()
    assert got["ok"] is False and got["error"]["code"] == "bad_response"


def test_live_seats_preflight_reports_unknown_not_zero(monkeypatch):
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": False, "error": {"message": "503"}})
    monkeypatch.setattr(pool_adapter, "capacity", lambda: {"ok": True, "value": {"max": 9}})
    seats = bundles._preflight(bundles.PreflightArgs())["value"]["seats"]
    assert seats["live"] is None and "cannot say" in seats["note"]
    monkeypatch.setattr(pool_adapter, "sessions", lambda: {"ok": True, "value": [
        {"handle": "a", "state": "starting"}, {"handle": "b", "state": "done"}, {"handle": "c", "state": "parked"}]})
    seats = bundles._preflight(bundles.PreflightArgs())["value"]["seats"]
    assert seats["live"] == 2 and seats["handles"] == ["a", "c"]  # host capacity: a parked shell is a process


# ------------------------------------------------------------------------------ R2-B: harness update


def _edited_catalog(monkeypatch):
    """The catalog now routes the live seat's model to codex; the seat was launched as claude."""
    monkeypatch.setattr(H.seat_choice, "_registry", lambda *a: {
        "models": {"edited-model": {"harness": "codex", "provider": "codex"}}})


def test_harness_update_recorded_row_harness_beats_an_edited_catalog(env, fake, monkeypatch):  # noqa: F811
    _edited_catalog(monkeypatch)
    fake.sessions = [{"handle": "running-seat", "state": "active", "model": "edited-model", "harness": "claude"}]
    assert H.live_seats_by_harness() == {"claude": ["running-seat"], "codex": [], "pi": []}
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H, json={})
    assert r.status_code == 409 and "running-seat" in r.text and fake.runs == []


def test_harness_update_spawn_settings_harness_when_the_row_has_none(env, fake, monkeypatch):  # noqa: F811
    _edited_catalog(monkeypatch)
    fake.sessions = [{"handle": "running-seat", "state": "resuming", "model": "edited-model",
                      "spawn_settings": {"model": "edited-model", "harness": "claude"}}]
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H, json={})
    assert r.status_code == 409 and fake.runs == []


def test_harness_update_unresolved_live_harness_is_409(env, fake, monkeypatch):  # noqa: F811
    monkeypatch.setattr(H.seat_choice, "_registry", lambda *a: {"models": {}})
    fake.sessions = [{"handle": "mystery", "state": "active", "model": "gone-from-catalog"}]
    assert H.live_seats_by_harness() is None
    for h in ("claude", "codex", "pi"):
        r = env.client.post(f"/v1/admin/harnesses/{h}/update", headers=ADMIN_H, json={})
        assert r.status_code == 409 and "pool cannot say" in r.text, h
    assert fake.runs == []


def test_harness_update_bad_sessions_schema_is_409(env, fake):  # noqa: F811
    fake.sessions = {"detail": "pool temporarily unavailable"}
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H, json={})
    assert r.status_code == 409 and fake.runs == []


def test_harness_update_catalog_fallback_and_finished_rows_still_idle(env, fake, monkeypatch):  # noqa: F811
    """An older pool row without a recorded harness still routes by the catalog; done rows are idle."""
    monkeypatch.setattr(H.seat_choice, "_registry", lambda *a: {
        "models": {"m-codex": {"harness": "codex"}}})
    fake.sessions = [{"handle": "cx", "state": "active", "model": "m-codex"},
                     {"handle": "old", "state": "done", "model": "unknown-model"}]
    assert H.live_seats_by_harness() == {"claude": [], "codex": ["cx"], "pi": []}
    r = env.client.post("/v1/admin/harnesses/claude/update", headers=ADMIN_H, json={})
    assert r.status_code == 200 and fake.runs == [["C:/bin/claude.exe", "update"]]
