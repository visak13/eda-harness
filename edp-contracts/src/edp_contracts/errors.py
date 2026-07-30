"""Stable machine error codes — the ``code`` field of :class:`ToolError`.

This module is the canonical registry. A new code is added to
:class:`ErrorCode` with a one-line meaning and nowhere else. Adding a code
is a minor (additive) version bump (LLD §8).

S3b refactor decision: codes are a :class:`StrEnum`, not loose ``str``
constants. It earns its keep — type-safe references (``ErrorCode.POOL_…``),
``list(ErrorCode)`` for tests, membership checks — while remaining
``str``-compatible so ``ToolError.code: str`` still accepts codes emitted by
microservices we don't know about.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    # ── local tool / validation ──────────────────────────────────────────
    TOOL_INPUT_INVALID = "tool_input_invalid"  # input failed InputModel
    TOOL_PRECONDITION = "tool_precondition"  # "do X first" instruction error

    # ── service ──────────────────────────────────────────────────────────
    UNHANDLED_EXCEPTION = "unhandled_exception"  # mount() catch-all envelope

    # ── pool ──────────────────────────────────────────────────────────────
    POOL_CAPACITY_EXCEEDED = "pool_capacity_exceeded"  # max workers (=3)
    POOL_SPAWN_FAILED = "pool_spawn_failed"  # shell failed to start
    POOL_UNKNOWN_HANDLE = "pool_unknown_handle"  # no such handle

    # ── broker ────────────────────────────────────────────────────────────
    BROKER_UNREGISTERED_KIND = "broker_unregistered_kind"
    BROKER_NO_ROUTE = "broker_no_route"  # no recipient resolves for `to`

    # ── fsm ───────────────────────────────────────────────────────────────
    FSM_UNDECIDABLE = "fsm_undecidable"  # deterministic + LLM both abstained

    # ── envelope integrity ────────────────────────────────────────────────
    # RAISED as an exception, never returned as a ToolError.
    ENVELOPE_VIOLATION = "envelope_violation"


#: Retryable-by-default codes. The LLM is still the deciding actor; this
#: only seeds the ``retryable`` flag in :meth:`Tool.propagate`.
RETRYABLE_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.POOL_CAPACITY_EXCEEDED,
    }
)

#: Every code, for validation/tests.
ALL_CODES: frozenset[ErrorCode] = frozenset(ErrorCode)


class EnvelopeViolation(Exception):
    """A microservice returned an error not in the standard envelope.

    Raised (never returned) by :meth:`edp_contracts.tool.Tool.from_upstream`
    so a non-conforming microservice fails loudly at the contract boundary
    instead of having its malformed error silently re-wrapped.
    """
