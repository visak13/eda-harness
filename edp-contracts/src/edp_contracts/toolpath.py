"""Where the external tools are: a setting, else PATH. Nothing else (S2 s-b7ec13d748, design §4.3).

Every tool the fleet starts (claude, codex, pi, node, git, bash) resolves here: first its setting (an
explicit path the operator chose), then ``shutil.which`` on this process's PATH. No install-directory
search: a tool not on PATH and not configured is reported as missing, with the setting that fixes it.

:func:`tool_argv` turns a resolved path into an argv prefix that ``subprocess`` can start without a shell:
a Windows ``.cmd``/``.bat`` shim goes through ``%COMSPEC% /d /c``, a ``.js`` entry point runs under node,
and an npm ``.ps1`` shim is swapped for its ``.cmd`` sibling.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from . import settings

#: tool name → the setting that overrides the PATH lookup
TOOL_KEYS: dict[str, str] = {
    "claude": "EDP_CLAUDE_BIN",
    "codex": "EDP_CODEX_BIN",
    "pi": "EDP_PI_BIN",
    "node": "EDP_NODE_BIN",
    "git": "EDP_GIT_BIN",
    "bash": "EDP_BASH_BIN",
}


class ToolMissing(FileNotFoundError):
    """A tool is neither configured nor on PATH."""


def find_tool(name: str, *, key: str | None = None) -> str | None:
    """The tool's path: its setting (``TOOL_KEYS[name]`` or `key`) when set, else PATH; None if neither."""
    k = key or TOOL_KEYS.get(name)
    if k:
        v = settings.env_raw(k)
        if v:
            return v.strip()
    return shutil.which(name)


def require_tool(name: str, *, key: str | None = None) -> str:
    """:func:`find_tool` that raises :class:`ToolMissing` naming the fix."""
    got = find_tool(name, key=key)
    if got:
        return got
    k = key or TOOL_KEYS.get(name)
    fix = f"set {k} or put {name} on PATH" if k else f"put {name} on PATH"
    raise ToolMissing(f"{name} not found: {fix}")


def tool_argv(path: str) -> list[str]:
    """argv prefix that starts `path` without a shell on this OS."""
    low = path.lower()
    if low.endswith(".js") or low.endswith(".mjs"):
        return [require_tool("node"), path]
    if sys.platform == "win32":
        if low.endswith(".ps1"):
            # npm writes name.ps1 next to name.cmd; CreateProcess cannot start a .ps1 at all
            cmd = Path(path).with_suffix(".cmd")
            if cmd.is_file():
                path, low = str(cmd), str(cmd).lower()
        if low.endswith((".cmd", ".bat")):
            comspec = settings.env_raw("COMSPEC") or "cmd.exe"
            return [comspec, "/d", "/c", path]
    return [path]


def git_bash() -> str | None:
    """A bash with the POSIX userland on its PATH. EDP_BASH_BIN wins. On Windows it is Git's bash, found
    through the git on PATH (``<git root>/bin/bash.exe``), then ``bash`` on PATH unless that is WSL's
    System32 relay (which runs in a different OS). On POSIX, ``bash`` on PATH."""
    configured = settings.env_raw("EDP_BASH_BIN")
    if configured:
        return configured.strip()
    if sys.platform != "win32":
        return shutil.which("bash")
    git = find_tool("git")
    if git:
        p = Path(git).resolve().parent
        # <root>/cmd/git.exe, <root>/bin/git.exe or <root>/mingw64/bin/git.exe
        for root in (p.parent, p.parent.parent, p):
            cand = root / "bin" / "bash.exe"
            if cand.is_file():
                return str(cand)
    found = shutil.which("bash")
    if found and not _is_wsl_relay(found):
        return found
    return None


def _is_wsl_relay(path: str) -> bool:
    windir = settings.env_raw("SystemRoot") or "C:\\Windows"
    try:
        return Path(path).resolve().is_relative_to(Path(windir).resolve())
    except OSError:
        return False


__all__ = ["TOOL_KEYS", "ToolMissing", "find_tool", "git_bash", "probe_version", "require_tool", "tool_argv"]


def probe_version(argv: list[str], *, timeout: float = 10.0) -> str | None:
    """`<argv> --version` over a pipe, no shell: the first output line, or None when the tool does not
    start, fails, or hangs past `timeout`. A health check that needs no install-layout knowledge."""
    import subprocess

    try:
        r = subprocess.run([*argv, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    line = (r.stdout or r.stderr).strip().splitlines()
    return line[0] if line else ""
