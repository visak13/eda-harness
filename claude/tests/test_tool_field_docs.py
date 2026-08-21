"""Tool-doc overhaul gates (2026-08-21).

1. COVERAGE: every input field of every registered tool resolves a doc
   (its own Field description, or the FIELD_DOCS table) — an
   undocumented field is how "hit or miss" tool calling returns.
2. NO LORE: the agent-visible documentation surfaces (catalog
   one-liners + field docs) carry no framework archaeology — incident
   ids, design-doc names, and dates mean nothing to a spawned agent
   and crowd out the contract.
3. WIRING: the MCP shim actually lands the docs in the exposed schema.
"""

import re
import tempfile
from pathlib import Path

from edp_claude.server import make_context
from edp_claude.tools import build_registry
from edp_claude.tools.catalog import TOOL_ONE_LINERS
from edp_claude.tools.field_docs import FIELD_DOCS, field_doc

_LORE = re.compile(
    r"(?:\bDESIGN-v\d|\bd\d{2,3}\b|\bF\d{1,2}#\d|\bWS\d\b|\bWP\d\b"
    r"|\bR\d[ab]\b|\b20\d{2}-\d{2}-\d{2}\b|\bs\d{1,2} item\b)")


def _tools():
    home = Path(tempfile.mkdtemp(prefix="edp-fdocs-"))
    return build_registry(make_context(home))


def test_every_tool_field_has_a_doc():
    missing = []
    for t in _tools():
        for fname, f in t.InputModel.model_fields.items():
            if not field_doc(t.name, fname, f.description):
                missing.append(f"{t.name}.{fname}")
    assert not missing, (
        "undocumented tool input fields — add one lean sentence per "
        "field to tools/field_docs.py (or a Field description on the "
        f"model): {missing}")


def test_field_docs_name_only_real_tools_and_fields():
    by_name = {t.name: t for t in _tools()}
    stale = []
    for tool_name, fields in FIELD_DOCS.items():
        t = by_name.get(tool_name)
        if t is None:
            stale.append(tool_name)
            continue
        for fname in fields:
            if fname not in t.InputModel.model_fields:
                stale.append(f"{tool_name}.{fname}")
    assert not stale, (
        f"FIELD_DOCS names tools/fields that do not exist — prune: {stale}")


def test_agent_visible_docs_carry_no_lore():
    hits = []
    for name, clause in TOOL_ONE_LINERS.items():
        if _LORE.search(clause):
            hits.append(f"one-liner {name}: {clause[:80]}")
    for t in _tools():
        for fname, f in t.InputModel.model_fields.items():
            d = field_doc(t.name, fname, f.description) or ""
            if _LORE.search(d):
                hits.append(f"{t.name}.{fname}: {d[:80]}")
    assert not hits, (
        "agent-visible documentation carries framework archaeology "
        "(incident ids / design-doc names / dates) — rewrite as a plain "
        f"contract: {hits}")


def test_docs_are_lean():
    over = []
    for t in _tools():
        for fname, f in t.InputModel.model_fields.items():
            d = field_doc(t.name, fname, f.description) or ""
            if len(d) > 400:
                over.append(f"{t.name}.{fname} ({len(d)} chars)")
    assert not over, (
        f"field docs must stay lean (<=400 chars): {over}")


def test_mcp_schema_carries_field_docs():
    import asyncio

    from edp_claude.mcp_server import build_mcp
    home = Path(tempfile.mkdtemp(prefix="edp-fdocs-mcp-"))
    mcp = build_mcp(home)
    tools = asyncio.run(mcp.list_tools())
    by_name = {t.name: t for t in tools}
    schema = by_name["add_action"].inputSchema
    props = schema.get("properties", {})
    assert "description" in props.get("plan_id", {}), props.get("plan_id")
    assert "append" in props["plan_id"]["description"] \
        or "plan" in props["plan_id"]["description"].lower()
