"""E6 test support: a task names the requirement ids it serves, so a test that needs a bare task asks for one.
(The module keeps its name; s-aa76c83998 replaced the asks ledger with marked requirements.)"""

from __future__ import annotations

from edp8.board import Board
from edp8.schemas import MessageKind


def serve(board: Board, parent_id: str) -> list[str]:
    """One requirement id on the epic that owns `parent_id`: a human posts text on the epic and marks it."""
    epic = board.epic_of(board.ticket(parent_id))
    humans = [p for p in board.store.query("participant", {"role": "owner"}) if p.type == "human"] or [
        board.participant_create("human", "owner", "ask-human")]
    h = humans[0]
    m = board.message_send(h, ticket_id=epic.id, to=None, kind=MessageKind.note, text="please do the work")
    return [board.requirement_mark(h, message_id=m.id).id]


def serve_rest(client, epic_id: str, owner_headers: dict[str, str]) -> list[str]:
    """The REST twin of `serve`: the epic's owner posts text and marks it, the requirement id comes back."""
    r = client.post("/v1/messages", headers=owner_headers,
                    json={"ticket_id": epic_id, "kind": "note", "text": "please do the work"}).json()
    assert r["ok"], r
    m = client.post("/v1/requirements", headers=owner_headers, json={"message_id": r["value"]["id"]}).json()
    assert m["ok"], m
    return [m["value"]["id"]]
