"""W14 (DESIGN-v6) — claude.exe auto-update guard for pool spawns.

Covers the pre-spawn health check + repair_claude_install() refuse-and-
explain path and the DISABLE_AUTOUPDATER build_env stamp. Every test uses
a FABRICATED npm layout under tmp_path plus stub/source binaries — the
real claude.exe is never read or written. Per d7, tests that touch
EDP_ROLE / EDP_HANDLE pin/clear them via monkeypatch.
"""
import os

import pytest

from edp_pool import pty_launcher as pl

_HEALTHY = pl._MIN_HEALTHY_BIN_BYTES + 10
_STUB = 500


def _make_install(root, *, bin_bytes, source_bytes=None, temp_shim=False):
    """Fabricate an npm claude-code layout under `root`.

    bin_bytes    → size of the resolved bin (small = stub).
    source_bytes → if set, write a versions-cache platform binary that big.
    temp_shim    → drop a `.claude-code-XXXX-TEMP` staging dir alongside.
    Returns the resolved bin path (str)."""
    adir = root / "node_modules" / "@anthropic-ai"
    binp = adir / "claude-code" / "bin" / "claude.exe"
    binp.parent.mkdir(parents=True, exist_ok=True)
    binp.write_bytes(b"\0" * bin_bytes)
    if source_bytes is not None:
        src = (adir / "claude-code" / "node_modules" / "@anthropic-ai"
               / "claude-code-win32-x64" / "claude.exe")
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(b"\0" * source_bytes)
    if temp_shim:
        (adir / ".claude-code-ABCD1234-TEMP").mkdir(parents=True,
                                                    exist_ok=True)
    return str(binp)


def test_health_check_trips_and_repair_fires(tmp_path):
    """A sub-1MB stub trips the check; ensure_claude_healthy self-repairs
    it from the versions cache so it is healthy afterward — no exception,
    no neuron Bash."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=_HEALTHY)
    assert pl.claude_bin_needs_repair(binp) is True

    out = pl.ensure_claude_healthy(binp)

    assert out == binp
    assert pl.claude_bin_needs_repair(binp) is False
    assert os.path.getsize(binp) >= pl._MIN_HEALTHY_BIN_BYTES


def test_temp_shim_trips_health_check(tmp_path):
    """A healthy-sized bin still trips when a leftover `.claude*-TEMP`
    staging shim marks an interrupted update."""
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY, temp_shim=True)
    assert pl.claude_bin_needs_repair(binp) is True


def test_repair_finishes_temp_rename(tmp_path):
    """repair restores the bin AND finishes the interrupted npm rename so
    no `-TEMP` staging residue remains to re-trip the check."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=_HEALTHY,
                         temp_shim=True)

    pl.repair_claude_install(binp)

    adir = tmp_path / "node_modules" / "@anthropic-ai"
    assert not list(adir.glob(".claude*-TEMP"))
    assert (adir / ".claude-code-ABCD1234").is_dir()  # renamed, not deleted
    assert pl.claude_bin_needs_repair(binp) is False


def test_repair_failure_refuses_with_self_healing_message(tmp_path):
    """With NO versions-cache source, repair cannot restore — the guard
    REFUSES (ClaudeInstallError) with a message naming the fix, and does
    NOT silently proceed (the stub is left untouched)."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=None)

    with pytest.raises(pl.ClaudeInstallError) as ei:
        pl.ensure_claude_healthy(binp)

    msg = str(ei.value)
    assert "python -m edp_pool.doctor" in msg
    assert "auto-repair failed" in msg
    assert "must NOT run Bash repair" in msg
    assert os.path.getsize(binp) == _STUB  # refused, not repaired


def test_build_env_stamps_disable_autoupdater(monkeypatch):
    """Every spawned shell's env carries DISABLE_AUTOUPDATER=1. d7: clear
    the runner's own EDP_ROLE/EDP_HANDLE so the copied env can't leak
    them, then assert build_env sets them from its args."""
    monkeypatch.delenv("EDP_ROLE", raising=False)
    monkeypatch.delenv("EDP_HANDLE", raising=False)

    env = pl.build_env("sess-1", "worker", "plan:act", "http://broker")

    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["EDP_ROLE"] == "worker"
    assert env["EDP_HANDLE"] == "plan:act"


def test_healthy_bin_is_not_flagged_or_touched(tmp_path):
    """A healthy bin is a no-op: not flagged, not modified, no false
    repair."""
    binp = _make_install(tmp_path, bin_bytes=_HEALTHY)
    before = os.path.getsize(binp)

    assert pl.claude_bin_needs_repair(binp) is False
    assert pl.ensure_claude_healthy(binp) == binp
    assert os.path.getsize(binp) == before


def test_bare_path_name_not_flagged():
    """A bare 'claude' resolved off PATH (not a file, not an npm layout)
    is a different, healthy scenario — never flagged for repair."""
    assert pl.claude_bin_needs_repair("claude") is False


def test_versions_cache_env_override_is_honored(tmp_path, monkeypatch):
    """EDP_CLAUDE_VERSIONS_CACHE lets an operator point repair at an
    explicit cache when the npm-nested source is absent."""
    binp = _make_install(tmp_path, bin_bytes=_STUB, source_bytes=None)
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "claude.exe").write_bytes(b"\0" * _HEALTHY)
    monkeypatch.setenv("EDP_CLAUDE_VERSIONS_CACHE", str(cache))

    pl.ensure_claude_healthy(binp)

    assert pl.claude_bin_needs_repair(binp) is False
