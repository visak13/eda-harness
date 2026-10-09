"""s-e60c3d42ad: the edp-wake mod rides the agent-home payload, so every install gets it beside the role cards."""
from __future__ import annotations

import json
from pathlib import Path

from edp8 import materialise

V8 = Path(__file__).resolve().parents[1]


def test_wake_mod_is_in_the_payload_and_the_wheel_force_include():
    assert ".claude/mods" in materialise.PAYLOAD
    shipped = materialise.shipped_files(V8)
    for rel in (".claude/mods/edp-wake/.claude-plugin/plugin.json", ".claude/mods/edp-wake/hooks/hooks.json",
                ".claude/mods/edp-wake/hooks/register.ts"):
        assert rel in shipped, rel
    assert '".claude/mods" = "edp8/agent_home/.claude/mods"' in (V8 / "pyproject.toml").read_text(encoding="utf-8")


def test_wake_mod_manifest_names_one_module():
    mod = V8 / ".claude" / "mods" / "edp-wake"
    assert json.loads((mod / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["name"] == "edp-wake"
    assert json.loads((mod / "hooks" / "hooks.json").read_text(encoding="utf-8"))["modules"] == ["./register.ts"]


def test_generated_mod_typings_are_not_shipped():
    shipped = materialise.shipped_files(V8)
    assert not [r for r in shipped if ".claude-plugin/types/" in r]




def _seat_with_mod(monkeypatch, bundles, tmp_path, *, ready=True, owner="mod"):
    from edp8 import feed_driver

    class Client:
        participant = "engineer.s-1"
        base_url = "http://127.0.0.1:9400"

        def listening(self):
            return {"ok": True, "value": {"receives": "x"}}

        def doc_reads_reset(self):
            return {"ok": True}

    monkeypatch.setattr(bundles, "get_client", lambda: Client())
    monkeypatch.setenv("CLAUDE_CODE_PLUGIN_DIRS", str(V8 / ".claude" / "mods"))
    monkeypatch.setenv("EDP8_FEED_PY", "python")
    monkeypatch.setenv("EDP8_FEED_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("EDP8_WAKE_READY_WAIT_S", "0")
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    if ready:
        feed_driver.Readiness("engineer.s-1", owner=owner).write()


def test_subscribe_arms_no_monitor_when_the_mod_listener_is_proven_ready(monkeypatch, tmp_path):
    from edp8 import bundles
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path)
    out = bundles._subscribe(SubscribeArgs())
    assert out["value"]["monitor_cmd"] is None and out["value"]["wake"] == "mod"
    assert "do NOT start a Monitor" in out["hint"]


def test_f1_configured_but_no_listener_still_gets_the_monitor(monkeypatch, tmp_path):
    from edp8 import bundles
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path, ready=False)
    out = bundles._subscribe(SubscribeArgs())
    assert "edp8.feed_driver --participant engineer.s-1" in out["value"]["monitor_cmd"]
    assert "wake" not in out["value"]


def test_subscribe_keeps_the_monitor_without_the_mod(monkeypatch, tmp_path):
    from edp8 import bundles
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path, ready=False)
    monkeypatch.delenv("EDP8_FEED_PY")
    out = bundles._subscribe(SubscribeArgs())
    assert "edp8.feed_driver --participant engineer.s-1" in out["value"]["monitor_cmd"]


def test_a_live_mod_listener_alone_proves_the_mod_whatever_the_service_env_says(monkeypatch, tmp_path):
    """The service has no CLAUDE_CODE_PLUGIN_DIRS / EDP8_FEED_PY of its own: a fresh mod-owned readiness file with a
    live pid is enough (qa m-dfb5b7f516)."""
    from edp8 import bundles
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path)
    monkeypatch.delenv("EDP8_FEED_PY")
    monkeypatch.delenv("CLAUDE_CODE_PLUGIN_DIRS")
    out = bundles._subscribe(SubscribeArgs())
    assert out["value"]["monitor_cmd"] is None and out["value"]["wake"] == "mod"


def test_f5_the_kill_switch_wins_over_a_preset_mod_env(monkeypatch, tmp_path):
    from edp8 import bundles
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path)
    monkeypatch.setenv("EDP_WAKE_MOD", "0")
    assert bundles.wake_mod_configured() is False
    out = bundles._subscribe(SubscribeArgs())
    assert out["value"]["monitor_cmd"] and "wake" not in out["value"]


def test_f1_a_monitor_run_driver_does_not_count_as_the_mod(monkeypatch, tmp_path):
    """Astra recheck: a Monitor-started feed_driver writes the same readiness file; subscribe must still hand out
    the monitor_cmd because no mod ran."""
    from edp8 import bundles, feed_driver
    from edp8.bundles import SubscribeArgs

    _seat_with_mod(monkeypatch, bundles, tmp_path, owner="monitor")
    assert feed_driver.listener_ready("engineer.s-1") is True                 # a listener is alive ...
    assert feed_driver.listener_ready("engineer.s-1", owner="mod") is False  # ... but not the mod's
    out = bundles._subscribe(SubscribeArgs())
    assert "edp8.feed_driver --participant engineer.s-1" in out["value"]["monitor_cmd"]
    assert "wake" not in out["value"]


def test_f1_a_readiness_file_without_an_owner_is_a_monitors(monkeypatch, tmp_path):
    import json
    import os
    import time

    from edp8 import feed_driver

    monkeypatch.setenv("EDP8_FEED_STATE_DIR", str(tmp_path))
    feed_driver._ready_path("engineer.s-1").write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()}), encoding="utf-8")   # the pre-owner format
    assert feed_driver.listener_ready("engineer.s-1", owner="mod") is False


def test_the_mod_starts_its_listener_as_the_wake_owner():
    register = (V8 / ".claude" / "mods" / "edp-wake" / "hooks" / "register.ts").read_text(encoding="utf-8")
    assert "'--wake-owner', 'mod'" in register


def test_feed_driver_takes_wake_owner_and_defaults_to_monitor():
    import re
    import subprocess
    import sys

    out = subprocess.run([sys.executable, "-m", "edp8.feed_driver", "--help"], capture_output=True, text=True,
                         timeout=60).stdout
    plain = re.sub(r"\[[0-9;]*m", "", out)
    assert "--wake-owner" in plain and "monitor,mod" in plain


# s-e60c3d42ad (c-97bff500ad): the mod's own tests run from the repo with one documented command, whatever the user's settings.
def test_the_readme_names_the_one_command_that_runs_the_mod_tests():
    readme = (V8 / ".claude" / "mods" / "edp-wake" / "README.md").read_text(encoding="utf-8")
    assert "uv run --no-sync python scripts/test_wake_mod.py" in readme and (V8 / "scripts" / "test_wake_mod.py").is_file()


def test_the_mod_tests_run_and_pass_even_when_the_users_settings_turn_hooks_off(tmp_path):
    import os
    import re
    import shutil
    import subprocess
    import sys

    import pytest
    if shutil.which("claude") is None:
        pytest.skip("Claude Code is not installed here")
    hostile = tmp_path / "user-config"
    hostile.mkdir()
    (hostile / "settings.json").write_text('{"disableAllHooks": true}', encoding="utf-8")  # what made `claude plugin test` refuse
    done = subprocess.run([sys.executable, str(V8 / "scripts" / "test_wake_mod.py")], text=True, capture_output=True,
                          env={**os.environ, "CLAUDE_CONFIG_DIR": str(hostile)}, timeout=180)
    out = done.stdout + done.stderr
    if "organisation policy" in out:
        pytest.skip("managed settings turn hook modules off on this machine")
    assert done.returncode == 0, out
    m = re.search(r"(\d+) pass\s+(\d+) fail", out)
    assert m and int(m.group(1)) >= 9 and m.group(2) == "0", out  # includes the EDP_HANDLE-only case
