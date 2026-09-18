"""edp8 delivery — the one place board writes fan out to the broker wake plane.

Both entry surfaces (the HTTP service and the /ui/me human forms) call these after
a successful board write, so a message/gate behaves identically no matter where it
was typed. All broker publishing is best-effort: the board record is the truth.
"""

from __future__ import annotations

from . import broker_adapter
from .board import Board, BoardError
from .schemas import Event, EventKind, Message, MessageKind, Reason


def delivery_plan(board: Board, ev: Event) -> list[tuple[str, list[Reason]]]:
    """The single decider of who a board event wakes and why (design §16.2 rule 0). One
    entry per recipient, its reasons in priority order. This is the one function behind the
    feed (`Board.relevant` = recipient in plan), the `why` clause, broker publication and the
    `/v1/messages/resolve` wake preview — so a preview can never drift from delivery.

    `ev` may be a real stored event or a synthetic one (the resolve preview builds a
    `message_sent`-shaped event that is never persisted)."""
    plan: list[tuple[str, list[Reason]]] = []
    for p in board.store.query("participant", {}, limit=100_000):
        reasons = board._reason_for(ev, p)  # the per-participant predicate (never parses text)
        if reasons:
            plan.append((p.id, reasons))
    # rule 3 — no silent drop: a question/deviation whose plan is otherwise empty (no addressee,
    # no working seat, no architect seat) falls back to the epic's human owner.
    if not plan and ev.kind == EventKind.message_sent \
            and ev.data.get("kind") in (MessageKind.question, MessageKind.deviation):
        owner = board.epic_owner(ev.subject_id)
        if owner:
            plan.append((owner, [Reason.recovery]))
    return plan


def _is_participant(board: Board, pid: str) -> bool:
    try:
        board.participant(pid)
        return True
    except BoardError:
        return False


def _seat_alive(board: Board, pid: str) -> bool | None:
    """Latest session state for a participant; None when it never had a shell."""
    rows = sorted(board.store.query("session", {"participant_id": pid}), key=lambda s: s.created_at)
    if not rows:
        return None
    return rows[-1].state.value in ("alive", "parked")


def after_message(board: Board, actor_id: str, m: Message) -> None:
    """Mirror an addressed message + every @mention into broker inboxes.

    Blind-spot guard: a message addressed to an AGENT seat with no live shell would
    otherwise wait silently — the epic's owning human gets an fyi naming the closed
    seat so the recovery decision (respawn / let it wait) is theirs, immediately."""
    targets: list[str] = []
    if m.to and _is_participant(board, m.to):
        targets.append(m.to)
    for pid in board.mentions(m.text, exclude={actor_id, *(t for t in targets)}):
        targets.append(pid)
    for to in targets:
        broker_adapter.publish(actor_id, to, m.kind.value,
                               {"ticket_id": m.ticket_id, "text": m.text, "board_msg_id": m.id,
                                # attachment refs only (R1): the recipient fetches bytes with its own identity
                                **({"artifacts": list(m.artifacts)} if m.artifacts else {})})
        try:
            p = board.participant(to)
        except BoardError:
            continue
        # closed-seat fyi: only for a REAL per-ticket seat (role.<ticket>) with no live shell —
        # a base-role stub is not a seat, and the fyi goes to THIS epic's human owner, else to
        # its live resident architect; never to a shared 'owner' handle (2026-09-05 flood)
        if p.type == "agent" and "." in to and _seat_alive(board, to) is not True and m.kind.value != "status":
            fyi_to = board.recovery_seat(m.ticket_id, exclude={to, actor_id})
            if fyi_to:
                broker_adapter.publish("board", fyi_to, "fyi",
                                       {"ticket_id": m.ticket_id,
                                        "text": f"{m.kind.value} from {actor_id} awaits CLOSED seat {to} "
                                                f"on {m.ticket_id} — it reads its inbox first thing on its "
                                                f"next shell; spawn(participant_id={to!r}) revives it "
                                                f"without reassigning the ticket",
                                        "board_msg_id": m.id, "closed_seat": to})


def spawner_of(participant_id: str) -> str | None:
    """The handle that spawned this participant's live shell (pool lineage); None when unknown."""
    try:
        from . import pool_adapter
        got = pool_adapter.sessions()
        if not got.get("ok"):
            return None
        rows = got["value"] if isinstance(got["value"], list) else got["value"].get("sessions", [])
        by_sid = {s.get("session_id"): s for s in rows}
        mine = next((s for s in rows if s.get("handle") == participant_id
                     and s.get("state") in ("active", "alive", "starting")), None) \
            or next((s for s in rows if s.get("handle") == participant_id), None)
        parent = by_sid.get((mine or {}).get("parent"))
        return parent.get("handle") if parent else None
    except Exception:  # noqa: BLE001 — lineage is a courtesy, never a failure
        return None


def after_status(board: Board, actor_id: str, m: Message, recipients: list[str]) -> list[str]:
    """A recorded status reaches the seat's spawner, the epic architect and the epic's human
    owner (computed by the board) — the spawner is added here from pool lineage."""
    targets = list(recipients)
    sp = spawner_of(actor_id)
    if sp and sp != actor_id and sp not in targets and _is_participant(board, sp):
        targets.append(sp)
    for pid in board.mentions(m.text, exclude={actor_id, *targets}):
        targets.append(pid)
    for to in targets:
        broker_adapter.publish(actor_id, to, "status",
                               {"ticket_id": m.ticket_id, "text": m.text, "board_msg_id": m.id,
                                "status": m.status.value if m.status else None})
    return targets


def after_gate_open(board: Board, actor_id: str, ticket_id: str, gate: str, note: str) -> str | None:
    """A gate needs a human: wake the epic's owning human (not the role broadcast). Returns
    who was woken, or None when the epic has no human owner (the gate still stands on the
    board; the UI shows it to whoever opens the epic)."""
    who = board.epic_owner(ticket_id)
    if who:
        broker_adapter.publish(actor_id, who, "question", {"ticket_id": ticket_id, "gate": gate, "note": note})
    return who


def after_gate_answer(board: Board, actor_id: str, ticket_id: str, gate: str, answer: str) -> None:
    """Wake the shell (a parked architect included) waiting on this gate."""
    t = board.ticket(ticket_id)
    if t.assignee:
        broker_adapter.publish(actor_id, t.assignee, "answer",
                               {"ticket_id": ticket_id, "gate": gate, "answer": answer})
