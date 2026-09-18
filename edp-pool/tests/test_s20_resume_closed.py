"""S20 (v8 epic-1b289d63f9) — resume a CLOSED seat, and per-seat env injection.

The pool half of criterion c-441256a773: POST /v1/resume_closed/{handle} fork-resumes a `done`
row from its stored claude_session_id with the role/env/model recorded at spawn (spawn_settings),
re-taking the freed handle lock. Plus the spawn-time env (EDP8_TOKEN) reaching the launcher.
FakeSpawner stands in for a real claude shell — the "context recalls the earlier conversation"
end-to-end assertion lives on the board (v8), which needs a real shell; here we pin the mechanism
(fork-resume from the stored session id) that makes recall possible.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


def _spawn(svc, handle="engineer.s-x", role="engineer", cs="cs-1", env=None):
    sid = svc.spawn(role, handle, None, "monitor", claude_session=cs, env=env)
    assert isinstance(sid, str), sid
    return sid


def test_spawn_records_spawn_settings_and_injects_env():
    svc = PoolService(FakeSpawner())
    sid = _spawn(svc, env={"EDP8_TOKEN": "tok-abc"})
    row = svc.sessions[sid]
    ss = row.get("spawn_settings")
    assert ss and ss["role"] == "engineer" and ss["mode"] == "monitor"
    assert ss["env"] == {"EDP8_TOKEN": "tok-abc"}
    # the env reached the launcher AFTER build_env's secret strip
    assert svc.spawner.launched[-1]["extra_env"] == {"EDP8_TOKEN": "tok-abc"}


def test_resume_closed_forks_from_stored_session_and_retakes_lock():
    svc = PoolService(FakeSpawner())
    h = "engineer.s-x"
    sid = _spawn(svc, handle=h, cs="cs-1", env={"EDP8_TOKEN": "tok-1"})
    # close it: release → state 'done', lock freed, claude_session_id + spawn_settings kept
    svc.release(sid, reason="closed by self: done")
    assert svc.sessions[sid]["state"] == "done"
    assert svc.locks.get(h) is None  # lock freed

    out = svc.resume_closed(h)
    assert out["resumed"] is True, out
    assert out["session_id"] == sid
    launched = svc.spawner.launched[-1]
    # fork-resume from the row's stored claude_session_id keeps the earlier transcript pristine
    assert launched["resume_session"] == "cs-1"
    assert launched["claude_session"] != "cs-1"  # a fresh fork id
    # spawn_settings reused: role and the per-seat env come back with it
    assert launched["role"] == "engineer"
    assert launched["extra_env"] == {"EDP8_TOKEN": "tok-1"}
    # the freed handle lock is re-taken and the row is live again
    assert svc.locks.get(h) == sid
    assert svc.sessions[sid]["state"] == "active"


def test_resume_closed_continues_a_file_resuming_backend(tmp_path):
    """owner m-a70e85dc0b (2026-09-18): a closed Pi seat has no claude_session_id but does have a
    session file; resume_closed continues it with the CLOSED_RESUME_ACTIVATION so the seat boots
    again (whoami/subscribe/Monitor/cron) instead of reading the role card as a re-prompt."""

    class FileSpawner(FakeSpawner):
        def closed_session_token(self, session_id, handle):
            return str(tmp_path / f"{handle}.jsonl")

    svc = PoolService(FileSpawner())
    h = "engineer.s-pi"
    sid = svc.spawn("engineer", h, None, "monitor", model="astra")
    svc.release(sid, reason="closed by self: handed_off")
    assert svc.sessions[sid].get("claude_session_id") is None
    out = svc.resume_closed(h)
    assert out["resumed"] is True, out
    launched = svc.spawner.launched[-1]
    assert launched["resume_session"] == str(tmp_path / f"{h}.jsonl")
    assert launched["model"] == "astra"
    assert "Boot again now" in launched["activation"]
    assert svc.sessions[sid]["state"] == "active" and svc.locks.get(h) == sid


def test_resume_closed_refuses_when_no_done_row():
    svc = PoolService(FakeSpawner())
    out = svc.resume_closed("engineer.s-never")
    assert out["resumed"] is False and "no closed" in out["reason"]


def test_resume_closed_refuses_when_handle_held_live():
    svc = PoolService(FakeSpawner())
    h = "engineer.s-x"
    _spawn(svc, handle=h)  # a live 'active' seat holds the lock
    out = svc.resume_closed(h)
    assert out["resumed"] is False and "held by" in out["reason"]


def test_capabilities_endpoint_reports_resume_closed():
    c = TestClient(create_app(FakeSpawner()))
    r = c.get("/v1/pool/capabilities")
    assert r.status_code == 200
    assert r.json() == {"resume_parked": True, "resume_closed": True, "park": True, "spawn": True}


def test_resume_closed_endpoint_round_trip():
    app = create_app(FakeSpawner())
    svc = app.state.svc
    c = TestClient(app)
    h = "engineer.s-y"
    sid = _spawn(svc, handle=h, cs="cs-2")
    svc.release(sid, reason="reaped on request")
    r = c.post(f"/v1/resume_closed/{h}")
    assert r.status_code == 200, r.text
    assert r.json()["resumed"] is True
    assert svc.sessions[sid]["state"] == "active"
