"""Operator documentation the board serves to people (Code tab FAQ, Remote access guide).

Lives in `v8/docs/operator/` (epic-0cec8d1c31 S9), not in the agent guides folder. The wheel ships the
served ones as package data under `edp8/operator_docs/`; a source checkout reads the docs folder; an
agent home that carries its own `docs/operator/<name>.md` overrides both.
"""
from __future__ import annotations

from importlib import resources
from pathlib import Path

from edp8 import settings

#: path shown to people, relative to the repo root
DOCS_DIR = "docs/operator"


def _shipped_dirs() -> list[Path]:
    from .materialise import checkout_root
    dirs = [Path(str(resources.files("edp8").joinpath("operator_docs")))]
    root = checkout_root()
    if root is not None:
        dirs.append(root / DOCS_DIR)
    return dirs


def read(name: str) -> str | None:
    """`<name>.md` text, or None when this build does not carry it."""
    for d in [settings.agent_home() / DOCS_DIR, *_shipped_dirs()]:
        try:
            return (d / f"{name}.md").read_text(encoding="utf-8")
        except OSError:
            continue
    return None


def shown_path(name: str) -> str:
    return f"{DOCS_DIR}/{name}.md"
