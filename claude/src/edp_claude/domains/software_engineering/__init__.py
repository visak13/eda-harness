"""software_engineering domain (DESIGN-v4 §5).

# TODO(claude-skeleton): capabilities.yaml + default_shapes.yaml are
# declared in the LLD but not load-bearing for WALK-1; add when a shape
# pipeline consumes them.
"""

from .. import Verdict


def kg_filter(fact: dict) -> Verdict:
    text = str(fact.get("text", "")).strip().lower()
    if not text:
        return Verdict(False, "empty fact")
    if any(
        chatter in text
        for chatter in ("let me", "i will now", "thinking about")
    ):
        return Verdict(False, "session chatter, not durable engineering fact")
    return Verdict(True, "durable engineering fact")


def success_criteria(plan) -> str | None:
    """SE plans: succeeded only if every action done AND every acceptance
    has a non-null actual (evidence). Distinguishes succeeded vs partial."""
    if not plan.actions:
        return None
    statuses = {a.status for a in plan.actions}
    if statuses & {"pending", "in_progress", "needs_review"}:
        return None  # not terminal yet
    all_done = statuses <= {"done", "skipped"}
    evidenced = all(
        a.acceptance.actual is not None
        for a in plan.actions
        if a.status == "done"
    )
    if all_done and evidenced:
        return "succeeded"
    if all_done and not evidenced:
        return "partial"  # done but unproven — the F4.c failure mode
    return "partial"
