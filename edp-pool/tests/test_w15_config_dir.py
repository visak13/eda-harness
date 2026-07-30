"""W15 (DESIGN-v6) — config-dir pin for pool spawns.

Covers the build_env CLAUDE_CONFIG_DIR stamp that kills the shadow
~/.claude store for pool-spawned shells: build_env must pin
CLAUDE_CONFIG_DIR to the checked-in .claude-pool skeleton, honoring an
explicit EDP_CLAUDE_CONFIG_DIR override. Per d7, tests clear the runner's
own EDP_ROLE / EDP_HANDLE (and EDP_CLAUDE_CONFIG_DIR) via monkeypatch so a
copied env can't leak them into the result.
"""
from pathlib import Path

from edp_pool import pty_launcher as pl


def _clear_leaky_env(monkeypatch):
    """d7: the runner's own lineage/config env must not skew build_env."""
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


def test_build_env_pins_claude_config_dir_to_pool_skeleton(monkeypatch):
    """build_env stamps CLAUDE_CONFIG_DIR to the repo's .claude-pool dir."""
    _clear_leaky_env(monkeypatch)

    env = pl.build_env("sess-1", "worker", "plan:act", "http://broker")

    assert env["CLAUDE_CONFIG_DIR"] == str(pl._CLAUDE_POOL_CONFIG_DIR)
    # self-located at the repo root, named exactly .claude-pool
    assert pl._CLAUDE_POOL_CONFIG_DIR.name == ".claude-pool"
    assert Path(env["CLAUDE_CONFIG_DIR"]).name == ".claude-pool"


def test_config_dir_is_not_the_user_home_store(monkeypatch):
    """The pin must NOT resolve to the operator's personal ~/.claude."""
    _clear_leaky_env(monkeypatch)

    env = pl.build_env("sess-1", "planner", "plan:act", "http://broker")

    user_store = Path.home() / ".claude"
    assert Path(env["CLAUDE_CONFIG_DIR"]).resolve() != user_store.resolve()


def test_explicit_override_env_wins(monkeypatch):
    """EDP_CLAUDE_CONFIG_DIR is the operator's intentional override knob."""
    _clear_leaky_env(monkeypatch)
    monkeypatch.setenv("EDP_CLAUDE_CONFIG_DIR", "/tmp/custom-claude-config")

    env = pl.build_env("sess-1", "worker", "plan:act", "http://broker")

    assert env["CLAUDE_CONFIG_DIR"] == "/tmp/custom-claude-config"


def test_pool_skeleton_exists_with_empty_memory_dir():
    """The checked-in .claude-pool skeleton has a memory/ dir and no
    memory files in it (only the .gitkeep placeholder)."""
    root = pl._CLAUDE_POOL_CONFIG_DIR
    assert root.is_dir(), f"missing skeleton: {root}"
    memory_dirs = list(root.glob("projects/*/memory"))
    assert memory_dirs, "no projects/*/memory dir in .claude-pool skeleton"
    for mem in memory_dirs:
        assert mem.is_dir()
        real_files = [p for p in mem.iterdir() if p.name != ".gitkeep"]
        assert real_files == [], f"memory/ not empty: {real_files}"
