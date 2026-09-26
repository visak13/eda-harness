"""t-67dad8c6aa: no role card, skill or built-in role takes the name of a Claude Code built-in slash command.

A seat boots by typing `/<card>`; a name Claude Code also owns may run the built-in instead of our card. The
list lives in edp8.workflow.CLAUDE_BUILTIN_COMMANDS; a name kept anyway sits in CLAUDE_BUILTIN_EXCEPTIONS
with the evidence that the project card wins (the Help seat's `doctor`, measured by card_collision_drill.py).
"""
from __future__ import annotations

from pathlib import Path

from edp8.schemas import Role
from edp8.workflow import CLAUDE_BUILTIN_COMMANDS, CLAUDE_BUILTIN_EXCEPTIONS, build_standard

V8 = Path(__file__).resolve().parents[1]


def _names() -> dict[str, str]:
    names = {p.stem: f".claude/commands/{p.name}" for p in (V8 / ".claude" / "commands").glob("*.md")}
    names |= {p.name: f".claude/skills/{p.name}" for p in (V8 / ".claude" / "skills").iterdir() if p.is_dir()}
    names |= {r.value: "schemas.Role" for r in Role}
    names |= {r.id: "workflow standard role" for r in build_standard().roles}
    return names


def test_no_card_skill_or_role_is_named_like_a_claude_builtin():
    hits = {n: where for n, where in _names().items()
            if n in CLAUDE_BUILTIN_COMMANDS and n not in CLAUDE_BUILTIN_EXCEPTIONS}
    assert not hits, (f"named like a Claude Code built-in slash command: {hits}; rename it, or record measured "
                      "evidence in workflow.CLAUDE_BUILTIN_EXCEPTIONS")


def test_every_exception_is_a_real_collision_with_evidence():
    names = _names()
    for n, why in CLAUDE_BUILTIN_EXCEPTIONS.items():
        assert n in CLAUDE_BUILTIN_COMMANDS and n in names and why.strip()


def test_the_tripwire_fires():
    assert {"help", "review", "init", "status", "model"} <= CLAUDE_BUILTIN_COMMANDS
    assert "engineer" not in CLAUDE_BUILTIN_COMMANDS
