"""Context-diet Phase 4 — role-tagged tool one-liners.

Every registered tool advertises "[roles] purpose-clause": the role tag is
DERIVED from ROLE_TOOLSETS at registration (it cannot drift from roles.py);
the clause is hand-written in tools/catalog.py. The generated
"(backing=...)" placeholder is dead — a tool missing from the catalog fails
HERE, not silently in the shell's tool list.
"""
from edp_claude.tools._tools import ALL_TOOL_CLASSES
from edp_claude.tools.catalog import TOOL_ONE_LINERS
from edp_claude.tools.roles import ROLE_TOOLSETS


def _registered_names() -> set[str]:
    return {cls.name for cls in ALL_TOOL_CLASSES}


def test_every_registered_tool_has_a_catalog_clause():
    missing = sorted(_registered_names() - set(TOOL_ONE_LINERS))
    assert not missing, (
        f"registered tools without a catalog one-liner: {missing} — add a "
        "single lean clause to tools/catalog.py (never the long docstring)")


def test_no_stale_catalog_entries():
    stale = sorted(set(TOOL_ONE_LINERS) - _registered_names())
    assert not stale, (
        f"catalog names no registry holds: {stale} — remove them (a stale "
        "entry is a description for a tool that cannot be called)")


def test_clauses_stay_lean():
    for name, clause in TOOL_ONE_LINERS.items():
        assert clause.strip(), name
        assert "\n" not in clause, f"{name}: one line means one line"
        assert len(clause) <= 220, (
            f"{name}: {len(clause)} chars — the W4/a3 ruling stands; "
            "verbose catalogs regress the planner")


def test_descriptions_carry_derived_role_tag(tmp_path, monkeypatch):
    monkeypatch.setenv("EDP_MCP_BACKEND", "stub")
    for var in ("EDP_ROLE", "EDP_HANDLE", "EDP_ROLE_SCOPE"):
        monkeypatch.delenv(var, raising=False)
    from edp_claude.mcp_server import build_mcp
    mcp = build_mcp(tmp_path)
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    assert tools, "empty registry"
    for name, t in tools.items():
        desc = t.description or ""
        assert "(backing=" not in desc, (
            f"{name}: generated placeholder survived Phase 4")
        assert desc.startswith("["), f"{name}: no role tag: {desc!r}"
        tag = desc[1:desc.index("]")]
        derived = sorted(r for r, ts in ROLE_TOOLSETS.items() if name in ts)
        if derived:
            assert tag == ",".join(derived), (
                f"{name}: tag {tag!r} != derived membership {derived}")
        else:
            assert tag == "unscoped", (name, tag)
    # spot-check the semantics reached the wire
    assert "fold" in tools["fold_decisions"].description
    assert tools["next_action"].description.startswith("[")
    assert "neuron" in tools["pool_spawn_planner"].description[:40]
