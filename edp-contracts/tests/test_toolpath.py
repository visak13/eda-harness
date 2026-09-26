"""S2 (s-b7ec13d748): external tools come from a setting or PATH, and start without a shell."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from edp_contracts import toolpath


def _exe(d: Path, name: str) -> Path:
    p = d / (f"{name}.exe" if sys.platform == "win32" else name)
    p.write_bytes(b"")
    p.chmod(0o755)
    return p


def test_setting_wins_over_path(tmp_path, monkeypatch):
    on_path = _exe(tmp_path, "node")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert Path(toolpath.find_tool("node")).resolve() == on_path.resolve()
    monkeypatch.setenv("EDP_NODE_BIN", "/opt/elsewhere/node")
    assert toolpath.find_tool("node") == "/opt/elsewhere/node"


def test_missing_tool_names_the_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("EDP_CODEX_BIN", raising=False)
    assert toolpath.find_tool("codex") is None
    with pytest.raises(toolpath.ToolMissing, match="EDP_CODEX_BIN"):
        toolpath.require_tool("codex")


def test_js_runs_under_the_configured_node(monkeypatch):
    monkeypatch.setenv("EDP_NODE_BIN", "/x/node")
    assert toolpath.tool_argv("/a/cli.js") == ["/x/node", "/a/cli.js"]


def test_plain_executable_is_its_own_argv():
    assert toolpath.tool_argv("/usr/local/bin/claude") == ["/usr/local/bin/claude"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shims")
def test_cmd_and_ps1_shims_go_through_comspec(tmp_path, monkeypatch):
    monkeypatch.setenv("COMSPEC", r"C:\Windows\system32\cmd.exe")
    cmd = tmp_path / "pi.cmd"
    cmd.write_text("@echo off\r\n")
    (tmp_path / "pi.ps1").write_text("")
    assert toolpath.tool_argv(str(cmd)) == [r"C:\Windows\system32\cmd.exe", "/d", "/c", str(cmd)]
    assert toolpath.tool_argv(str(tmp_path / "pi.ps1"))[-1] == str(cmd)


@pytest.mark.skipif(sys.platform != "win32", reason="Git bash lookup is the Windows rule")
def test_git_bash_is_found_beside_git_never_the_wsl_relay(tmp_path, monkeypatch):
    root = tmp_path / "Git"
    (root / "cmd").mkdir(parents=True)
    (root / "bin").mkdir()
    git = _exe(root / "cmd", "git")
    bash = _exe(root / "bin", "bash")
    monkeypatch.delenv("EDP_BASH_BIN", raising=False)
    monkeypatch.setenv("EDP_GIT_BIN", str(git))
    assert Path(toolpath.git_bash()).resolve() == bash.resolve()

    # no git: a bash under SystemRoot (WSL's System32 relay) is refused
    sysroot = tmp_path / "Windows"
    (sysroot / "System32").mkdir(parents=True)
    _exe(sysroot / "System32", "bash")
    monkeypatch.setenv("EDP_GIT_BIN", str(tmp_path / "nowhere" / "git.exe"))
    monkeypatch.setenv("SystemRoot", str(sysroot))
    monkeypatch.setenv("PATH", str(sysroot / "System32"))
    assert toolpath.git_bash() is None
    monkeypatch.setenv("EDP_BASH_BIN", r"D:\tools\bash.exe")
    assert toolpath.git_bash() == r"D:\tools\bash.exe"
