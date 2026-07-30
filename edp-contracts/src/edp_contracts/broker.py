"""The communication contract — one envelope for all inter-shell traffic.

DESIGN-v4 §13.3: no component invents its own message shape. ``kind`` must
be registered (registry-not-enum: extensible without editing this file, but
an unregistered kind fails at message-construction time so the protocol
cannot silently fork).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

# kind -> human docstring. Single source of truth for the protocol surface.
_REGISTRY: dict[str, str] = {}


def register_kind(kind: str, doc: str) -> None:
    """Register a broker message kind.

    Idempotent for an identical (kind, doc). Re-registering a kind with a
    *different* doc raises — that would mean two components disagree on what
    the kind means, which is exactly the silent-fork this guards against.
    """
    if not kind or not doc:
        raise ValueError("register_kind requires non-empty kind and doc")
    existing = _REGISTRY.get(kind)
    if existing is not None and existing != doc:
        raise ValueError(
            f"BrokerKind {kind!r} already registered with a different doc; "
            f"refusing conflicting redefinition"
        )
    _REGISTRY[kind] = doc


def is_registered(kind: str) -> bool:
    return kind in _REGISTRY


def registered_kinds() -> dict[str, str]:
    """A copy of the registry (for tooling/tests/introspection)."""
    return dict(_REGISTRY)


#: Core protocol kinds, registered at import time.
CORE_KINDS: dict[str, str] = {
    "spawned": "pool spawned a shell for a handle",
    "ready": "a spawned shell finished init-ack",
    "done": "a unit of work completed normally",
    "crashed": "pool detected a shell crash",
    "question": "child asks caller for a decision",
    "answer": "caller answers a child's question",
    "steer": "caller sends mid-task redirection",
    "plan_closed": "a plan reached terminal_status",
    "step_done": "a recipe step completed",
    "consult": "host asks a skill/helper for a verdict",
    "verdict": "a skill/helper returns a verdict",
    # team-architecture Phase 2 (2026-05-21) — upward notifications:
    "progress": "child reports forward progress to caller (one-way)",
    "observation": "child surfaces a discovery / unexpected finding "
    "(one-way, no decision required)",
    "alert": "child surfaces an unexpected condition that may need attention",
    # DESIGN-v6 W2/a5 (grounding-kind gap): a child's upward assumption-surface
    # (notify_above) and the planner's courtesy-CC both cross the shell->BROKER
    # process boundary, and the broker validates against CORE_KINDS only. These
    # were previously registered in-process (edp_claude/tools/_tools.py) so the
    # MCP process accepted them but the SEPARATE broker process rejected them as
    # unregistered — so they MUST be CORE kinds, registered in every process.
    "grounding": "pre-work assumption surface: a child states the load-bearing "
    "assumptions it is proceeding with; parent steers ONLY if one is wrong "
    "(timeout-and-proceed, never a hard block)",
    "fyi": "courtesy copy — informational, no reply expected (e.g. the "
    "planner's CC when a worker routes a decision-class question straight to "
    "the neuron)",
    # DESIGN-v6 W12 (browser panel, inline plan review): the panel renders a
    # brief, the user selects text and attaches comments, and ALL comments are
    # submitted as ONE message — the PR-review interaction the CLI lacks.
    # body = {"brief": <path/id>, "comments": [{"anchor_quote", "comment"}, …]}
    # It MUST be registered here, in edp-contracts, and not in-process: the
    # broker validates every inbound message against this registry in its OWN
    # process and fails CLOSED on an unregistered kind, so a kind registered
    # only inside the MCP server is accepted there and rejected at the broker.
    # That is the exact bug the `grounding`/`fyi` entries above were added to
    # fix; `review_comments` would have reproduced it.
    "review_comments": "a batch of anchored review comments on a brief, "
    "submitted together from the W12 panel (body: {brief, comments: "
    "[{anchor_quote, comment}]})",
    "steer_ack": "receiver restates a steer in its own terms ({restatement, "
    "steer_msg_id}); the sender verifies the restatement matches its intent "
    "— the general defense against a directive being absorbed unread.",
}

for _k, _doc in CORE_KINDS.items():
    register_kind(_k, _doc)


class BrokerMessage(BaseModel):
    """The one envelope for every inter-shell message.

    ``from`` is a Python keyword, so the field is ``from_`` with a wire
    alias of ``from``. Populate/serialize using the alias.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    msg_id: str = Field(min_length=1)  # uuid4 str
    ts: datetime  # tz-aware UTC
    from_: str = Field(alias="from", min_length=1)
    to: str = Field(min_length=1)  # role | relative-ref | session id
    kind: str
    body: dict[str, Any] = Field(default_factory=dict)
    corr_id: str | None = None

    @model_validator(mode="after")
    def _kind_registered(self) -> "BrokerMessage":
        if self.kind not in _REGISTRY:
            raise ValueError(
                f"unregistered BrokerKind {self.kind!r}; call "
                f"register_kind({self.kind!r}, <doc>) before sending"
            )
        return self
