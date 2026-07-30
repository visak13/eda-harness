"""The PreToolUse destructive-command guard (2026-05-31 blackout fix).

Deterministic harness enforcement (a worker's `taskkill /F /IM python.exe`
killed the whole stack; prompt prohibitions don't reliably prevent that).
Tests the pure `decide()` matcher: DENY blanket name/image kills of stack
processes; ALLOW targeted PID kills and everything else.
"""

import importlib.util
from pathlib import Path

_HOOK = (Path(__file__).resolve().parents[1]
         / ".claude" / "hooks" / "guard-destructive.py")


def _load():
    spec = importlib.util.spec_from_file_location("guard_destructive", _HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load()


def test_denies_the_exact_blackout_command():
    assert guard.decide("taskkill /F /IM python.exe") is not None


def test_denies_blanket_name_image_kills():
    for cmd in (
        "taskkill /IM python.exe",
        "taskkill /f /im pythonw.exe",
        "taskkill /F /IM node.exe",
        "taskkill /F /IM claude.exe",
        "taskkill /F /T",                       # force tree, no /PID
        "Stop-Process -Name python -Force",
        "Stop-Process -Name uvicorn",
        "pkill -f python",
        "pkill uvicorn",
        "killall node",
    ):
        assert guard.decide(cmd) is not None, cmd


def test_allows_targeted_and_harmless():
    for cmd in (
        "taskkill /PID 41712 /F",               # specific pid
        "taskkill /F /T /PID 41712",            # tree of a specific pid
        "Stop-Process -Id 41712",
        "Stop-Process -Id 41712 -Force",
        "kill 41712",
        "taskkill /F /IM notepad.exe",          # not a stack process
        "ls -la",
        "git status",
        "python -m pytest",
        "echo done",
    ):
        assert guard.decide(cmd) is None, cmd


def test_empty_and_none_are_allowed():
    assert guard.decide("") is None
    assert guard.decide(None) is None
