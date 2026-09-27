"""Item 14 (qa m-96b136614b): the pool's Claude settings.json ships as a tracked template and is seeded.

`.gitignore` ignores the whole pool config dir, so a clone or an install has no settings.json there. The
template is package data; seeding writes it only when the file is missing, never over an owner's edit.
"""

import json
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
    assert cmds and all(
        c.startswith('"D:/py/python.exe" "${CLAUDE_PROJECT_DIR}/.claude/hooks/')
        for c in cmds
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
