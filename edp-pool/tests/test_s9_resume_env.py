"""e0cec S9 G7 (memory pool-resume-drops-seat-token): a resumed seat is launched with the env it was spawned with, so
EDP8_TOKEN survives resume and resume_closed. A seat resumed without its token dies on its first board call."""

from __future__ import annotations

from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner

TOKEN_ENV = {"EDP8_TOKEN": "tok-seat-1"}


def _spawned(handle):
    spawner = FakeSpawner()
    svc = PoolService(spawner)
    sid = svc.spawn("engineer", handle, None, "monitor", env=dict(TOKEN_ENV))
    assert isinstance(sid, str), sid
    assert spawner.launched[-1]["extra_env"] == TOKEN_ENV
    return svc, spawner, sid


def test_resume_replays_spawn_env_token():
    svc, spawner, sid = _spawned("engineer.s-resume-env")
    svc.sessions[sid]["state"] = "parked"
    spawner.kill(sid)
    out = svc.resume("engineer.s-resume-env")
    assert out["resumed"] is True, out
    assert spawner.launched[-1]["extra_env"] == TOKEN_ENV


def test_resume_closed_replays_spawn_env_token():
    svc, spawner, sid = _spawned("engineer.s-closed-env")
    svc.release(sid, reason="reaped on request (deliberate stop)")
    out = svc.resume_closed("engineer.s-closed-env")
    assert out["resumed"] is True, out
    assert spawner.launched[-1]["extra_env"] == TOKEN_ENV
