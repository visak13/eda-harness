"""Shared bounds / pagination primitives — ONE place (coding-standard #16).

The read/list branches (recipe / action / step / outcome / message / list)
all need the same two things: a count-first way to return a bounded slice of
a sequence, and a defensive token-budget guard so a payload can't blow past
what a caller can hold. Rather than re-deriving that shape per branch, they
share the helpers here.

The shape is modeled on the repo's EXISTING count-first idioms, not a new
invention:

- ``check_inbox`` (see ``_tools.py``) resumes from a PERSISTED next-position
  cursor instead of re-delivering everything — so ``windowed`` returns a
  ``cursor`` that is the next offset to resume from (``None`` at the end).
- ``read_worklog`` exposes a ``tail`` / ``since`` window over a longer log —
  so ``windowed`` always reports the FULL ``count`` alongside the returned
  slice, and how many were ``elided``.

This module lands the reusable primitives ONLY; no tool behavior changes
here (that is a2/a3). Deterministic, no LLM (principle-6).
"""

import json

# Default page size for a windowed slice, and the approximate-token budget a
# bounded payload must stay under. Named constants so the window size and the
# budget live in ONE place (coding-standard #16) instead of scattered inline.
WINDOW = 40
BUDGET = 9000

# Default byte budget for the inbox reader. check_inbox's per-message budget
# (full bodies oldest-first, summaries past the line) is now the DEFAULT rather
# than an opt-in (s17 a7) — a fresh/compacted shell polling a large retained
# inbox no longer dumps every full body. ~4 bytes/token over BUDGET, matching
# the approx_tokens ratio so the byte ceiling tracks the token budget.
INBOX_MAX_BYTES = BUDGET * 4


class BoundsExceeded(ValueError):
    """Raised by :func:`assert_bounded` when a payload exceeds its budget.

    A ``ValueError`` subclass so a caller that only wants fail-fast behavior
    can catch the standard type, while a caller that wants to special-case the
    budget breach can catch this precise one.
    """


def approx_tokens(obj) -> int:
    """Rough token estimate for a JSON-serializable object (~4 chars/token).

    Promoted verbatim from the closure formerly defined inside
    ``get_recipe_digest`` so every bounded branch shares one estimator. The
    ~4-chars/token ratio is deliberately conservative — it is a guardrail
    floor, not an exact tokenizer count.
    """
    return len(json.dumps(obj, default=str)) // 4


def windowed(seq, offset=0, limit=WINDOW):
    """Return a count-first window over ``seq``.

    The bounded slice is returned ALONGSIDE the full ``count`` so a reader
    always learns how many items exist even when only ``limit`` are handed
    back — the same count-first contract as ``check_inbox`` / ``read_worklog``.

    Keys:

    - ``items``  — the bounded slice (``seq[offset:offset+limit]``).
    - ``count``  — the FULL length of ``seq`` (before windowing).
    - ``offset`` — the clamped start offset actually used.
    - ``cursor`` — the next offset to resume from, or ``None`` when the window
      already reaches the end (mirrors check_inbox's persisted next-offset
      cursor).
    - ``elided`` — how many items were NOT returned (``count - len(items)``).

    ``offset`` / ``limit`` are clamped non-negative at the boundary
    (coding-standard #14) so out-of-range paging is well-defined — an offset
    past the end yields empty ``items`` and ``cursor=None`` rather than raising.
    """
    items_all = list(seq)
    count = len(items_all)
    offset = max(0, int(offset))
    limit = max(0, int(limit))
    window = items_all[offset:offset + limit]
    next_offset = offset + len(window)
    cursor = next_offset if next_offset < count else None
    return {
        "items": window,
        "count": count,
        "offset": offset,
        "cursor": cursor,
        "elided": count - len(window),
    }


def budget_report(payload, budget=BUDGET) -> dict:
    """Non-truncating budget signal for CONTENT / GROUNDING-DELIVERY outputs.

    #18 has two output classes (s17 a7, neuron ruling). A LIST output (one row
    per decision/action/event/message) is bounded by :func:`windowed` — a fixed
    window + cursor, pull-on-demand. A CONTENT/GROUNDING output — a compiled
    specialist doc, an assembled ruleset, a spec dump — is different: the
    consumer applies it IN FULL and there is NO deferred pull target (the doc IS
    the full-fidelity artifact), so truncating it at delivery would silently
    drop ``[required]`` rules and break the specialist worker. Such payloads
    therefore MUST NOT be windowed; instead they carry this NON-truncating
    signal so a ballooned payload is CAUGHT in review (and bounded at AUTHOR
    time, e.g. ``write_specialist_doc``) rather than blowing a caller's context
    unnoticed.

    Returns ``{approx_tokens, budget, oversize}`` — ``oversize`` is True when
    the payload exceeds ``budget``. It never raises and never drops content;
    it only measures.
    """
    size = approx_tokens(payload)
    return {"approx_tokens": size, "budget": budget, "oversize": size > budget}


def assert_bounded(payload, budget=BUDGET):
    """Guard a payload against the token ``budget``.

    Raises :class:`BoundsExceeded` when ``approx_tokens(payload)`` exceeds
    ``budget`` (this is the check the guardrail tests assert on). On success
    returns the measured approx-token size so a caller can log how close to
    the ceiling it ran.
    """
    size = approx_tokens(payload)
    if size > budget:
        raise BoundsExceeded(
            f"payload approx_tokens={size} exceeds budget={budget}")
    return size
