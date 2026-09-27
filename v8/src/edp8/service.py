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
import threading
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError

from . import __version__, pool_adapter, seat_choice, settings
from . import workflow as wflow
from edp_contracts.settings import secrets as secret_files
from . import rsi  # S18: imported at boot so rsi.LOADED hashes the retrieval code this process runs
from .board import QUICK_TAG, Board, BoardError
from .contextual_work import HistoryCategory, contextual_work
from .design_review import DocumentComment, ReviewDecision, comment, decide, source_context
from .doc_tools import DocEdit
from .schemas import (
    DESCRIBE,
    OBJECT_TYPES,
    ArtifactForm,
    Check,
    ClaimBasis,
    ClaimStatus,
    CodeContext,
    DocStatus,
    DocType,
    EventKind,
    Gate,
    MessageKind,
    Participant,
    Relation,
    Role,
    RoleId,
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
    role: RoleId  # a built-in role or a pinned workflow's role (S13; the board validates it)
    handle: str
    location: str | None = None
    model: str | None = None
    id: str | None = None


class TicketIn(BaseModel):
    kind: TicketKind
    work_type: WorkType
    title: str
    words: str | None = None  # epic only: the owner's verbatim request (ruling #32); title may be its short form
    parent_id: str | None = None
    assignee: str | None = None
    description: str = ""
    tags: list[str] | None = None
    workflow: str | None = None  # S13, epic only: 'lean' (latest published) or 'lean@2'; default standard@1


class WorkflowRefIn(BaseModel):
    """S13: POST /v1/workflows/duplicate — copy `ref` into a new draft (`new_id`@1, or its next version)."""
    ref: str
    new_id: str | None = None


class TicketPatch(BaseModel):
    status: TicketStatus | None = None
    title: str | None = None  # a short human title (<=80 chars), epic/story, architect/owner (ruling #32)
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
    note: str = ""  # the checker's reason with a verdict; the board records it as a claim (S-IMPLICIT)


class DocIn(BaseModel):
    doc_type: DocType
    title: str
    body_md: str
    scope: str
    tags: list[str] | None = None
    status: DocStatus | None = None  # active (default) | proposed
    proposes: str | None = None  # proposed: the active doc this would become the next version of
    ticket_id: str | None = None  # proposed: the ticket it came from (its source)


class LibraryImportIn(BaseModel):
    url: str
    scope: str = "global"
    tags: list[str] | None = None


class DocPatch(BaseModel):
    body_md: str | None = None
    title: str | None = None
    tags: list[str] | None = None
    compact: bool = False


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
    # epic-91fcd3b370 S4: a code anchor. Taken raw and validated in the route, so a bad field is a
    # 400 naming `code_context.<field>` (FastAPI's body validation would answer an unnamed 422).
    code_context: Any = None
    # C18 (design-10b21760d9 §14.5): ordered quotes, taken raw and verified in the route (edp8.quotes)
    quotes: Any = None


def code_context_in(raw: Any) -> CodeContext | None:
    """Validate a message's code anchor; a bad field is a BoardError (400) that names it."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BoardError("schema", f"code_context: must be an object, not {type(raw).__name__}",
                         "send the anchor as an object; see describe('message') for its fields")
    try:
        return CodeContext.model_validate(raw)
    except ValidationError as e:
        bad = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            bad.append(f"code_context{'.' + loc if loc else ''}: {err.get('msg')}")
        raise BoardError("schema", "; ".join(bad),
                         "fix the named code_context field; see describe('message') for the anchor rules") from None


class StatusIn(BaseModel):
    status: StatusValue
    note: str = ""
    to: str | None = None
    ticket_id: str | None = None


class DecisionIn(BaseModel):
    scope: str
    text: str
    detail: str = ""
    replaces: list[str] = []
    binding: bool | None = None  # None = inherit from the replaced decisions
    source: str | None = None
    domains: list[str] = []


class ClaimIn(BaseModel):
    scope: str
    text: str
    basis: ClaimBasis = ClaimBasis.assumption
    evidence: list[str] = []
    source: str | None = None
    status: ClaimStatus = ClaimStatus.open


class LessonIn(BaseModel):
    domain: str
    topic: str
    text: str
    evidence: list[str] = []


class WithdrawIn(BaseModel):
    reason: str = ""


class SetBindingIn(BaseModel):
    binding: bool
    reason: str = ""


class DocResolveIn(BaseModel):
    """C17: the version the owner read; a proposal that moved on since is refused with a 409."""
    expected_version: int | None = Field(default=None, ge=1)


class ResolveIn(BaseModel):
    ticket_id: str
    to: str | None = None
    kind: MessageKind = MessageKind.question
    text: str = ""  # the draft body: its @mentions join the wake preview (adversary round 2 #7)


class ArtifactIn(BaseModel):
    form: ArtifactForm
    uri: str
    note: str = ""
    ticket_id: str | None = None


class ArtifactFinalizeIn(BaseModel):
    artifact_ids: list[str]  # staged upload ids to attach directly onto the ticket (§18.1 finding 11)
    ticket_id: str


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
    role: RoleId  # a built-in role or a role of the target epic's workflow (S13)
    participant_id: str
    ticket_id: str | None = None  # for architect authz (target seat's epic); optional for owner
    parent_session: str | None = None
    model: str | None = None   # a seat name ("astra") or exact id; omitted = the epic's seat choice
    effort: str | None = None  # low | medium | high; omitted = the epic's seat choice (Claude capped at medium)
    mode: str | None = None
    assign: bool = False       # S-ROLES Spawn seat: the spawned seat becomes the ticket's assignee


class QuickTaskIn(BaseModel):
    """Body for POST /v1/quick-tasks (S-QUICK): the owner's words, a short title, the engineer model."""
    title: str
    words: str
    model: str | None = None   # an engineer-catalog id; omitted = the engineer catalog default
    effort: str | None = None  # S-UI: low|medium|high for the engineer; Claude is capped at medium
    tags: list[str] = []       # t-683d0033bb: plain words for the Library auto-link; seat keys are dropped
    description: str = ""
    work_type: WorkType = WorkType.feature


class SessionActionIn(BaseModel):
    """Body for POST /v1/sessions/{resume,reap,close,seat-token}."""
    participant_id: str
    ticket_id: str | None = None
    reason: str = ""
    model: str | None = None  # seat-token only: the resolved model, for the Fable adversary gate (S4)


class ServiceEventIn(BaseModel):
    """Body for POST /v1/service_event — the launcher records a service_restarted (design §22)."""
    service: str
    reason: str
    by: str = "supervisor"
    git_rev: str = "unknown"


# --------------------------------------------------------------- public-mode reach (S17)

DEFAULT_ADMIN_TOKEN = "dev"
# one read-modify-write of a tokens file at a time in this process (agent mint, expert mint/revoke)
_TOKENS_WRITE = threading.RLock()


def public_mode() -> bool:
    """Reach-from-another-machine is on when EDP8_PUBLIC_URL is set (design §15, S17)."""
    return bool(settings.get("EDP8_PUBLIC_URL"))


def ui_url(request: Request) -> str:
    """S16 (owner m-cc3a6656ee): the base a seat puts in front of `/ticket/<id>` or `/doc/<id>` in a hand-off link, so
    the owner gets a click, not an id to look up. EDP8_PUBLIC_URL when set (the address the owner reaches), else the
    address this request came in on. Never hardcoded."""
    base = (settings.get("EDP8_PUBLIC_URL") or "").strip() or str(request.base_url)
    return base.rstrip("/") + "/ui"


def resolve_host() -> str:
    """Bind address. Public mode defaults to 0.0.0.0 so another machine can reach the
    board; EDP8_HOST always overrides (even in public mode). Trusted mode → 127.0.0.1."""
    explicit = settings.get("EDP8_HOST")
    if explicit:
        return explicit
    return "0.0.0.0" if public_mode() else "127.0.0.1"


def tokens_file_path() -> Path:
    return settings.get("EDP8_TOKENS")


def _replace_private(f: Path, text: str) -> None:
    """Rewrite a secret file atomically AND keep it private: the temp file is created owner-only
    (write_secret) and the rename carries that ACL. A plain write_text temp inherited the directory's ACL,
    so the first token mint/invite/revoke on an installed copy left tokens.json readable by others and the
    next board start refused (found by the S6 private-instance walkthrough)."""
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    secret_files.write_secret(tmp, text)
    os.replace(tmp, f)


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
        # S12 (m-cea5526782) + t-96df382440: every real board start creates the data-dir catalog when it is
        # missing (no `init`: e2e homes, pre-S12 homes, a deleted file) and merges newer shipped rows into it
        log = logging.getLogger("edp8.service")
        try:
            from . import model_catalog
            for change in model_catalog.ensure():
                log.warning("models: %s", change)
        except (OSError, ValueError) as e:  # /v1/models then reads the shipped catalog (seat_choice._registry)
            log.warning("models: catalog materialise failed, serving the shipped catalog read-only: %s", e)
        db = str(settings.get("EDP8_DB"))
        Path(db).parent.mkdir(parents=True, exist_ok=True)
        index = None
        try:
            from .search import Index, VectorCache, make_embedder

            # Persist embeddings to a small SQLite file beside the board DB, keyed by text hash, so a
            # board restart reuses vectors instead of re-embedding the whole corpus (ffb0476 left the
            # ~520 s startup warm as a follow-up). EDP8_VEC_CACHE overrides the default path.
            cache = None
            try:
                vec_path = str(settings.get("EDP8_VEC_CACHE") or str(db) + ".vec")
                cache = VectorCache(vec_path)
            except Exception:
                cache = None
            index = Index(cache=cache)  # board-picked embedder: a low_ram fallback re-arms (Astra finding 9)
        except Exception:
            index = None
        store = Store(db)
        board = Board(store, index)
        if index is not None:
            try:
                index.rebuild(store.all_text_units())
            except Exception as e:  # search degrades to nothing; the board keeps running, loudly
                logging.getLogger("edp8.service").warning("search index rebuild failed: %s", e)
    admin_token = admin_token or settings.admin_token()
    try:
        board.ensure_epic_ids()
    except Exception as e:  # noqa: BLE001
        logging.getLogger("edp8.service").warning("epic_id backfill failed: %s", e)
    try:  # S18 §9 c7: the RSI tables exist on any DB (Store init); the incumbent policy p-0 is written once
        rsi.ensure_p0(board.store)
    except Exception as e:  # noqa: BLE001 — never block startup on the monitor's bookkeeping
        logging.getLogger("edp8.service").warning("rsi p-0 bootstrap failed: %s", e)
    retired = getattr(board.store, "retired_roles", None)
    if retired:  # s-ccdafcb229: coordinator/consultant/owner-agent seats deleted at open
        logging.getLogger("edp8.service").warning("retired role seats deleted: %s", retired)
    moved = getattr(board.store, "migrated_reviewer", None)
    if moved and any(moved.values()):  # S-ROLES: reviewer -> qa at open (Store._migrate_reviewer_locked)
        logging.getLogger("edp8.service").warning("migrated reviewer -> qa: %s", moved)
    app = FastAPI(title="edp8 board", version=__version__)
    app.state.board = board

    # Reach-from-another-machine (S17, design §15). Public mode fails closed BEFORE the app is
    # usable: no default admin token, credentials for every participant type, and header-only
    # requests refused at actor(). Trusted single-machine mode is the default and unchanged.
    public = public_mode()
    app.state.public_mode = public  # what THIS process started with (Admin → Remote access: restarted yet?)
    if public:
        err = public_startup_error(admin_token, tokens_file_path())
        if err:
            raise RuntimeError(err)
    if not settings.dev_mode():  # installed: a tokens file others can read is refused (strategyhl-86b4805322 §3)
        loose = secret_files.problems(tokens_file_path())
        if loose:
            raise RuntimeError("refusing to start: the tokens file is not private: " + "; ".join(loose))

    # Fixed ONCE per app (S-SME-SURFACE incident m-c31573e1a2): resolving the env on every call let a test
    # app's background thread, outliving its monkeypatched EDP8_TOKENS, fall back to the cwd's tokens.json
    # — the fleet file — and rewrite it. An app writes only the tokens file it was built with.
    _tokens_path = tokens_file_path()

    def _tokens_file() -> Path:
        return _tokens_path

    from .admin import AdminContext, LastSeen, admin_router
    _last_seen = LastSeen(settings.run_dir() / "last-seen.json")

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
        if getattr(p, "retired", False):
            # t-501e39f939: a removed participant is refused even with a matching token (a join that raced
            # the Remove, a token file restored from backup); its leftover human entry is dropped on sight.
            if p.type == "human" and p.handle.lstrip("@") in humans:
                try:
                    _revoke_human_token(p.handle)
                except (OSError, ValueError, RuntimeError):
                    logging.getLogger("edp8.service").warning("could not drop the removed %s's token", p.handle)
            return f"{p.handle.lstrip('@')!r} was removed; ask an admin for a new invite"
        secret = (humans if p.type == "human" else agents).get(p.handle.lstrip("@"))
        if secret is None:
            if p.role == Role.expert:  # S-SME-SURFACE: an expert is never header-only, in any mode
                return f"X-Token required for expert {p.handle!r} (removed experts have none)"
            if public:  # fail closed: an uncredentialed participant cannot act from the network
                return f"X-Token required for {p.type} participant {p.handle!r} (public mode)"
            # Human #34 (2026-09-10, P1): once tokens.json exists the board is in token mode — a HUMAN
            # with no minted entry is refused, never trusted on the header alone (the fleet board
            # accepted `X-Participant: owner` with no X-Token because its tokens.json listed only
            # agents). Agents are still minted at spawn (S20); a pre-token agent stays header-only.
            if p.type == "human" and _tokens_file().exists():
                return f"no token minted for {p.handle.lstrip('@')} — mint one (tokens.json top-level handle→secret)"
            return None
        if token != secret:
            return f"X-Token required for {p.type} participant {p.handle!r}"
        return None

    def topic_actor(x_participant: str | None = Header(default=None),
                    x_token: str | None = Header(default=None)) -> Participant:
        """Every authenticated participant, experts included — only the topic routes use it, and they
        scope an expert to its own topic (api_topics)."""
        if not x_participant:
            raise HTTPException(401, "X-Participant header missing (participant id or @handle)")
        try:
            p = board.participant(x_participant)
        except BoardError as e:
            raise HTTPException(401, e.message)
        err = _verify_token(p, x_token)
        if err:
            raise HTTPException(401, err)
        _last_seen.touch(p.id)
        return p

    def actor(x_participant: str | None = Header(default=None),
              x_token: str | None = Header(default=None)) -> Participant:
        p = topic_actor(x_participant, x_token)
        if p.role == Role.expert:  # S-SME-SURFACE: an expert's token reaches its topic and nothing else
            raise HTTPException(403, f"expert {p.handle!r} reaches only its Library topic (/v1/topics/<id>)")
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
        if p.role == Role.expert:  # the legacy /ui forms are not an expert's; its topic page is
            raise HTTPException(403, f"expert {p.handle!r} reaches only its Library topic")
        return p

    def _mint_agent_token(handle: str) -> str | None:
        """Mint and persist a per-seat secret into tokens.json's `agents` map for `handle`,
        returning it. Trusted mode (no tokens.json) → None: nothing to inject, the shell is
        header-only. Rewrites the file atomically-ish; the mtime bump invalidates _tokens cache."""
        with _TOKENS_WRITE:
            return _mint_agent_token_locked(handle)

    def _mint_agent_token_locked(handle: str) -> str | None:
        f = _tokens_file()
        if not f.exists():
            return None
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # never rewrite a tokens file we could not read: writing `{}` back would drop every human and
            # agent credential in it (incident m-c31573e1a2). The pairing queue retries on the next tick.
            raise RuntimeError(f"cannot read {f}; not minting {handle}: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"{f} is not a JSON object; not minting {handle}")
        agents = data.get("agents")
        if not isinstance(agents, dict):
            agents = {}
        secret = secrets.token_urlsafe(24)
        agents[handle.lstrip("@")] = secret
        data["agents"] = agents
        _replace_private(f, json.dumps(data, indent=2))
        return secret

    def _write_humans(update) -> None:
        """Apply `update(data)` to tokens.json atomically (the owner's human map is its top level)."""
        f = _tokens_file()
        with _TOKENS_WRITE:
            data = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise RuntimeError(f"{f} is not a JSON object; not writing it")
            update(data)
            _replace_private(f, json.dumps(data, indent=2))

    def _mint_human_token(handle: str) -> str | None:
        """S-SME-SURFACE: an expert's token, minted exactly like the owner's — a top-level handle→secret in
        tokens.json. Trusted mode (no tokens.json) → None: the caller refuses, an expert is never header-only."""
        if not _tokens_file().exists():
            return None
        secret = secrets.token_urlsafe(24)
        _write_humans(lambda d: d.__setitem__(handle.lstrip("@"), secret))
        return secret

    def _revoke_human_token(handle: str) -> None:
        if _tokens_file().exists():
            _write_humans(lambda d: d.pop(handle.lstrip("@"), None))

    # §24 finding 4: auto-paired qa seats spawn through the board, so give the board the
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
        status = (409 if e.code in ("transition", "conflict", "version_mismatch") else 403 if e.code == "forbidden"
                  else 422 if e.code in ("quote_mismatch", "quote_source_missing", "too_long") else 400)
        return JSONResponse(status_code=status, content=e.to_dict())

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
    from .api_settings import settings_router
    from .api_topics import topics_router
    from .api_usage import usage_router
    app.include_router(settings_router(actor))
    app.include_router(topics_router(board, actor, topic_actor, _mint_human_token, _revoke_human_token))

    app.include_router(usage_router(actor))
    # S5: the admin console backend (/v1/admin/*), behind its own admin-human gate (edp8.admin.auth)
    _admin_ctx = AdminContext(board=board, tokens=_tokens, write_tokens=_write_humans,
                              tokens_file=_tokens_file, last_seen=_last_seen)
    app.include_router(admin_router(_admin_ctx))
    # t-882e4d2eeb: the one "who belongs in the people pickers" rule (views.human_active reads it)
    from .admin.teammates import human_active as _human_active
    board.human_active = lambda p: _human_active(_admin_ctx, p)  # type: ignore[attr-defined]
    # S19: Ask for help, the Help seat's read-only diagnostics and the admin approval of its fixes
    from .admin import make_admin_actor
    from .api_doctor import doctor_router
    app.include_router(doctor_router(board, actor, make_admin_actor(_admin_ctx), _last_seen))
    # epic-91fcd3b370 S3: where code-server is (port from EDP_CODE_PORT) and whether it is up; the FAQ
    from .api_code import code_router
    from .views import render_markdown
    # s-17c13096e5: the guard session is minted only for a human whose token was checked (a minted
    # secret in tokens.json that actor() compared), never on a trusted-mode header alone
    app.include_router(code_router(actor, render_markdown,
                                   credentialed=lambda p: p.type == "human" and p.handle.lstrip("@") in _tokens()[0]))

    # identity -----------------------------------------------------------------
    @app.get("/v1/whoami")
    def whoami(request: Request, a: Participant = Depends(actor)):
        tickets = board.my_tickets(a)
        # S13: the seat's tool bundle comes from its epic's pinned workflow
        wf = board.workflow_of(board.seat_ticket(a))
        from .admin import is_admin  # S6: the SPA shows Admin only to admins (flag or the init human)
        return ok({"participant": _dump(a), "tickets": [t.id for t in tickets], "ui_url": ui_url(request),
                   "workflow": wf.ref, "bundle": wf.bundle(a.role.value), "admin": is_admin(a)},
                  "next: subscribe() to arm your feed, then context() to load your ticket")

    @app.get("/v1/describe/{type_}")
    def describe(type_: str):
        if type_ not in OBJECT_TYPES:
            raise BoardError("not_found", f"unknown object type {type_!r}", f"types: {sorted(OBJECT_TYPES)}")
        return ok({"type": type_, "contract": DESCRIBE[type_], "schema": OBJECT_TYPES[type_].model_json_schema()})

    @app.get("/v1/context")
    def context(ticket_id: str | None = None, a: Participant = Depends(actor)):
        return ok(board.context(a, ticket_id))

    @app.get("/v1/context_delta")
    def context_delta(cursor: str, ticket_id: str | None = None, limit: int = 50,
                      a: Participant = Depends(actor)):
        return ok(board.context_delta(a, cursor, ticket_id, limit))

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
        # admin registers anyone; a spawner role (engineer/architect) registers AGENT participants
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
            if a.role not in (Role.owner, Role.engineer, Role.architect) or b.type != "agent":
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
                                tags=b.tags, words=b.words, workflow=b.workflow)
        if t.kind == TicketKind.epic:
            hint = "epic created; an architect designs it (doc_create design, criteria, stories)"
        elif t.kind == TicketKind.task:
            hint = ("task created under its story — work it with the low-level craft; "
                    "evidence lands on the story's criteria")
        else:
            hint = "add criteria before it becomes ready"
        return ok(_dump(t), hint)

    @app.get("/v1/tickets/{id_}")
    def ticket_get(id_: str, include: str | None = None, thread_limit: int = Query(default=20, ge=0, le=200),
                   a: Participant = Depends(actor)):
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
                                description=b.description, tags=b.tags, title=b.title)
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
        warnings: list[str] = []
        c = board.criterion_update(a, id_, evidence_ref=b.evidence_ref, verdict=b.verdict, text=b.text,
                                   evidence_version=b.evidence_version, stale_ok=b.stale_ok, note=b.note,
                                   warnings=warnings)
        pending = [x.id for x in board.criteria(c.ticket_id) if x.verdict != Verdict.passed]
        hint = (f"{len(pending)} criteria not yet passed on {c.ticket_id}" if pending else
                "all criteria passed; the ticket can be marked done by its checker")
        return ok(_dump(c), "; ".join([hint, *warnings]))

    # docs / links / artifacts ---------------------------------------------------
    @app.post("/v1/docs")
    def doc_create(b: DocIn, a: Participant = Depends(actor)):
        d = board.doc_create(a, doc_type=b.doc_type, title=b.title, body_md=b.body_md, scope=b.scope,
                             tags=b.tags, status=b.status, proposes=b.proposes, ticket_id=b.ticket_id)
        if d.status == DocStatus.proposed:
            return ok(_dump(d), "proposed: the owner approves or rejects it in the Library (POST /v1/docs/{id}/approve|reject)")
        if b.doc_type in (DocType.strategy_hl, DocType.strategy_ll):
            hint = ("link it: extends -> its parent layer (doc), uses_strategy -> the epic; "
                    "assemble_ruleset composes the chain at read time")
        else:
            hint = ("link it: link_create(from_id=<ticket>, to_id=<doc>, "
                    "relation=designed_by|uses_strategy|uses_domain|evidence_for)")
        return ok(_dump(d), hint)

    @app.get("/v1/docs/{id_}")
    def doc_get(id_: str, version: int | None = None, offset: int | None = None,
                limit: int | None = None, section: str | None = None, a: Participant = Depends(actor)):
        d = board.doc(id_, version)
        if offset is not None or limit is not None or section is not None:
            from .doc_tools import bounded_read
            if (offset is not None and offset < 0) or (limit is not None and not 1 <= limit <= 32768):
                raise BoardError("range", "offset must be >=0 and limit must be 1..32768 characters")
            return ok(bounded_read(d, offset=offset or 0, limit=limit or 8192, section=section))
        return ok({**_dump(d), "versions": board.store.doc_versions(id_)})

    @app.get("/v1/docs")
    def doc_query(doc_type: DocType | None = None, scope: str | None = None, owner_role: Role | None = None,
                  tag: str | None = None, status: DocStatus | None = None, a: Participant = Depends(actor)):
        return ok([board._doc_summary(d) for d in board.docs_query(doc_type=doc_type, scope=scope,
                                                                   owner_role=owner_role, tag=tag, status=status)])

    @app.post("/v1/docs/{id_}/approve")
    def doc_approve(id_: str, b: DocResolveIn | None = None, a: Participant = Depends(actor)):
        r = board.doc_resolve(a, id_, approve=True, expected_version=b.expected_version if b else None)
        t = r["target"]
        return ok({"doc": _dump(r["doc"]), "target": _dump(t) if t else None},
                  f"{t.id} is now v{t.version}; briefs linking it carry the new text" if t else f"{id_} is active")

    @app.post("/v1/docs/{id_}/reject")
    def doc_reject(id_: str, b: DocResolveIn | None = None, a: Participant = Depends(actor)):
        r = board.doc_resolve(a, id_, approve=False, expected_version=b.expected_version if b else None)
        return ok({"doc": _dump(r["doc"]), "target": None}, f"{id_} retired")

    @app.get("/v1/docs/{id_}/diff")
    def doc_diff(id_: str, a: Participant = Depends(actor)):
        return ok(board.doc_diff(id_))

    @app.get("/v1/knowledge")
    def knowledge_list(a: Participant = Depends(actor)):
        from .library import knowledge_view
        return ok(knowledge_view(board))

    @app.post("/v1/library/import")
    def library_import(b: LibraryImportIn, a: Participant = Depends(actor)):
        from .library import import_skill
        r = import_skill(board, a, b.url, scope=b.scope, tags=b.tags)
        d = r["doc"]
        return ok({"doc": _dump(d), "created": r["created"], "fetched": r["fetched"]},
                  (f"imported as {d.id} v1" if r["created"] else f"re-import: {d.id} is now v{d.version}")
                  + "; link it to an epic (uses_strategy) to put it in that epic's brief index")

    @app.patch("/v1/docs/{id_}")
    def doc_update(id_: str, b: DocPatch, a: Participant = Depends(actor)):
        from .doc_tools import receipt
        d = board.doc_update(a, id_, body_md=b.body_md, title=b.title, tags=b.tags)
        return ok(receipt(d, [k for k in ("body_md", "title", "tags") if getattr(b, k) is not None])
                  if b.compact else _dump(d))

    @app.post("/v1/docs/{id_}/edit")
    def doc_edit(id_: str, b: DocEdit, a: Participant = Depends(actor)):
        return ok(board.doc_edit(a, id_, b), "doc_read(id, version) for the resulting body")

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

    @app.post("/v1/artifacts/upload-authorize")
    def artifact_upload_authorize(a: Participant = Depends(actor), x_token: str | None = Header(default=None)):
        """Strict credential probe for opt-in proxy file access; trusted-mode headers are insufficient."""
        import hmac
        humans, agents = _tokens()
        secret = (humans if a.type == 'human' else agents).get(a.handle.lstrip('@'))
        if not secret or not x_token or not hmac.compare_digest(secret.encode(), x_token.encode()):
            raise HTTPException(401, 'configured participant credential required for HTTP file access')
        return ok({'participant_id': a.id})

    @app.post("/v1/artifacts/upload")
    async def artifact_upload(file: UploadFile = File(...), note: str = Form(default=""),
                              ticket_id: str | None = Form(default=None), a: Participant = Depends(actor)):
        """Drop a file, get a STAGED artifact (design §18.1). The bytes stream to a temp file under
        the cap for their sniffed type (25 MB; 100 MB for mp4/webm video, t-f01372d361); the type
        is SNIFFED from them (the client's name/Content-Type are never trusted); an SVG is stored
        as a file, never an inline image. The artifact is invisible until a message finalises it —
        attach it with POST /v1/messages artifacts:[id]. The framework still spools the multipart
        body before this loop runs; the loop itself never holds more than one chunk in memory."""
        import os
        import tempfile
        from . import uploads
        dest = uploads.uploads_dir()
        dest.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=dest, prefix=".upload-", suffix=".part")
        head = b""
        size = 0
        try:
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    if len(head) < 4096:
                        head = (head + chunk)[:4096]
                    size += len(chunk)
                    cap = uploads.limit_for(head)
                    if size > cap:
                        return JSONResponse(status_code=413, content={"ok": False, "error": {"code": "too_large",
                            "message": f"the file is over the {cap // (1024 * 1024)} MB upload limit"},
                            "hint": "compress it or share a link instead"})
                    out.write(chunk)
            ctype = uploads.sniff_upload(head, file.filename or "")
            if ctype is None:
                return JSONResponse(status_code=415, content={"ok": False, "error": {"code": "unsupported_type",
                    "message": "that file type is not accepted; allowed: images, pdf, text, markdown, json, log, "
                               "zip, svg, mp4/webm video"},
                    "hint": "the type is read from the file's bytes, not its name"})
            form = ArtifactForm.image if uploads.is_inline_image(ctype) else ArtifactForm.file
            art = board.artifact_upload(a, form=form, content_type=ctype, filename=file.filename or "", note=note)
            os.replace(tmp, dest / f"{art.id}.{uploads.ext_for(ctype)}")
            tmp = None
        finally:
            if tmp is not None and os.path.exists(tmp):
                os.unlink(tmp)
        return ok(_dump(art), "staged; post a message with artifacts:[this id] to attach it — "
                              "unfinalised uploads are swept after 24 h")

    @app.post("/v1/artifacts/finalize")
    def artifact_finalize(b: ArtifactFinalizeIn, a: Participant = Depends(actor)):
        """Attach staged uploads straight onto a ticket, no message (§18.1 finding 11: a file
        dropped on the ticket's Files card must really attach — flip staged→False and link
        `produced` — not linger staged in the SPA until the 24 h sweep). Same all-or-nothing
        validation and uploader-scope check as the message finalise path."""
        arts = board.artifact_finalise(a, artifact_ids=b.artifact_ids, ticket_id=b.ticket_id)
        return ok([_dump(x) for x in arts], "attached to the ticket")

    @app.get("/v1/artifacts/{id_}/content")
    def artifact_content(id_: str, a: Participant = Depends(actor)):
        """Serve an uploaded artifact's bytes with the sniffed type. Never sniffs in the browser
        (X-Content-Type-Options: nosniff) and forces a download for everything but the four inline
        image types and mp4/webm video — an uploaded SVG is thus never rendered (design §18.1).
        Range requests get 206 partial content (FileResponse), so a <video> can seek."""
        from . import uploads
        art = board._get("artifact", id_, "artifact")
        if getattr(art, "staged", False) and art.created_by != a.id:  # §18.1: a staged upload is
            raise HTTPException(404, f"{id_!r} is not an artifact")  # invisible until its owner attaches it
        ctype = art.content_type or "application/octet-stream"
        path = uploads.uploads_dir() / f"{id_}.{uploads.ext_for(ctype)}"
        if not path.exists():
            raise BoardError("not_found", f"artifact {id_} has no stored content")
        disp = "inline" if uploads.is_inline_image(ctype) or uploads.is_inline_video(ctype) else "attachment"
        name = art.filename or path.name
        return FileResponse(path, media_type=ctype, headers={
            "X-Content-Type-Options": "nosniff",
            # RFC 6266: a non-Latin or quoted filename must not raise (finding 14).
            "Content-Disposition": uploads.content_disposition(disp, name)})

    @app.get("/v1/artifacts/{id_}")
    def artifact_get(id_: str, a: Participant = Depends(actor)):
        art = board._get("artifact", id_, "artifact")
        if getattr(art, "staged", False) and art.created_by != a.id:  # §18.1 finding 4: staged uploads
            raise HTTPException(404, f"{id_!r} is not an artifact")  # are invisible to everyone but the uploader
        from . import uploads
        return ok({**_dump(art), "has_content": uploads.has_content(art)})

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
        code_context = code_context_in(b.code_context)  # before any artifact is finalised: a 400 changes nothing
        from .quotes import quotes_in
        with board._lock, board.store._lock:  # C18: verified against the sources before anything changes
            quotes = quotes_in(board, a, b.quotes)
        if b.artifacts:
            board.artifact_finalise(a, artifact_ids=b.artifacts, ticket_id=b.ticket_id)
        try:
            m = board.message_send(a, ticket_id=b.ticket_id, to=b.to, kind=b.kind, text=b.text, reply_to=b.reply_to,
                                   artifacts=b.artifacts, code_context=code_context, quotes=quotes)
        except Exception:
            if was_staged:  # all-or-nothing: the message failed, so nothing it carried becomes visible
                board.artifact_unfinalise(artifact_ids=was_staged, ticket_id=b.ticket_id)
            raise
        delivery.after_message(board, a.id, m)
        note = getattr(board, "last_send_note", "")
        hint = "delivered to the recipient's feed; end your turn if you are waiting for an answer"
        # unresolved_mentions: @handles that match no participant — the message posted, but nobody
        # was woken for these (design §4.1). The caller surfaces them so a typo'd @handle is visible.
        return ok({**_dump(m), "unresolved_mentions": views.unresolved_mentions(board, b.text, m.quotes)},
                  f"{note}; {hint}" if note else hint)

    @app.post("/v1/status")
    def record_status(b: StatusIn, a: Participant = Depends(actor)):
        m, recipients = board.record_status(a, status=b.status, note=b.note, to=b.to, ticket_id=b.ticket_id)
        told = delivery.after_status(board, a.id, m, recipients)
        return ok({"message": _dump(m), "told": told},
                  "status recorded; next: close_self() (resident seats: keep listening)")

    @app.post("/v1/decisions")
    def record_decision(b: DecisionIn, a: Participant = Depends(actor)):
        d = board.record_decision(a, scope=b.scope, text=b.text, detail=b.detail, replaces=b.replaces,
                                  binding=b.binding, source=b.source, domains=b.domains)
        return ok(_dump(d), f"decision recorded; {len(d.replaces)} replaced" if d.replaces
                  else "decision recorded")

    @app.post("/v1/claims")
    def record_claim(b: ClaimIn, a: Participant = Depends(actor)):
        c = board.record_claim(a, scope=b.scope, text=b.text, basis=b.basis, evidence=b.evidence,
                               source=b.source, status=b.status)
        return ok(_dump(c), "claim recorded")

    @app.post("/v1/lessons")
    def record_lesson(b: LessonIn, a: Participant = Depends(actor)):
        le = board.record_lesson(a, domain=b.domain, topic=b.topic, text=b.text, evidence=b.evidence)
        return ok(_dump(le), "lesson recorded; lookup shows it under 'Lessons from elsewhere' from any epic")

    @app.post("/v1/decisions/{id_}/withdraw")
    def withdraw_decision(id_: str, b: WithdrawIn, a: Participant = Depends(actor)):
        d = board.withdraw_decision(a, decision_id=id_, reason=b.reason)
        return ok(_dump(d), "decision withdrawn; lookup and search no longer return it")

    @app.get("/v1/decisions")
    def scope_decisions(scope: str, a: Participant = Depends(actor)):
        """C17 (design-10b21760d9 §14.2): the scope's live and withdrawn decisions (a ticket and every ticket
        under it), live binding first, then newest; the epic's participants only."""
        return ok(board.scope_decisions(a, scope),
                  "live binding first, then newest; withdraw: POST /v1/decisions/{id}/withdraw, "
                  "binding: POST /v1/decisions/{id}/binding (architect or owner)")

    @app.post("/v1/claims/{id_}/withdraw")
    def withdraw_claim(id_: str, b: WithdrawIn, a: Participant = Depends(actor)):
        c = board.withdraw_claim(a, claim_id=id_, reason=b.reason)
        return ok(_dump(c), "claim withdrawn; lookup and search no longer return it")

    @app.post("/v1/decisions/{id_}/binding")
    def set_binding(id_: str, b: SetBindingIn, a: Participant = Depends(actor)):
        """D5 re-judge: promote/demote a live decision's binding flag (architect or owner only). The
        id and its kglinks stay; a binding_changed audit event records who, when and why."""
        d = board.set_binding(a, decision_id=id_, binding=b.binding, reason=b.reason)
        return ok(_dump(d), f"binding set to {b.binding}; audit event written")

    @app.get("/v1/index/dense_search")
    def index_dense_search(scope: str, question: str, k: int = 10, a: Participant = Depends(actor)):
        """Read-only D4/D5 diagnostic: dense-only cosine top-k over this epic's live records (no BM25,
        no graph). Shows what the dense seed leg votes for, which the fused lookup hides."""
        return ok(board.dense_diagnostic(a, scope=scope, question=question, k=k),
                  "dense-only cosine top-k, scope-limited to the epic's live records")

    @app.get("/v1/recall")
    def recall(ticket_id: str, a: Participant = Depends(actor)):
        """S-IMPLICIT: the ticket's recall section (records.recall — FTS + graph, capped, no model call);
        assemble_ruleset appends it to the brief."""
        from . import records
        board.ticket(ticket_id)  # 404 on an unknown ticket
        return ok(records.recall(board.store, ticket_id), "decisions/claims/lessons for this ticket, capped")

    @app.get("/v1/lookup")
    def lookup(scope: str, question: str | None = None, id: str | None = None,
               path: str | None = None, a: Participant = Depends(actor)):
        return ok(board.lookup(a, scope=scope, question=question, id=id, path=path),
                  "records: json.dumps(records) at most 16000 bytes; binding never cut; receipt names what was cut")

    @app.post("/v1/index/reembed")
    def index_reembed(a: Participant = Depends(actor)):
        """R2 item-3: run the in-board bounded re-embed pass for any unit lacking a vector (no
        restart). The board is the only process allowed to hold the model."""
        return ok(board.reembed(), "re-embed pass triggered on the board (bounded batch path)")

    @app.get("/v1/index/binding_audit")
    def index_binding_audit(a: Participant = Depends(actor)):
        """Every replaced/withdrawn binding decision must have a live binding successor; lists those
        that do not (m-0cccdead3e)."""
        return ok(board.binding_audit(), "binding decisions left without a live binding successor")

    @app.get("/v1/index/embed_counts")
    def index_embed_counts(scope: str, a: Participant = Depends(actor)):
        """R2 item-3: embedded vs unembedded live records for an epic."""
        return ok(board.embed_counts(scope), "embedded/unembedded live records for the epic")

    @app.post("/v1/index/backfill_decided_at")
    def index_backfill_decided_at(a: Participant = Depends(actor)):
        """Data pass (steer m-34d0beb1e8): set decided_at from each record's source date, so scoring
        and render use when it was decided, not when it was backfilled. No re-embed needed."""
        return ok(board.backfill_decided_at(), "decided_at backfilled from source dates")

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
        from .quotes import with_quotes
        out = [with_quotes({**_dump(m), "seq": seq}, m) for seq, m in rows]  # C18: quotes rendered above text
        return ok(out, f"last_seq={rows[-1][0] if rows else (since_seq or 0)}; pass it as since_seq next time "
                       "to get only what is new")

    @app.post("/v1/messages/resolve")
    def message_resolve(b: ResolveIn, a: Participant = Depends(actor)):
        r = board.resolve(a, ticket_id=b.ticket_id, to=b.to, kind=b.kind, text=b.text)
        return ok(r, "wake preview only — nothing was sent; `wakes`/`plan` are the same list "
                     "(each {recipient, reason, why}); an empty list means nobody is woken")

    @app.get("/v1/messages/{id_}")
    def message_get(id_: str, a: Participant = Depends(actor)):
        return ok(board.message_read(id_))

    @app.get("/v1/tickets/{id_}/contextual")
    def ticket_contextual(id_: str, category: HistoryCategory = "all", a: Participant = Depends(actor)):
        return ok(contextual_work(board, id_, category))

    @app.get("/v1/docs/{id_}/sources")
    def document_sources(id_: str, a: Participant = Depends(actor)):
        board.doc(id_)
        ids = {link.from_id for link in board.store.query("link", {"to_id": id_}, limit=100000)
               if board.store.get("ticket", link.from_id)}
        ids.update(t.id for t in board.store.query("ticket", limit=100000) if t.design_ref == id_)
        ids.update(c.ticket_id for c in board.store.query("criterion", limit=100000) if c.evidence_ref == id_)
        return ok([{"id": ident, "title": board.ticket(ident).title} for ident in sorted(ids)])

    @app.get("/v1/docs/{id_}/comments")
    def doc_comments(id_: str, version: int | None = None, a: Participant = Depends(actor)):
        rows = board.doc_comments(id_, version)
        return ok(rows, f"{len(rows)} comment(s) on {id_}{f' v{version}' if version else ''}: design-review "
                        "comments and messages quoting it")

    @app.get("/v1/docs/{id_}/context")
    def document_context(id_: str, source: str, version: int, request: str | None = None,
                         a: Participant = Depends(actor)):
        with board._lock, board.store._lock:
            return ok(source_context(board, a, source, id_, version, request))

    @app.post("/v1/gates/decide")
    def review_decide(b: ReviewDecision, a: Participant = Depends(actor)):
        result, fresh = decide(board, a, b)
        if fresh:
            if b.decision == "approve":
                delivery.after_gate_answer(board, a.id, b.ticket_id, Gate.design_signoff.value,
                                           f"Approved {b.design_ref} v{b.reviewed_version}")
            else:
                delivery.after_message(board, a.id, board._get("message", result["message_id"]))
        return ok(result)

    @app.post("/v1/docs/comments")
    def document_comment(b: DocumentComment, a: Participant = Depends(actor)):
        result, fresh = comment(board, a, b)
        if fresh:
            delivery.after_message(board, a.id, board._get("message", result["message_id"]))
        return ok(result)

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
    def events(subject_id: str | None = None, since: int = 0, limit: int = 200, watch: bool = False,
               a: Participant = Depends(actor)):
        if subject_id:
            return ok(_dump(board.store.query("event", {"subject_id": subject_id}, limit=limit)))
        return ok([{"seq": s, **_dump(e)} for s, e in board.iter_replay(a, since, watch=watch, limit=limit)])

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

    def _seat_secret(handle: str) -> str | None:
        """Get-or-mint a seat's secret: its existing `agents` entry, else a freshly minted one. Trusted mode
        (no tokens.json) → None. Never rotates, so a spawn the pool then refuses (the seat is alive) cannot
        lock the live shell out — and a respawn keeps the secret the pool's resume re-injects anyway."""
        with _TOKENS_WRITE:
            if not _tokens_file().exists():
                return None
            existing = _tokens()[1].get(handle.lstrip("@"))
            return existing or _mint_agent_token_locked(handle)

    @app.post("/v1/sessions/seat-token")
    def session_seat_token(b: SessionActionIn, a: Participant = Depends(actor)):
        """C8 (s-a4fd5df319): the spawn env for a seat the MCP `spawn` tool starts. That tool calls the
        pool directly, so without this its seats had no EDP8_TOKEN and 401 in public mode. Same authz as
        /v1/sessions/spawn (owner any seat, architect its own epic); agents with a spawnable role only."""
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        p = board.store.get("participant", b.participant_id)
        if p is None or p.type != "agent" or str(p.role) not in board.workflow_of(b.ticket_id).spawnable:
            raise BoardError("scope", f"{b.participant_id!r} is not a registered seat of a spawnable role",
                             "register the seat first (spawn does), then ask for its token")
        refused = board.fable_refusal(p.role.value, b.model)
        if refused:  # S4 §4.11: the MCP spawn tool's path, gated like POST /v1/sessions/spawn
            raise BoardError("scope", refused, "a human acknowledges it once: POST /v1/harness/fable-ack")
        token = _seat_secret(b.participant_id)
        env = {"EDP8_TOKEN": token} if token else {}
        env.update(board.seat_spawn_spec(b.ticket_id, p.role.value)["env"])  # S13: the pinned version's card
        return ok({"env": env or None},
                  "pass value.env to the pool spawn; null = trusted mode (no tokens.json), header-only seat")

    @app.post("/v1/sessions/spawn")
    def session_spawn(b: SessionSpawnIn, a: Participant = Depends(actor),
                      idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        spawnable = board.workflow_of(b.ticket_id).spawnable  # S13: the target epic's workflow decides
        if str(b.role) not in spawnable:  # S-ADV finding 1: no owner (or retired) seat is ever minted by a spawn
            raise BoardError("scope", f"a {b.role.value} seat is not spawned; spawnable roles: "
                                      f"{sorted(spawnable)}",
                             "the owner is a human; architect/engineer/qa/adversary/sme are seats")
        if b.participant_id and b.ticket_id:  # S-ADV finding 4: the handle's epic is the authorised epic
            pe, te = _target_epic(b.participant_id, None), _target_epic(None, b.ticket_id)
            if pe and te and pe != te:
                raise BoardError("scope", f"{b.participant_id!r} belongs to {pe}, not to {te} ({b.ticket_id})",
                                 "name a ticket in the seat's own epic")
        if b.assign and b.role in (Role.qa, Role.adversary):
            # S-QUICK (owner m-6914670391): a checker spawns with the ticket as its scope, never as its doer
            raise BoardError("scope", f"a {b.role.value} seat checks the ticket and never becomes its assignee",
                             "spawn it without assign; the doer stays the assignee")
        if not pool_adapter.reachable():
            return _pool_down_envelope()
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay: same session, no second shell"}
        out = _spawn_seat(a, b)
        if out.get("ok"):
            _idem_put(a, idempotency_key, out)
            return out
        return _pool_result(out)

    def _spawn_seat(a: Participant, b: SessionSpawnIn) -> dict[str, Any]:
        """Register the seat, mint its token and ask the pool to start it on the resolved seat choice;
        with `assign`, the new seat becomes the ticket's assignee. Returns the pool envelope (ok or
        not) — authorisation, reachability and idempotency are the caller's."""
        # pain p-9ba7b6b6: the seat must EXIST on the board before its token is minted, or every
        # MCP call from the new shell 401s "participant X is not registered". Same idempotent step
        # as the board's pairing path (Board._spawn_seat); a handle race is fine.
        # owner m-2d7ef9243d: the spawn inherits the EPIC's seat choice (seat-model/seat-effort tags)
        # unless the body names its own model/effort; Claude effort high is capped to medium.
        choice = board.seat_choice_for(b.ticket_id, model=b.model, effort=b.effort, role=b.role.value)
        why = seat_choice.unknown_model(b.role.value, choice.model, seat_choice.agent_home())
        if why:  # S-ADV finding 10: the catalog is a validation boundary, not a passthrough
            raise BoardError("invalid", why, "pick an id from GET /v1/models for that role")
        refused = board.fable_refusal(b.role.value, choice.model)
        if refused:  # S4 §4.11 (R5): no adversary on Fable before a human acknowledges the risk
            raise BoardError("scope", refused, "a human acknowledges it once: POST /v1/harness/fable-ack")
        if board.store.get("participant", b.participant_id) is None:
            try:
                board.participant_create("agent", b.role, b.participant_id, id_=b.participant_id,
                                         model=choice.model)
            except BoardError:
                pass
        token = _mint_agent_token(b.participant_id)
        env = {"EDP8_TOKEN": token} if token else None
        spec = board.seat_spawn_spec(b.ticket_id, b.role.value)  # S13: the pinned version's card + capacity
        if spec["env"]:
            env = {**(env or {}), **spec["env"]}
        out = pool_adapter.spawn(b.role.value, b.participant_id, parent_session=b.parent_session,
                                 model=choice.pool_model, mode=b.mode, env=env, effort=choice.effort,
                                 **spec["capacity"])
        if out.get("ok") and isinstance(out.get("value"), dict):
            out["value"]["seat_choice"] = choice.as_dict()
            if b.assign and b.ticket_id:  # the owner's Spawn seat puts the new seat on the ticket
                t = board.ticket_update(a, b.ticket_id, assignee=b.participant_id)
                out["value"]["assignee"] = t.assignee
        return out

    @app.post("/v1/quick-tasks")
    def quick_task_create(b: QuickTaskIn, a: Participant = Depends(actor),
                          idempotency_key: str | None = Header(default=None)):
        """S-QUICK (design-34bf11cc07 §4.2): the owner's one-step quick task — create a parentless story
        tagged `quick` (it starts ready; the words are its design), spawn `engineer.<story>` on the chosen
        model and make it the assignee. The pool is probed FIRST so a down pool never leaves a ticket
        with nobody on it; a spawn the pool refuses after the create keeps the ticket and says so."""
        if a.role != Role.owner:
            raise BoardError("scope", f"{a.role.value} may not open a quick task", "the owner opens quick tasks")
        if not b.title.strip() or not b.words.strip():
            raise BoardError("schema", "a quick task needs a title and the owner's words")
        if not pool_adapter.reachable():
            return _pool_down_envelope()
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay: same quick task, no second ticket"}
        from .library import plain_tags
        from .schemas import normalize_tags
        t = board.ticket_create(a, kind=TicketKind.story, work_type=b.work_type, title=b.title.strip(),
                                words=b.words, description=b.description,
                                # S-UI: the quick story is its own root, so its seat choice lives on it
                                # t-683d0033bb: the owner's plain tags (words only — never a seat
                                # key) ride along, so the Library auto-link at create can match them
                                tags=[QUICK_TAG,
                                      *[t for t in normalize_tags(b.tags) if t in plain_tags(b.tags)],
                                      *seat_choice.tags_for_role_models({"engineer": b.model or ""}),
                                      *seat_choice.tags_for_role_efforts({"engineer": b.effort or ""})])
        seat = f"engineer.{t.id}"
        spawned = _spawn_seat(a, SessionSpawnIn(role=Role.engineer, participant_id=seat, ticket_id=t.id,
                                                model=b.model or None, effort=b.effort or None,
                                                assign=True))
        if not spawned.get("ok"):
            err = (spawned.get("error") or {}).get("message", "the pool refused the spawn")
            return {"ok": True, "value": {"ticket": _dump(board.ticket(t.id)), "seat": None, "spawn_error": err},
                    "hint": f"{t.id} is open but no engineer started ({err}); use Spawn seat on the ticket to retry"}
        out = ok({"ticket": _dump(board.ticket(t.id)), "seat": seat, "spawn": spawned.get("value")},
                 f"{t.id} is ready; {seat} is starting on it and will write the plan and criteria")
        _idem_put(a, idempotency_key, out)
        return out

    @app.post("/v1/sessions/resume")
    def session_resume(b: SessionActionIn, a: Participant = Depends(actor),
                       idempotency_key: str | None = Header(default=None)):
        _authorize_pool_op(a, b.participant_id, b.ticket_id)
        if not pool_adapter.reachable():
            return _pool_down_envelope()
        cached = _idem_get(a, idempotency_key)
        if cached is not None:
            return {**cached, "hint": "idempotent replay"}
        # The pool owns state and session continuity. A board-side guess based on
        # any old done row can select the wrong branch for a newer live seat.
        out = pool_adapter.resume(b.participant_id)
        if out.get("ok"):
            value = out.get("value") or {}
            if not value.get("resumed") and not value.get("no_op"):
                return _pool_result({"ok": False, "error": {"code": "pool", "message":
                                     value.get("reason", "resume refused")}})
            out["hint"] = value.get("message") or value.get("reason", "resume accepted")
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

    # ------------------------------------------------------------------ workflows (S13, design §4.14(b))
    def _wf_error(e: wflow.WorkflowError) -> JSONResponse:
        status = 404 if e.code == "not_found" else 409 if e.code in ("immutable", "conflict") else 400
        return JSONResponse(status_code=status, content={
            "ok": False, "error": {"code": e.code, "message": e.message, "problems": e.problems}, "hint": e.hint})

    def _wf_author(a: Participant) -> None:
        # S14: the Design tab is admin-editable and read-only for everyone else; an architect seat keeps the
        # S13 authoring API (it writes workflows for its epics from the board tools)
        from .admin import is_admin
        if not (is_admin(a) or a.role == Role.architect):
            raise BoardError("scope", f"{a.handle} may not edit workflows (admins only)",
                             "an admin edits workflows in the Design tab; everyone else reads them")

    def _wf_admin(a: Participant) -> None:
        # t-0c16c00424: deleting and restoring a version is an admin's call only (an architect seat included)
        from .admin import is_admin
        if not is_admin(a):
            raise BoardError("scope", f"{a.handle} may not delete workflows (admins only)",
                             "an admin deletes or restores workflows in the Design tab")

    @app.get("/v1/workflows")
    def workflows_list(archived: bool = False, a: Participant = Depends(actor)):
        """Every workflow version: the built-in presets (published, immutable) and stored ones, each with
        the epics pinned to it and the version it was duplicated from (S14). `archived=true` also lists the
        archived versions; each row's `delete_outcome` says what Delete would do (t-0c16c00424)."""
        from .admin import is_admin
        return ok(board.workflows.list(archived=archived),
                  "GET /v1/workflows/<id>[@version] reads one; epics pin a published one"
                  + ("" if (is_admin(a) or a.role == Role.architect) else "; read-only: only an admin edits"))

    @app.get("/v1/workflows/templates")
    def workflow_templates(a: Participant = Depends(actor)):
        """S14 (§4.14(e).3): Add role starting points (builder, checker, reviewer), the hook registry with
        its params, the predicate vocabulary and the kernel tools, for the Design tab's inline help."""
        from . import workflow_design as wd
        from .bundles import ALL_TOOLS
        tools = [{"name": n, "description": (ALL_TOOLS[n].description or "").strip().split(". ")[0][:160]}
                 for n in sorted(ALL_TOOLS)]
        return ok({"roles": wd.ROLE_TEMPLATES, "hooks": wflow.HOOKS, "predicates": sorted(wflow.PREDICATES),
                   "kernel_tools": list(wflow.KERNEL_TOOLS), "why_fix": wflow.WHY_FIX,
                   "tool_needs": wflow.TOOL_NEEDS, "tools": tools})

    @app.post("/v1/workflows/card-preview")
    def workflow_card_preview(body: dict[str, Any], a: Participant = Depends(actor)):
        """S14: a role card's markdown rendered as the board renders docs (the card editor's preview)."""
        from .views import render_markdown
        return ok({"html": render_markdown(str(body.get("card_md") or "")),
                   "kernel_preamble": wflow.KERNEL_PREAMBLE})

    @app.get("/v1/workflows/{ref_}/card/{role}")
    def workflow_card(ref_: str, role: str, a: Participant = Depends(actor)):
        """S14: a role's card as written in the version (inline) or shipped in the agent home (Standard)."""
        from .views import render_markdown
        try:
            d = board.workflows.get(*wflow.parse_ref(ref_))
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        r = next((x for x in d.roles if x.id == role), None)
        if r is None:
            return _wf_error(wflow.WorkflowError("not_found", f"{d.ref} has no role {role!r}"))
        if r.card_md:
            md, source, name = r.card_md, "inline", wflow.card_name(d.id, d.version, r.id)
        else:
            path = wflow.card_path(r.card or r.id) if (r.card or not r.human) else None
            md, source, name = (path.read_text(encoding="utf-8") if path else ""), "shipped", (r.card or r.id)
        return ok({"role": role, "name": name, "source": source if md else "none", "markdown": md,
                   "html": render_markdown(md), "kernel_preamble": wflow.KERNEL_PREAMBLE})

    @app.post("/v1/workflows/diff")
    def workflow_diff_body(body: dict[str, Any], a: Participant = Depends(actor)):
        """S14: the diff of an unsaved definition (`definition`) against a stored version (`against`)."""
        from . import workflow_design as wd
        try:
            against = str(body.get("against") or "")
            base = board.workflows.snapshot(against)
            return ok({"against": against, "changes": wd.diff(base, body.get("definition") or {})})
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)

    @app.post("/v1/workflows/dryrun")
    def workflow_dryrun(body: dict[str, Any], a: Participant = Depends(actor)):
        """S14 (§4.14(e).3): walk a synthetic epic through a definition on a throwaway in-memory board;
        the timeline lists spawns, wakes, gates and transitions, and `stall` names the step no role can take."""
        from . import workflow_design as wd
        run = wd.dry_run(body)
        return ok(run, "publishable walk" if run["ok"] else "fix the stalled step; a stall blocks Publish")

    @app.get("/v1/workflows/{ref_}")
    def workflow_get(ref_: str, a: Participant = Depends(actor)):
        try:
            wf_id, ver = (wflow.parse_ref(ref_) if "@" in ref_ else (ref_, None))
            d = board.workflows.get(wf_id, ver)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok({**wflow.dump(d), "problems": wflow.validate(d)})

    @app.get("/v1/workflows/{ref_}/lifecycle")
    def workflow_lifecycle(ref_: str, kind: str = "epic", a: Participant = Depends(actor)):
        """The lifecycle of `kind` rendered from a version (what the /epic and /ticket skills show)."""
        try:
            w = board.workflows.resolve(ref_)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok({"ref": w.ref, "kind": kind, "markdown": wflow.lifecycle_md(w, kind)})

    @app.get("/v1/workflows/{ref_}/diff")
    def workflow_diff(ref_: str, against: str | None = None, a: Participant = Depends(actor)):
        """S14: what changed from `against` (default: the version it was duplicated from) to `ref_`."""
        from . import workflow_design as wd
        try:
            d = board.workflows.get(*wflow.parse_ref(ref_))
            base_ref = against or d.source
            if not base_ref:
                return ok({"ref": d.ref, "against": None, "changes": []}, "a preset has no source to diff against")
            base = board.workflows.snapshot(base_ref) if base_ref == d.source else board.workflows.get(
                *wflow.parse_ref(base_ref))
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok({"ref": d.ref, "against": base_ref, "changes": wd.diff(base, d)})

    @app.get("/v1/workflows/{ref_}/upstream")
    def workflow_upstream(ref_: str, a: Participant = Depends(actor)):
        """S14 (§4.14(e).4): has the version this one came from moved on (e.g. Standard@N → N+1)?"""
        try:
            return ok(board.workflows.upstream(ref_))
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)

    @app.post("/v1/workflows/{ref_}/merge-upstream")
    def workflow_merge_upstream(ref_: str, a: Participant = Depends(actor)):
        """S14: three-way merge the upstream change into a NEW draft version; conflicts keep this version's
        value and are listed for the author."""
        _wf_author(a)
        try:
            out = board.workflows.merge_upstream(ref_, by=a.id)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok(out, f"draft {out['draft']['id']}@{out['draft']['version']}; review the conflicts, then publish")

    @app.post("/v1/workflows/validate")
    def workflow_validate(body: dict[str, Any], a: Participant = Depends(actor)):
        """Lint a definition without storing it: each problem names its code, message and severity. A
        definition with no lint error is also walked by the dry run (S14): a stall is an error too."""
        problems = wflow.validate(body)
        if not any(p["severity"] == "error" for p in problems):
            from . import workflow_design as wd
            stall = wd.dry_run(body)["stall"]
            if stall is not None:
                problems.append(wd.stall_problem(stall))
        errors = [p for p in problems if p["severity"] == "error"]
        return ok({"valid": not errors, "problems": problems},
                  "fix each error before publishing" if errors else "publishable")

    @app.put("/v1/workflows")
    def workflow_save(body: dict[str, Any], a: Participant = Depends(actor)):
        """Create or replace a DRAFT version; a built-in or published version is refused (immutable)."""
        _wf_author(a)
        try:
            d = board.workflows.save(body, by=a.id)
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok({**wflow.dump(d), "problems": wflow.validate(d)}, "a draft; POST /v1/workflows/<ref>/publish")

    @app.post("/v1/workflows/duplicate")
    def workflow_duplicate(b: WorkflowRefIn, a: Participant = Depends(actor)):
        _wf_author(a)
        try:
            d = board.workflows.duplicate(b.ref, new_id=b.new_id, by=a.id)
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok(wflow.dump(d), f"draft {d.ref}; edit it with PUT /v1/workflows, then publish")

    @app.delete("/v1/workflows/{ref_}")
    def workflow_delete(ref_: str, a: Participant = Depends(actor)):
        """t-0c16c00424: delete an unpublished draft; archive a published version no epic pins (restorable);
        refuse a pinned version (409, naming the epics) and a built-in preset."""
        _wf_admin(a)
        try:
            out = board.workflows.delete(ref_, by=a.id)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok(out, f"{out['ref']} deleted" if out["outcome"] == "deleted"
                  else f"{out['ref']} archived; POST /v1/workflows/{out['ref']}/restore brings it back")

    @app.post("/v1/workflows/{ref_}/restore")
    def workflow_restore(ref_: str, a: Participant = Depends(actor)):
        _wf_admin(a)
        try:
            out = board.workflows.restore(ref_)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok(out, f"{out['ref']} is back in the list")

    @app.post("/v1/workflows/{ref_}/publish")
    def workflow_publish(ref_: str, a: Participant = Depends(actor)):
        _wf_author(a)
        try:
            wf_id, ver = wflow.parse_ref(ref_)
            d = board.workflows.publish(wf_id, ver, by=a.id)
        except ValueError as e:
            return _wf_error(wflow.WorkflowError("schema", str(e)))
        except wflow.WorkflowError as e:
            return _wf_error(e)
        return ok(wflow.dump(d), f"{d.ref} is published and immutable; new epics may pin it")

    @app.get("/v1/models")
    def models_catalog(a: Participant = Depends(actor)):
        """S-ROLES: the per-role model catalog (models.json `role_models`, first entry = the role's
        default) — the new-epic dialog, the Epic page and Spawn seat read this one list."""
        from . import seat_choice
        cat = seat_choice.catalog(seat_choice.agent_home())
        raw = seat_choice._registry(seat_choice.agent_home())
        return ok({"roles": cat, "defaults": {r: ids[0] for r, ids in cat.items()},
                   "models": raw.get("models") or {}},
                  "models route by explicit catalog harness")

    @app.get("/v1/harness")
    def harness_state(a: Participant = Depends(actor)):
        """S4 (§4.11): the selected harnesses, the adversary's model and whether the Fable risk is acknowledged."""
        from . import harness, seat_choice
        reg = seat_choice._registry(seat_choice.agent_home())
        picked = harness.selected(reg)
        adv = (seat_choice.catalog(seat_choice.agent_home()).get("adversary") or [None])[0]
        ack = harness.read_ack(harness.ack_path(board.store.path))
        return ok({"harnesses": list(picked), "adversary_model": adv, "fable_ack": ack,
                   "notice": harness.FABLE_RISK_NOTICE if adv == harness.FABLE else None},
                  "set seats.harnesses in configuration; an adversary on Fable needs POST /v1/harness/fable-ack")

    @app.post("/v1/harness/fable-ack")
    def harness_fable_ack(a: Participant = Depends(actor)):
        """S4 (§4.11, R5): a HUMAN records once that an adversary on Fable may decline or soften a review."""
        from . import harness
        if a.type != "human":
            raise BoardError("scope", "only a human acknowledges the Fable adversary risk",
                             "ask the owner to acknowledge it in the web UI or with their token")
        path = harness.ack_path(board.store.path)
        if path is None:
            raise BoardError("invalid", "an in-memory board keeps no acknowledgement", "run the board on a file")
        return ok(harness.write_ack(path, a.id), "adversary spawns on Fable are now allowed")

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
    async def feed(since: int = Query(default=-1), watch: bool = Query(default=False),
                   a: Participant = Depends(actor)):
        # `watch=true` is the web page's view feed (S19 chat freeze): every event, each still
        # tagged with `why` (None when it does not page this viewer) so the page can tell its
        # own pages apart. Default stays the wake-filtered seat feed.
        def frame(s: int | None, e) -> bytes:
            # every event carries WHY this subscriber was woken (design §16.2 rule 5) so a seat
            # can tell a page from a courtesy copy
            return f"data: {json.dumps({'seq': s, 'why': board.why(e, a), **_dump(e)})}\n\n".encode()

        async def gen() -> AsyncIterator[bytes]:
            q = board.subscribe(a.id, watch=watch)
            try:
                start = since if since >= 0 else board.store.max_seq()
                cursor = start
                for s, e in board.iter_replay(a, start, watch=watch):
                    cursor = max(cursor, s)
                    yield frame(s, e)
                # S19 qa (adversary #1): the ready frame carries the cursor so a client that never
                # saw a data frame reconnects from HERE, not from "now" — a drop before the first
                # event used to skip everything posted during the gap.
                yield f": ready {cursor}\n\n".encode()
                while True:
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield b": ping\n\n"
                        continue
                    if q.resync:
                        # S22 c-0615088222: the bounded queue dropped its oldest event(s) — tell the
                        # client and end; it reconnects from `cursor` and the replay refills the gap.
                        yield f": resync {cursor}\n\n".encode()
                        return
                    s = board.store.seq_of("event", e.id)
                    cursor = max(cursor, s or cursor)
                    yield frame(s, e)
            finally:
                board.unsubscribe(a.id, q)

        return StreamingResponse(gen(), media_type="text/event-stream")

    from . import pool_adapter as _pool_gate
    _foreign = _pool_gate.foreign_board_reason()
    if _foreign:
        logging.getLogger("edp8.poolwatch").info("pool watcher off: %s", _foreign)
    if not _foreign and (settings.is_set("EDP_POOL_URL") or settings.get("EDP8_POOL_WATCH")):
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
                    # qa seats whose RAM headroom is now sufficient, retry the ones still under the
                    # seat floor (the queued-note guard keeps the retry quiet).
                    res = board.run_pending_pairings()
                    if res.get("spawned"):
                        log.info("paired checkers: %s", res["spawned"])
                except Exception as e:
                    log.warning("pairing drain error: %s", e)
                time.sleep(10)  # death-detection latency rides this cadence

        threading.Thread(target=_pool_watch, name="edp8-pool-watch", daemon=True).start()

    from .ui import router as ui_router
    from .webapp import mount_spa
    from .webapp.serve import CollapseLeadingSlashes

    app.add_middleware(CollapseLeadingSlashes)  # t-67dad8c6aa: `//ui/…` redirects to `/ui/…`, never a bare 404

    # Cutover switch (design §4.1 Transition, S12; rollback contract narrowed by ruling on
    # report-0e7081b562's second opinion — c-a8c1be7137). EDP8_UI selects which renderer owns /ui:
    #   folio  (default) — SPA at /ui, legacy renderer kept at /ui-legacy as a one-flag rollback
    #   legacy           — legacy renderer at /ui, and NO SPA is mounted (one flag, one bundle): a
    #                      /ui-built bundle cannot also serve at /app because BASE_URL is compiled in,
    #                      so the rollback is simply "the SPA is off; the legacy renderer is /ui".
    # The legacy router ALWAYS registers the fixed /ui/poll route (its prefix never moves poll),
    # and under folio is included BEFORE the SPA catch-all so /ui/poll and every /v1 route keep
    # priority. A missing build under folio → 503 page from mount_spa, never a failed create_app().
    ui_mode = settings.get("EDP8_UI").strip().lower()
    if ui_mode == "legacy":
        app.include_router(ui_router(board, verify=human_verify, public=public, prefix="/ui"))
    else:  # folio
        app.include_router(ui_router(board, verify=human_verify, public=public, prefix="/ui-legacy"))
        # t-b2f8859d30: an e2e board serves its private build (EDP8_WEB_DIST); unset = the packaged dist
        mount_spa(app, "/ui", settings.get("EDP8_WEB_DIST") or None)

    if settings.get("EDP8_PLANE_URL"):
        from .plane_adapter import start_mirror_thread, webhook_router

        app.include_router(webhook_router(board))
        start_mirror_thread(board)

    # S11 F6: a pinned version's inline card whose file is missing (renamed by the collision fix, or a fresh
    # agent home) is written again, so a resumed seat still boots its card.
    try:
        board.materialise_pinned_cards()
    except Exception as e:  # noqa: BLE001 — card migration must never block startup
        logging.getLogger("edp8.service").warning("pinned-card materialise failed: %s", e)

    # §18.1: reap staged uploads nobody finalised — once at startup, then hourly.
    try:
        swept = board.sweep_staged_artifacts()
        if swept:
            logging.getLogger("edp8.service").info("swept %d stale staged upload(s)", len(swept))
    except Exception as e:  # noqa: BLE001 — a sweep failure must never block startup
        logging.getLogger("edp8.service").warning("staged-artifact sweep failed: %s", e)
    if settings.get("EDP8_UPLOAD_SWEEP"):
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

    # S18: the RSI regression tripwire, OFF unless EDP8_RSI=1; the flag is re-read every loop and
    # app.state.rsi_stop ends it at once.
    app.state.rsi_stop = None
    if settings.get("EDP8_RSI"):
        _rsi_thread, app.state.rsi_stop = rsi.start_thread(board)

    # S5: the process start, so a UI that asked the supervisor to restart the board polls until it changes
    _started_at = datetime.now(UTC).isoformat()

    # home_id + home: the launcher acts only on a board of its own home (t-596660619c)
    from edp_contracts.identity import home_identity
    _identity = home_identity()

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "started_at": _started_at, **_identity}

    @app.get("/v1/health")
    def v1_health():
        """Uniform health route the launcher's supervisor probes (design §22 rule 3), same
        shape the pool and broker expose. No auth: it is the liveness probe."""
        from . import run_state
        return {"ok": True, "service": "board", "version": app.version, "git_rev": run_state.git_rev(),
                "started_at": _started_at, **_identity}

    return app


def run() -> None:
    import sys

    import uvicorn

    host = resolve_host()  # 0.0.0.0 in public mode (EDP8_PUBLIC_URL), else 127.0.0.1; EDP8_HOST overrides
    port = settings.get("EDP8_PORT")
    try:
        app = create_app()  # public mode fails closed here with a plain message
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e
    uvicorn.run(app, host=host, port=port, log_level=settings.get("EDP8_LOG"))


if __name__ == "__main__":
    run()
