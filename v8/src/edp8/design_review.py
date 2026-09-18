"""Source-bound review actions, distinct from the legacy acceptance-only gate answer."""
from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

from .board import Board, BoardError
from .schemas import DocumentContext, EventKind, Gate, MessageKind, Participant, Role


class ReviewDecision(BaseModel):
    ticket_id: str
    gate_event_id: str
    decision: Literal["approve", "request_changes"]
    design_ref: str
    reviewed_version: int = Field(ge=1)
    feedback: str = ""
    artifacts: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=128)


class DocumentComment(BaseModel):
    ticket_id: str
    design_ref: str
    reviewed_version: int = Field(ge=1)
    text: str = Field(min_length=1)
    artifacts: list[str] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1, max_length=128)


def source_context(board: Board, actor: Participant, ticket_id: str, doc_id: str, version: int,
                   gate_event_id: str | None = None) -> dict:
    """Validate selectors independently of URL hints; reading follows existing board visibility."""
    ticket = board.ticket(ticket_id)
    linked = ticket.design_ref == doc_id or any(
        link.to_id == doc_id for link in board.store.query("link", {"from_id": ticket_id})) or any(
        criterion.evidence_ref == doc_id for criterion in board.criteria(ticket_id))
    if not linked:
        raise BoardError("scope", "document is not linked to the selected source")
    doc = board.doc(doc_id, version)
    current = board.doc(doc_id)
    gates = board.open_gates(ticket_id, Gate.design_signoff)
    gate = next((g for g in gates if gate_event_id is None or g.id == gate_event_id), None)
    owner = board.epic_owner(ticket_id)
    can_review = actor.type == "human" and actor.role == Role.owner and actor.id == owner
    return {"ticket_id": ticket_id, "source_title": ticket.title, "source_kind": ticket.kind,
            "design_ref": doc.id, "reviewed_version": doc.version, "current_version": current.version,
            "gate_event_id": gate.id if gate else None,
            "can_approve": bool(can_review and gate and ticket.design_ref == doc_id and version == current.version),
            "can_review": can_review}


def _receipt(board: Board, actor: Participant, body: BaseModel) -> dict | None:
    # Deterministic event lookup bounds retry cost independently of the source's history size.
    import hashlib
    key = hashlib.sha256(f"{actor.id}:{body.idempotency_key}".encode()).hexdigest()
    event = board.store.get("event", f"review-{key}")
    if event is None:
        return None
    if event.data.get("request") != body.model_dump(mode="json"):
        raise BoardError("conflict", "idempotency key already used for a different action")
    return event.data["result"]


def _save_receipt(board: Board, actor: Participant, body: BaseModel, result: dict) -> None:
    import hashlib
    from .schemas import Event
    key = hashlib.sha256(f"{actor.id}:{body.idempotency_key}".encode()).hexdigest()
    event = Event(id=f"review-{key}", subject_id=body.ticket_id, kind=EventKind.design_reviewed,
                  created_by=actor.id, data={"request": body.model_dump(mode="json"), "result": result})
    board.store.put("event", event)
    board.store.after_commit(lambda: board._fanout(event))


def _feedback(board: Board, actor: Participant, body: ReviewDecision | DocumentComment, text: str,
              kind: MessageKind):
    if not text.strip():
        raise BoardError("schema", "feedback must not be blank")
    if body.artifacts:
        board.artifact_finalise(actor, artifact_ids=body.artifacts, ticket_id=body.ticket_id)
    message = board.message_send(actor, ticket_id=body.ticket_id, to="architect", kind=kind,
                                 text=f"[{body.design_ref} v{body.reviewed_version}] {text}")
    message.document_context = DocumentContext(design_ref=body.design_ref, reviewed_version=body.reviewed_version)
    board.store.put("message", message)
    return message


def decide(board: Board, actor: Participant, body: ReviewDecision) -> tuple[dict, bool]:
    with board._lock, board.store.transaction():
        if actor.type != "human" or actor.role != Role.owner:
            raise BoardError("scope", "only the human owner may decide a design review")
        owner = board.epic_owner(body.ticket_id)
        if owner != actor.id:
            raise BoardError("scope", "this review has no matching human owner")
        cached = _receipt(board, actor, body)
        if cached is not None:
            return cached, False
        ctx = source_context(board, actor, body.ticket_id, body.design_ref, body.reviewed_version, body.gate_event_id)
        if not ctx["can_approve"]:
            raise BoardError("conflict", "review source, gate or version changed; review the current design",
                             f"current version {ctx['current_version']}; feedback was not sent")
        if body.decision == "approve":
            if body.artifacts:
                raise BoardError("schema", "approval does not accept attachments; send a comment first")
            event = board.gate_answer(actor, body.ticket_id, Gate.design_signoff,
                                      f"Approved {body.design_ref} v{body.reviewed_version}")
            event.data.update(design_ref=body.design_ref, reviewed_version=body.reviewed_version,
                              gate_event_id=body.gate_event_id)
            board.store.put("event", event)
            result = {"event_id": event.id, "decision": "approve", **ctx}
        else:
            message = _feedback(board, actor, body, body.feedback, MessageKind.steer)
            from .views import unresolved_mentions
            result = {"message_id": message.id, "decision": "request_changes", "delivery_note": board.last_send_note,
                      "unresolved_mentions": unresolved_mentions(board, body.feedback), **ctx}
        _save_receipt(board, actor, body, result)
        return result, True


def comment(board: Board, actor: Participant, body: DocumentComment) -> tuple[dict, bool]:
    with board._lock, board.store.transaction():
        cached = _receipt(board, actor, body)
        if cached is not None:
            return cached, False
        ctx = source_context(board, actor, body.ticket_id, body.design_ref, body.reviewed_version)
        message = _feedback(board, actor, body, body.text, MessageKind.note)
        from .views import unresolved_mentions
        result = {"message_id": message.id, "delivery_note": board.last_send_note,
                  "unresolved_mentions": unresolved_mentions(board, body.text), **ctx}
        _save_receipt(board, actor, body, result)
        return result, True
