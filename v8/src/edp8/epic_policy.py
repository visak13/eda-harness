"""Epic policy tags (e0cec S6): `sme:on|off` (default off) and `project:<key>`.

SMEs are opt-in per epic: while `sme:on` is absent a `spawn(role=sme)` on that epic is refused by one board
rule that every spawn path calls (REST spawn, the MCP spawn tool's seat-token step, the board's own checker
pairing). A Library topic is not an epic; its resident sme is the owner's and is never gated here.
"""

from __future__ import annotations

from typing import Any

SME_TAG = "sme:"
SME_VALUES = ("on", "off")
POLICY_PREFIXES = (SME_TAG, "project:")


def sme_on(tags: list[str] | None) -> bool:
    """True when the tags carry `sme:on`; the last `sme:` tag wins, none = off."""
    state = "off"
    for t in tags or []:
        if t.startswith(SME_TAG):
            state = t[len(SME_TAG):].strip().lower()
    return state == "on"


def tag_problem(tags: list[str] | None) -> str | None:
    """Why a policy tag is malformed, else None: `sme:` takes on|off, `project:` needs a key."""
    for t in tags or []:
        if t.startswith(SME_TAG) and t[len(SME_TAG):].strip().lower() not in SME_VALUES:
            return f"{t!r}: sme takes on or off (sme:on, sme:off)"
        if t.startswith("project:") and not t[len("project:"):].strip():
            return f"{t!r}: project needs a key (project:<key>)"
    return None


def sme_refusal(role: str | None, epic: Any | None) -> str | None:
    """The refusal text for spawning an sme on `epic`, else None. `epic` None or a topic (the Library's own
    resident sme) is never gated."""
    if str(role or "") != "sme" or epic is None:
        return None
    if str(getattr(epic, "kind", "")) == "topic":
        return None
    if sme_on(list(getattr(epic, "tags", None) or [])):
        return None
    return (f"SMEs are off for {epic.id}: its knowledge work is the architect's, and a spawn(role=sme) is "
            "refused until the epic's SMEs switch is on")
