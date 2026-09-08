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
import secrets
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import pool_adapter
from .board import Board, BoardError
from .schemas import (
    DESCRIBE,
    OBJECT_TYPES,
    ArtifactForm,
    Check,
    DocType,
    EventKind,
    Gate,
    MessageKind,
    Participant,
    Relation,
    Role,
    SessionState,
    StatusValue,
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
    description: str = ""
    tags: list[str] | None = None


class TicketPatch(BaseModel):
    status: TicketStatus | None = None
    assignee: str | None = None
    design_ref: str | None = None
    description: str | None = None
    tags: list[str] | None = None


class CriterionIn(BaseModel):
    ticket_id: str
    text: str
    check: Check
    checked_by: str | None = None  # accepted for one release, ignored unless owner + override_reason
    override_reason: str | None = None


class CriterionPatch(BaseModel):
    model_config = {"extra": "forbid"}  # unknown kwargs error out — never a silent drop
    evidence_ref: str | None = None
    verdict: Verdict | None = None
    text: str | None = None
    evidence_version: int | None = None  # the doc version this verdict signs off (design §14)
    stale_ok: bool = False  # rule an older doc version deliberately


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
    artifacts: list[str] | None = None  # staged upload ids to finalise onto this ticket (§18.1)


class StatusIn(BaseModel):
    status: StatusValue
    note: str = ""
    to: str | None = None
    ticket_id: str | None = None


class ResolveIn(BaseModel):
    ticket_id: str
    to: str | None = None
    kind: MessageKind = MessageKind.question


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
    reason: str = ""
    presence_stale: bool = False  # sweep had no fresh answer for a live row: keep prev state, no event


class SessionSpawnIn(BaseModel):
    """Body for POST /v1/sessions/spawn (S20 pool control plane)."""
    role: Role
    participant_id: str
    ticket_id: str | None = None  # for architect authz (target seat's epic); optional for owner
    parent_session: str | None = None
    model: str | None = None
    mode: str | None = None


class SessionActionIn(BaseModel):
    """Body for POST /v1/sessions/{resume,reap,close}."""
    participant_id: str
    ticket_id: str | None = None
    reason: str = ""


class ServiceEventIn(BaseModel):
    """Body for POST /v1/service_event — the launcher records a service_restarted (design §22)."""
    service: str
    reason: str
    by: str = "supervisor"
    git_rev: str = "unknown"


# --------------------------------------------------------------- public-mode reach (S17)

DEFAULT_ADMIN_TOKEN = "dev"


def public_mode() -> bool:
    """Reach-from-another-machine is on when EDP8_PUBLIC_URL is set (design §15, S17)."""
    return bool(os.environ.get("EDP8_PUBLIC_URL"))


def resolve_host() -> str:
    """Bind address. Public mode defaults to 0.0.0.0 so another machine can reach the
    board; EDP8_HOST always overrides (even in public mode). Trusted mode → 127.0.0.1."""
    explicit = os.environ.get("EDP8_HOST")
    if explicit:
        return explicit
    return "0.0.0.0" if public_mode() else "127.0.0.1"


def tokens_file_path() -> Path:
    return Path(os.environ.get("EDP8_TOKENS", str(Path(os.environ.get("EDP8_HOME", ".")) / "tokens.json")))


def public_startup_error(admin_token: str | None, tokens_path: Path | None = None) -> str | None:
    """§15/§20 fail-closed gate for public mode. Returns a one-line plain reason to REFUSE
    start (never bind to the network open), or None when it is safe. Trusted mode is the
    default and one env var away — this is only consulted when EDP8_PUBLIC_URL is set."""
    if (admin_token or DEFAULT_ADMIN_TOKEN) == DEFAULT_ADMIN_TOKEN:
        return ("refusing public start: EDP8_PUBLIC_URL is set but EDP8_ADMIN_TOKEN is the default "
                "'dev'. Set EDP8_ADMIN_TOKEN to a non-default secret.")
    f = tokens_path or tokens_file_path()
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
    except (OSError, ValueError):
        return (f"refusing public start: {f} is missing or invalid. Public mode needs credentials "
                "for every participant (humans + agents) — no host may act header-only from the network.")
    humans = {k: v for k, v in raw.items() if k != "agents"}
    agents = raw.get("agents")
    if not humans:
        return f"refusing public start: {f} has no human credentials (top-level handle→secret entries)."
    if not isinstance(agents, dict) or not agents:
        return (f"refusing public start: {f} has no agent credentials. Seed at least one agent secret "
                "under 'agents' (S20 mints them at spawn), or run one spawn in trusted mode first.")
    return None


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
    try:
        board.ensure_epic_ids()
    except Exception as e:  # noqa: BLE001
        logging.getLogger("edp8.service").warning("epic_id backfill failed: %s", e)
    app = FastAPI(title="edp8 board", version="0.8.0")
    app.state.board = board

    # Reach-from-another-machine (S17, design §15). Public mode fails closed BEFORE the app is
    # usable: no default admin token, credentials for every participant type, and header-only
    # requests refused at actor(). Trusted single-machine mode is the default and unchanged.
    public = public_mode()
    if public:
        err = public_startup_error(admin_token, tokens_file_path())
        if err:
            raise RuntimeError(err)

    def _tokens_file() -> Path:
        return tokens_file_path()

    def _tokens() -> tuple[dict[str, str], dict[str, str]]:
        """(humans, agents) handle -> secret, read from tokens.json (top-level keys are
        HUMANS; the `agents` sub-map is AGENT seat secrets minted at spawn by S20). Absent
        file = trusted single-machine mode (({}, {}) — header-only identity for everyone)."""
        f = _tokens_file()
        try:
            mtime = f.stat().st_mtime
        except OSError:
            return {}, {}
        cache = getattr(_tokens, "_cache", None)
        if cache and cache[0] == (str(f), mtime):
            return cache[1]
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            agents = {str(k).lstrip("@"): str(v) for k, v in (raw.get("agents") or {}).items()}
            humans = {str(k).lstrip("@"): str(v) for k, v in raw.items() if k != "agents"}
        except (OSError, ValueError, AttributeError):
            humans, agents = {}, {}
        _tokens._cache = ((str(f), mtime), (humans, agents))  # type: ignore[attr-defined]
        return humans, agents

    def _verify_token(p: Participant, token: str | None) -> str | None:
        """Return an error message if p's token is required and wrong, else None. An agent is
        verified exactly as a human (§20 finding 1): its secret lives in tokens.json's `agents`
        map. Trusted mode: a participant with no configured secret is header-only. Public mode
        (S17): a participant with no credential is REFUSED — no host acts header-only over the net."""
        humans, agents = _tokens()
        secret = (humans if p.type == "human" else agents).get(p.handle.lstrip("@"))
        if secret is None:
            if public:  # fail closed: an uncredentialed participant cannot act from the network
                return f"X-Token required for {p.type} participant {p.handle!r} (public mode)"
            return None
        if token != secret:
            return f"X-Token required for {p.type} participant {p.handle!r}"
        return None

    def actor(x_participant: str | None = Header(default=None),
              x_token: str | None = Header(default=None)) -> Participant:
        if not x_participant:
            raise HTTPException(401, "X-Participant header missing (participant id or @handle)")
        try:
            p = board.participant(x_participant)
        except BoardError as e:
            raise HTTPException(401, e.message)
        err = _verify_token(p, x_token)
        if err:
            raise HTTPException(401, err)
        return p

    def human_verify(handle: str, token: str | None) -> Participant:
        """The /ui/me forms authenticate through the same gate as the API."""
        try:
            p = board.participant(handle)
        except BoardError as e:
            raise HTTPException(401, e.message)
        err = _verify_token(p, token)
        if err:
            raise HTTPException(401, err.replace("X-Token required for", "token required for"))
        return p

    def _mint_agent_token(handle: str) -> str | None:
        """Mint and persist a per-seat secret into tokens.json's `agents` map for `handle`,
        returning it. Trusted mode (no tokens.json) → None: nothing to inject, the shell is
        header-only. Rewrites the file atomically-ish; the mtime bump invalidates _tokens cache."""
        f = _tokens_file()
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (OSError, ValueError):
            data = {}
        agents = data.get("agents")
        if not isinstance(agents, dict):
            agents = {}
        secret = secrets.token_urlsafe(24)
        agents[handle.lstrip("@")] = secret
        data["agents"] = agents
        tmp = f.with_suffix(f.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, f)
        return secret

    # §24 finding 4: auto-paired reviewer/qa seats spawn through the board, so give the board the
    # same token minter the service spawn route uses — the seat gets its EDP8_TOKEN injected and can
    # authenticate in public mode (trusted mode mints None and injects nothing, unchanged).
    board._mint_token = _mint_agent_token

    def admin(x_admin: str | None = Header(default=None)) -> None:
        if x_admin != admin_token:
            raise HTTPException(403, "X-Admin token invalid")

    # pool control plane (S20) ---------------------------------------------------
    _idem: dict[tuple[str, str], tuple[float, dict]] = {}
    _IDEM_TTL = 600.0  # an Idempotency-Key is honoured for 10 minutes (design §15/§20-1)

    def _idem_get(a: Participant, key: str | None) -> dict | None:
        if not key:
            return None
        now = time.time()
        for k in [k for k, (exp, _) in _idem.items() if exp < now]:
            _idem.pop(k, None)
        hit = _idem.get((a.id, key))
        return hit[1] if hit else None

    def _idem_put(a: Participant, key: str | None, result: dict) -> None:
        if key:
            _idem[(a.id, key)] = (time.time() + _IDEM_TTL, result)

    def _target_epic(participant_id: str | None, ticket_id: str | None) -> str | None:
        if ticket_id:
            return board._epic_id_of(ticket_id)
        if participant_id and "." in participant_id:
            return board._epic_id_of(participant_id.split(".", 1)[1])
        return None

    def _authorize_pool_op(a: Participant, participant_id: str | None, ticket_id: str | None) -> None:
        """Owner: any seat. Architect: only seats in its own epic. Everyone else: refused with a
        §19 error naming the allowed roles (design §15/§20 finding 1)."""
        allowed = ["owner", "architect (own epic only)"]
        if a.role == Role.owner:
            return
        if a.role == Role.architect:
            epic = _target_epic(participant_id, ticket_id)
            if epic and epic in board.my_epics(a):
                return
            raise HTTPException(403, json.dumps({
                "message": f"architect {a.handle!r} may only operate seats in its own epic"
                           + (f" (target epic {epic})" if epic else "; target epic could not be resolved"
                              " — pass ticket_id"),
                "allowed": allowed}))
        raise HTTPException(403, json.dumps({
            "message": f"role {a.role.value!r} may not operate the pool control plane", "allowed": allowed}))

    def _pool_result(out: dict):
        """Pass a pool success through; map a pool failure to a {code,message,hint} envelope with
        the right HTTP status and a next-step hint (design §20 finding 15)."""
        if out.get("ok"):
            return out
        code = (out.get("error") or {}).get("code", "pool")
        hint = out.get("hint") or ("start the pool (edp-pool) and retry" if code == "unavailable"
                                   else "check the edp-pool logs; retry or pick a different verb")
        out = {**out, "hint": hint}
        return JSONResponse(status_code=503 if code == "unavailable" else 502, content=out)

    @app.exception_handler(BoardError)
    async def _board_error(_: Request, e: BoardError):
        return JSONResponse(status_code=409 if e.code in ("transition", "conflict") else 400, content=e.to_dict())

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, e: HTTPException):
        # a 403 whose detail is our JSON {message, allowed} renders as a §19 forbidden envelope
        if e.status_code == 403 and isinstance(e.detail, str) and e.detail.startswith("{"):
            try:
                d = json.loads(e.detail)
                return JSONResponse(status_code=403, content={
                    "ok": False, "error": {"code": "forbidden", "message": d.get("message", ""),
                                           "allowed": d.get("allowed", [])},
                    "hint": "sign as owner, or as the architect of this epic"})
            except ValueError:
                pass
        return JSONResponse(status_code=e.status_code,
                            content={"ok": False, "error": {"code": "http", "message": str(e.detail)}, "hint": ""})

    # JSON API over the same view derivations (design §4.1, was S3): the SPA reads these; the
    # legacy /ui renders from the identical views.py functions, so they can never drift. Included
    # HERE (ahead of the dynamic /v1/tickets/{id} and /v1/docs/{id} routes) so its static
    # sub-paths — /v1/tickets/table, /v1/epics/{id}/page, /v1/docs/{id}/html — win the match;
    # Starlette resolves routes in registration order (design §4.1 note: "after the /v1 block"
    # assumed no static-under-dynamic collision; /v1/tickets/table is one, so it registers first).
    from .api_views import views_router

    app.include_router(views_router(board, actor))

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

    @app.get("/v1/inbox")
    def inbox(a: Participant = Depends(actor)):
        rows = board.inbox(a)
        return ok(rows, "" if rows else "inbox clear")

    @app.get("/v1/close_check")
    def close_check(a: Participant = Depends(actor)):
        return ok(board.close_check(a))

    # registry (admin) -----------------------------------------------------------
    @app.post("/v1/participants")
    def participant_create(b: ParticipantIn, x_admin: str | None = Header(default=None),
                           x_participant: str | None = Header(default=None),
                           x_token: str | None = Header(default=None)):
        # admin registers anyone; a spawner role (coordinator/engineer/architect) registers AGENT participants
        # for the tickets it spawns shells on — the scope a per-ticket spawn needs, nothing more.
        if x_admin != admin_token:
            if not x_participant:
                raise HTTPException(403, "X-Admin token invalid (or sign as a spawner role with X-Participant)")
            try:
                a = board.participant(x_participant)
            except BoardError as e:
                raise HTTPException(401, e.message)
            err = _verify_token(a, x_token)  # same gate as actor(): public mode refuses header-only
            if err:
                raise HTTPException(401, err)
            if a.role not in (Role.owner, Role.coordinator, Role.engineer, Role.architect) or b.type != "agent":
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
                                parent_id=b.parent_id, assignee=b.assignee, description=b.description,
                                tags=b.tags)
        if t.kind == TicketKind.epic:
            hint = "epic created; an architect designs it (doc_create design, criteria, stories)"
        elif t.kind == TicketKind.task:
            hint = ("task created under its story — work it with the low-level craft; "
                    "evidence lands on the story's criteria")
        else:
            hint = "add criteria before it becomes ready"
        return ok(_dump(t), hint)

    @app.get("/v1/tickets/{id_}")
    def ticket_get(id_: str, include: str | None = None, thread_limit: int = 20, a: Participant = Depends(actor)):
        view = board.ticket_view(id_, include=include.split(",") if include else None, thread_limit=thread_limit)
        # flat ticket fields at the top level (back-compat) + every section
        return ok({**view["ticket"], **{k: v for k, v in view.items() if k != "ticket"}},
                  "one read: chain, criteria, docs(+relation), children(+assignee_role), blockers, open_gates, "
                  "thread tail (thread_seq = newest seq; message_query(since_seq=…) for what follows)")

    @app.get("/v1/tickets")
    def ticket_query(kind: TicketKind | None = None, work_type: WorkType | None = None,
                     parent_id: str | None = None, status: TicketStatus | None = None,
                     assignee: str | None = None, epic_id: str | None = None, created_by: str | None = None,
                     tag: str | None = None, q: str | None = None, a: Participant = Depends(actor)):
        rows = board.store.query("ticket", {"kind": kind, "work_type": work_type, "parent_id": parent_id,
                                            "status": status, "assignee": assignee, "epic_id": epic_id,
                                            "created_by": created_by}, limit=5000)
        if tag:
            rows = [t for t in rows if tag in (t.tags or [])]
        if q:
            hit_ids = [h["id"] for h in board.store.fts_search(q, types={"ticket"}, limit=500)]
            order = {i: n for n, i in enumerate(hit_ids)}
            rows = sorted([t for t in rows if t.id in order], key=lambda t: order[t.id])
        return ok(_dump(rows))

    @app.patch("/v1/tickets/{id_}")
    def ticket_update(id_: str, b: TicketPatch, a: Participant = Depends(actor)):
        t = board.ticket_update(a, id_, status=b.status, assignee=b.assignee, design_ref=b.design_ref,
                                description=b.description, tags=b.tags)
        hint = ""
        if b.status == TicketStatus.in_progress and t.kind == TicketKind.story:
            hint = ("bigger than one sitting? split it into task tickets NOW (ticket_create kind=task) — "
                    "a compaction/respawn resumes from the task list, not from lost context")
        return ok(_dump(t), hint)

    # criteria -----------------------------------------------------------------
    @app.post("/v1/criteria")
    def criterion_create(b: CriterionIn, a: Participant = Depends(actor)):
        c = board.criterion_create(a, ticket_id=b.ticket_id, text=b.text, check=b.check,
                                   checked_by=b.checked_by, override_reason=b.override_reason)
        hint = ""
        if b.checked_by and b.checked_by != c.checked_by:
            hint = (f"checked_by is ignored — the board derived checked_by={c.checked_by} from this "
                    f"ticket (design §24.1); an owner override needs override_reason")
        elif b.checked_by and b.checked_by == c.checked_by and a.role == Role.owner and b.override_reason:
            hint = f"owner override recorded: checked_by={c.checked_by}"
        return ok(_dump(c), hint)

    @app.get("/v1/criteria")
    def criterion_query(ticket_id: str, a: Participant = Depends(actor)):
        return ok(_dump(board.criteria(ticket_id)))

    @app.patch("/v1/criteria/{id_}")
    def criterion_update(id_: str, b: CriterionPatch, a: Participant = Depends(actor)):
        c = board.criterion_update(a, id_, evidence_ref=b.evidence_ref, verdict=b.verdict, text=b.text,
                                   evidence_version=b.evidence_version, stale_ok=b.stale_ok)
        pending = [x.id for x in board.criteria(c.ticket_id) if x.verdict != Verdict.passed]
        return ok(_dump(c), f"{len(pending)} criteria not yet passed on {c.ticket_id}" if pending else
                  "all criteria passed; the ticket can be marked done by its checker")

    # docs / links / artifacts ---------------------------------------------------
    @app.post("/v1/docs")
    def doc_create(b: DocIn, a: Participant = Depends(actor)):
        d = board.doc_create(a, doc_type=b.doc_type, title=b.title, body_md=b.body_md, scope=b.scope)
        if b.doc_type in (DocType.strategy_hl, DocType.strategy_ll):
            hint = ("link it: extends -> its parent layer (doc), uses_strategy -> the epic; "
                    "assemble_ruleset composes the chain at read time")
        else:
            hint = ("link it: link_create(from_id=<ticket>, to_id=<doc>, "
                    "relation=designed_by|uses_strategy|uses_domain|evidence_for)")
        return ok(_dump(d), hint)

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

    @app.post("/v1/artifacts/upload")
    async def artifact_upload(file: UploadFile = File(...), note: str = Form(default=""),
                              ticket_id: str | None = Form(default=None), a: Participant = Depends(actor)):
        """Drop a file, get a STAGED artifact (design §18.1). The bytes stream to disk under a
        25 MB cap; the type is SNIFFED from them (the client's name/Content-Type are never
        trusted); an SVG is stored as a file, never an inline image. The artifact is invisible
        until a message finalises it — attach it with POST /v1/messages artifacts:[id]."""
        from . import uploads
        buf = bytearray()
        head = b""
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > uploads.MAX_UPLOAD_BYTES:
                return JSONResponse(status_code=413, content={"ok": False, "error": {"code": "too_large",
                    "message": f"the file is over the {uploads.MAX_UPLOAD_BYTES // (1024 * 1024)} MB upload limit"},
                    "hint": "compress it or share a link instead"})
            if len(head) < 4096:
                head = bytes(buf[:4096])
        ctype = uploads.sniff_upload(head, file.filename or "")
        if ctype is None:
            return JSONResponse(status_code=415, content={"ok": False, "error": {"code": "unsupported_type",
                "message": "that file type is not accepted; allowed: images, pdf, text, markdown, json, log, zip, svg"},
                "hint": "the type is read from the file's bytes, not its name"})
        form = ArtifactForm.image if uploads.is_inline_image(ctype) else ArtifactForm.file
        art = board.artifact_upload(a, form=form, content_type=ctype, filename=file.filename or "", note=note)
        (uploads.uploads_dir() / f"{art.id}.{uploads.ext_for(ctype)}").write_bytes(bytes(buf))
        return ok(_dump(art), "staged; post a message with artifacts:[this id] to attach it — "
                              "unfinalised uploads are swept after 24 h")

    @app.get("/v1/artifacts/{id_}/content")
    def artifact_content(id_: str, a: Participant = Depends(actor)):
        """Serve an uploaded artifact's bytes with the sniffed type. Never sniffs in the browser
        (X-Content-Type-Options: nosniff) and forces a download for everything but the four inline
        image types — an uploaded SVG is thus never rendered (design §18.1)."""
        from . import uploads
        art = board._get("artifact", id_, "artifact")
        ctype = art.content_type or "application/octet-stream"
        path = uploads.uploads_dir() / f"{id_}.{uploads.ext_for(ctype)}"
        if not path.exists():
            raise BoardError("not_found", f"artifact {id_} has no stored content")
        disp = "inline" if uploads.is_inline_image(ctype) else "attachment"
        name = art.filename or path.name
        return FileResponse(path, media_type=ctype, headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"{disp}; filename=\"{name}\""})

    @app.get("/v1/artifacts/{id_}")
    def artifact_get(id_: str, a: Participant = Depends(actor)):
        return ok(_dump(board._get("artifact", id_)))

    # messages / gates -----------------------------------------------------------
    # Addressed traffic and @mentions are mirrored into edp-broker inboxes
    # (best-effort): the broker is the wake plane — the pool resumes a parked
    # shell when its inbox grows, and every shell's feed monitor tails its inbox.
    from . import broker_adapter, delivery

    @app.post("/v1/messages")
    def message_send(b: MessageIn, a: Participant = Depends(actor)):
        from . import views
        # §18.1: finalise any staged uploads BEFORE the message posts — all-or-nothing, so a bad
        # artifact id raises here and nothing (message or artifact) becomes visible.
        was_staged = [x for x in (b.artifacts or [])
                      if getattr(board.store.get("artifact", x), "staged", False)]
        if b.artifacts:
            board.artifact_finalise(a, artifact_ids=b.artifacts, ticket_id=b.ticket_id)
        try:
            m = board.message_send(a, ticket_id=b.ticket_id, to=b.to, kind=b.kind, text=b.text, reply_to=b.reply_to)
        except Exception:
            if was_staged:  # all-or-nothing: the message failed, so nothing it carried becomes visible
                board.artifact_unfinalise(artifact_ids=was_staged, ticket_id=b.ticket_id)
            raise
        delivery.after_message(board, a.id, m)
        note = getattr(board, "last_send_note", "")
        hint = "delivered to the recipient's feed; end your turn if you are waiting for an answer"
        # unresolved_mentions: @handles that match no participant — the message posted, but nobody
        # was woken for these (design §4.1). The caller surfaces them so a typo'd @handle is visible.
        return ok({**_dump(m), "unresolved_mentions": views.unresolved_mentions(board, b.text)},
                  f"{note}; {hint}" if note else hint)

    @app.post("/v1/status")
    def record_status(b: StatusIn, a: Participant = Depends(actor)):
        m, recipients = board.record_status(a, status=b.status, note=b.note, to=b.to, ticket_id=b.ticket_id)
        told = delivery.after_status(board, a.id, m, recipients)
        return ok({"message": _dump(m), "told": told},
                  "status recorded; next: close_self() (resident seats: keep listening)")

    @app.post("/v1/service_event")
    def service_event(b: ServiceEventIn, _: None = Depends(admin)):
        """The launcher's supervisor (or `start.* --restart`) records that it restarted a shared
        service (design §22 rule 3). Admin-guarded: only the launcher, which holds the admin token,
        may post it. Delivery to the owner/architect listening set is S18's job; here we just record."""
        ev = board._emit(f"service/{b.service}", EventKind.service_restarted,
                         {"service": b.service, "reason": b.reason, "by": b.by, "git_rev": b.git_rev})
        return ok({"event": ev.id, "service": b.service, "reason": b.reason},
                  "service_restarted recorded on the board event log")

    @app.get("/v1/messages")
    def message_query(ticket_id: str | None = None, to: str | None = None, kind: MessageKind | None = None,
                      created_by: str | None = None, since_seq: int | None = None, limit: int = 50,
                      a: Participant = Depends(actor)):
        rows = board.store.query_seq("message", {"ticket_id": ticket_id, "to": to, "kind": kind,
                                                 "created_by": created_by}, since_seq=since_seq, limit=100000)
        rows = rows[-limit:] if since_seq is None else rows[:limit]
        out = [{**_dump(m), "seq": seq} for seq, m in rows]
        return ok(out, f"last_seq={rows[-1][0] if rows else (since_seq or 0)}; pass it as since_seq next time "
                       "to get only what is new")

    @app.post("/v1/messages/resolve")
    def message_resolve(b: ResolveIn, a: Participant = Depends(actor)):
        r = board.resolve(a, ticket_id=b.ticket_id, to=b.to, kind=b.kind)
        return ok(r, "wake preview only — nothing was sent; `wakes`/`plan` are the same list "
                     "(each {recipient, reason, why}); an empty list means nobody is woken")

    @app.get("/v1/messages/{id_}")
    def message_get(id_: str, a: Participant = Depends(actor)):
        return ok(board.message_read(id_))

    @app.post("/v1/gates/{ticket_id}/{gate}/open")
    def gate_open(ticket_id: str, gate: Gate, b: GateOpenIn, a: Participant = Depends(actor)):
        ev = board.gate_open(ticket_id, gate, by=a.id, note=b.note)
        who = delivery.after_gate_open(board, a.id, ticket_id, gate.value, b.note)
        return ok(_dump(ev), f"{who} is notified" if who else
                  "this epic has no human owner: the gate stands on the board for whoever opens the epic page")

    @app.post("/v1/gates/{ticket_id}/{gate}/answer")
    def gate_answer(ticket_id: str, gate: Gate, b: GateAnswerIn, a: Participant = Depends(actor)):
        ev = board.gate_answer(a, ticket_id, gate, b.answer)
        delivery.after_gate_answer(board, a.id, ticket_id, gate.value, b.answer)
        return ok(_dump(ev))

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
    def find(q: str, k: int = 10, types: str | None = None, epic_id: str | None = None,
             a: Participant = Depends(actor)):
        return ok(board.find(q, k=k, types=types.split(",") if types else None, epic_id=epic_id),
                  "hits carry ticket_id/epic_id; ticket_read(id) or doc_read(id) for the full object")

    # sessions (pool, admin) -----------------------------------------------------
    @app.put("/v1/sessions/{id_}", dependencies=[Depends(admin)])
    def session_upsert(id_: str, b: SessionIn):
        prev = board.store.get("session", id_)
        s = board.session_upsert(id_=id_, participant_id=b.participant_id, ticket_id=b.ticket_id,
                                 pool_id=b.pool_id, state=b.state, resume_token=b.resume_token,
                                 reason=b.reason, presence_stale=b.presence_stale)
        # a death/stall TRANSITION is crucial: besides the shell_dead feed event, drop a durable
        # crashed notice in the owner's broker inbox (the recovery seat wakes even if its feed
        # stream happened to be down at that moment). Clean closes (finish/reap/clean exit)
        # carry their reason and are marked clean so nobody treats them as failures.
        # A presence-stale upsert is a MISSED PROBE, not a death: the state did not change and
        # no crashed notice is sent (design §18.3 — silence is never rendered as Closed).
        if (not b.presence_stale and s.state in (SessionState.dead, SessionState.stalled)
                and (prev is None or prev.state != s.state)):
            clean = any(k in (b.reason or "").lower() for k in ("closed by self", "reaped", "clean exit"))
            who = board.recovery_seat(b.ticket_id, exclude={b.participant_id}) if b.ticket_id else None
            if who:  # THIS epic's human owner, else its live resident architect — never a shared handle
                broker_adapter.publish("pool", who, "fyi" if clean else "crashed",
                                       {"participant": b.participant_id, "ticket_id": b.ticket_id,
                                        "session_id": id_, "state": b.state.value,
                                        "reason": b.reason, "clean": clean})
        return ok(_dump(s))

    @app.get("/v1/sessions")
    def sessions(participant_id: str | None = None, ticket_id: str | None = None, state: SessionState | None = None,
                 a: Participant = Depends(actor)):
        return ok(_dump(board.store.query("session", {"participant_id": participant_id, "ticket_id": ticket_id,
                                                      "state": state})))

    # pool control plane: spawn/resume/reap/close proxy edp-pool (S20) ------------
    def _pool_down_envelope() -> dict[str, Any]:
        """A plain sentence naming when the pool was last seen, within 2s — never a 90s hang
        (design §22 rule 4). The launcher's supervisor records pool freshness under v8/.run/."""
        from . import run_state
        rec = run_state.read("pool") or {}
        since = rec.get("last_ok") or rec.get("started_at") or "an unknown time"
        return {"ok": False, "error": {"code": "unavailable",
                "message": f"pool is down (no response since {since}); the launcher's supervisor "
                           "restarts it — retry shortly, or run `start.* --restart pool`."},
                "hint": "seats never start the pool themselves (design §22); the launcher owns it"}

    @app.post("/v1/sessions/spawn")
    def session_spawn(b: SessionSpawnIn, a: Participant = Depends(actor),
                      idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        if not pool_adapter.reachable():
            return _pool_down_envelope()
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay: same session, no second shell"}
        token = _mint_agent_token(b.participant_id)
        env = {"EDP8_TOKEN": token} if token else None
        out = pool_adapter.spawn(b.role.value, b.participant_id, parent_session=b.parent_session,
                                 model=b.model, mode=b.mode, env=env)
        if out.get("ok"):
            _idem_put(a, idempotency_key, out)
            return out
        return _pool_result(out)

    @app.post("/v1/sessions/resume")
    def session_resume(b: SessionActionIn, a: Participant = Depends(actor),
                       idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        if not pool_adapter.reachable():
            return _pool_down_envelope()
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay"}
        # accept CLOSED participants: a done pool row resumes from its stored session id (§18.3)
        got = pool_adapter.sessions()
        closed = False
        if got.get("ok"):
            rows = got["value"] if isinstance(got["value"], list) else (got.get("value") or {}).get("sessions", [])
            closed = any(s.get("handle") == b.participant_id and s.get("state") == "done" for s in rows)
        out = (pool_adapter.resume_closed(b.participant_id) if closed
               else pool_adapter.resume(b.participant_id))
        if out.get("ok"):
            _idem_put(a, idempotency_key, out)
            return out
        return _pool_result(out)

    @app.post("/v1/sessions/reap")
    def session_reap(b: SessionActionIn, a: Participant = Depends(actor),
                     idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay"}
        out = pool_adapter.reap(b.participant_id)
        if out.get("ok"):
            _idem_put(a, idempotency_key, out)
            return out
        return _pool_result(out)

    @app.post("/v1/sessions/close")
    def session_close(b: SessionActionIn, a: Participant = Depends(actor),
                      idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay"}
        out = pool_adapter.close(b.participant_id, b.reason or "closed via board")
        if out.get("ok"):
            _idem_put(a, idempotency_key, out)
            return out
        return _pool_result(out)

    @app.get("/v1/pool/capabilities")
    def pool_capabilities(a: Participant = Depends(actor)):
        """What the pool supports, read live (never hard-coded). Pool unreachable → every
        capability false plus a reason, so the UI hides pool controls rather than guessing."""
        keys = ("resume_parked", "resume_closed", "park", "spawn")
        out = pool_adapter.capabilities()
        if out.get("ok") and isinstance(out.get("value"), dict):
            v = out["value"]
            return ok({k: bool(v.get(k, False)) for k in keys},
                      "the UI reads these to decide which pool controls to show (S10 Resume, S16 spawn)")
        reason = (out.get("error") or {}).get("message", "pool unreachable")
        return ok({**{k: False for k in keys}, "reason": reason},
                  "pool unreachable — every capability false; the UI hides pool controls")

    # feed (SSE) ------------------------------------------------------------------
    @app.get("/v1/listening")
    def listening(a: Participant = Depends(actor)):
        return ok(board.listening(a.role.value),
                  "your listening contract — what wakes you, how to get what does not, how to reach the architect")

    @app.get("/v1/feed")
    async def feed(since: int = Query(default=-1), a: Participant = Depends(actor)):
        def frame(s: int | None, e) -> bytes:
            # every event carries WHY this subscriber was woken (design §16.2 rule 5) so a seat
            # can tell a page from a courtesy copy
            return f"data: {json.dumps({'seq': s, 'why': board.why(e, a), **_dump(e)})}\n\n".encode()

        async def gen() -> AsyncIterator[bytes]:
            q = board.subscribe(a.id)
            try:
                start = since if since >= 0 else board.store.max_seq()
                for s, e in board.replay(a, start):
                    yield frame(s, e)
                yield b": ready\n\n"
                while True:
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15)
                        yield frame(board.store.seq_of("event", e.id), e)
                    except asyncio.TimeoutError:
                        yield b": ping\n\n"
            finally:
                board.unsubscribe(a.id, q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    if os.environ.get("EDP_POOL_URL") or os.environ.get("EDP8_POOL_WATCH"):
        import threading

        def _pool_watch() -> None:
            import time

            from . import pool_adapter
            log = logging.getLogger("edp8.poolwatch")
            time.sleep(5)  # let the server start listening
            while True:
                try:
                    out = pool_adapter.sync_sessions(board_url=None, admin_token=admin_token)
                    if not out.get("ok"):
                        log.warning("pool session mirror failed: %s", out.get("error"))
                except Exception as e:
                    log.warning("pool watcher error: %s", e)
                try:
                    # design §24 rule 3: drain the checker-pairing queue on the same tick — spawn a
                    # reviewer/qa whose RAM headroom is now sufficient, retry the ones still under the
                    # seat floor (the queued-note guard keeps the retry quiet).
                    res = board.run_pending_pairings()
                    if res.get("spawned"):
                        log.info("paired checkers: %s", res["spawned"])
                except Exception as e:
                    log.warning("pairing drain error: %s", e)
                time.sleep(10)  # death-detection latency rides this cadence

        threading.Thread(target=_pool_watch, name="edp8-pool-watch", daemon=True).start()

    from .ui import router as ui_router

    app.include_router(ui_router(board, verify=human_verify))

    # SPA (Folio) mounted AFTER the legacy router so /ui/poll and every /v1 route keep
    # priority; the catch-all only matches under its prefix. Missing build → 503 page,
    # never a failed create_app() (webapp/serve.py).
    from .webapp import mount_spa

    mount_spa(app, os.environ.get("EDP8_WEB_PREFIX", "/app"))

    if os.environ.get("EDP8_PLANE_URL"):
        from .plane_adapter import start_mirror_thread, webhook_router

        app.include_router(webhook_router(board))
        start_mirror_thread(board)

    # §18.1: reap staged uploads nobody finalised — once at startup, then hourly.
    try:
        swept = board.sweep_staged_artifacts()
        if swept:
            logging.getLogger("edp8.service").info("swept %d stale staged upload(s)", len(swept))
    except Exception as e:  # noqa: BLE001 — a sweep failure must never block startup
        logging.getLogger("edp8.service").warning("staged-artifact sweep failed: %s", e)
    if os.environ.get("EDP8_UPLOAD_SWEEP", "1") != "0":
        import threading

        def _sweep_loop() -> None:
            import time
            log = logging.getLogger("edp8.uploadsweep")
            while True:
                time.sleep(3600)
                try:
                    board.sweep_staged_artifacts()
                except Exception as e:
                    log.warning("hourly staged-artifact sweep failed: %s", e)

        threading.Thread(target=_sweep_loop, name="edp8-upload-sweep", daemon=True).start()

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/v1/health")
    def v1_health():
        """Uniform health route the launcher's supervisor probes (design §22 rule 3), same
        shape the pool and broker expose. No auth: it is the liveness probe."""
        from . import run_state
        return {"ok": True, "service": "board", "version": app.version, "git_rev": run_state.git_rev()}

    return app


def run() -> None:
    import sys

    import uvicorn

    host = resolve_host()  # 0.0.0.0 in public mode (EDP8_PUBLIC_URL), else 127.0.0.1; EDP8_HOST overrides
    port = int(os.environ.get("EDP8_PORT", "9400"))
    try:
        app = create_app()  # public mode fails closed here with a plain message
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e
    uvicorn.run(app, host=host, port=port, log_level=os.environ.get("EDP8_LOG", "warning"))


if __name__ == "__main__":
    run()
