"""A private, in-process pool seam for every resumable state and harness."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from edp_pool.service import PoolService, create_app
from edp_pool.spawner import FakeSpawner


class HarnessSpawner(FakeSpawner):
    def __init__(self, harness: str, session_file):
        super().__init__()
        self.harness = harness
        self.session_file = session_file

    def pins_session_id(self, _session_id):
        return self.harness == "claude"

    def closed_session_token(self, _session_id, _handle):
        return str(self.session_file) if self.session_file.is_file() else None


@pytest.mark.parametrize("state", ["parked", "dead", "done", "stalled"])
@pytest.mark.parametrize("harness", ["claude", "codex", "pi"])
def test_resume_continues_stored_session_for_every_state_and_harness(
    tmp_path, state, harness,
):
    """The stored ID/file remains the base, never a fresh launch."""
    session_file = tmp_path / ("thread.json" if harness == "codex" else "seat.jsonl")
    stored_id = f"{harness}-session-before"
    if harness == "codex":
        session_file.write_text(json.dumps({"threadId": stored_id}), encoding="utf-8")
    elif harness == "pi":
        session_file.write_text(json.dumps({"id": stored_id}) + "\n", encoding="utf-8")
    spawner = HarnessSpawner(harness, session_file)
    svc = PoolService(spawner)
    handle = f"engineer.{harness}.{state}"
    sid = svc.spawn("engineer", handle, None, "headless", model=harness,
                    claude_session=stored_id if harness == "claude" else None)
    assert isinstance(sid, str)
    before = svc.sessions[sid]["claude_session_id"] or str(session_file)
    if state == "done":
        svc.release(sid, reason="closed by self")
    else:
        svc.sessions[sid]["state"] = "active" if state == "stalled" else state
        spawner.kill(sid)  # stalled is an active row whose process stopped responding

    out = svc.resume(handle)
    assert out["resumed"] is True, out
    assert out["message"] == f"continued {before}"
    assert spawner.launched[-1]["resume_session"] == before
    assert svc.sessions[sid]["state"] == "active"
    if harness == "claude":
        assert out["claude_session_id"] != before  # Claude forks the stored base.
        assert svc.sessions[sid]["claude_session_id"] == out["claude_session_id"]
    elif harness == "codex":
        assert out["claude_session_id"] is None
        content = json.loads(session_file.read_text(encoding="utf-8"))
        assert content["threadId"] == stored_id
    elif harness == "pi":
        assert out["claude_session_id"] is None
        assert json.loads(session_file.read_text(encoding="utf-8"))["id"] == stored_id


@pytest.mark.parametrize("state", ["parked", "done"])
def test_missing_stored_session_explicitly_starts_fresh(tmp_path, state):
    spawner = HarnessSpawner("pi", tmp_path / "missing.jsonl")
    svc = PoolService(spawner)
    handle = f"engineer.pi.{state}"
    sid = svc.spawn("engineer", handle, None, "headless", model="pi")
    if state == "done":
        svc.release(sid)
    else:
        svc.sessions[sid]["state"] = "parked"
        spawner.kill(sid)
    out = svc.resume(handle)
    assert out["resumed"] is True
    assert out["message"] == "started fresh: no stored session"
    assert spawner.launched[-1]["resume_session"] is None


def test_failed_continue_does_not_fall_back_to_fresh(tmp_path):
    spawner = HarnessSpawner("claude", tmp_path / "unused")
    svc = PoolService(spawner)
    handle = "engineer.claude.failed"
    sid = svc.spawn("engineer", handle, None, "headless", claude_session="old-session")
    svc.sessions[sid]["state"] = "parked"
    spawner.kill(sid)
    launches = len(spawner.launched)

    def fail(*_args, **_kwargs):
        raise RuntimeError("resume failed")

    spawner.launch = fail
    out = svc.resume(handle)
    assert out["resumed"] is False
    assert len(spawner.launched) == launches
    assert svc.sessions[sid]["claude_session_id"] == "old-session"


def test_one_pool_endpoint_continues_a_closed_session():
    app = create_app(FakeSpawner())
    svc = app.state.svc
    handle = "engineer.closed.api"
    sid = svc.spawn("engineer", handle, None, "headless", claude_session="api-before")
    svc.release(sid)
    result = TestClient(app).post(f"/v1/resume/{handle}")
    assert result.status_code == 200
    assert result.json()["message"] == "continued api-before"
    assert svc.spawner.launched[-1]["resume_session"] == "api-before"
