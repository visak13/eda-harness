"""Actor attribution resolved IN CODE — the single source of truth for
*who* performed a state-mutating store write (W15, DESIGN-v6).

principle-6 (no LLM in a tool): the attribution is READ from the process
environment the pool stamps onto every spawned shell (`EDP_ROLE` /
`EDP_HANDLE`) — it is never supplied by a caller / model, so it cannot be
spoofed by a payload. This module is the ONE place that resolution lives:
spec_store stamps it today, and the recipe/plan stores reuse `actor()`
verbatim (a4) so attribution is identical across every store.
"""

import os

# The env vars the pool stamps onto a spawned shell (see /worker Step 1).
_ROLE_ENV = "EDP_ROLE"
_HANDLE_ENV = "EDP_HANDLE"
_UNKNOWN = "unknown"


def is_spawned() -> bool:
    """True when this shell was stamped by the pool (`EDP_HANDLE` present).

    F37#5 (2026-08-18): the trust pivot for role-less shells. The pool stamps
    BOTH vars on every spawn, so a shell with a handle but no role is a
    spawn-env bug (or a cleared var), never the operator console — role
    guards must treat it as UNTRUSTED, not exempt. The operator's foreground
    base shell has neither var and stays fully trusted.
    """
    return bool(os.environ.get(_HANDLE_ENV, "").strip())


def trusted_as(role: str) -> bool:
    """True when the calling shell may act as `role` for a role-gated write.

    - `EDP_ROLE` set: exact match only.
    - `EDP_ROLE` absent: trusted ONLY for a non-spawned shell (the operator
      console / tests). A spawned shell missing its role fails CLOSED
      (F37#5 — the old ``if role and role != x`` guards skipped when the
      role was empty, so clearing the var was privilege escalation).
    """
    got = os.environ.get(_ROLE_ENV, "").strip()
    if got:
        return got == role
    return not is_spawned()


def actor() -> dict:
    """Resolve the acting shell's attribution from the environment.

    Returns ``{"role", "handle"}`` — both non-empty (``"unknown"`` when the
    env var is unset/blank, e.g. the neuron shell has no `EDP_HANDLE`), so a
    worklog record always carries a concrete `by`. No LLM value ever reaches
    here (principle-6): the caller passes nothing.
    """
    role = os.environ.get(_ROLE_ENV, "").strip() or _UNKNOWN
    handle = os.environ.get(_HANDLE_ENV, "").strip() or _UNKNOWN
    return {"role": role, "handle": handle}
