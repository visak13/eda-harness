"""Fail-closed constraint guards — DESIGN-v6 §W2 leg 3.

`check_constraints(recipe, payload_kind, text)` executes every ACTIVE
constraint whose `applies_to` includes `payload_kind` against `text` and
returns the list of `Violation`s (empty when clean). This is the executable
teeth W1 gave a recorded decision/ban: a `Decision` / `RejectedOption` that
carries a populated `constraint` becomes *enforced* instead of merely
*remembered* — "a ban becomes checkable, not remembered" (DESIGN-v6 §W1).

DETERMINISTIC ONLY (principle 6): a pure regex/substring test, NEVER an LLM
inside a tool. Legacy prose decisions carry `constraint=None`, so they are a
structural no-op here (advisory continuity) — only typed constraints bite.

This module is READ-ONLY over the recipe. Per d24 it adds NO length/format
cap and NO pydantic schema/hydration validator — any such cap lives on the
tool WRITE PATH only. Nothing here touches recipe load/save, so a legacy
recipe (0e7ca8 + the 38 lazy-hydrate dirs) is unaffected.

Callers (all in `tools/_tools.py`):
- `RecordActionStatus`: a completion whose evidence matches an active
  `applies_to=["action_result"]` constraint is REFUSED (`_precondition`)
  naming the decision id + message — the worker learns WHY at the moment of
  violation (fail closed).
- `PoolSpawnWorker`: a stamped spec whose compiled doc matches an active
  `applies_to=["spec_doc"]` constraint REFUSES the spawn — a poisoned spec
  can never reach another worker (d50 "fix it at the source").
- `emit_recipe_event` / `broker_send`: an `applies_to=["llm_payload"]` hit is
  a WARN-ONLY stamp — comms are never blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The three artifact streams W2/W9 guard. `applies_to` is a free list[str]
# on the schema (forward-compatible), so an unknown kind simply never
# matches — these are the named set the wired seams pass.
ACTION_RESULT = "action_result"
SPEC_DOC = "spec_doc"
LLM_PAYLOAD = "llm_payload"


@dataclass(frozen=True)
class Violation:
    """One constraint hit against a scanned artifact.

    `decision_id` names the recorded decision/ban carrying the constraint so
    a refusal can cite WHY; `message` is the neuron-authored explanation;
    `source` is 'decision' | 'rejected_option'; `payload_kind` echoes which
    artifact stream hit."""

    decision_id: str
    message: str
    match: str
    match_kind: str
    payload_kind: str
    source: str


def _hit(match: str, match_kind: str, text: str) -> bool:
    """Deterministic single-constraint test against `text`.

    A malformed regex can never match and must NOT crash the guard — it is
    treated as a no-hit (the write path validates the pattern; this is
    defence in depth). An unknown `match_kind` is forward-compatible: no hit.
    """
    if not text:
        return False
    if match_kind == "substring":
        return match in text
    if match_kind == "regex":
        try:
            return re.search(match, text) is not None
        except re.error:
            # Un-compilable stored pattern: cannot evaluate → NO-HIT rather
            # than raising, so a bad constraint never breaks the tool it
            # guards. record_context validates the pattern at WRITE time.
            return False
    return False


def check_constraints(recipe, payload_kind: str, text: str) -> list[Violation]:
    """Run every ACTIVE constraint whose `applies_to` includes `payload_kind`
    against `text`; return the violations (empty == clean).

    Scanned sources: `recipe.context.decisions` (ACTIVE only — a superseded
    decision has left the active set and must not still bite) and
    `recipe.context.rejected_options` (a ban). A record with
    `constraint=None` — every legacy prose decision — is skipped (no teeth).
    Defensive to a None/shape-light recipe so a caller on the comms path
    never has to guard the call itself.
    """
    violations: list[Violation] = []
    if recipe is None:
        return violations
    ctx = getattr(recipe, "context", None)
    if ctx is None:
        return violations
    body = text or ""

    def _scan(records, source: str) -> None:
        for rec in records or []:
            c = getattr(rec, "constraint", None)
            if c is None:
                continue
            # Active-only. Decisions carry a status; a RejectedOption has no
            # status field (a ban is always active) → default "active".
            if getattr(rec, "status", "active") != "active":
                continue
            if payload_kind not in (c.applies_to or []):
                continue
            if _hit(c.match, c.match_kind, body):
                violations.append(Violation(
                    decision_id=getattr(rec, "id", "?"),
                    message=c.message or "",
                    match=c.match,
                    match_kind=c.match_kind,
                    payload_kind=payload_kind,
                    source=source,
                ))

    _scan(getattr(ctx, "decisions", None), "decision")
    _scan(getattr(ctx, "rejected_options", None), "rejected_option")
    return violations


def describe(violations: list[Violation]) -> str:
    """Render violations for a refusal/warning message — the decision id, the
    neuron's message, and the matched pattern (so a reader can see WHY and
    fix the source)."""
    parts = []
    for v in violations:
        parts.append(
            f"decision {v.decision_id}: "
            f"{v.message or '(no message recorded)'} "
            f"[{v.match_kind} match {v.match!r}]"
        )
    return "; ".join(parts)
