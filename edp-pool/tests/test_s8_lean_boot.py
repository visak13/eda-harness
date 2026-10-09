"""S8 (s-60c63f2d8e): a Claude seat boots lean — no claude.ai connectors, only its role's skills listed, unused
tools denied, Bash/Read output capped. The per-change token deltas are measured in v8/docs/evidence/e0cec-s8/after."""

from __future__ import annotations

import json
from pathlib import Path

from edp_pool import lean_boot
from edp_pool.pty_launcher import build_env, variadic_safe

V8 = Path(__file__).resolve().parents[2] / "v8"


def test_env_connectors_off_cron_off_and_caps(monkeypatch):
    for k in (*lean_boot.LEAN_ENV, *lean_boot.CAP_ENV, "EDP_LEAN_BOOT"):
        monkeypatch.delenv(k, raising=False)
    env = lean_boot.apply_env(build_env("s1", "engineer", "engineer.x", None))
    assert env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "false"
    assert env["CLAUDE_CODE_DISABLE_CRON"] == "1"
    assert env["BASH_MAX_OUTPUT_LENGTH"] == "15000"
    assert env["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"] == "8000"


def test_operator_env_wins(monkeypatch):
    monkeypatch.setenv("BASH_MAX_OUTPUT_LENGTH", "40000")
    monkeypatch.setenv("ENABLE_CLAUDEAI_MCP_SERVERS", "true")
    env = lean_boot.apply_env({"BASH_MAX_OUTPUT_LENGTH": "40000", "ENABLE_CLAUDEAI_MCP_SERVERS": "true"})
    assert env["BASH_MAX_OUTPUT_LENGTH"] == "40000" and env["ENABLE_CLAUDEAI_MCP_SERVERS"] == "true"


def test_lean_boot_off_keeps_caps_only(monkeypatch, tmp_path):
    monkeypatch.setenv("EDP_LEAN_BOOT", "0")
    env = lean_boot.apply_env({})
    assert "ENABLE_CLAUDEAI_MCP_SERVERS" not in env and "CLAUDE_CODE_DISABLE_CRON" not in env
    assert env["BASH_MAX_OUTPUT_LENGTH"] == "15000"
    assert lean_boot.lean_args("engineer", None, V8, tmp_path) == []


def test_engineer_skills_are_the_cards_own(tmp_path):
    named, known = lean_boot.role_skills("engineer", V8)
    assert {"ticket", "verify", "methodology", "demo", "pain"} <= named
    assert "epic" not in named and "harvest" not in named     # the architect's and qa's
    s = lean_boot.settings_dict("engineer", V8)
    ov = s["skillOverrides"]
    assert s["disableClaudeAiConnectors"] is True and s["disableBundledSkills"] is True
    assert not any(ov.get(n) for n in named | {"engineer"})   # kept: nothing overrides them
    assert ov["epic"] == "off" and ov["anthropic-skills:docx"] == "off"
    assert ov["architect"] == "user-invocable-only" and "engineer" not in ov


def test_deny_list_has_workflow_and_cron_but_not_what_cards_use():
    deny = lean_boot.settings_dict("engineer", V8)["permissions"]["deny"]
    assert {"Workflow", "CronCreate", "CronList", "CronDelete"} <= set(deny)
    cards = " ".join(p.read_text(encoding="utf-8") for p in (V8 / ".claude/commands").glob("*.md"))
    assert not [t for t in deny if t in cards], "a card names a denied tool"
    assert not {"Monitor", "TaskStop", "SendMessage", "Agent", "Bash", "Read", "EnterPlanMode"} & set(deny)


def test_settings_file_is_per_card_and_idempotent(tmp_path):
    p = lean_boot.settings_path(tmp_path, "qa", V8)
    assert p == tmp_path / "lean" / "qa.settings.json"
    first = p.stat().st_mtime_ns
    assert lean_boot.settings_path(tmp_path, "qa", V8) == p and p.stat().st_mtime_ns == first
    assert "harvest" not in [n for n, v in json.loads(p.read_text())["skillOverrides"].items() if v]
    assert lean_boot.settings_path(tmp_path, "../evil", V8) is None


def test_lean_args_use_the_spawn_card_and_survive_variadic_safe(tmp_path):
    args = lean_boot.lean_args("engineer", {"EDP_CARD": "engineer-quick"}, V8, tmp_path)
    assert args[0] == "--settings" and args[1].endswith("engineer-quick.settings.json")
    # --settings is not variadic: the activation prompt placed after it stays its own argv entry
    assert variadic_safe([*args, "--disallowedTools", "Bash"])[:2] == args


def test_unreadable_config_dir_never_blocks_a_seat(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert lean_boot.lean_args("engineer", None, V8, blocker / "cfg") == []
    assert lean_boot.lean_args("engineer", None, None, tmp_path) == []


def test_spawner_wires_lean_boot():
    src = (Path(lean_boot.__file__).parent / "spawner.py").read_text(encoding="utf-8")
    assert "lean_boot.apply_env(env)" in src and "lean_boot.lean_args(" in src


def test_wake_mod_env_points_at_the_shipped_mods(monkeypatch, tmp_path):
    """s-e60c3d42ad: a seat is launched with the edp-wake mod loaded and the listener interpreter named."""
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    monkeypatch.setattr(lean_boot, "can_run_listener", lambda: True)
    manifest = tmp_path / ".claude" / "mods" / "edp-wake" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    env = lean_boot.apply_wake_mod({}, tmp_path)
    assert env["CLAUDE_CODE_PLUGIN_DIRS"] == str(tmp_path / ".claude" / "mods")
    assert env["EDP8_FEED_PY"]
    assert lean_boot.apply_wake_mod({"CLAUDE_CODE_PLUGIN_DIRS": "x"}, tmp_path)["CLAUDE_CODE_PLUGIN_DIRS"] == "x"


def test_wake_mod_env_absent_without_the_mod_or_when_switched_off(monkeypatch, tmp_path):
    assert lean_boot.apply_wake_mod({}, tmp_path) == {}
    manifest = tmp_path / ".claude" / "mods" / "edp-wake" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("EDP_WAKE_MOD", "0")
    assert lean_boot.apply_wake_mod({}, tmp_path) == {}



def test_wake_mod_env_absent_when_the_pool_python_cannot_run_the_listener(monkeypatch, tmp_path):
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    monkeypatch.setattr(lean_boot, "can_run_listener", lambda: False)
    manifest = tmp_path / ".claude" / "mods" / "edp-wake" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    assert lean_boot.apply_wake_mod({}, tmp_path) == {}


def test_can_run_listener_is_false_where_edp8_is_not_installed():
    """The edp-pool dev venv has no edp8, so a dev pool keeps the Monitor wake instead of a looping mod."""
    lean_boot.can_run_listener.cache_clear()
    try:
        import edp8  # noqa: F401
    except ImportError:
        assert lean_boot.can_run_listener() is False
    else:
        assert lean_boot.can_run_listener() is True


def test_f5_the_kill_switch_in_the_seat_env_turns_the_mod_off(monkeypatch, tmp_path):
    """Astra F5: EDP_WAKE_MOD=0 arrives in the seat's own env (extra_env merged before apply_wake_mod)."""
    monkeypatch.delenv("EDP_WAKE_MOD", raising=False)
    monkeypatch.setattr(lean_boot, "can_run_listener", lambda: True)
    manifest = tmp_path / ".claude" / "mods" / "edp-wake" / ".claude-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("{}", encoding="utf-8")
    env = lean_boot.apply_wake_mod({"EDP_WAKE_MOD": "0", "CLAUDE_CODE_PLUGIN_DIRS": "D:/operator/plugins"}, tmp_path)
    assert env == {"EDP_WAKE_MOD": "0", "CLAUDE_CODE_PLUGIN_DIRS": "D:/operator/plugins"}   # operator dirs untouched
