"""v0.9.1 (s-dbe96f11cd, owner m-0967afb055): a claude seat imported into the installed pool has
its transcript under the OLD config dir and cwd key, so `claude --resume <base>` found nothing and
the shell exited within a second. A resume whose base transcript is missing starts fresh with the
resume_self activation; a base that is present still fork-resumes."""

from __future__ import annotations

from edp_pool.composite_spawner import CompositeSpawner
from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner, SubprocessSpawner


class _ProbeSpawner(FakeSpawner):
    def __init__(self, present: set[str]):
        super().__init__()
        self.present = present

    def has_transcript(self, claude_session):
        return claude_session in self.present


def _closed(svc, handle="engineer.s-x", cs="cs-1"):
    sid = svc.spawn("engineer", handle, None, "monitor", claude_session=cs)
    svc.release(sid, reason="closed by self: done")
    return sid


def test_resume_closed_with_missing_transcript_starts_fresh():
    svc = PoolService(_ProbeSpawner(present=set()))
    sid = _closed(svc)
    out = svc.resume_closed("engineer.s-x")
    assert out["resumed"] is True, out
    assert out["via"] == "started-fresh"
    rec = svc.spawner.launched[-1]
    assert rec["session_id"] == sid
    assert rec["resume_session"] is None
    assert "resume_self()" in rec["activation"]
    assert svc.sessions[sid]["state"] == "active"


def test_resume_closed_with_present_transcript_still_forks():
    svc = PoolService(_ProbeSpawner(present={"cs-1"}))
    _closed(svc)
    out = svc.resume_closed("engineer.s-x")
    assert out["via"] == "resume-from-closed"
    assert svc.spawner.launched[-1]["resume_session"] == "cs-1"


def test_parked_resume_with_missing_transcript_starts_fresh(monkeypatch):
    svc = PoolService(_ProbeSpawner(present=set()))
    sid = svc.spawn("planner", "rec-x:s1", None, claude_session="base-1")
    monkeypatch.setattr(svc, "_inbox_depth", lambda h: 0)
    assert svc.park_session(sid, flush_timeout=0.05, flush_quiesce=0.01)["parked"]
    svc._kill_session(sid)
    out = svc.resume("rec-x:s1")
    assert out["resumed"] is True and out["via"] == "started-fresh", out
    assert svc.spawner.launched[-1]["resume_session"] is None


def test_subprocess_spawner_probes_config_dir_under_cwd_key(tmp_path, monkeypatch):
    cfg = tmp_path / "claude-pool"
    home = tmp_path / "agent home"
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", str(cfg))
    sp = SubprocessSpawner(cwd=str(home))
    assert sp.has_transcript("abc") is False
    key = "".join(c if c.isalnum() else "-" for c in str(home))
    (cfg / "projects" / key).mkdir(parents=True)
    (cfg / "projects" / key / "abc.jsonl").write_text("{}\n", encoding="utf-8")
    assert sp.has_transcript("abc") is True
    # the composite asks its claude primary
    assert CompositeSpawner(sp, FakeSpawner()).has_transcript("abc") is True
    assert CompositeSpawner(sp, FakeSpawner()).has_transcript("zzz") is False
