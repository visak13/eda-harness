"""CHANNELS (topology 2026-07-21) — pure derivation, no I/O.

The channel graph IS the existing inbox graph, promoted:

    #team-<step>  = the plan inbox        (plan_id, e.g. rec-s3)
    #leads        = the recipe inbox      (recipe_id)
    #product      = <recipe_id>-product   (user + PM)
    #experts      = "experts"             (PM, leads, SMEs)

Membership is durable in the broker's channel registry (PUT
/v1/channels/<name>); this module derives names and default membership
from handles, and implements the `for:` delivery filter. Delivery
semantics (backward compatible by construction):

    * a message with body["for"] is FOR that handle (or "@all");
    * a message WITHOUT body["for"] is for the channel's OWNER — exactly
      today's behavior, so every existing flow is unchanged;
    * non-owner members receive only messages addressed to them.
"""

from __future__ import annotations

EXPERTS_CHANNEL = "experts"


def team_channel(plan_id: str) -> str:
    return plan_id


def leads_channel(recipe_id: str) -> str:
    return recipe_id


def product_channel(recipe_id: str) -> str:
    return f"{recipe_id}-product"


def plan_of(handle: str) -> str | None:
    """`<plan_id>:<action_id>` → plan_id; else None."""
    return handle.split(":", 1)[0] if ":" in handle else None


def channel_owner(channel: str) -> str:
    """The historical single reader whose unaddressed mail this is:
    the channel name itself (plan inbox → planner-as-plan-reader,
    recipe inbox → neuron). Pure convention, needs no lookup."""
    return channel


def member_channels(handle: str, role: str) -> list[str]:
    """Default channel memberships derived from a handle. The broker
    registry is authoritative once written; this is the seed."""
    if role in ("worker", "reviewer"):
        p = plan_of(handle)
        return [team_channel(p)] if p else []
    if role == "planner":
        # `<recipe>:<step>` — lead sits in #leads and its own #team.
        if ":" in handle:
            recipe, step = handle.rsplit(":", 1)
            return [leads_channel(recipe), f"{recipe}-{step}"]
        return []
    if role in ("specialist", "consult"):
        return [EXPERTS_CHANNEL]
    if role == "neuron":
        return []          # the neuron derives its channels per recipe
    return []


def addressed_to(body: dict, me: str, channel: str) -> bool:
    """The `for:` delivery filter. Owner gets unaddressed mail (today's
    semantics); everyone gets their own mentions and @all."""
    target = (body or {}).get("for")
    if target in (me, "@all"):
        return True
    if target is None:
        return me == channel_owner(channel)
    return False
