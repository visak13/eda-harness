"""W15 (DESIGN-v6) — config-dir pin for pool spawns.

Covers the build_env CLAUDE_CONFIG_DIR stamp that kills the shadow
~/.claude store for pool-spawned shells: build_env must pin
CLAUDE_CONFIG_DIR to the pool's own config dir (dev: <repo>/edp-pool/.claude-pool,
installed: <data>/claude-pool), honoring an
explicit EDP_CLAUDE_CONFIG_DIR override. Per d7, tests clear the runner's
own EDP_ROLE / EDP_HANDLE (and EDP_CLAUDE_CONFIG_DIR) via monkeypatch so a
copied env can't leak them into the result.
"""
import subprocess
from pathlib import Path

import pytest

from edp_pool import pty_launcher as pl


def _clear_leaky_env(monkeypatch):
    """d7: the runner's own lineage/config env must not skew build_env."""
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)
    monkeypatch.delenv("EDP_CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)


_MODE_VARS = ("EDP_HOME", "EDP8_HOME", "EDP_DEV", "EDP8_DATA")
_REPO = Path(__file__).resolve().parents[2]


def _set_mode(monkeypatch, home):
    """Dev mode = EDP_HOME at the source checkout's v8/; installed = no EDP_HOME/EDP_DEV (as in CI)."""
    for n in _MODE_VARS:
        monkeypatch.delenv(n, raising=False)
    if home is not None:
        monkeypatch.setenv("EDP_HOME", str(home))


def test_build_env_pins_claude_config_dir_to_pool_skeleton_dev_mode(monkeypatch):
    """Dev mode: build_env stamps CLAUDE_CONFIG_DIR to the repo's edp-pool/.claude-pool."""
    _clear_leaky_env(monkeypatch)
    _set_mode(monkeypatch, _REPO / "v8")

    env = pl.build_env("sess-1", "worker", "plan:act", "http://broker")

    assert pl.claude_pool_config_dir() == _REPO / "edp-pool" / ".claude-pool"
    assert env["CLAUDE_CONFIG_DIR"] == str(_REPO / "edp-pool" / ".claude-pool")


def test_build_env_pins_claude_config_dir_to_data_dir_installed(monkeypatch, tmp_path):
    """Installed (no EDP_HOME, no EDP_DEV): <data>/claude-pool, resolved on call, not at import."""
    _clear_leaky_env(monkeypatch)
    _set_mode(monkeypatch, None)
    monkeypatch.setenv("EDP8_DATA", str(tmp_path / "data"))

    env = pl.build_env("sess-1", "worker", "plan:act", "http://broker")

    assert pl.claude_pool_config_dir() == tmp_path / "data" / "claude-pool"
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "data" / "claude-pool")


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


def _git(*args):
    return subprocess.run(["git", "-C", str(_REPO), *args], capture_output=True, text=True)


def test_pool_skeleton_tracks_no_seat_memory():
    """The TRACKED .claude-pool skeleton holds no memory file, and seat memory is gitignored.

    The fleet pool writes live seat memory (host paths, names) into the working copy's
    .claude-pool/projects/*/memory, so the live dir is never empty on a fleet host; what
    must hold is that git tracks none of it and would refuse to add it."""
    if _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout")
    tracked = _git("ls-files", "--", "edp-pool/.claude-pool").stdout.splitlines()
    memory = [p for p in tracked if "/memory/" in p and not p.endswith("/.gitkeep")]
    assert memory == [], f"seat memory tracked: {memory}"
    probe = "edp-pool/.claude-pool/projects/C--x/memory/MEMORY.md"
    assert _git("check-ignore", "-q", "--no-index", probe).returncode == 0, f"not ignored: {probe}"
