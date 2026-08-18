"""F1 (2026-08-17) — role-registration drift gate.

Every registered tool must be scoped to >=1 role in ROLE_TOOLSETS or be
consciously named in UNSCOPED_OK. A NEW tool added to ALL_TOOL_CLASSES that
nobody scopes fails here — it can never silently fall outside the role map
and become reachable only by role-less shells (or, worse, believed scoped
when it is not).

Also pins the inverse: every name a role set grants must resolve to a
registered tool (build_mcp refuses to build on this drift at runtime; this
makes it a static CI failure instead of a spawn-time crash).
"""

from edp_claude.tools._tools import ALL_TOOL_CLASSES
from edp_claude.tools.roles import ROLE_TOOLSETS, UNSCOPED_OK


def test_every_registered_tool_is_scoped_or_consciously_unscoped():
    registered = {cls.name for cls in ALL_TOOL_CLASSES}
    scoped = set().union(*ROLE_TOOLSETS.values())
    drift = registered - scoped - UNSCOPED_OK
    assert not drift, (
        f"tool(s) {sorted(drift)} are registered but appear in NO role "
        "surface and are not named in roles.UNSCOPED_OK — scope each to its "
        "owning role(s) in ROLE_TOOLSETS, or add it to UNSCOPED_OK with a "
        "comment saying why it is deliberately role-less.")


def test_every_scoped_name_is_a_registered_tool():
    registered = {cls.name for cls in ALL_TOOL_CLASSES}
    for role, names in ROLE_TOOLSETS.items():
        missing = set(names) - registered
        assert not missing, (
            f"role {role!r} grants {sorted(missing)} which are not "
            "registered tools — remove them or register the classes.")


def test_unscoped_ok_names_are_real_and_truly_unscoped():
    registered = {cls.name for cls in ALL_TOOL_CLASSES}
    scoped = set().union(*ROLE_TOOLSETS.values())
    assert UNSCOPED_OK <= registered, (
        f"UNSCOPED_OK names unregistered tools: "
        f"{sorted(UNSCOPED_OK - registered)}")
    overlap = UNSCOPED_OK & scoped
    assert not overlap, (
        f"{sorted(overlap)} are in UNSCOPED_OK but ALSO scoped to a role — "
        "remove them from UNSCOPED_OK (the list is for role-less tools only).")
