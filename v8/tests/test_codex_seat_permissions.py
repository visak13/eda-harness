"""The pool's explicit skip-permissions flag applies to Codex seats too."""
import json
from pathlib import Path

import pytest

from edp8.codex_seat.seat import CodexSeat, monitor_sandbox_prefix, sandbox_for

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("role", ["engineer", "architect", "sme", "qa", "adversary", "owner"])
def test_explicit_skip_permissions_disables_sandbox(role):
    assert sandbox_for(role, {"EDP_SKIP_PERMISSIONS": "1"}) == "danger-full-access"


@pytest.mark.parametrize("mode", ["read-only", "workspace-write", "danger-full-access"])
def test_explicit_sandbox_override_wins(mode):
    assert sandbox_for("engineer", {"EDP_SKIP_PERMISSIONS": "1", "EDP_CODEX_SANDBOX": mode}) == mode


def test_default_role_policy_is_unchanged():
    assert sandbox_for("engineer", {}) == "workspace-write"
    assert sandbox_for("adversary", {"EDP_SKIP_PERMISSIONS": "0"}) == "read-only"
    assert monitor_sandbox_prefix("codex", "danger-full-access") == []
    assert "sandbox_mode=read-only" in monitor_sandbox_prefix("codex", "read-only")


@pytest.mark.parametrize("resume", [False, True])
def test_thread_and_monitor_share_launch_policy(tmp_path, resume):
    log = tmp_path / "fake.jsonl"
    seat = CodexSeat(cwd=ROOT, role="engineer", handle="engineer.permissions", log_dir=tmp_path,
                     codex_bin=str(ROOT / "tests/codex_seat/fake_app_server.py"), board=False,
                     discover=lambda _c: ([], None), skill_roots=[],
                     env={"EDP_SKIP_PERMISSIONS": "1", "EDP_CODEX_SANDBOX": "",
                          "FAKE_APPSERVER_LOG": str(log)})
    if resume:
        seat.state_path.parent.mkdir(parents=True, exist_ok=True)
        seat.state_path.write_text(json.dumps({"threadId": "thr-prior"}), encoding="utf-8")
    try:
        seat.start(resume=resume)
        messages = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        request = next(m for m in messages if m.get("method") == ("thread/resume" if resume else "thread/start"))
        assert request["params"]["sandbox"] == "danger-full-access"
        assert seat.tools.sandbox_prefix == []
        assert "approval_policy=never" in seat.argv()
    finally:
        seat.stop()
