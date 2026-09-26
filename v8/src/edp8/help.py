"""S19 help threads (design-e963c656f5 §4.14(e).5): "Ask for help" and `heronry doctor --agent`.

A help thread is a Library-style topic tagged `help` (architect ruling m-ec43dddf3e): a parentless ticket of
kind `topic` whose resident seat is `doctor.<topic>` rather than an sme, woken by every message on it
(Board._general_reasons). Any human may open one, unlike a Library topic, which only the owner opens. A
second ask from the same person resumes their newest open help thread rather than opening another, and
re-queues its doctor seat if the seat is gone. Help threads never appear in the Library list
(topics.list_view). The person who asked, or the owner, closes the thread; closing releases the seat.

The seat is spawned by the board's pairing queue, which the pool-watch tick drains every ~10 s, the same
path as a Library topic's sme.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import topics
from .board import HELP_TAG, _TERMINAL, Board, BoardError, is_help
from .schemas import EventKind, MessageKind, Participant, Role, Ticket, TicketKind, TicketStatus, WorkType
from .store import new_id

TITLE_MAX = 80
DEFAULT_ASK = "I need help: something is not working."


def _title(text: str) -> str:
    line = " ".join(text.split())
    return "Help: " + (line[: TITLE_MAX - 9] + "…" if len(line) > TITLE_MAX - 6 else line)


def open_thread(board: Board, actor: Participant) -> Ticket | None:
    """The person's newest open help thread, if any."""
    rows = board.store.query("ticket", {"kind": TicketKind.topic.value, "created_by": actor.id}, limit=-1,
                             newest_first=True)
    for t in rows:
        if is_help(t) and t.status not in _TERMINAL:  # type: ignore[arg-type]
            return t  # type: ignore[return-value]
    return None


def _create(board: Board, actor: Participant, text: str) -> Ticket:
    """Open a help topic as `actor`. Built here rather than through Board.ticket_create, whose workflow table
    lets only the owner create topics: help is open to every human, and the tag is fixed at create."""
    with board._lock:
        t = Ticket(id=new_id("topic"), kind=TicketKind.topic, work_type=WorkType.knowledge, title=_title(text),
                   words=text, created_by=actor.id, description="", tags=[HELP_TAG])
        t.status = TicketStatus.in_progress  # open from birth, like every topic
        t.epic_id = t.id
        board.store.put("ticket", t)
    board._index("ticket", t.id, board.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
    board._emit(t.id, EventKind.ticket_created, {"kind": TicketKind.topic, "parent_id": None, "by": actor.id,
                                                 "help": True})
    return t


def ask(board: Board, actor: Participant, text: str | None = None) -> dict[str, Any]:
    """Open or resume the caller's help thread, keep its doctor seat queued, post the ask (when given).
    Returns {topic, seat, resumed, message, url}."""
    if actor.type != "human" or actor.role == Role.expert:
        raise BoardError("forbidden", "Ask for help is for the people who run this board",
                         "an expert asks on its Library topic; a seat asks its architect")
    text = (text or "").strip()
    t = open_thread(board, actor)
    resumed = t is not None
    if t is None:
        t = _create(board, actor, text or DEFAULT_ASK)
    seat = topics.ensure_seat(board, t.id)
    msg = None
    if text or not resumed:
        m = board.message_send(actor, ticket_id=t.id, to=seat, kind=MessageKind.question,
                               text=text or DEFAULT_ASK)
        msg = m.id
    return {"topic": board.ticket(t.id).model_dump(mode="json"), "seat": topics.seat_view(board, t.id),
            "resumed": resumed, "message": msg, "url": f"/ui/library/topics/{t.id}"}


# ----------------------------------------------------------------------------- `heronry doctor --agent`
def _owner_credentials() -> tuple[str, str | None]:
    """The CLI speaks as the install's human (EDP8_OWNER), with its token from tokens.json when there is one
    (the file is owner-only on disk; header-only boards run without it)."""
    from . import settings
    handle = str(settings.get("EDP8_OWNER"))
    try:
        data = json.loads(Path(settings.get("EDP8_TOKENS")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return handle, None
    tok = data.get(handle) if isinstance(data, dict) else None
    return handle, tok if isinstance(tok, str) else None


def agent_cmd(argv: list[str]) -> int:
    """`heronry doctor --agent [question…]`: open or resume the caller's help thread on the running board and
    print where to follow it. The question is optional (a fresh thread gets a generic opener)."""
    import httpx

    from . import launcher, settings
    text = " ".join(a for a in argv if not a.startswith("--")).strip()
    base = launcher.url("board") or f"http://127.0.0.1:{launcher.port('board')}"
    handle, token = _owner_credentials()
    headers = {"X-Participant": handle, **({"X-Token": token} if token else {})}
    try:
        r = httpx.post(f"{base}/v1/help", json={"text": text}, headers=headers, timeout=30.0)
    except httpx.HTTPError as e:
        print(f"the board is not answering at {base} ({type(e).__name__}); start it with `heronry start`, "
              "or run `heronry doctor` for the offline checks", file=sys.stderr)
        return 1
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400 or not body.get("ok", False):
        err = body.get("error")
        detail = (err.get("message") if isinstance(err, dict) else err) or body.get("hint") or r.text[:300]
        print(f"the board refused the help request ({r.status_code}): {detail}", file=sys.stderr)
        return 1
    v = body["value"]
    public = settings.get("EDP8_PUBLIC_URL") or base
    print(("resumed" if v["resumed"] else "opened") + f" help thread {v['topic']['id']}")
    print(f"  Help seat {v['seat']['participant']}: {v['seat']['state']} (it answers on the thread)")
    print(f"  follow it at {str(public).rstrip('/')}{v['url']}")
    return 0
