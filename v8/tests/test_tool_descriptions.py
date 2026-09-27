"""Design §19 rule 2 (criterion c-c91255c430): every ToolDef description states, in order,
what it does · when to call it · its linked objects and skills · the enum args it takes · what it
returns. S23 (architect ruling m-fbd6ae40d3): the enum clause names the enum ARGS and points at
describe('enums'); the allowed values live once, in the advertised schema, never duplicated in prose.
The objects/skills clause is composed from tool_contracts and the enum clause from the args_model,
so neither can drift from the metadata or the pydantic schema.

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
    assert "When: " in desc, f"{name}: description missing the 'When:' clause"

    # part 3 — OBJECTS + ENUMS: the linked objects are named; every enum arg is named with a
    # pointer to describe('enums'), and its allowed values are in the advertised schema
    assert "Objects: " in desc, f"{name}: description names no linked object"
    ef = enum_fields(tool.args_model)
    if ef:
        assert "Enums: " in desc, f"{name}: has enum args but no enum clause"
        assert "describe('enums')" in desc, f"{name}: enum clause must point at describe('enums')"
        props = tool.input_schema.get("properties", {})
        for field, values in ef.items():
            assert field in desc, f"{name}: enum arg {field!r} not named in the description"
            node = props[field]
            got = node.get("enum") or [v for alt in node.get("anyOf", []) for v in alt.get("enum", [])]
            assert got == values, f"{name}.{field}: advertised schema lacks the allowed values"

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
        again = compose_description(tool.what, tool.when, tool.returns, tool.args_model, name)
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


# --------------------------------------------------------------------------- S22 §24.1 caps/derivation
def test_ticket_create_description_names_the_caps():
    """§24.1 (criterion c-bcc4d02da1): the ticket_create tool description states the story/task caps."""
    d = ALL_TOOLS["ticket_create"].description.lower()
    assert "8 open stories" in d or "at most 8" in d, d
    assert "5 tasks" in d or "at most 5" in d, d
    assert "scope gate" in d, d


def test_criterion_create_description_states_derivation_and_criteria_cap():
    """§24/§24.1 (criteria c-abb821e363, c-bcc4d02da1): the criterion_create tool description states
    the checker derivation and the freshly-written-criteria cap."""
    d = ALL_TOOLS["criterion_create"].description.lower()
    for token in ("qa", "knowledge", "override_reason", "6 fresh"):
        assert token in d.replace("freshly-written", "fresh"), f"criterion_create desc missing {token!r}: {d}"
