"""Admin → Teammates (design-e963c656f5 §4.8): humans, their tokens, invites, and the live agent tokens.

* ``POST /v1/admin/teammates`` creates a human participant and returns a ONE-TIME invite: a code in
  ``<board>/ui/join?code=…`` (24 h) and the same code in a VS Code sign-in deep link. The Library-expert
  flow's rule carries over: the link holds a code, never the token. Unlike the expert flow the code is kept
  hashed in an owner-only file (so an admin restarting the board does not kill a pending invite), and the
  token is minted when the code is redeemed — it appears in exactly one response.
* ``POST /v1/join {code}`` redeems (no credential: the code is the credential, spent on first use).
* Revoke drops the token (the next request with it is 401) and any pending invite; rotate replaces it and
  returns the new one once; admin can be granted or removed (the init human is always an admin).
* Agent tokens stay minted at spawn; the admin lists and revokes them.
* Remove (t-882e4d2eeb) = revoke + retire: the human leaves every people picker and People list for good;
  history keeps the name, greyed. :func:`human_active` is the one rule the pickers read.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from edp_contracts.settings import secrets as secret_files

from .. import settings
from ..board import BoardError
from ..schemas import Participant, Role
from .auth import is_admin, owner_handle
from .context import AdminContext

INVITE_TTL_S = 24 * 3600
INVITES_FILE = "invites.json"
VSCODE_EXTENSION_ID = "edp.edp-code"
#: a revoked agent token's tombstone (an unguessable secret nobody holds)
REVOKED_PREFIX = "revoked:"


class TeammateIn(BaseModel):
    handle: str
    role: str = "owner"      # a human's role on the board (owner = full member, not admin)
    admin: bool = False


class TeammatePatch(BaseModel):
    admin: bool


class JoinIn(BaseModel):
    code: str


def _iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


class InviteStore:
    """sha256(code) -> {handle, expires, by}, in an owner-only file in the secrets dir.

    `lock` is the ONE lock for a teammate's access (t-501e39f939): spending a code, writing the token it
    mints, and revoke/remove/rotate all run under it. `drop` bumps the handle's revocation epoch; a
    redemption commits its token only if the epoch it spent the code under is still current, so a revoke
    that lands between the spend and the token write makes the redemption fail instead of restoring access."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._epochs: dict[str, int] = {}

    def epoch(self, handle: str) -> int:
        with self.lock:
            return self._epochs.get(handle.lstrip("@"), 0)

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

    def issue(self, handle: str, by: str, *, keep_token: bool = False) -> tuple[str, float]:
        """`keep_token` (the first-run setup code, S6): redeeming hands back the teammate's CURRENT token
        instead of rotating it, so signing in to the wizard never breaks a token already in use."""
        code, now = secrets.token_urlsafe(24), time.time()
        with self.lock:
            data = {k: v for k, v in self._load().items() if v.get("expires", 0) > now and v.get("handle") != handle}
            data[_hash(code)] = {"handle": handle, "expires": now + INVITE_TTL_S, "by": by,
                                 **({"keep_token": True} if keep_token else {})}
            self._save(data)
        return code, now + INVITE_TTL_S

    def redeem(self, code: str) -> str | None:
        """The handle for a live code, spending it; None when unknown, used or expired."""
        hit = self.redeem_entry(code)
        return None if hit is None else str(hit["handle"])

    def redeem_entry(self, code: str) -> dict[str, Any] | None:
        """The stored entry for a live code, spending it; None when unknown, used or expired. The entry carries
        `epoch`: the handle's revocation epoch at the spend (see :meth:`epoch`)."""
        key, now = _hash(code), time.time()
        with self.lock:
            data = self._load()
            hit = next((data.pop(k) for k in list(data) if hmac.compare_digest(k, key)), None)
            live = {k: v for k, v in data.items() if v.get("expires", 0) > now}
            if hit is not None or len(live) != len(data):
                self._save(live)
            if hit is not None:
                hit = {**hit, "epoch": self._epochs.get(str(hit.get("handle", "")).lstrip("@"), 0)}
        if hit is None or hit.get("expires", 0) <= now:
            return None
        return hit

    def pending(self) -> dict[str, float]:
        now = time.time()
        return {v["handle"]: v["expires"] for v in self._load().values() if v.get("expires", 0) > now}

    def drop(self, handle: str) -> None:
        """Drop every invite for `handle` and bump its revocation epoch (an in-flight redemption then fails)."""
        with self.lock:
            h = handle.lstrip("@")
            self._epochs[h] = self._epochs.get(h, 0) + 1
            data = self._load()
            keep = {k: v for k, v in data.items() if v.get("handle") != handle}
            if len(keep) != len(data):
                self._save(keep)


_STORES: dict[Path, InviteStore] = {}
_STORES_LOCK = threading.Lock()


def invite_store() -> InviteStore:
    """The one InviteStore per invites file in this process (Teammates and access requests share its lock)."""
    path = settings.secrets_dir() / INVITES_FILE
    with _STORES_LOCK:
        return _STORES.setdefault(path, InviteStore(path))


def human_active(ctx: AdminContext, p: Participant) -> bool:
    """Whether a person belongs in the people pickers and People lists (t-882e4d2eeb). A removed (retired)
    human never does. In token mode a human counts only while they hold a token or a live invite (revoked, or
    an invite that expired unredeemed = out); the init human always counts. Trusted mode: everyone else."""
    if p.type != "human":
        return True
    if getattr(p, "retired", False):
        return False
    if not ctx.tokens_file().exists():
        return True
    h = p.handle.lstrip("@")
    return h == owner_handle() or h in ctx.tokens()[0] or h in invite_store().pending()


def board_url(request: Request) -> str:
    return ((settings.get("EDP8_PUBLIC_URL") or "").strip() or str(request.base_url)).rstrip("/")


def invite_links(request: Request, handle: str, code: str) -> dict[str, str]:
    base = board_url(request)
    return {
        "link": f"{base}/ui/join?code={quote(code)}",
        "vscode_link": f"vscode://{VSCODE_EXTENSION_ID}/signin?" + urlencode({"board": base, "handle": handle,
                                                                                "code": code}),
    }


def token_mode(ctx: AdminContext) -> None:
    if not ctx.tokens_file().exists():
        raise HTTPException(409, "this board runs without a tokens file (trusted mode): teammates need "
                                 "tokens; run `heronry init` to create one")


def human(ctx: AdminContext, handle: str) -> Participant:
    try:
        p = ctx.board.participant(handle)
    except BoardError as e:
        raise HTTPException(404, e.message) from None
    if p.type != "human":
        raise HTTPException(404, f"{handle!r} is an agent, not a teammate")
    return p


def set_token(ctx: AdminContext, handle: str, secret: str | None) -> None:
    h = handle.lstrip("@")
    if secret is None:
        ctx.write_tokens(lambda d: d.pop(h, None))
    else:
        ctx.write_tokens(lambda d: d.__setitem__(h, secret))


def redeem_invite(ctx: AdminContext, code: str) -> tuple[str, str]:
    """Spend a one-time invite code: (handle, token). The one redeem path behind `/v1/join` and an approved
    access request's claim (t-882e4d2eeb). 401 when the code is unknown, used or expired."""
    hit = invite_store().redeem_entry(code)
    if hit is None:
        raise HTTPException(401, "this invite was already used or has expired; ask an admin for a new one")
    handle = str(hit["handle"])
    token_mode(ctx)
    store = invite_store()
    with store.lock:  # t-501e39f939: the checks and the token write are one step against revoke/remove
        try:
            p = human(ctx, handle)
        except HTTPException:
            raise HTTPException(401, "this invite's teammate no longer exists") from None
        if getattr(p, "retired", False):
            raise HTTPException(401, "this teammate was removed; ask an admin for a new invite")
        if store.epoch(handle) != hit.get("epoch", 0):
            raise HTTPException(401, "this teammate's access was revoked; ask an admin for a new invite")
        current = ctx.tokens()[0].get(handle)
        if hit.get("keep_token") and current:
            return handle, current  # the setup sign-in: the init human's token stays the one in use
        secret = secrets.token_urlsafe(24)
        set_token(ctx, handle, secret)
    return handle, secret


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()
    invites = invite_store()
    board = ctx.board

    def _token_mode() -> None:
        token_mode(ctx)

    def _human(handle: str) -> Participant:
        return human(ctx, handle)

    def _set_token(handle: str, secret: str | None) -> None:
        set_token(ctx, handle, secret)

    def _row(p: Participant, humans: dict[str, str], pending: dict[str, float]) -> dict[str, Any]:
        h = p.handle.lstrip("@")
        return {"id": p.id, "handle": h, "role": p.role.value, "admin": is_admin(p),
                "init_human": h == owner_handle(), "has_token": h in humans,
                "last_seen": _iso(ctx.last_seen.get(p.id)), "invite_expires": _iso(pending.get(h)),
                "retired": bool(getattr(p, "retired", False))}

    @r.get("/v1/admin/teammates")
    def teammates_list(a: Participant = Depends(admin_actor)):
        humans, pending = ctx.tokens()[0], invites.pending()
        rows = [_row(p, humans, pending) for p in board.store.query("participant", {}) if p.type == "human"]
        return {"ok": True, "value": sorted(rows, key=lambda x: x["handle"]), "hint": ""}

    @r.post("/v1/admin/teammates")
    def teammate_create(b: TeammateIn, request: Request, a: Participant = Depends(admin_actor)):
        _token_mode()
        handle = b.handle.strip().lstrip("@")
        if b.role == Role.expert.value:
            raise HTTPException(400, "experts are added from their Library topic, not as teammates")
        if handle == "agents":  # tokens.json keeps humans and the agents map in one namespace (les-b1fa61c4c4)
            raise HTTPException(400, "'agents' is reserved")
        try:
            p = board.participant_create("human", b.role, handle)
        except BoardError as e:
            raise HTTPException(409 if e.code == "conflict" else 400, e.message) from None
        if b.admin:
            p = board.store.put("participant", p.model_copy(update={"admin": True}))
        code, exp = invites.issue(p.handle, a.handle)
        out = {"teammate": _row(p, ctx.tokens()[0], invites.pending()),
               "invite": {**invite_links(request, p.handle, code), "code": code, "expires_at": _iso(exp)}}
        return {"ok": True, "value": out,
                "hint": "hand the link over now: it works once, within 24 h, and signs them in"}

    @r.post("/v1/admin/teammates/{handle}/invite")
    def teammate_reinvite(handle: str, request: Request, a: Participant = Depends(admin_actor)):
        _token_mode()
        with invites.lock:
            p = _human(handle)
            if getattr(p, "retired", False):  # a fresh invite brings a removed teammate back
                p = board.store.put("participant", p.model_copy(update={"retired": False}))
            code, exp = invites.issue(p.handle, a.handle)
        return {"ok": True, "value": {**invite_links(request, p.handle, code), "code": code, "expires_at": _iso(exp)},
                "hint": "any earlier invite for this teammate no longer works"}

    @r.put("/v1/admin/teammates/{handle}")
    def teammate_patch(handle: str, b: TeammatePatch, a: Participant = Depends(admin_actor)):
        p = _human(handle)
        if p.role == Role.expert and b.admin:
            raise HTTPException(400, "an expert cannot be an admin")
        if not b.admin and p.handle.lstrip("@") == owner_handle():
            raise HTTPException(409, "the init human (EDP8_OWNER) is always an admin")
        p = board.store.put("participant", p.model_copy(update={"admin": b.admin}))
        return {"ok": True, "value": _row(p, ctx.tokens()[0], invites.pending()), "hint": ""}

    @r.post("/v1/admin/teammates/{handle}/revoke")
    def teammate_revoke(handle: str, a: Participant = Depends(admin_actor)):
        _token_mode()
        p = _human(handle)
        if p.id == a.id:
            raise HTTPException(409, "you cannot revoke your own token here (another admin can)")
        with invites.lock:  # an in-flight redemption either finished (its token goes now) or fails
            invites.drop(p.handle)
            _set_token(p.handle, None)
        return {"ok": True, "value": {"handle": p.handle, "revoked": True},
                "hint": "their token is refused from now on; a new invite signs them in again"}

    @r.post("/v1/admin/teammates/{handle}/remove")
    def teammate_remove(handle: str, a: Participant = Depends(admin_actor)):
        """Revoke + retire (t-882e4d2eeb): the token is refused, any invite dropped, and the person leaves
        every picker and People list. Their name stays on history (greyed)."""
        _token_mode()
        p = _human(handle)
        if p.id == a.id:
            raise HTTPException(409, "you cannot remove yourself (another admin can)")
        if p.handle.lstrip("@") == owner_handle():
            raise HTTPException(409, "the init human (EDP8_OWNER) cannot be removed")
        with invites.lock:  # same lock as the redemption: a racing join cannot bring the token back
            invites.drop(p.handle)
            _set_token(p.handle, None)
            p = board.store.put("participant", _human(handle).model_copy(update={"retired": True, "admin": False}))
        return {"ok": True, "value": {"handle": p.handle.lstrip("@"), "removed": True},
                "hint": "their token is refused and they no longer appear in pickers; history keeps their name"}

    @r.post("/v1/admin/teammates/{handle}/rotate")
    def teammate_rotate(handle: str, a: Participant = Depends(admin_actor)):
        _token_mode()
        with invites.lock:
            p = _human(handle)
            if getattr(p, "retired", False):
                raise HTTPException(409, f"{p.handle.lstrip('@')} was removed; send a new invite to bring them back")
            secret = secrets.token_urlsafe(24)
            _set_token(p.handle, secret)
        return {"ok": True, "value": {"handle": p.handle, "token": secret},
                "hint": "shown once: the old token is refused from now on"}

    @r.get("/v1/admin/tokens/agents")
    def agent_tokens(a: Participant = Depends(admin_actor)):
        rows = []
        agents = ctx.tokens()[1]
        for h in sorted(agents):
            try:
                p = board.participant(h)
            except BoardError:
                p = None
            rows.append({"handle": h, "participant_id": p.id if p else None,
                         "role": p.role.value if p else None, "model": p.model if p else None,
                         "last_seen": _iso(ctx.last_seen.get(p.id)) if p else None,
                         "revoked": agents[h].startswith(REVOKED_PREFIX)})
        return {"ok": True, "value": rows, "hint": ""}

    @r.delete("/v1/admin/tokens/agents/{handle}")
    def agent_token_revoke(handle: str, a: Participant = Depends(admin_actor)):
        _token_mode()
        h = handle.lstrip("@")
        if h not in ctx.tokens()[1] or ctx.tokens()[1][h].startswith(REVOKED_PREFIX):
            raise HTTPException(404, f"no agent token for {h!r}")
        # a tombstone, not a delete: an agent with NO entry is still header-only in trusted-token mode
        # (a pre-token seat), so removing the entry would not refuse it; nobody knows this secret
        tomb = REVOKED_PREFIX + secrets.token_urlsafe(24)
        ctx.write_tokens(lambda d: d.setdefault("agents", {}).__setitem__(h, tomb))
        return {"ok": True, "value": {"handle": h, "revoked": True},
                "hint": "that seat's calls are refused from now on; a respawn mints a new token"}

    @r.post("/v1/join")
    def join(b: JoinIn, request: Request):
        """Redeem a teammate invite: the handle and a fresh token, once. No credential — the code is it."""
        handle, secret = redeem_invite(ctx, b.code)
        return {"ok": True, "value": {"handle": handle, "token": secret, "board_url": board_url(request)},
                "hint": "signed in: this invite no longer works"}

    return r
