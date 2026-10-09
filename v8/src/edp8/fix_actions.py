"""The closed set of S19 fix actions (fixes.py), in a module without board imports so the MCP tool schema can
publish the same discriminated union the board validates (audit R3, report-8dbe7c91c9: propose_fix advertised
`action` as any object and refused bad nested fields only downstream)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

from .schemas import Gate

#: an id or handle that goes into a route path: no slash, dot-dot, query or escape can steer the call elsewhere
_ID = r"^@?[A-Za-z0-9][A-Za-z0-9_\-]*(\.[A-Za-z0-9_\-]+)*$"


class _A(BaseModel):
    model_config = {"extra": "forbid"}


class ServiceAction(_A):
    kind: Literal["service.restart", "service.start", "service.stop"]
    service: Literal["board", "broker", "pool", "mcp", "bridge"]
    force: bool = False        # pool stop/restart with live seats: take them offline
    keep_seats: bool = False   # pool: restart the process only, seats are re-adopted


class PoolLimitsAction(_A):
    kind: Literal["pool.set_limits"]
    max_total_shells: int | None = Field(default=None, ge=1)
    max_live_shells: int | None = Field(default=None, ge=1)
    classes: dict[Literal["builder", "planner"], Annotated[int, Field(ge=1)]] | None = None
    role_caps: dict[str, Annotated[int, Field(ge=1)]] | None = None


class GateOpenAction(_A):
    kind: Literal["gate.open"]
    ticket_id: str = Field(pattern=_ID, max_length=80)
    gate: Gate
    note: str = Field(min_length=1, max_length=2000)


class GateAnswerAction(_A):
    kind: Literal["gate.answer"]
    ticket_id: str = Field(pattern=_ID, max_length=80)
    gate: Gate
    answer: str = Field(min_length=1, max_length=2000)


class RotateTokenAction(_A):
    kind: Literal["teammate.rotate_token"]
    handle: str = Field(pattern=_ID, max_length=80)


class RevokeAgentTokenAction(_A):
    kind: Literal["agent_token.revoke"]
    handle: str = Field(pattern=_ID, max_length=80)


Action = Annotated[ServiceAction | PoolLimitsAction | GateOpenAction | GateAnswerAction | RotateTokenAction
                   | RevokeAgentTokenAction, Field(discriminator="kind")]
_ACTION = TypeAdapter(Action)
KINDS = ("service.restart", "service.start", "service.stop", "pool.set_limits", "gate.open", "gate.answer",
         "teammate.rotate_token", "agent_token.revoke")


def _fields_by_kind() -> str:
    parts = []
    for m in (ServiceAction, PoolLimitsAction, GateOpenAction, GateAnswerAction, RotateTokenAction,
              RevokeAgentTokenAction):
        kinds = "|".join(m.model_fields["kind"].annotation.__args__)
        fields = [n + ("" if f.is_required() else "?") for n, f in m.model_fields.items() if n != "kind"]
        parts.append(f"{kinds} {{{', '.join(fields)}}}")
    return "; ".join(parts)

