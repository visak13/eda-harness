"""t-f42af1ca59 — resume dispatches on the harness the row recorded, never on a model guess.

Live 2026-09-26 22:07Z (owner m-ccbf57c574): resume_closed of a codex seat whose recorded model
("codex/gpt-6-sol") the catalog no longer mapped routed to the claude launcher, which got the codex
thread file as its resume base. These tests drive the REAL CompositeSpawner stack the pool builds in
main.py (claude primary, then pi, then codex) over in-memory backends, so routing is the production
routing: a model the catalog does not map lands on claude for a FRESH spawn, exactly as live.
"""

from __future__ import annotations

import json

import pytest

from edp_pool.composite_spawner import CompositeSpawner
from edp_pool.service import PoolService
from edp_pool.spawner import FakeSpawner


class Backend(FakeSpawner):
    """An in-memory backend of one harness with that harness's closed-session store."""

    def __init__(self, harness: str, store):
        super().__init__()
        self.harness = harness
        self.store = store  # dir of <handle>.json (codex) / <handle>.jsonl (pi); None for claude

    def pins_session_id(self, _sid):
        return self.harness == "claude"

    def session_token(self, _sid):
        return None

    def close_viewport(self, _sid):
        return None

    def closed_session_token(self, _sid, handle):
        if self.store is None:
            return None
        f = self.store / f"{handle}.{'json' if self.harness == 'codex' else 'jsonl'}"
        return str(f) if f.is_file() else None


CODEX_MODELS = {"gpt-6-sol"}  # the catalog's codex ids today; "codex/gpt-6-sol" is NOT one


def _stack(tmp_path):
    claude = Backend("claude", None)
    pi = Backend("pi", tmp_path / "pi-sessions")
    codex = Backend("codex", tmp_path / "codex-sessions")
    for d in (pi.store, codex.store):
        d.mkdir(exist_ok=True)
    spawner = CompositeSpawner(
        CompositeSpawner(claude, pi, route_model=lambda m: m == "astra"),
        codex, route_model=lambda m: m in CODEX_MODELS)
    return spawner, claude, pi, codex


def _thread_file(codex, handle, thread_id):
    f = codex.store / f"{handle}.json"
    f.write_text(json.dumps({"threadId": thread_id, "handle": handle}), encoding="utf-8")
    return f


def _closed_codex_row(tmp_path, handle, *, spawn_model="gpt-6-sol", row_model=..., legacy=False):
    """A codex seat spawned through the stack, then closed; its row then carries `row_model`."""
    spawner, claude, pi, codex = _stack(tmp_path)
    svc = PoolService(spawner)
    sid = svc.spawn("engineer", handle, None, "monitor", model=spawn_model)
    assert isinstance(sid, str), sid
    assert codex.launched[-1]["handle"] == handle          # it really was a codex seat
    row = svc.sessions[sid]
    assert row["harness"] == "codex" and row["claude_session_id"] is None
    thread = _thread_file(codex, handle, "01a0df49-thread-before")
    svc.release(sid, reason="reaped on request (deliberate stop)")
    if row_model is not ...:
        row["model"] = row_model
        row["spawn_settings"]["model"] = row_model
    if legacy:  # a row persisted before the pool recorded harnesses
        row.pop("harness")
        row["spawn_settings"].pop("harness")
    # a fresh pool (restart): no backend knows the sid, only the row and the stores remain
    fresh, claude2, pi2, codex2 = _stack(tmp_path)
    svc2 = PoolService(fresh)
    svc2.sessions, svc2.locks = svc.sessions, svc.locks
    return svc2, sid, thread, claude2, codex2


@pytest.mark.parametrize("row_model", [None, "codex/gpt-6-sol"], ids=["no-model", "unmapped-model"])
@pytest.mark.parametrize("legacy", [False, True], ids=["recorded", "legacy-row"])
def test_closed_codex_row_resumes_through_codex(tmp_path, row_model, legacy):
    handle = "engineer.s-32035a77da"
    svc, sid, thread, claude, codex = _closed_codex_row(
        tmp_path, handle, row_model=row_model, legacy=legacy)
    before = json.loads(thread.read_text(encoding="utf-8"))["threadId"]

    out = svc.resume_closed(handle)

    assert out["resumed"] is True, out
    assert claude.launched == []                                # never the claude CLI
    launched = codex.launched[-1]
    assert launched["session_id"] == sid
    assert launched["resume_session"] == str(thread)            # codex thread resume
    assert launched["model"] == row_model
    assert out["claude_session_id"] is None                     # no claude fork minted onto the row
    row = svc.sessions[sid]
    assert row["harness"] == "codex" and row["state"] == "active"
    after = json.loads(thread.read_text(encoding="utf-8"))["threadId"]
    assert after == before
    print(f"codex resume ({row_model}, legacy={legacy}): thread {before} -> {after}")


def test_parked_codex_row_with_unmapped_model_resumes_through_codex(tmp_path):
    spawner, claude, _pi, codex = _stack(tmp_path)
    svc = PoolService(spawner)
    handle = "engineer.s-parked"
    sid = svc.spawn("engineer", handle, None, "monitor", model="gpt-6-sol")
    thread = _thread_file(codex, handle, "thread-parked")
    svc.sessions[sid]["model"] = svc.sessions[sid]["spawn_settings"]["model"] = "codex/gpt-6-sol"
    svc.sessions[sid]["state"] = "parked"
    codex.kill(sid)

    out = svc.resume(handle)

    assert out["resumed"] is True, out
    assert claude.launched == []
    assert codex.launched[-1]["resume_session"] == str(thread)
    assert svc.sessions[sid]["harness"] == "codex"


def test_codex_row_carrying_a_claude_base_is_refused(tmp_path):
    """The live incident's aftermath: a codex row whose stored id is a claude fork."""
    handle = "engineer.s-mixed"
    svc, sid, _thread, claude, codex = _closed_codex_row(tmp_path, handle)
    svc.sessions[sid]["claude_session_id"] = "2c100bf1-64a3-4e7c-8d35-1a7ebd3ab180"

    out = svc.resume_closed(handle)

    assert out["resumed"] is False
    assert "claude session id" in out["reason"] and "codex" in out["reason"]
    assert claude.launched == [] and codex.launched == []
    assert svc.sessions[sid]["state"] == "done" and svc.locks.get(handle) is None


def test_claude_row_whose_only_base_is_a_codex_file_is_refused(tmp_path):
    spawner, claude, _pi, codex = _stack(tmp_path)
    svc = PoolService(spawner)
    handle = "engineer.s-reused"
    sid = svc.spawn("engineer", handle, None, "monitor", model="claude-opus-5-5")
    assert svc.sessions[sid]["harness"] == "claude"
    svc.sessions[sid]["claude_session_id"] = None   # no stored claude conversation
    _thread_file(codex, handle, "someone-elses-thread")
    svc.release(sid)
    launched = len(claude.launched)

    out = svc.resume_closed(handle)

    assert out["resumed"] is False
    assert "belongs to the codex harness" in out["reason"]
    assert len(claude.launched) == launched and codex.launched == []


def test_claude_row_still_fork_resumes_on_claude(tmp_path):
    spawner, claude, _pi, codex = _stack(tmp_path)
    svc = PoolService(spawner)
    handle = "engineer.s-claude"
    sid = svc.spawn("engineer", handle, None, "monitor", claude_session="cs-before",
                    model="gpt-6-sol-typo")   # an unmapped model routes to claude, as before
    svc.release(sid)
    out = svc.resume_closed(handle)
    assert out["resumed"] is True, out
    assert codex.launched == []
    assert claude.launched[-1]["resume_session"] == "cs-before"
    assert svc.sessions[sid]["claude_session_id"] == out["claude_session_id"] != "cs-before"


def test_harness_missing_from_the_pool_is_refused(tmp_path):
    """A codex row brought to a pool with no codex backend is refused, not launched on claude."""
    handle = "engineer.s-nocodex"
    svc, sid, _thread, _claude, _codex = _closed_codex_row(tmp_path, handle)
    only_claude = Backend("claude", None)
    bare = PoolService(only_claude)
    bare.sessions, bare.locks = svc.sessions, svc.locks
    out = bare.resume_closed(handle)
    assert out["resumed"] is False and "no backend for" in out["reason"]
    assert only_claude.launched == []


def test_composite_launch_harness_dispatch(tmp_path):
    spawner, claude, pi, codex = _stack(tmp_path)
    assert spawner.harnesses == ("claude", "pi", "codex")
    spawner.launch_harness("pi", "s1", "qa", "qa.x", mode="headless", model=None)
    assert pi.launched[-1]["session_id"] == "s1" and spawner.harness_of("s1") == "pi"
    with pytest.raises(LookupError):
        spawner.launch_harness("opencode", "s2", "qa", "qa.y", mode="headless")
