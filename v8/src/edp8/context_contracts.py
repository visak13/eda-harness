"""Discovery shapes for context reads; opaque cursors are caller state, not credentials."""
from typing import Any
from pydantic import BaseModel, Field


class ContextChange(BaseModel):
    event_id: str
    seq: int
    kind: str
    object_id: str
    object_type: str
    action: str
    read_ref: dict[str, Any] | None = None
    text: str | None = None
    truncated: bool = False
    version: int | None = None


class ContextSnapshot(BaseModel):
    participant: dict[str, Any]
    tickets: list[dict[str, Any]]
    asks_for_me: list[dict[str, Any]]
    hint: str
    cursor: str = Field(description='Opaque signed caller-owned baseline; bound to participant/scope/stream. Not a credential.')


class ContextDelta(BaseModel):
    changed: bool
    next_cursor: str = Field(description='Save only after consumption. Replay allowed; deduplicate event_id/seq.')
    has_more: bool = Field(description='Continue using next_cursor and the same scope; frozen through-watermark.')
    changes: list[ContextChange] = Field(default_factory=list)
    asks_changed: dict[str, Any] | None = None
    orientation_changed: dict[str, Any] | None = Field(default=None, description='Non-thread orientation changed, including legacy writes without events; follow read_ref')


CONTEXT_TYPES = {c.__name__: c for c in (ContextSnapshot, ContextDelta, ContextChange)}
