"""The pool's Claude settings.json: a tracked template, seeded into the pool config dir.

The pool config dir (`claude_pool_config_dir()`: dev <repo>/edp-pool/.claude-pool, installed
<data>/claude-pool) is gitignored whole, because seats write transcripts, memory and sign-in into it.
So its settings.json never ships. The template beside this module is the shipped copy: the hooks,
`outputStyle: edp-terse`, effort, skill overrides. It is seeded into the config dir at pool start and at
`heronry init`, only when the file is missing, so an owner's edits are never overwritten. It carries no
`model` (the catalog passes --model) and no host paths.
"""

from __future__ import annotations

import os
import sys
import tempfile
from importlib import resources
from pathlib import Path

SETTINGS = "settings.json"
#: The hook interpreter the template names: the agent home's own venv (a source checkout has one).
VENV_PYTHON = "${CLAUDE_PROJECT_DIR}/.venv/Scripts/python.exe"


def template_text() -> str:
    return (
        resources.files("edp_pool")
        .joinpath("claude_pool_template", SETTINGS)
        .read_text(encoding="utf-8")
    )


def render(agent_home: Path | None, python: str | None = None) -> str:
    """The template with its hook interpreter resolved for this machine: the agent home's .venv python
    when the home has one, else the interpreter the pool runs (an installed home has no .venv)."""
    text = template_text()
    if (
        agent_home is not None
        and (Path(agent_home) / ".venv" / "Scripts" / "python.exe").is_file()
    ):
        return text
    exe = (python or sys.executable).replace("\\", "/")
    return text.replace(VENV_PYTHON, exe)


def seed_settings(
    config_dir: Path, agent_home: Path | None = None, python: str | None = None
) -> bool:
    """Write <config_dir>/settings.json from the template when it is missing. Returns True when written.
    An existing file is left alone, whatever it holds (the owner's edits win)."""
    config_dir = Path(config_dir)
    dst = config_dir / SETTINGS
    if dst.exists():
        return False
    config_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_dir, prefix=f".{SETTINGS}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(render(agent_home, python))
        # atomic create-if-absent: a concurrent seed or an owner's file is never replaced
        try:
            os.link(tmp, dst)
        except FileExistsError:
            return False
        except OSError:  # no hard links on this filesystem: re-check, then move
            if dst.exists():
                return False
            os.replace(tmp, dst)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True
