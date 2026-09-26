"""S19 (story s-d8a2452ae9): a seat whose spawn env names disallowed tools gets claude's own deny list, so the
read-only Help seat (edp8 role `doctor`) has no Bash/PowerShell/Edit/Write even under skip-permissions."""

from edp_pool import spawner as pl


def test_disallowed_tools_env_becomes_the_claude_flag():
    env = {pl.DISALLOWED_TOOLS_ENV: "Bash,PowerShell,Edit,Write,MultiEdit,NotebookEdit"}
    assert pl.disallowed_tools_args(env) == ["--disallowedTools",
                                             "Bash PowerShell Edit Write MultiEdit NotebookEdit"]
    assert pl.disallowed_tools_args({}) == []
    assert pl.disallowed_tools_args(None) == []
    assert pl.disallowed_tools_args({pl.DISALLOWED_TOOLS_ENV: " , "}) == []
