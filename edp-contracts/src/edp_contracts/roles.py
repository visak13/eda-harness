"""Roles that are people, never seats (owner m-da9a2ae62f, t-cd4712c855).

"ensure that human role is non-agent and our app complies with that. no way anyone can launch the
owner role." A role in NON_AGENT_ROLES is held by a human in the UI; no path (MCP spawn, REST, the
pool, the SPA, the workflow editor, the Help seat) may start a shell for it or register an agent
participant under it. Every layer calls `non_agent_refusal` so the refusal reads the same everywhere.
"""

from __future__ import annotations

#: The built-in human roles plus the generic "human": a workflow may not redefine any of them as an
#: agent role, and a seat is never spawned, resumed or registered for one.
NON_AGENT_ROLES: frozenset[str] = frozenset({"owner", "expert", "human"})

#: Role ids the owner removed (m-bba708e10e, m-da9a2ae62f, m-b0a7f9cda9). No workflow, participant, spawn or
#: SPA list may use them again; old database rows are migrated at open (edp8.store). This is the one
#: place the ids are spelled in code; v8/tests/test_no_retired_role.py keeps it that way.
RETIRED_ROLES: frozenset[str] = frozenset({"reviewer", "coordinator", "consultant"})


class NonAgentRole(ValueError):
    """Raised where a caller asks for a person's seat model or launch: a person has neither."""


def is_non_agent(role: object) -> bool:
    """True when `role` (a Role, a custom role id or a plain string) names a human role."""
    return str(getattr(role, "value", role) or "").strip().lower() in NON_AGENT_ROLES


def non_agent_refusal(role: object, handle: str | None = None) -> str | None:
    """The refusal message when a launch names a human role, or a handle of the form `<human role>.…`
    or `<human role>`; None when the launch may go on."""
    r = str(getattr(role, "value", role) or "").strip().lower()
    if r in NON_AGENT_ROLES:
        return f"the {r} role is a person, not an agent: no seat is ever spawned or launched as {r}"
    h = str(handle or "").lstrip("@").strip().lower()
    head = h.split(".", 1)[0]
    if head in NON_AGENT_ROLES:
        return f"handle {handle!r} names the {head} role, a person: no seat is ever launched under it"
    return None


def retired_refusal(role: object) -> str | None:
    """The refusal message when `role` is a removed role id; None otherwise."""
    r = str(getattr(role, "value", role) or "").strip().lower()
    if r in RETIRED_ROLES:
        return f"{r!r} is a removed role: no workflow, seat or participant may use it (qa checks stories)"
    return None


def refuse_non_agent(role: object, handle: str | None = None) -> None:
    """Raise NonAgentRole when `role` or `handle` names a person (see non_agent_refusal)."""
    why = non_agent_refusal(role, handle)
    if why:
        raise NonAgentRole(why)
