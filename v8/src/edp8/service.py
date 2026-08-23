"""edp8 board service — HTTP over Board (FastAPI).

Identity: every request carries `X-Participant: <id | @handle>`. Registry and
pool endpoints carry `X-Admin: <EDP8_ADMIN_TOKEN>` (default "dev").
Every response is `{ok: true, value: ...}` or `{ok: false, error: {code, message}, hint}`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .board import Board, BoardError
from .schemas import (
    DESCRIBE,
    OBJECT_TYPES,
    ArtifactForm,
    Check,
    DocType,
    Gate,
    MessageKind,
    Participant,
    Relation,
    Role,
    SessionState,
    TicketKind,
    TicketStatus,
    Verdict,
    WorkType,
)
from .store import Store


def ok(value: Any, hint: str = "") -> dict[str, Any]:
    return {"ok": True, "value": value, "hint": hint}


def _dump(o: Any) -> Any:
    if isinstance(o, BaseModel):
        return o.model_dump(mode="json")
    if isinstance(o, list):
        return [_dump(x) for x in o]
    if isinstance(o, dict):
        return {k: _dump(v) for k, v in o.items()}
    if isinstance(o, tuple):
        return [_dump(x) for x in o]
    return o


# ----------------------------------------------------------------------------- bodies


class ParticipantIn(BaseModel):
    type: str
    role: Role
    handle: str
    location: str | None = None
    model: str | None = None
    id: str | None = None


class TicketIn(BaseModel):
    kind: TicketKind
    work_type: WorkType
    title: str
    parent_id: str | None = None
    assignee: str | None = None


class TicketPatch(BaseModel):
    status: TicketStatus | None = None
    assignee: str | None = None
    design_ref: str | None = None


class CriterionIn(BaseModel):
    ticket_id: str
    text: str
    check: Check
    checked_by: str


class CriterionPatch(BaseModel):
    evidence_ref: str | None = None
    verdict: Verdict | None = None


class DocIn(BaseModel):
    doc_type: DocType
    title: str
    body_md: str
    scope: str


class DocPatch(BaseModel):
    body_md: str | None = None
    title: str | None = None


class LinkIn(BaseModel):
    from_id: str
    to_id: str
    relation: Relation


class MessageIn(BaseModel):
    ticket_id: str
    to: str | None = None
    kind: MessageKind
    text: str
    reply_to: str | None = None


class ArtifactIn(BaseModel):
    form: ArtifactForm
    uri: str
    note: str = ""
    ticket_id: str | None = None


class GateAnswerIn(BaseModel):
    answer: str


class GateOpenIn(BaseModel):
    note: str = ""


class SessionIn(BaseModel):
    participant_id: str
    ticket_id: str | None = None
    pool_id: str
    state: SessionState
    resume_token: str = ""


# ----------------------------------------------------------------------------- app


def create_app(board: Board | None = None, admin_token: str | None = None) -> FastAPI:
    if board is None:
        db = os.environ.get("EDP8_DB", str(Path(os.environ.get("EDP8_HOME", ".")) / "edp8.db"))
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        index = None
        try:
            from .search import Index, make_embedder

            index = Index(embedder=make_embedder())
        except Exception:
            index = None
        store = Store(db)
        board = Board(store, index)
        if index is not None:
            try:
                index.rebuild(store.all_text_units())
            except Exception as e:  # search degrades to nothing; the board keeps running, loudly
                logging.getLogger("edp8.service").warning("search index rebuild failed: %s", e)
    admin_token = admin_token or os.environ.get("EDP8_ADMIN_TOKEN", "dev")
    app = FastAPI(title="edp8 board", version="0.8.0")
    app.state.board = board

    def actor(x_participant: str | None = Header(default=None)) -> Participant:
        if not x_participant:
            raise HTTPException(401, "X-Participant header missing (participant id or @handle)")
        try:
            return board.participant(x_participant)
        except BoardError as e:
            raise HTTPException(401, e.message)

    def admin(x_admin: str | None = Header(default=None)) -> None:
        if x_admin != admin_token:
            raise HTTPException(403, "X-Admin token invalid")

    @app.exception_handler(BoardError)
    async def _board_error(_: Request, e: BoardError):
        return JSONResponse(status_code=409 if e.code in ("transition", "conflict") else 400, content=e.to_dict())

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, e: HTTPException):
        return JSONResponse(status_code=e.status_code,
                            content={"ok": False, "error": {"code": "http", "message": str(e.detail)}, "hint": ""})

    # identity -----------------------------------------------------------------
    @app.get("/v1/whoami")
    def whoami(a: Participant = Depends(actor)):
        tickets = board.my_tickets(a)
        return ok({"participant": _dump(a), "tickets": [t.id for t in tickets]},
                  "next: subscribe() to arm your feed, then context() to load your ticket")

    @app.get("/v1/describe/{type_}")
    def describe(type_: str):
        if type_ not in OBJECT_TYPES:
            raise BoardError("not_found", f"unknown object type {type_!r}", f"types: {sorted(OBJECT_TYPES)}")
        return ok({"type": type_, "contract": DESCRIBE[type_], "schema": OBJECT_TYPES[type_].model_json_schema()})

    @app.get("/v1/context")
    def context(ticket_id: str | None = None, a: Participant = Depends(actor)):
        return ok(board.context(a, ticket_id))

    # registry (admin) -----------------------------------------------------------
    @app.post("/v1/participants")
    def participant_create(b: ParticipantIn, x_admin: str | None = Header(default=None),
                           x_participant: str | None = Header(default=None)):
        # admin registers anyone; a spawner role (coordinator/engineer/architect) registers AGENT participants
        # for the tickets it spawns shells on — the scope a per-ticket spawn needs, nothing more.
        if x_admin != admin_token:
            if not x_participant:
                raise HTTPException(403, "X-Admin token invalid (or sign as a spawner role with X-Participant)")
            try:
                a = board.participant(x_participant)
            except BoardError as e:
                raise HTTPException(401, e.message)
            if a.role not in (Role.coordinator, Role.engineer, Role.architect) or b.type != "agent":
                raise HTTPException(403, "only admin, or a spawner role registering an agent participant")
        p = board.participant_create(b.type, b.role, b.handle, location=b.location, model=b.model, id_=b.id)
        return ok(_dump(p))

    @app.get("/v1/participants")
    def participants(role: Role | None = None, a: Participant = Depends(actor)):
        return ok(_dump(board.store.query("participant", {"role": role})))

    @app.get("/v1/participants/{id_}")
    def participant_get(id_: str, a: Participant = Depends(actor)):
        return ok(_dump(board.participant(id_)))

    # tickets ------------------------------------------------------------------
    @app.post("/v1/tickets")
    def ticket_create(b: TicketIn, a: Participant = Depends(actor)):
        t = board.ticket_create(a, kind=b.kind, work_type=b.work_type, title=b.title,
                                parent_id=b.parent_id, assignee=b.assignee)
        hint = ("epic created; an architect designs it (doc_create design, criteria, stories)"
                if t.kind == TicketKind.epic else "add criteria before it becomes ready")
        return ok(_dump(t), hint)

    @app.get("/v1/tickets/{id_}")
    def ticket_get(id_: str, a: Participant = Depends(actor)):
        t = board.ticket(id_)
        return ok({**_dump(t), "criteria": _dump(board.criteria(id_)),
                   "docs": [board._doc_summary(d) for d in board.linked_docs(id_)],
                   "open_gates": [e.data.get("gate") for e in board.open_gates(id_)]})

    @app.get("/v1/tickets")
    def ticket_query(kind: TicketKind | None = None, work_type: WorkType | None = None,
                     parent_id: str | None = None, status: TicketStatus | None = None,
                     assignee: str | None = None, a: Participant = Depends(actor)):
        return ok(_dump(board.store.query("ticket", {"kind": kind, "work_type": work_type, "parent_id": parent_id,
                                                     "status": status, "assignee": assignee})))

    @app.patch("/v1/tickets/{id_}")
    def ticket_update(id_: str, b: TicketPatch, a: Participant = Depends(actor)):
        t = board.ticket_update(a, id_, status=b.status, assignee=b.assignee, design_ref=b.design_ref)
        return ok(_dump(t))

    # criteria -----------------------------------------------------------------
    @app.post("/v1/criteria")
    def criterion_create(b: CriterionIn, a: Participant = Depends(actor)):
        return ok(_dump(board.criterion_create(a, ticket_id=b.ticket_id, text=b.text, check=b.check,
                                               checked_by=b.checked_by)))

    @app.get("/v1/criteria")
    def criterion_query(ticket_id: str, a: Participant = Depends(actor)):
        return ok(_dump(board.criteria(ticket_id)))

    @app.patch("/v1/criteria/{id_}")
    def criterion_update(id_: str, b: CriterionPatch, a: Participant = Depends(actor)):
        c = board.criterion_update(a, id_, evidence_ref=b.evidence_ref, verdict=b.verdict)
        pending = [x.id for x in board.criteria(c.ticket_id) if x.verdict != Verdict.passed]
        return ok(_dump(c), f"{len(pending)} criteria not yet passed on {c.ticket_id}" if pending else
                  "all criteria passed; the ticket can be marked done by its checker")

    # docs / links / artifacts ---------------------------------------------------
    @app.post("/v1/docs")
    def doc_create(b: DocIn, a: Participant = Depends(actor)):
        return ok(_dump(board.doc_create(a, doc_type=b.doc_type, title=b.title, body_md=b.body_md, scope=b.scope)),
                  "link it: link_create(from_id=<ticket>, to_id=<doc>, "
                  "relation=designed_by|uses_strategy|uses_domain|evidence_for)")

    @app.get("/v1/docs/{id_}")
    def doc_get(id_: str, version: int | None = None, a: Participant = Depends(actor)):
        d = board.doc(id_, version)
        return ok({**_dump(d), "versions": board.store.doc_versions(id_)})

    @app.get("/v1/docs")
    def doc_query(doc_type: DocType | None = None, scope: str | None = None, owner_role: Role | None = None,
                  a: Participant = Depends(actor)):
        return ok([board._doc_summary(d) for d in board.store.query("doc", {"doc_type": doc_type, "scope": scope,
                                                                             "owner_role": owner_role})])

    @app.patch("/v1/docs/{id_}")
    def doc_update(id_: str, b: DocPatch, a: Participant = Depends(actor)):
        return ok(_dump(board.doc_update(a, id_, body_md=b.body_md, title=b.title)))

    @app.post("/v1/links")
    def link_create(b: LinkIn, a: Participant = Depends(actor)):
        return ok(_dump(board.link_create(a, from_id=b.from_id, to_id=b.to_id, relation=b.relation)))

    @app.get("/v1/links")
    def link_query(from_id: str | None = None, to_id: str | None = None, relation: Relation | None = None,
                   a: Participant = Depends(actor)):
        return ok(_dump(board.links(from_id=from_id, to_id=to_id, relation=relation)))

    @app.delete("/v1/links/{id_}")
    def link_delete(id_: str, a: Participant = Depends(actor)):
        return ok({"deleted": board.store.delete("link", id_)})

    @app.post("/v1/artifacts")
    def artifact_create(b: ArtifactIn, a: Participant = Depends(actor)):
        return ok(_dump(board.artifact_create(a, form=b.form, uri=b.uri, note=b.note, ticket_id=b.ticket_id)))

    @app.get("/v1/artifacts/{id_}")
    def artifact_get(id_: str, a: Participant = Depends(actor)):
        return ok(_dump(board._get("artifact", id_)))

    # messages / gates -----------------------------------------------------------
    @app.post("/v1/messages")
    def message_send(b: MessageIn, a: Participant = Depends(actor)):
        m = board.message_send(a, ticket_id=b.ticket_id, to=b.to, kind=b.kind, text=b.text, reply_to=b.reply_to)
        return ok(_dump(m), "delivered to the recipient's feed; end your turn if you are waiting for an answer")

    @app.get("/v1/messages")
    def message_query(ticket_id: str | None = None, to: str | None = None, kind: MessageKind | None = None,
                      limit: int = 50, a: Participant = Depends(actor)):
        return ok(_dump(board.store.query("message", {"ticket_id": ticket_id, "to": to, "kind": kind}, limit=limit)))

    @app.post("/v1/gates/{ticket_id}/{gate}/open")
    def gate_open(ticket_id: str, gate: Gate, b: GateOpenIn, a: Participant = Depends(actor)):
        return ok(_dump(board.gate_open(ticket_id, gate, by=a.id, note=b.note)), "the owner is notified")

    @app.post("/v1/gates/{ticket_id}/{gate}/answer")
    def gate_answer(ticket_id: str, gate: Gate, b: GateAnswerIn, a: Participant = Depends(actor)):
        return ok(_dump(board.gate_answer(a, ticket_id, gate, b.answer)))

    @app.get("/v1/gates/{ticket_id}")
    def gates(ticket_id: str, a: Participant = Depends(actor)):
        return ok([e.data for e in board.open_gates(ticket_id)])

    # board / events / find -------------------------------------------------------
    @app.get("/v1/board/{epic_id}")
    def board_view(epic_id: str, a: Participant = Depends(actor)):
        return ok(board.board(epic_id))

    @app.get("/v1/events")
    def events(subject_id: str | None = None, since: int = 0, limit: int = 200, a: Participant = Depends(actor)):
        if subject_id:
            return ok(_dump(board.store.query("event", {"subject_id": subject_id}, limit=limit)))
        return ok([{"seq": s, **_dump(e)} for s, e in board.replay(a, since)][:limit])

    @app.get("/v1/find")
    def find(q: str, k: int = 10, types: str | None = None, a: Participant = Depends(actor)):
        return ok(board.find(q, k=k, types=types.split(",") if types else None))

    # sessions (pool, admin) -----------------------------------------------------
    @app.put("/v1/sessions/{id_}", dependencies=[Depends(admin)])
    def session_upsert(id_: str, b: SessionIn):
        return ok(_dump(board.session_upsert(id_=id_, participant_id=b.participant_id, ticket_id=b.ticket_id,
                                             pool_id=b.pool_id, state=b.state, resume_token=b.resume_token)))

    @app.get("/v1/sessions")
    def sessions(participant_id: str | None = None, ticket_id: str | None = None, state: SessionState | None = None,
                 a: Participant = Depends(actor)):
        return ok(_dump(board.store.query("session", {"participant_id": participant_id, "ticket_id": ticket_id,
                                                      "state": state})))

    # feed (SSE) ------------------------------------------------------------------
    @app.get("/v1/feed")
    async def feed(since: int = Query(default=-1), a: Participant = Depends(actor)):
        async def gen() -> AsyncIterator[bytes]:
            q = board.subscribe(a.id)
            try:
                start = since if since >= 0 else board.store.max_seq()
                for s, e in board.replay(a, start):
                    yield f"data: {json.dumps({'seq': s, **_dump(e)})}\n\n".encode()
                yield b": ready\n\n"
                while True:
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15)
                        s = board.store.seq_of("event", e.id)
                        yield f"data: {json.dumps({'seq': s, **_dump(e)})}\n\n".encode()
                    except asyncio.TimeoutError:
                        yield b": ping\n\n"
            finally:
                board.unsubscribe(a.id, q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    from .ui import router as ui_router

    app.include_router(ui_router(board))

    if os.environ.get("EDP8_PLANE_URL"):
        from .plane_adapter import start_mirror_thread, webhook_router

        app.include_router(webhook_router(board))
        start_mirror_thread(board)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


def run() -> None:
    import uvicorn

    host = os.environ.get("EDP8_HOST", "127.0.0.1")
    port = int(os.environ.get("EDP8_PORT", "9400"))
    uvicorn.run(create_app(), host=host, port=port, log_level=os.environ.get("EDP8_LOG", "warning"))


if __name__ == "__main__":
    run()
