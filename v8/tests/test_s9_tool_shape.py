"""e0cec S9 (s-8ca20e8543) task 4: the one shape every ToolDef description and schema keeps, pinned.

Shape: `<what>. When: <when>. [Enums: <f1>, <f2>. ]Returns <returns>.` with no Objects/Skills clause
(architect m-1fc3764b91: describe_objects() carries it). Every arg is described, or typed (enum/bool), or named in the
prose, or a self-evident name (tool_contracts.SELF_EVIDENT_ARGS). A closed vocabulary is a typed enum, never a
`a|b|c` string; no arg description repeats its own name.
"""
from __future__ import annotations

import os
import re

os.environ.setdefault("EDP8_EMBEDDER", "none")

import pytest

from edp8.bundles import ALL_TOOLS, enum_fields
from edp8.tool_contracts import SELF_EVIDENT_ARGS

_SHAPE = re.compile(r"^[^\n]+?\. When: .+?(?: Enums: [^\n]+?\.)? Returns .+\.$", re.S)
_PIPE_LIST = re.compile(r"\b\w+(?:\|\w+){2,}\b")
_OPEN_VOCAB = {("doctor_logs", "service")}  # also takes pool-logs/<name>, so not a closed vocabulary
_FILLER = {"id", "ids", "the", "a", "of", "ticket", "doc", "message", "kind", "body", "title", "seat", "role", "text"}


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_description_has_one_shape(name):
    d = ALL_TOOLS[name].description
    assert _SHAPE.match(d), f"{name}: not `what. When: … [Enums: …] Returns …`: {d[:120]}"
    assert "Objects: " not in d and "Skills: " not in d, name


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_enum_clause_lists_exactly_the_enum_args(name):
    tool = ALL_TOOLS[name]
    m = re.search(r" Enums: ([^\n]+?)\. Returns ", tool.description)
    listed = [x.strip() for x in m.group(1).split(",")] if m else []
    assert sorted(listed) == sorted(enum_fields(tool.args_model)), name


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_every_arg_is_described_typed_or_named(name):
    tool = ALL_TOOLS[name]
    for f, node in tool.input_schema.get("properties", {}).items():
        ok = (node.get("description") or node.get("enum") or "$ref" in node or node.get("type") == "boolean"
              or f in SELF_EVIDENT_ARGS or f in tool.description)
        assert ok, f"{name}.{f}: undescribed, untyped and not named in the description"


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_a_closed_vocabulary_is_a_typed_enum(name):
    for f, node in ALL_TOOLS[name].input_schema.get("properties", {}).items():
        d = node.get("description", "")
        if node.get("type") == "string" and not node.get("enum") and (name, f) not in _OPEN_VOCAB:
            assert not _PIPE_LIST.search(d), f"{name}.{f}: a|b|c in a string description — make it a Literal/StrEnum: {d[:80]}"


@pytest.mark.parametrize("name", sorted(ALL_TOOLS))
def test_no_arg_description_repeats_its_name(name):
    for f, node in ALL_TOOLS[name].input_schema.get("properties", {}).items():
        d = node.get("description")
        if not d:
            continue
        own = set(re.split(r"[_\W]+", f.lower())) | _FILLER
        words = set(re.split(r"[_\W]+", d.lower())) - {""}
        assert not (words <= own and len(words) <= 3), f"{name}.{f}: description {d!r} only restates the name"
