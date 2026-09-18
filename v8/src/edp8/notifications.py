"""Privacy-minimal notification selectors. Authority stays with inbox/open-gate derivations."""
from __future__ import annotations

from urllib.parse import urlencode

from . import views
from .board import Board
from .schemas import EventKind, Participant


def attention(board: Board, actor: Participant, *, since: int = -1,
              request: str | None = None) -> dict:
    # Snapshot cursor + pending requests under the same writer lock: no enable/backlog race.
    with board._lock, board.store._lock:
        cursor = board.store.max_seq()
        if request is None and since < 0:
            return {"participant": actor.id, "cursor": cursor, "requests": []}
        asks = {m["id"]: m for m in board.inbox(actor) if m["kind"] == "question"}
        gates = {ev.id: (tid, ev) for tid, ev in views._owner_gates(board, actor)}
        if request is not None:
            event = board.store.get("event", request)
            events = [event] if event else []
        else:
            batch = board.store.events_since(since, limit=200)
            events = [event for _, event in batch]
            cursor = batch[-1][0] if batch else cursor
        rows = []
        for event in events:
            message = None
            if event.kind == EventKind.message_sent:
                message = asks.get(event.data.get("message"))
                if not message:
                    continue
                tid = message["ticket_id"]
            elif event.kind == EventKind.gate_opened and event.id in gates:
                tid = gates[event.id][0]
            else:
                continue
            ticket = board.ticket(tid)
            path = "epic" if ticket.kind.value == "epic" else "ticket"
            url = f"/ui/{path}/{tid}?{urlencode({'request': event.id})}"
            if message:
                url += f"#{message['id']}"
            rows.append({"request": event.id, "url": url})
        return {"participant": actor.id, "cursor": cursor, "requests": rows}
