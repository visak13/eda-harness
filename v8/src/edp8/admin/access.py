"""Accounts (t-882e4d2eeb, design-e963c656f5 §4.18): web Sign out and Request access.

Sign out
    ``POST /v1/signout`` needs no credential. The SPA holds its token in tab storage, not a cookie, and drops
    it itself; this route expires the one cookie a browser of this host holds for us, the code-server
    guard's (``edp-code-guard``: cookies ignore the port, so the board's answer clears it).

Request access (only while Remote access is on: the board runs in public mode)
    * ``GET /v1/access-requests/available`` says whether the sign-in page offers it, with the reason when not.
    * ``POST /v1/access-requests {name, role_wanted, note}`` needs no token and is rate-limited per client and
      board-wide. It stores a pending :class:`~edp8.schemas.AccessRequest` (what admins see; S20's attention
      trail reads it) and returns a one-time claim code to the requester's browser only.
    * An admin approves (``POST /v1/admin/access-requests/{id}/approve``): the S5 teammate path creates the
      human and issues an invite whose code is kept, hashed-keyed, with the claim. Deny drops it.
    * The browser polls ``POST /v1/access-requests/claim {code}``: pending, denied (once), or approved — the
      invite is redeemed through the one S5 redeem path and the token is returned exactly once; the claim is
      then burned, so a second claim, like an unknown code, is 401.

No token and no code is ever in a board record, a message, a URL or a log line: codes travel in POST bodies,
the claims file lives in the secrets dir with owner-only permissions and is keyed by sha256(code).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from edp_contracts.settings import secrets as secret_files

from .. import settings
from ..board import BoardError
from ..code_guard import GUARD_COOKIE
from ..schemas import AccessRequest, Participant, Role, now
from ..store import new_id
from . import teammates
from .context import AdminContext

CLAIMS_FILE = "access-claims.json"
#: a claim (and the request behind it) lives this long; an unanswered request then drops off the list
CLAIM_TTL_S = 7 * 24 * 3600
#: POST /v1/access-requests: per client, and for the whole board, in a sliding hour
ASK_PER_CLIENT = 5
ASK_PER_BOARD = 30
ASK_WINDOW_S = 3600
#: open requests at once (a flood cannot bury the admins' attention list)
MAX_PENDING = 25
#: POST /v1/access-requests/claim per client in a sliding minute (the browser polls every 5 s)
CLAIM_PER_CLIENT = 30
CLAIM_WINDOW_S = 60
POLL_S = 5

OFF_REASON = ("Remote access is off on this board, so it takes no access requests. "
              "Ask the person who runs it to invite you.")

#: roles a person may ask for (a human's board role; experts join from a Library topic, never here)
#: owner m-ab7c81eb8d: a person is a guest (external, scoped to the epics they are added to) or a member (`owner`);
#: an agent role is never a person's, and an expert comes only from a Library topic
HUMAN_ROLES = (Role.guest.value, Role.owner.value)


class AccessIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    role_wanted: str = Field(default="guest", max_length=20)  # e0cec S5: owner access is an explicit grant
    note: str = Field(default="", max_length=500)


class ClaimIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class ApproveIn(BaseModel):
    handle: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=20)
    admin: bool = False


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class RateLimit:
    """Sliding-window counts per key, in memory (a restart forgets them, which only ever loosens a limit)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        t = time.monotonic()
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= t - window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(t)
            return True


class ClaimStore:
    """sha256(claim code) -> {request_id, expires, invite?}, owner-only, in the secrets dir. `invite` is the
    S5 invite code an approval issued; it leaves this file only when the claim redeems it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.unlink(missing_ok=True)
        secret_files.write_secret(tmp, json.dumps(data, indent=1))
        os.replace(tmp, self.path)

    def _live(self, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        t = time.time()
        return {k: v for k, v in data.items() if v.get("expires", 0) > t}

    def issue(self, request_id: str) -> str:
        code = secrets.token_urlsafe(24)
        with self.lock:
            data = self._live(self._load())
            data[_hash(code)] = {"request_id": request_id, "expires": time.time() + CLAIM_TTL_S}
            self._save(data)
        return code

    def attach_invite(self, request_id: str, invite_code: str) -> bool:
        with self.lock:
            data = self._live(self._load())
            hit = next((v for v in data.values() if v.get("request_id") == request_id), None)
            if hit is None:
                return False
            hit["invite"] = invite_code
            self._save(data)
            return True

    def peek(self, code: str) -> dict[str, Any] | None:
        key = _hash(code)
        with self.lock:
            data = self._live(self._load())
        return next((dict(v) for k, v in data.items() if hmac.compare_digest(k, key)), None)

    def burn(self, code: str) -> dict[str, Any] | None:
        key = _hash(code)
        with self.lock:
            data = self._load()
            hit = next((data.pop(k) for k in list(data) if hmac.compare_digest(k, key)), None)
            self._save(self._live(data))
        return hit

    def drop_request(self, request_id: str) -> None:
        with self.lock:
            data = self._load()
            keep = {k: v for k, v in data.items() if v.get("request_id") != request_id}
            if len(keep) != len(data):
                self._save(keep)


_CLAIMS: dict[Path, ClaimStore] = {}
_CLAIMS_LOCK = threading.Lock()


def claim_store() -> ClaimStore:
    """The one ClaimStore per claims file in this process (the public and admin routes share its lock)."""
    path = settings.secrets_dir() / CLAIMS_FILE
    with _CLAIMS_LOCK:
        return _CLAIMS.setdefault(path, ClaimStore(path))


def client_key(request: Request) -> str:
    """Who is asking, for the rate limit. Behind `tailscale serve` every request arrives from loopback, so a
    loopback peer's X-Forwarded-For first hop names the client; a remote peer is taken as it is."""
    peer = request.client.host if request.client else "?"
    fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return fwd if fwd and peer in ("127.0.0.1", "::1", "localhost", "testclient") else peer


def remote_on(request: Request) -> bool:
    return bool(getattr(request.app.state, "public_mode", False))


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return (s or "teammate")[:30]


def _stale(q: AccessRequest) -> bool:
    return q.status == "pending" and q.created_at.timestamp() <= time.time() - CLAIM_TTL_S


def _expire(board: Any, q: AccessRequest) -> AccessRequest:
    out = board.store.put("access_request", q.model_copy(update={"status": "expired"}))
    _settle_notice(board, q.id, "expired")
    return out


def _owner_of_board(board: Any) -> Any:
    """The human owner a new access request is told to: the first owner-role person, an admin first."""
    owners = [p for p in board.store.query("participant", {"role": "owner"}, limit=100) if p.type == "human"]
    owners.sort(key=lambda p: (not p.admin, p.created_at))
    return owners[0] if owners else None


def _access_topic(board: Any, owner: Any) -> Any:
    """The one standing "Access requests" topic, opened by the board the first time it is needed. It has no resident
    seat and is not a Library topic (s-aa76c83998: the message needs a thread, the owner wants no new structure)."""
    from ..board import ACCESS_TAG, is_access
    from ..schemas import EventKind, Ticket, TicketKind, TicketStatus, WorkType
    from ..store import new_id
    with board._lock:
        for t in board.store.query("ticket", {"kind": TicketKind.topic.value}, limit=-1):
            if is_access(t):
                return t
        t = Ticket(id=new_id("topic"), kind=TicketKind.topic, work_type=WorkType.knowledge, title="Access requests",
                   words="People who ask for access from the sign-in page. Each request is decided on the Access page.",
                   created_by=owner.id, description="", tags=[ACCESS_TAG])
        t.status = TicketStatus.in_progress
        t.epic_id = t.id
        board.store.put("ticket", t)
    board._index("ticket", t.id, board.store._fts_text("ticket", t.model_dump(mode="json")) or t.title)
    board._emit(t.id, EventKind.ticket_created, {"kind": TicketKind.topic, "parent_id": None, "by": owner.id,
                                                 "access": True})
    return t


def _notify_owner(board: Any, q: AccessRequest) -> None:
    """A new request is also a chat message to the owner, linked to the Access page. Never blocks the request."""
    try:
        owner = _owner_of_board(board)
        if owner is None:
            return
        t = _access_topic(board, owner)
        board.owner_notice(t.id, f"New access request {q.id}: {q.name} asks for access as {q.role_wanted}."
                                 f"{f' They say: {q.note}' if q.note else ''} "
                                 f"Decide it on the Access page: /ui/admin?tab=teammates#{q.id}")
    except Exception:  # noqa: BLE001 — the sign-in page must not fail because the owner message could not be posted
        pass


def _settle_notice(board: Any, request_id: str, reason: str) -> None:
    """The request was decided (or expired): its message stops waiting on the owner."""
    try:
        for t in board.store.query("ticket", {"kind": "topic"}, limit=-1):
            from ..board import is_access
            if not is_access(t):
                continue
            for m in board.store.query("message", {"ticket_id": t.id, "created_by": "board"}, limit=1000):
                if request_id in m.text:
                    board.settle_notice(m.id, reason=reason, via=request_id)
    except Exception:  # noqa: BLE001
        pass


def reconcile_expired(board: Any) -> None:
    """Mark every pending request past the TTL expired (which settles its owner notice). Safe to call on any read."""
    try:
        live_pending(board)
    except Exception:  # noqa: BLE001 — a read of someone's attention must not fail on this
        pass


def live_pending(board: Any) -> list[AccessRequest]:
    """The one definition of an open request (S11 F4): pending and inside the TTL. The cap, the admin list, the
    attention list and the claim path all read it; a pending row past the TTL is marked expired here, on read."""
    live = []
    with board._lock:
        for q in board.store.query("access_request", {"status": "pending"}, limit=500):
            if _stale(q):
                _expire(board, q)
            else:
                live.append(q)
    return live


def _view(q: AccessRequest) -> dict[str, Any]:
    return {"id": q.id, "created_at": q.created_at.isoformat(), "name": q.name, "role_wanted": q.role_wanted,
            "note": q.note, "status": q.status, "decided_by": q.decided_by,
            "decided_at": q.decided_at.isoformat() if q.decided_at else None, "handle": q.handle}


def public_router(ctx: AdminContext) -> APIRouter:
    """The routes a browser with no credential reaches: sign out, and asking for access."""
    r = APIRouter()
    claims = claim_store()
    limits = RateLimit()
    board = ctx.board

    @r.post("/v1/signout")
    def signout(response: Response):
        response.set_cookie(GUARD_COOKIE, "", max_age=0, expires=0, path="/", httponly=True, samesite="strict")
        return {"ok": True, "value": {"signed_out": True},
                "hint": "drop the token this tab holds; the next request without it is refused"}

    @r.get("/v1/access-requests/available")
    def available(request: Request):
        on = remote_on(request) and ctx.tokens_file().exists()
        return {"ok": True, "value": {"enabled": on, "reason": None if on else OFF_REASON, "roles": list(HUMAN_ROLES)},
                "hint": ""}

    @r.post("/v1/access-requests")
    def ask(b: AccessIn, request: Request):
        if not remote_on(request) or not ctx.tokens_file().exists():
            raise HTTPException(409, OFF_REASON)
        role = b.role_wanted.strip() or "guest"
        if role not in HUMAN_ROLES:
            raise HTTPException(400, f"role_wanted must be one of {list(HUMAN_ROLES)}")
        name = " ".join(b.name.split())
        if not name:
            raise HTTPException(400, "say who you are")
        if not limits.allow("ask:" + client_key(request), ASK_PER_CLIENT, ASK_WINDOW_S) \
                or not limits.allow("ask:*", ASK_PER_BOARD, ASK_WINDOW_S):
            raise HTTPException(429, "too many access requests from here; try again in an hour")
        with board._lock:
            if len(live_pending(board)) >= MAX_PENDING:
                raise HTTPException(429, "this board has too many open access requests; try again later")
            q = board.store.put("access_request", AccessRequest(id=new_id("acc"), created_by="", name=name,
                                                                 role_wanted=role, note=b.note.strip()))
            _notify_owner(board, q)
        code = claims.issue(q.id)
        return {"ok": True, "value": {"id": q.id, "claim_code": code, "poll_s": POLL_S},
                "hint": "keep this page open: it signs you in once an admin approves"}

    @r.post("/v1/access-requests/claim")
    def claim(b: ClaimIn, request: Request):
        if not limits.allow("claim:" + client_key(request), CLAIM_PER_CLIENT, CLAIM_WINDOW_S):
            raise HTTPException(429, "checking too often; wait a minute")
        hit = claims.peek(b.code)
        q = board.store.get("access_request", hit["request_id"]) if hit else None
        if hit is None or q is None:
            reconcile_expired(board)  # the code lapsed with its request: settle the owner's notice now (review F5)
            raise HTTPException(401, "this request code is unknown, expired or already used")
        if _stale(q):
            with board._lock:
                q = board.store.get("access_request", q.id) or q
                if _stale(q):
                    q = _expire(board, q)
        if q.status == "expired":
            claims.burn(b.code)
            return {"ok": True, "value": {"status": "expired"}, "hint": "no admin answered in time; ask again"}
        if q.status == "pending":
            return {"ok": True, "value": {"status": "pending", "poll_s": POLL_S}, "hint": "not decided yet"}
        if q.status == "denied":
            claims.burn(b.code)
            return {"ok": True, "value": {"status": "denied"}, "hint": "an admin declined this request"}
        spent = claims.burn(b.code)  # burn first: two racing polls cannot both redeem
        if q.status != "approved" or not spent or not spent.get("invite"):
            raise HTTPException(401, "this request code is unknown, expired or already used")
        handle, token = teammates.redeem_invite(ctx, str(spent["invite"]))
        board.store.put("access_request", q.model_copy(update={"status": "claimed"}))
        return {"ok": True, "value": {"status": "approved", "handle": handle, "token": token,
                                      "board_url": teammates.board_url(request)},
                "hint": "signed in: this code no longer works"}

    return r


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    """Admin → Teammates → Requests: list, approve (S5 invite path), deny."""
    r = APIRouter()
    board = ctx.board
    claims = claim_store()

    def _pending(req_id: str) -> AccessRequest:
        q = board.store.get("access_request", req_id)
        if q is None:
            raise HTTPException(404, f"no access request {req_id!r}")
        if _stale(q):
            q = _expire(board, q)
        if q.status != "pending":
            raise HTTPException(409, f"this request was already {q.status}")
        return q

    @r.get("/v1/admin/access-requests")
    def requests_list(a: Participant = Depends(admin_actor)):
        cutoff = time.time() - CLAIM_TTL_S
        decided = [q for q in board.store.query("access_request", {}, limit=500)
                   if q.status in ("approved", "denied", "claimed")
                   and (q.decided_at or q.created_at).timestamp() > cutoff]
        rows = live_pending(board) + decided
        rows.sort(key=lambda q: (q.status != "pending", -q.created_at.timestamp()))
        return {"ok": True, "value": [_view(q) for q in rows], "hint": ""}

    @r.post("/v1/admin/access-requests/{req_id}/approve")
    def approve(req_id: str, b: ApproveIn | None = None, a: Participant = Depends(admin_actor)):
        b = b or ApproveIn()
        teammates.token_mode(ctx)
        with board._lock:
            q = _pending(req_id)
            handle = (b.handle or "").strip().lstrip("@") or _slug(q.name)
            # the requester's role_wanted is only a note to the admin: approving grants guest unless the admin
            # chooses member here (owner m-ab7c81eb8d: a stranger approved with one click is never a member)
            role = (b.role or Role.guest.value).strip()
            if role not in HUMAN_ROLES:
                raise HTTPException(400, f"role must be one of {list(HUMAN_ROLES)}")
            if b.admin and role != Role.owner.value:
                raise HTTPException(400, "a guest cannot be an admin")
            if handle == "agents":
                raise HTTPException(400, "'agents' is reserved")
            try:
                p = board.participant_create("human", role, handle)
            except BoardError as e:
                raise HTTPException(409 if e.code == "conflict" else 400,
                                    f"{e.message}; choose another handle for this person") from None
            if b.admin:
                p = board.store.put("participant", p.model_copy(update={"admin": True}))
            code, _ = teammates.invite_store().issue(p.handle, a.handle)
            if not claims.attach_invite(q.id, code):
                teammates.invite_store().drop(p.handle)
                raise HTTPException(410, "this request expired before it was approved")
            q = board.store.put("access_request", q.model_copy(update={
                "status": "approved", "decided_by": a.id, "decided_at": now(), "handle": p.handle.lstrip("@")}))
            _settle_notice(board, q.id, "approved")
        return {"ok": True, "value": _view(q),
                "hint": "their browser signs in on its next check; nothing to send them"}

    @r.post("/v1/admin/access-requests/{req_id}/deny")
    def deny(req_id: str, a: Participant = Depends(admin_actor)):
        with board._lock:
            q = _pending(req_id)
            q = board.store.put("access_request", q.model_copy(update={
                "status": "denied", "decided_by": a.id, "decided_at": now()}))
            _settle_notice(board, q.id, "denied")
        return {"ok": True, "value": _view(q), "hint": "their page says the request was declined"}

    return r

