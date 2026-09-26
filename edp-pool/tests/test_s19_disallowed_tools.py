"""S19 (story s-d8a2452ae9): a seat whose spawn env names disallowed tools gets claude's own deny list, so the
read-only Help seat (edp8 role `doctor`) has no Bash/PowerShell/Edit/Write even under skip-permissions.

t-67dad8c6aa: the deny list rode argv as `--disallowedTools "<names>"`, and that flag is variadic, so a monitor
seat's argv prompt (`/doctor`) was parsed as one more tool name and the seat idled on an empty prompt. The
flag is now one `--disallowedTools=<names>` token, and every launch argv keeps the card prompt as its own
last argument with no bare variadic flag before it."""

import pytest

from edp_pool import pty_launcher
from edp_pool import spawner as pl

DENY = "Bash,PowerShell,Edit,Write,MultiEdit,NotebookEdit"


def test_disallowed_tools_env_becomes_one_flag_token():
    env = {pl.DISALLOWED_TOOLS_ENV: DENY}
    assert pl.disallowed_tools_args(env) == ["--disallowedTools=Bash PowerShell Edit Write MultiEdit NotebookEdit"]
    assert pl.disallowed_tools_args({}) == []
    assert pl.disallowed_tools_args(None) == []
    assert pl.disallowed_tools_args({pl.DISALLOWED_TOOLS_ENV: " , "}) == []


def test_variadic_safe_joins_every_variadic_pair():
    args = ["--session-id", "abc", "--add-dir", "C:/x", "--disallowedTools", "Bash Edit", "--mcp-config", "m.json",
            "--disallowedTools=Write"]
    assert pty_launcher.variadic_safe(args) == [
        "--session-id", "abc", "--add-dir=C:/x", "--disallowedTools=Bash Edit", "--mcp-config=m.json",
        "--disallowedTools=Write"]


def _bare_variadic(argv: list[str]) -> list[str]:
    return [a for a in argv if a in pty_launcher.CLAUDE_VARIADIC_FLAGS]


@pytest.mark.parametrize("mode", ["monitor", "headless"])
@pytest.mark.parametrize("card", [None, "engineer-quick"])
@pytest.mark.parametrize("resume", [None, "base-session"])
def test_launch_argv_with_a_deny_list_keeps_the_card_prompt_separate(tmp_path, monkeypatch, mode, card, resume):
    """Every launch route: a monitor seat's argv ends in the card prompt as its own argument; a headless seat
    types it after readiness. Neither argv carries a bare variadic flag that could swallow a later argument."""
    import edp_pool.console_launcher as cl
    captured: dict = {}

    class FakeConsole:
        def __init__(self, argv, env, cwd):
            captured["argv"] = list(argv)
            self.pid = 4242

        def spawn(self):
            pass

        def is_alive(self):
            return True

        def terminate(self):
            pass

    class FakePty:
        def __init__(self, argv, env, cwd, log_path, name):
            captured["argv"] = list(argv)
            self.pid = 4243

        def spawn(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(cl, "ConsoleLaunch", FakeConsole)
    monkeypatch.setattr(pty_launcher, "PtyLaunch", FakePty)
    monkeypatch.setattr(pty_launcher, "resolve_claude_bin", lambda b: "claude.exe")
    monkeypatch.setattr(pty_launcher, "ensure_claude_healthy", lambda b: b)
    monkeypatch.setattr(pty_launcher, "ensure_claude_runs", lambda b: b)
    monkeypatch.setattr(pl.SubprocessSpawner, "_activate_pty",
                        lambda self, launch, sid, handle, line, log: captured.setdefault("typed", line))
    sp = pl.SubprocessSpawner(cwd=str(tmp_path), log_dir=tmp_path)
    env = {pl.DISALLOWED_TOOLS_ENV: DENY, **({"EDP_CARD": card} if card else {})}
    sp.launch("doctor:1", "doctor", "doctor.topic-x", mode=mode, model="claude-haiku-4-5-20251001",
              claude_session="s-1", resume_session=resume, extra_env=env)
    argv = captured["argv"]
    assert not _bare_variadic(argv), argv
    assert "--disallowedTools=Bash PowerShell Edit Write MultiEdit NotebookEdit" in argv
    assert argv[argv.index("--model") + 1] == "claude-haiku-4-5-20251001"
    prompt = f"/{card or 'doctor'}"
    if mode == "monitor":
        assert argv[-1] == prompt, argv
    else:
        assert prompt not in argv and captured["typed"] == prompt  # typed into the PTY after readiness
