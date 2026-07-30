"""Generic domain — conservative fallback (DESIGN-v4 §5)."""

from .. import Verdict


def kg_filter(fact: dict) -> Verdict:
    # Conservative: reject unless explicitly marked durable.
    if fact.get("durable") is True:
        return Verdict(True, "explicitly marked durable")
    return Verdict(False, "generic domain rejects by default (not durable)")


def success_criteria(plan) -> str | None:
    """Return terminal_status, or None if not yet terminal."""
    if not plan.actions:
        return None
    statuses = {a.status for a in plan.actions}
    if statuses <= {"done", "skipped"}:
        return "succeeded"
    if "failed" in statuses and not (
        statuses & {"pending", "in_progress", "needs_review"}
    ):
        return "partial"
    return None
