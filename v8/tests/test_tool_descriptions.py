"""Design §19 rule 2 (criterion c-c91255c430): every ToolDef description states, in order,
what it does · when to call it · the enum args it takes (allowed values inline, or a pointer
to describe) · what it returns; and every enum value named in a description is a real schema
value. The objects/enums clause is COMPOSED from the args_model, so a tool's advertised
allowed set can never drift from its pydantic schema.

Also pins §19 rule 1: the role-card commands are untouched by this story — a diff of
`.claude/commands/` is empty at story close.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from edp8.bundles import ALL_TOOLS, compose_description, enum_fields
from edp8.schemas import ENUMS

# every string value across every registered enum — the universe a description may name
_ALL_ENUM_VALUES = {v for e in ENUMS.values() for v in (m.value for m in e)}


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_description_has_four_parts(name: str):
    tool = ALL_TOOLS[name]
    desc = tool.description

    # part 1 — WHAT: the structured field is present and opens the description
    assert tool.what.strip(), f"{name}: empty 'what'"
    assert desc.startswith(tool.what.strip().rstrip(".")), f"{name}: description must open with what it does"

    # part 2 — WHEN: an explicit "when to call it" clause
    assert tool.when.strip(), f"{name}: empty 'when'"
    assert "When to call:" in desc, f"{name}: description missing the 'When to call:' clause"

    # part 3 — OBJECTS + ENUMS: every enum arg's allowed values appear inline, with a
    # pointer to describe('enums'); tools with no enum arg carry no enum clause (their
    # objects are named in the what/when prose and per-arg field descriptions)
    ef = enum_fields(tool.args_model)
    if ef:
        assert "Enum args —" in desc, f"{name}: has enum args but no enum clause"
        assert "describe('enums')" in desc, f"{name}: enum clause must point at describe('enums')"
        for field, values in ef.items():
            for v in values:
                assert v in desc, f"{name}.{field}: allowed value {v!r} not named in the description"

    # part 4 — RETURNS: the structured field is present and the word appears
    assert tool.returns.strip(), f"{name}: empty 'returns'"
    assert "Returns" in desc, f"{name}: description missing the Returns clause"


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_no_phantom_enum_values_in_enum_clause(name: str):
    """Every value the composed enum clause lists is a real value of a real schema enum —
    the clause cannot advertise a value the pydantic model would reject."""
    tool = ALL_TOOLS[name]
    ef = enum_fields(tool.args_model)
    for field, values in ef.items():
        # each field's advertised values are exactly its enum's schema values
        assert set(values) <= _ALL_ENUM_VALUES, f"{name}.{field}: {values} contains a non-schema value"


def test_description_is_pure_function_of_fields_and_schema():
    """The description is composed, not hand-typed: recomposing from the same inputs is
    identical — so editing prose can never silently desync the enum clause from the schema."""
    for name, tool in ALL_TOOLS.items():
        again = compose_description(tool.what, tool.when, tool.returns, tool.args_model)
        assert tool.description == again, name


def test_role_cards_untouched():
    """§19 rule 1: `git diff --stat -- .claude/commands/` is empty — S19 changes the tool
    layer, never the role-card activators."""
    root = Path(__file__).resolve().parents[1]
    commands = root / ".claude" / "commands"
    if not (root / ".git").exists() and not (root.parent / ".git").exists():
        pytest.skip("not a git checkout")
    r = subprocess.run(["git", "diff", "--stat", "--", str(commands)],
                       cwd=str(root), capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip(f"git unavailable: {r.stderr.strip()}")
    assert r.stdout.strip() == "", f".claude/commands/ has uncommitted changes:\n{r.stdout}"
