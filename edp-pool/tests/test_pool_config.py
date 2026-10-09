"""Item 14 (qa m-96b136614b): the pool's Claude settings.json ships as a tracked template and is seeded.

`.gitignore` ignores the whole pool config dir, so a clone or an install has no settings.json there. The
template is package data; seeding writes it only when the file is missing, never over an owner's edit.
"""

import json
import sys
import subprocess
from pathlib import Path

import pytest

from edp_pool import pool_config

_REPO = Path(__file__).resolve().parents[2]
_HOOKS = ("guard-destructive.py", "pool-ping.py", "notify-user.py")


def _commands(cfg: dict) -> list[str]:
    return [
        h["command"]
        for groups in cfg["hooks"].values()
        for g in groups
        for h in g["hooks"]
    ]


def test_the_template_ships_the_style_and_hooks_without_model_or_host_paths():
    text = pool_config.template_text()
    cfg = json.loads(text)
    assert cfg["outputStyle"] == "edp-terse"
    assert "model" not in cfg  # the catalog passes --model
    assert (
        cfg["enableAllProjectMcpServers"] is True
        and cfg["skipDangerousModePermissionPrompt"] is True
    )
    joined = " ".join(_commands(cfg))
    for hook in _HOOKS:
        assert f"${{CLAUDE_PROJECT_DIR}}/.claude/hooks/{hook}" in joined
    for host in ("C:", "Users", "\\\\"):
        assert host not in text


def test_the_template_is_tracked_and_not_ignored():
    if subprocess.run(
        ["git", "-C", str(_REPO), "rev-parse", "--git-dir"], capture_output=True
    ).returncode:
        pytest.skip("not a git checkout")
    rel = "edp-pool/src/edp_pool/claude_pool_template/settings.json"
    ignored = subprocess.run(
        ["git", "-C", str(_REPO), "check-ignore", "-q", "--no-index", rel]
    )
    assert ignored.returncode == 1, f"{rel} is gitignored: it would never ship"


def test_seeding_a_fresh_dir_writes_the_style_and_hooks(tmp_path):
    cfg_dir = tmp_path / "claude-pool"
    home = tmp_path / "agent-home"
    (home / ".venv" / "Scripts").mkdir(parents=True)
    (home / ".venv" / "Scripts" / "python.exe").write_bytes(b"")

    assert pool_config.seed_settings(cfg_dir, home) is True

    cfg = json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
    assert cfg["outputStyle"] == "edp-terse"
    cmds = _commands(cfg)
    assert {"PreToolUse", "PostToolUse", "Stop", "SessionEnd", "Notification"} <= set(
        cfg["hooks"]
    )
    assert all(
        c.startswith(f'"{pool_config.VENV_PYTHON}"') for c in cmds
    )  # the home's venv is kept


def test_a_home_without_a_venv_gets_the_pools_interpreter(tmp_path):
    cfg_dir = tmp_path / "claude-pool"
    assert (
        pool_config.seed_settings(
            cfg_dir, tmp_path / "installed-home", python=r"D:\py\python.exe"
        )
        is True
    )
    cmds = _commands(
        json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
    )
    assert cmds and all(c.startswith('"D:/py/python.exe" ') for c in cmds)
    assert all(
        c.startswith('"D:/py/python.exe" "${CLAUDE_PROJECT_DIR}/.claude/hooks/')
        for c in cmds
        if " -c " not in c
    )
    assert pool_config.VENV_PYTHON not in (cfg_dir / "settings.json").read_text(
        encoding="utf-8"
    )


def test_a_second_seed_leaves_an_edited_file_alone(tmp_path):
    cfg_dir = tmp_path / "claude-pool"
    assert pool_config.seed_settings(cfg_dir, tmp_path) is True
    edited = '{"outputStyle": "mine", "theme": "light"}\n'
    (cfg_dir / "settings.json").write_text(edited, encoding="utf-8")

    assert pool_config.seed_settings(cfg_dir, tmp_path) is False

    assert (cfg_dir / "settings.json").read_text(encoding="utf-8") == edited
    assert [p.name for p in cfg_dir.iterdir()] == [
        "settings.json"
    ]  # no temp file left behind


def test_pool_startup_seeds_the_config_dir(monkeypatch, tmp_path):
    """Installed mode (no EDP_HOME/EDP_DEV): startup seeds <data>/claude-pool."""
    import asyncio

    from edp_pool.service import PoolService
    from edp_pool.spawner import FakeSpawner

    for n in (
        "EDP_HOME",
        "EDP8_HOME",
        "EDP_DEV",
        "EDP_AGENT_HOME",
        "EDP_CLAUDE_CONFIG_DIR",
    ):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("EDP_RESUME_WATCHDOG", "0")
    svc = PoolService(spawner=FakeSpawner(), state_path=tmp_path / "state.json")
    asyncio.run(svc.startup())
    try:
        cfg = json.loads(
            (tmp_path / "data" / "claude-pool" / "settings.json").read_text(
                encoding="utf-8"
            )
        )
        assert cfg["outputStyle"] == "edp-terse"
    finally:
        asyncio.run(svc.shutdown())


def test_a_compaction_restarts_the_seat_with_resume_self_then_context(tmp_path):
    """e0cec S3: after /compact a seat runs on a summary only. The SessionStart hook (matcher "compact")
    injects the instruction to call resume_self() then context(); other session starts are untouched."""
    cfg = json.loads(pool_config.template_text())
    groups = cfg["hooks"]["SessionStart"]
    assert [g["matcher"] for g in groups] == ["compact"]
    (hook,) = groups[0]["hooks"]
    assert hook["type"] == "command" and hook["timeout"] <= 5

    rendered = json.loads(pool_config.render(tmp_path, python=sys.executable))
    cmd = rendered["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    code = cmd.split(" -c ", 1)[1].strip().strip(chr(34))
    assert cmd.startswith(f"\"{Path(sys.executable).as_posix()}\" -c ")
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert "resume_self()" in out and "context()" in out
    assert out.index("resume_self()") < out.index("context()")


def _old_install(cfg_dir: Path) -> dict:
    """A 0.9.1 install's settings.json: the S7 effortLevel pin, no compact SessionStart hook, an installed
    interpreter, and two of the owner's own values (a theme and a hook of theirs)."""
    old = json.loads(pool_config.render(None, python="C:/Prog/heronry.exe"))
    old["hooks"].pop("SessionStart")
    old["effortLevel"] = "medium"
    old["theme"] = "light"
    old["hooks"]["PreToolUse"].append(
        {"matcher": "Edit", "hooks": [{"type": "command", "command": "mine.exe"}]}
    )
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "settings.json").write_text(json.dumps(old), encoding="utf-8")
    return old


def test_s12_upgrade_merges_the_new_template_into_an_existing_install_once(tmp_path):
    """S12 (m-07507eb2cb): an upgrade brings the compact SessionStart hook in and drops the retired effortLevel
    pin; the owner's theme and own hook stay; a second start changes nothing."""
    cfg_dir = tmp_path / "claude-pool"
    _old_install(cfg_dir)
    assert pool_config.seed_settings(cfg_dir, tmp_path) is False  # an existing file is never re-seeded

    changed = pool_config.upgrade_settings(cfg_dir, tmp_path / "installed-home", python="C:/Prog/heronry.exe")

    cfg = json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
    assert "effortLevel" not in cfg and "dropped effortLevel" in changed
    start = cfg["hooks"]["SessionStart"]
    assert [g["matcher"] for g in start] == ["compact"]
    assert "resume_self()" in start[0]["hooks"][0]["command"]
    assert start[0]["hooks"][0]["command"].startswith('"C:/Prog/heronry.exe" ')
    assert cfg["theme"] == "light"  # the owner's value
    assert any(g.get("matcher") == "Edit" for g in cfg["hooks"]["PreToolUse"])  # the owner's hook
    bash = next(g for g in cfg["hooks"]["PreToolUse"] if g.get("matcher") == "Bash")
    assert len(bash["hooks"]) == 2  # the hooks it already had are not duplicated
    assert (cfg_dir / pool_config.STAMP).is_file()

    assert pool_config.upgrade_settings(cfg_dir, tmp_path / "installed-home", python="C:/Prog/heronry.exe") == []
    del cfg["hooks"]["SessionStart"]  # the owner removes it after the upgrade: it stays removed
    (cfg_dir / "settings.json").write_text(json.dumps(cfg), encoding="utf-8")
    assert pool_config.upgrade_settings(cfg_dir, tmp_path) == []
    assert "SessionStart" not in json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))["hooks"]


def test_s12_upgrade_leaves_a_missing_or_unreadable_file_alone(tmp_path):
    cfg_dir = tmp_path / "claude-pool"
    assert pool_config.upgrade_settings(cfg_dir, tmp_path) == []
    assert not cfg_dir.exists() or not (cfg_dir / "settings.json").exists()
    cfg_dir.mkdir()
    (cfg_dir / "settings.json").write_text("{not json", encoding="utf-8")
    assert pool_config.upgrade_settings(cfg_dir, tmp_path) == []
    assert (cfg_dir / "settings.json").read_text(encoding="utf-8") == "{not json"


def test_s12_a_fresh_seed_then_upgrade_is_a_no_op(tmp_path):
    cfg_dir = tmp_path / "claude-pool"
    assert pool_config.seed_settings(cfg_dir, tmp_path, python="D:/py/python.exe") is True
    before = (cfg_dir / "settings.json").read_text(encoding="utf-8")
    assert pool_config.upgrade_settings(cfg_dir, tmp_path, python="D:/py/python.exe") == []
    assert (cfg_dir / "settings.json").read_text(encoding="utf-8") == before


def test_s12_pool_startup_upgrades_an_existing_install(monkeypatch, tmp_path):
    from edp_pool.service import PoolService

    for n in ("EDP_HOME", "EDP8_HOME", "EDP_DEV", "EDP_AGENT_HOME", "EDP_CLAUDE_CONFIG_DIR"):
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))
    from edp_pool.pty_launcher import claude_pool_config_dir

    cfg_dir = claude_pool_config_dir()
    _old_install(cfg_dir)
    svc = PoolService.__new__(PoolService)
    svc._spawner_agent_home = lambda: str(tmp_path / "installed-home")
    svc._seed_claude_settings()
    cfg = json.loads((cfg_dir / "settings.json").read_text(encoding="utf-8"))
    assert "effortLevel" not in cfg and "SessionStart" in cfg["hooks"]
