"""S19 routes (design-e963c656f5 §4.14(e).5): Ask for help, the doctor's read-only diagnostics, and the
admin approval of its proposed fixes.

- `POST /v1/help` (any human except an expert) opens or resumes the caller's help thread with its doctor
  seat (edp8.help). The SPA rail's Ask for help and `heronry doctor --agent` both call it.
- `GET /v1/doctor/*` serves the reads in edp8.doctor. Only the doctor role and admin humans may call it,
  because service status, logs and pool internals are an operator's view.
- `POST /v1/fixes` lets the doctor file a proposal on its own thread. `GET /v1/fixes` lists proposals to an
  admin (all of them) or to a doctor (its own thread's).
- `POST /v1/admin/fixes/{id}/approve|reject` sits behind the S5 admin gate. Approve runs the proposal's
  exact request once, in-process against this app, with the approving admin's own X-Participant/X-Token,
  so the S5 route's guards apply unchanged (edp8.fixes).
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import doctor, fixes, help as help_threads
from .admin import is_admin
from .board import Board, BoardError
from .schemas import Participant, Role


class HelpIn(BaseModel):
    text: str = Field(default="", max_length=4000)


class FixIn(BaseModel):
    topic_id: str
    action: dict[str, Any]
    effect: str = Field(min_length=1, max_length=1000)


class RejectIn(BaseModel):
    reason: str = Field(default="", max_length=500)


def _ok(value: Any, hint: str = "") -> dict[str, Any]:
    return {"ok": True, "value": value, "hint": hint}


def _raise(e: BoardError) -> HTTPException:
    code = {"not_found": 404, "forbidden": 403, "scope": 403, "transition": 409}.get(e.code, 422)
    return HTTPException(code, f"{e.message}" + (f" — {e.hint}" if e.hint else ""))


def in_process_runner(app: Any, headers: dict[str, str]) -> Callable[[str, str, Any], tuple[int, Any]]:
    """(method, path, body) → (status, json), run against `app` itself with `headers`. Called from a
    sync route (an anyio worker thread), so the call hops back onto the server's loop."""
    import anyio
    import httpx

    async def call(method: str, path: str, body: Any) -> tuple[int, Any]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1",
                                     timeout=120.0) as c:
            r = await c.request(method, path, headers=headers, json=body)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:500]}

    return lambda method, path, body: anyio.from_thread.run(call, method, path, body)


def doctor_router(board: Board, actor: Callable[..., Participant], admin_actor: Callable[..., Participant],
                  last_seen: Any = None) -> APIRouter:
    r = APIRouter()

    def reader(a: Participant = Depends(actor)) -> Participant:
        if a.role == Role.doctor or is_admin(a):
            return a
        raise HTTPException(403, "the doctor's diagnostics are for the Help seat and admins")

    def _call(fn: Callable[[], Any]) -> dict[str, Any]:
        try:
            return _ok(fn())
        except BoardError as e:
            raise _raise(e) from None

    # ---- Ask for help
    @r.post("/v1/help")
    def ask(b: HelpIn, a: Participant = Depends(actor)):
        try:
            out = help_threads.ask(board, a, b.text)
        except BoardError as e:
            raise _raise(e) from None
        return _ok(out, "the Help seat answers on the thread; it is spawned within a few seconds")

    @r.get("/v1/help")
    def help_list(closed: bool = False, a: Participant = Depends(actor)):
        return _call(lambda: help_threads.threads(board, a, include_closed=closed))

    # ---- read-only diagnostics
    @r.get("/v1/doctor/health")
    def d_health(a: Participant = Depends(reader)):
        return _call(lambda: doctor.health(board))

    @r.get("/v1/doctor/pool")
    def d_pool(a: Participant = Depends(reader)):
        return _call(lambda: doctor.pool_view(board))

    @r.get("/v1/doctor/feed-lag")
    def d_lag(a: Participant = Depends(reader)):
        return _call(lambda: doctor.feed_lag(board, last_seen))

    @r.get("/v1/doctor/dead-mail")
    def d_dead(a: Participant = Depends(reader)):
        return _call(lambda: doctor.dead_mail(board))

    @r.get("/v1/doctor/why-stuck/{ticket_id}")
    def d_stuck(ticket_id: str, a: Participant = Depends(reader)):
        return _call(lambda: doctor.why_stuck(board, ticket_id))

    @r.get("/v1/doctor/workflow/{ref}")
    def d_workflow(ref: str, a: Participant = Depends(reader)):
        return _call(lambda: doctor.workflow_check(board, ref))

    @r.get("/v1/doctor/pains")
    def d_pains(a: Participant = Depends(reader)):
        return _call(doctor.pains)

    @r.get("/v1/doctor/logs/{service:path}")
    def d_logs(service: str, lines: int = 100, a: Participant = Depends(reader)):
        return _call(lambda: doctor.logs(service, lines))

    # ---- fixes
    @r.post("/v1/fixes")
    def fix_propose(b: FixIn, a: Participant = Depends(actor)):
        try:
            f = fixes.propose(board, a, topic_id=b.topic_id, action=b.action, effect=b.effect)
        except BoardError as e:
            raise _raise(e) from None
        return _ok(fixes.view(f), "posted as an admin approval card; nothing runs until an admin approves")

    @r.get("/v1/fixes")
    def fix_list(topic_id: str | None = None, status: str | None = None, a: Participant = Depends(actor)):
        if not is_admin(a):
            mine = board.topic_of_seat(a) if a.role == Role.doctor else None
            if mine is None or (topic_id and topic_id != mine.id):
                raise HTTPException(403, "fix proposals are listed to admins, and to a doctor for its own thread")
            topic_id = mine.id
        return _ok([fixes.view(f) for f in fixes.listing(board, topic_id=topic_id, status=status)])

    @r.post("/v1/admin/fixes/{fix_id}/approve")
    def fix_approve(fix_id: str, request: Request, a: Participant = Depends(admin_actor)):
        headers = {"X-Participant": request.headers.get("x-participant", ""),
                   "X-Token": request.headers.get("x-token", "")}
        try:
            f, raw = fixes.approve(board, a, fix_id, in_process_runner(request.app, headers))
        except BoardError as e:
            raise _raise(e) from None
        # the approver sees the route's own answer (a rotated token appears here, once); the thread has it redacted
        return _ok({"fix": fixes.view(f), "response": raw},
                   "applied" if f.status == "applied" else "the action ran and failed; the result is on the thread")

    @r.post("/v1/admin/fixes/{fix_id}/reject")
    def fix_reject(fix_id: str, b: RejectIn | None = None, a: Participant = Depends(admin_actor)):
        try:
            f = fixes.reject(board, a, fix_id, (b or RejectIn()).reason)
        except BoardError as e:
            raise _raise(e) from None
        return _ok(fixes.view(f), "rejected: nothing ran")

    return r
