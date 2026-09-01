"""edp8 delivery — the one place board writes fan out to the broker wake plane.

Both entry surfaces (the HTTP service and the /ui/me human forms) call these after
a successful board write, so a message/gate behaves identically no matter where it
was typed. All broker publishing is best-effort: the board record is the truth.
"""

from __future__ import annotations

from . import broker_adapter
from .board import Board, BoardError
from .schemas import Message


def _is_participant(board: Board, pid: str) -> bool:
    try:
        board.participant(pid)
        return True
    except BoardError:
        return False


def after_message(board: Board, actor_id: str, m: Message) -> None:
    """Mirror an addressed message + every @mention into broker inboxes."""
    targets: list[str] = []
    if m.to and _is_participant(board, m.to):
        targets.append(m.to)
    for pid in board.mentions(m.text, exclude={actor_id, *(t for t in targets)}):
        targets.append(pid)
    for to in targets:
        broker_adapter.publish(actor_id, to, m.kind.value,
                               {"ticket_id": m.ticket_id, "text": m.text, "board_msg_id": m.id})


def after_gate_open(board: Board, actor_id: str, ticket_id: str, gate: str, note: str) -> None:
    """A gate needs a human: wake the epic's owning human (not the role broadcast)."""
    broker_adapter.publish(actor_id, board.epic_owner(ticket_id), "question",
                           {"ticket_id": ticket_id, "gate": gate, "note": note})


def after_gate_answer(board: Board, actor_id: str, ticket_id: str, gate: str, answer: str) -> None:
    """Wake the shell (a parked architect included) waiting on this gate."""
    t = board.ticket(ticket_id)
    if t.assignee:
        broker_adapter.publish(actor_id, t.assignee, "answer",
                               {"ticket_id": ticket_id, "gate": gate, "answer": answer})
