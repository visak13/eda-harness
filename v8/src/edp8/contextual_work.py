"""Direct-ticket history and linked records; never silently substitute an epic subtree."""
from typing import Literal
from .board import Board
from .schemas import EventKind, MessageKind, TicketStatus

HistoryCategory = Literal["all", "conversation", "decisions", "status", "documents", "activity"]
CATEGORIES = {
    "conversation": {EventKind.message_sent},
    "decisions": {EventKind.gate_opened, EventKind.gate_answered, EventKind.gate_closed, EventKind.criterion_checked, EventKind.design_reviewed},
    "status": {EventKind.status_changed, EventKind.status_recorded, EventKind.assigned, EventKind.ticket_updated},
    "documents": {EventKind.doc_updated},
}

def contextual_work(board: Board, ticket_id: str, category: HistoryCategory = "all") -> dict:
    ticket = board.ticket(ticket_id)
    links = board.store.query("link", {"from_id": ticket_id}, limit=100000)
    records = []
    for link in links:
        doc = board.store.get("doc", link.to_id)
        art = board.store.get("artifact", link.to_id)
        record = doc or art
        if record is None or getattr(record, "staged", False):
            continue
        group = {"designed_by": "Design", "uses_strategy": "References", "uses_domain": "References",
                 "evidence_for": "Evidence", "produced": "Deliverables"}.get(link.relation.value, "Other")
        records.append({"record": record.model_dump(mode="json"), "group": group, "relation": link.relation,
                        "type": "doc" if doc else "artifact"})
    if ticket.design_ref and not any(r["record"]["id"] == ticket.design_ref and r["group"] == "Design" for r in records):
        records.insert(0, {"record": board.doc(ticket.design_ref).model_dump(mode="json"), "group": "Design", "relation": "design_ref", "type": "doc"})
    for criterion in board.criteria(ticket_id):
        if criterion.evidence_ref and not any(r["record"]["id"] == criterion.evidence_ref and r["group"] == "Evidence" for r in records):
            records.append({"record": board.doc(criterion.evidence_ref).model_dump(mode="json"), "group": "Evidence", "relation": "criterion", "type": "doc"})
    events = board.store.query("event", {"subject_id": ticket_id}, limit=100000)
    doc_ids = {r["record"]["id"] for r in records if r["type"] == "doc"}
    for doc_id in doc_ids:
        events.extend(board.store.query("event", {"subject_id": doc_id, "kind": EventKind.doc_updated}, limit=100000))
    if category in CATEGORIES:
        events = [e for e in events if e.kind in CATEGORIES[category]]
    elif category == "activity":
        named = set().union(*CATEGORIES.values())
        events = [e for e in events if e.kind not in named]
    events.sort(key=lambda e: e.created_at, reverse=True)
    # Source-wide outstanding directed asks, not an invented wake/recipient count.
    # Match inbox answer/lifecycle semantics, without its per-recipient 100-row cap.
    asks = []
    if ticket.status != TicketStatus.dropped and board.epic_of(ticket).status not in {TicketStatus.done, TicketStatus.partial, TicketStatus.dropped}:
        for message in board.store.query("message", {"ticket_id": ticket_id, "kind": [MessageKind.question, MessageKind.steer]}, limit=100000):
            if message.to and not board.ask_resolved(message):  # closed-seat asks and addressee replies resolve (c-8f893cc2e8)
                asks.append({"id": message.id, "kind": message.kind.value, "to": message.to,
                             # S-UI: the header badge lists them oldest first and jumps to each
                             "by": message.created_by, "at": message.created_at.isoformat(),
                             "text": message.text[:160]})
        asks.sort(key=lambda m: m["at"])
    return {"ticket_id": ticket_id, "title": ticket.title, "kind": ticket.kind, "status": ticket.status,
            "owner": board.epic_owner(ticket_id), "requester": ticket.created_by, "assignee": ticket.assignee,
            "blockers": [{"id": t.id, "title": t.title, "status": t.status} for t in board.blockers(ticket_id) if t.status.value != "done"],
            "unresolved_asks": asks,
            "design_ref": ticket.design_ref, "gates": [e.model_dump(mode="json") for e in board.open_gates(ticket_id)],
            "scope": "Direct source only; linked document version events included", "category": category,
            "records": records, "events": [e.model_dump(mode="json") for e in events[:200]],
            "truncated": len(events) > 200}
