"""Privacy-minimal notification selectors. Authority is the S20 attention derivation (attention.items): an event
notifies only while the item it raised is still in the viewer's list, and it deep-links into that item's trail."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import attention as _attention
from .board import Board
from .schemas import EventKind, Participant


def _landing(url: str, request: str) -> str:
    """The item's trail url carrying ?request=<event> (the click-time revalidation key), before any #anchor."""
    base, _, anchor = url.partition("#")
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "request"] + [("request", request)]
    return urlunsplit(parts._replace(query=urlencode(query))) + (f"#{anchor}" if anchor else "")


def attention(board: Board, actor: Participant, *, since: int = -1,
              request: str | None = None) -> dict:
    # Snapshot cursor + pending requests under the same writer lock: no enable/backlog race.
    with board._lock, board.store._lock:
        cursor = board.store.max_seq()
        if request is None and since < 0:
            return {"participant": actor.id, "cursor": cursor, "requests": []}
        # message id / gate event id -> the attention item it raised (S20: no rule of its own here)
        live = {it["id"]: it for it in _attention.items(board, actor) if it["kind"] in ("ask", "gate")}
        if request is not None:
            event = board.store.get("event", request)
            events = [event] if event else []
        else:
            batch = board.store.events_since(since, limit=200)
            events = [event for _, event in batch]
            cursor = batch[-1][0] if batch else cursor
        rows = []
        for event in events:
            if event.kind == EventKind.message_sent:
                item = live.get(event.data.get("message"))
            elif event.kind == EventKind.gate_opened:
                item = live.get(event.id)
            else:
                item = None
            if item is not None:
                rows.append({"request": event.id, "url": _landing(item["url"], event.id)})
        return {"participant": actor.id, "cursor": cursor, "requests": rows}
