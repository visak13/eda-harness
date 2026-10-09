"""The S14 pain inventory's routing (note-5df2381eb1, taken 2026-10-02), carried onto the board's pain rows.

Each entry says where one imported pain went: `fixed` (with the commit), `ticket` (the story that owns the
fix) or `duplicate` (of the root pain). `apply` writes it only onto a pain that was IMPORTED from a jsonl
store and is still open — a pain the board itself filed, or one already resolved, is never touched — and
a ticket that does not exist on this board is skipped, so a private board imports cleanly.
"""

from __future__ import annotations

from typing import Any

from .schemas import PainStatus

SOURCE = "note-5df2381eb1"
S3, S6, S9, S14, S15 = "s-a75c9807a8", "s-c1637c4854", "s-8ca20e8543", "s-f5192222b1", "s-6c2f5a8593"

# (pain id, status, ref, note)
DISPOSITIONS: tuple[tuple[str, str, str, str], ...] = (
    ("p-892b786f", "fixed", "4644c81", "S3: a dead checker is requeued; the record_status receipt names who checks"),
    ("p-3eba4926", "fixed", "4644c81", "S3: dec-49f1f6a911 fallback chain (requeued checker, then the architect)"),
    ("p-c3c5d460", "fixed", "4644c81", "S3: same chain as p-3eba4926"),
    ("p-a05affa0", "ticket", S14, "spawn session must carry the ticket_id passed to spawn"),
    ("p-77ab1bf1", "ticket", S15, "gate answer must surface the BoardError; epic carried to designed"),
    ("p-03acb4cd", "ticket", S6, "knowledge criteria are checked_by=sme: the sme verdicts its own lines"),
    ("p-5592b872", "ticket", S6, "a knowledge ticket no longer carries a designed epic to in_progress"),
    ("p-fc50ec61", "ticket", S6, "the ruleset tool previews an sme's proposed docs (tool removed in S17); resolve fixed once merged"),
    ("p-ff30576a", "ticket", S6, "a topic sme amends its own unapproved note; resolve fixed once merged"),
    ("p-a3ae2179", "ticket", S15, "artifact_upload refused from every pool seat (root)"),
    ("p-69a7583c", "duplicate", "p-a3ae2179", ""),
    ("p-312d8e99", "duplicate", "p-a3ae2179", ""),
    ("p-320be927", "duplicate", "p-a3ae2179", ""),
    ("p-5d1361d2", "duplicate", "p-a3ae2179", ""),
    ("p-787dec07", "ticket", S15, "GET /v1/harvest/cost returns HTTP 500"),
    ("p-c98f480b", "ticket", S15, "harvest_cost misses the claude-pool projects log root"),
    ("p-60fe5eac", "ticket", S15, "harvest_cost cannot find the Codex QA transcript (root)"),
    ("p-18e1cfb3", "duplicate", "p-60fe5eac", ""),
    ("p-59f06ccc", "ticket", S15, "topic_research truncates a source at 12000 chars, no continuation"),
    ("p-c4adfd0f", "ticket", S15, "topic_research ConnectError (skills.sh, GitHub)"),
    ("p-13172d54", "ticket", S9, "get_guide not_found on a hermetic board (root)"),
    ("p-3836c51f", "duplicate", "p-13172d54", ""),
    ("p-06664d53", "duplicate", "p-13172d54", ""),
    ("p-7fc6b2a2", "ticket", S9, "part 2: tool errors name accepted args and enums"),
)


def apply(board: Any) -> int:
    """Route every listed pain that is imported and still open; returns how many were routed."""
    store, n = board.store, 0
    for pid, status, ref, note in DISPOSITIONS:
        p = store.get("pain", pid)
        if p is None or p.status != PainStatus.open or not str(p.source).startswith("import:"):
            continue
        if status == "ticket":
            if store.get("ticket", ref) is None:
                continue
            p.status, p.ticket_ref = PainStatus.ticket, ref
        elif status == "fixed":
            p.status, p.fixed_commit = PainStatus.fixed, ref
        elif status == "duplicate":
            if store.get("pain", ref) is None:
                continue
            p.status, p.dup_of = PainStatus.duplicate, ref
        else:
            continue
        p.resolved_by, p.resolution_note = f"board:{SOURCE}", note
        p.resolved_at = ""
        store.put("pain", p)
        n += 1
    return n
