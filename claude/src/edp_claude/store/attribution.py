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
