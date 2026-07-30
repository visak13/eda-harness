"""Context-diet Phase 6 — spawn-env stamps.

Every spawned shell arms the worker-close-nudge Stop hook and carries the
auto-compact window safety net (operator request: ~350k effective window).
Explicit operator pre-sets win; "0" disables the auto-compact stamp.
"""
import os

from edp_pool.pty_launcher import build_env


def _env(role="worker", **pre):
    saved = {}
    for k, v in pre.items():
        saved[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        return build_env(role=role, handle="p1:a1", session_id="s",
                         broker_url=None, pool_url=None, agent_home=None,
                         log_dir=None, defaults={})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_close_nudge_armed_by_default():
    assert _env()["EDP_WORKER_CLOSE_NUDGE"] == "1"


def test_close_nudge_operator_preset_wins():
    assert _env(EDP_WORKER_CLOSE_NUDGE="0")["EDP_WORKER_CLOSE_NUDGE"] == "0"


def test_auto_compact_window_default():
    assert _env()["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "350000"


def test_auto_compact_window_per_role_override():
    env = _env(EDP_AUTO_COMPACT_WINDOW_WORKER="250000")
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "250000"
    env = _env(role="planner", EDP_AUTO_COMPACT_WINDOW_WORKER="250000")
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "350000"


def test_auto_compact_window_disable():
    assert "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in _env(
        EDP_AUTO_COMPACT_WINDOW="0")
