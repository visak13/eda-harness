"""Advice: a rule that used to refuse now says so in the reply and lets the call go ahead.

design-63db8a7d42 item I (owner m-d611346eca, m-f65239bfa7): the board refuses only state transitions, who may change
status or approve, safety and security, evidence_ref, the doc version check, the shell cap and "no one approves their
own work". Every other rule calls `advise(...)`; the service puts the advice in the reply's `hint`. A silent rewrite of
an agent's input (an ignored field, a derived value) calls it too, so the reply names the change.

The list is per request context (a FastAPI handler runs in its own copied context), drained when the reply is built.
"""
from __future__ import annotations

from contextvars import ContextVar

MAX_LINES = 12  # a context that never builds a reply (a background thread) cannot grow without bound
_ADVICE: ContextVar[list[str] | None] = ContextVar("edp8_advice", default=None)


def advise(message: str) -> None:
    """Add one line of advice to the current request's reply (duplicates collapse)."""
    cur = _ADVICE.get()
    if cur is None:
        cur = []
        _ADVICE.set(cur)
    if message not in cur and len(cur) < MAX_LINES:
        cur.append(message)


def take() -> list[str]:
    """Drain the advice collected so far (the reply builder calls this once per reply)."""
    cur = _ADVICE.get() or []
    _ADVICE.set(None)
    return cur
