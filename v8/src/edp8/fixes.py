"""S19 approval-gated fixes (design-e963c656f5 §4.14(e).5; architect ruling m-ec43dddf3e).

The Help seat never changes anything itself. It proposes one structured action from a closed set, and the
board turns the action into the exact route call that would carry it out. That call is always an existing
S5 admin route (services, capacity, teammates, agent tokens) or the board's own gate route. It is stored
as a `FixProposal` and shown to admins as an approval card on the help thread.

Nothing runs before Approve. On Approve, the admin's own credentials run that one call, in-process against
the same app, so every S5 guard (admin gate, supervisor refusals, pool clamps, token mode) applies exactly
as if the admin had pressed the button in Admin. The proposal moves proposed → applied|failed under the
board lock, so it runs at most once. The result, with any secret stripped, is posted back on the thread,
which wakes the doctor. Reject records who rejected it and runs nothing.

A workflow pin is never changed (ruling m-ec43dddf3e: pins are the upgrade-safety guarantee). The doctor
proposes a fixed workflow version for new epics, or the gate or checker action that unblocks a stuck one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from .board import _TERMINAL, Board, BoardError, is_help
from .fix_actions import (_ACTION, KINDS, Action, GateAnswerAction, GateOpenAction,  # noqa: F401 - re-exported
                          PoolLimitsAction, RevokeAgentTokenAction, RotateTokenAction, ServiceAction,
                          _fields_by_kind)
from .schemas import FixProposal, Participant, Role, now
from .store import new_id

SERVICES = ("board", "broker", "pool", "mcp", "bridge")
#: response keys never copied into the thread or the stored result (a rotated token is shown once, to the approver)
SECRET_KEYS = frozenset({"token", "secret", "key", "auth_key", "password"})


def parse(action: dict[str, Any]) -> BaseModel:
    try:
        return _ACTION.validate_python(action)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ())) or "action"
        raise BoardError("invalid", f"not a fix action: {where}: {first.get('msg')}",
                         f"action.kind and fields (? optional): {_fields_by_kind()}") \
            from None


def request_for(a: BaseModel) -> dict[str, Any]:
    """The exact route call Approve runs: {method, path, body}."""
    k = a.kind  # type: ignore[attr-defined]
    if isinstance(a, ServiceAction):
        verb = k.split(".", 1)[1]
        return {"method": "POST", "path": f"/v1/admin/services/{a.service}/{verb}",
                "body": {"force": a.force, "keep_seats": a.keep_seats}}
    if isinstance(a, PoolLimitsAction):
        body = a.model_dump(exclude={"kind"}, exclude_none=True)
        if not body:
            raise BoardError("invalid", "pool.set_limits changes nothing", "name at least one cap")
        return {"method": "PUT", "path": "/v1/admin/capacity", "body": body}
    if isinstance(a, GateOpenAction):
        return {"method": "POST", "path": f"/v1/gates/{a.ticket_id}/{a.gate.value}/open", "body": {"note": a.note}}
    if isinstance(a, GateAnswerAction):
        return {"method": "POST", "path": f"/v1/gates/{a.ticket_id}/{a.gate.value}/answer",
                "body": {"answer": a.answer}}
    if isinstance(a, RotateTokenAction):
        return {"method": "POST", "path": f"/v1/admin/teammates/{a.handle.lstrip('@')}/rotate", "body": {}}
    if isinstance(a, RevokeAgentTokenAction):
        return {"method": "DELETE", "path": f"/v1/admin/tokens/agents/{a.handle.lstrip('@')}", "body": None}
    raise BoardError("invalid", f"no route for {k}")


def card_text(f: FixProposal) -> str:
    body = f.request.get("body")
    return (f"[fix proposed] {f.id}: {f.action.get('kind')} → {f.request['method']} {f.request['path']}"
            + (f" {body}" if body else "") + f"\nEffect: {f.effect}\n"
            "Nothing runs until an admin presses Approve (this thread's fix card).")


# ----------------------------------------------------------------------------- lifecycle
def _topic_of_doctor(board: Board, actor: Participant, topic_id: str) -> None:
    if actor.role != Role.doctor:
        raise BoardError("forbidden", "only the Help seat proposes fixes", "an admin runs a fix from Admin directly")
    t = board.store.get("ticket", topic_id)
    if not is_help(t) or board.topic_of_seat(actor) is None or board.topic_of_seat(actor).id != topic_id:
        raise BoardError("scope", f"{actor.id} proposes fixes on its own help thread only",
                         "pass the help topic id from your context()")
    if t.status in _TERMINAL:  # type: ignore[union-attr]
        raise BoardError("transition", f"help thread {topic_id} is closed")


def propose(board: Board, actor: Participant, *, topic_id: str, action: dict[str, Any], effect: str) -> FixProposal:
    """File one inert proposal and post its card on the help thread."""
    _topic_of_doctor(board, actor, topic_id)
    if not (effect or "").strip():
        raise BoardError("invalid", "say what the fix will do (effect)", "one or two plain sentences")
    a = parse(action)
    f = FixProposal(id=new_id("fix"), created_by=actor.id, topic_id=topic_id, action=a.model_dump(mode="json"),
                    effect=effect.strip()[:1000], request=request_for(a))
    board.store.put("fix", f)
    board._pairing_note(topic_id, card_text(f))
    return f


def get(board: Board, fix_id: str) -> FixProposal:
    f = board.store.get("fix", fix_id)
    if f is None:
        raise BoardError("not_found", f"no fix {fix_id}")
    return f  # type: ignore[return-value]


def listing(board: Board, *, topic_id: str | None = None, status: str | None = None) -> list[FixProposal]:
    return board.store.query("fix", {"topic_id": topic_id, "status": status}, limit=500,  # type: ignore[return-value]
                             newest_first=True)


def _claim(board: Board, fix_id: str, admin: Participant, to: str) -> FixProposal:
    """proposed → `to`, once. A second decision (a double click, two admins) is refused."""
    with board._lock:
        f = get(board, fix_id)
        if f.status != "proposed":
            raise BoardError("transition", f"{fix_id} was already {f.status} by {f.decided_by}",
                             "a decided fix never runs again; the doctor proposes a new one")
        t = board.store.get("ticket", f.topic_id)
        if t is None or t.status in _TERMINAL:
            raise BoardError("transition", f"help thread {f.topic_id} is closed; its fixes cannot run")
        f = f.model_copy(update={"status": to, "decided_by": admin.id, "decided_at": now()})
        board.store.put("fix", f)
        return f


def reject(board: Board, admin: Participant, fix_id: str, reason: str = "") -> FixProposal:
    f = _claim(board, fix_id, admin, "rejected")
    if reason.strip():
        f = f.model_copy(update={"result": {"reason": reason.strip()[:500]}})
        board.store.put("fix", f)
    _post_back(board, f, f"[fix rejected] {f.id} by {admin.id}; nothing ran."
               + (f" Reason: {reason.strip()[:500]}" if reason.strip() else ""))
    return f


def _redact(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: ("<shown once to the approver>" if k in SECRET_KEYS else _redact(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact(x) for x in v]
    return v


def approve(board: Board, admin: Participant, fix_id: str, run: Any) -> tuple[FixProposal, dict[str, Any]]:
    """Claim the proposal, then run its request once through `run(method, path, body) -> (status, json)`,
    which is the admin's own in-process call. Returns (stored proposal, the raw response for the approver).
    The stored result and the thread note carry the response with secrets replaced."""
    f = _claim(board, fix_id, admin, "applied")
    req = f.request
    try:
        code, out = run(req["method"], req["path"], req.get("body"))
    except Exception as e:  # noqa: BLE001 — a crashed call is a failed fix, recorded, never a 500 loop
        code, out = 599, {"error": f"{type(e).__name__}: {e}"}
    ok = code < 400 and (not isinstance(out, dict) or out.get("ok", True) is not False)
    summary = _redact(out)
    f = f.model_copy(update={"status": "applied" if ok else "failed",
                             "result": {"http_status": code, "response": summary}})
    board.store.put("fix", f)
    word = "applied" if ok else "failed"
    detail = _one_line(summary)
    _post_back(board, f, f"[fix {word}] {f.id} approved by {admin.id}: {req['method']} {req['path']} → "
                         f"HTTP {code}. {detail}\nVerify with the matching doctor read tool and report.")
    return f, out if isinstance(out, dict) else {"value": out}


def _one_line(v: Any, cap: int = 600) -> str:
    import json
    s = json.dumps(v, default=str)
    return s if len(s) <= cap else s[:cap] + "…"


def _post_back(board: Board, f: FixProposal, text: str) -> None:
    """A board note on the help thread; its resident doctor hears every message there and wakes."""
    board._pairing_note(f.topic_id, text)


def view(f: FixProposal) -> dict[str, Any]:
    return {**f.model_dump(mode="json"), "card": card_text(f)}

