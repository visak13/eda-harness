"""Admin → Remote access (design-e963c656f5 §4.8, R7 = both).

(a) Tailnet public mode: status (readiness rows, `tailscale serve` state, the resulting URL), apply and
remove — :mod:`edp8.tailnet`, the same classifier `edp.ps1 tailnet check` prints.

(b) Tailscale auth keys for a teammate's machine: with a Tailscale OAuth client configured (a secret
setting, scope `auth_keys`), the admin mints a one-off key — reusable no, ephemeral by default,
preauthorized, tagged, with an expiry — through the Tailscale API. Off (409) until the credential is set.
The key is returned once and never stored.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import launcher, settings, tailnet
from ..board import BoardError
from ..schemas import Participant
from . import net
from .context import AdminContext

MAX_KEY_EXPIRY_S = 90 * 24 * 3600


class ApplyIn(BaseModel):
    force: bool = False


class KeyIn(BaseModel):
    ephemeral: bool = True
    preauthorized: bool = True
    expiry_s: int = Field(default=24 * 3600, ge=60, le=MAX_KEY_EXPIRY_S)
    tags: list[str] | None = None


def tailscale_configured() -> bool:
    return bool(settings.get("EDP_TAILSCALE_OAUTH_CLIENT_ID")) and bool(settings.get("EDP_TAILSCALE_OAUTH_CLIENT_SECRET"))


def _seat_handles() -> list[str] | None:
    try:
        rows = launcher.live_seats() if launcher.running("pool") else []
    except Exception:  # noqa: BLE001
        return None
    return None if rows is None else [r.split(" (pid", 1)[0] for r in rows]


def mint_auth_key(*, description: str, ephemeral: bool, preauthorized: bool, expiry_s: int,
                  tags: list[str]) -> dict[str, Any]:
    """OAuth client-credentials token, then POST /api/v2/tailnet/<tailnet>/keys. The key is returned to the
    caller only."""
    api = str(settings.get("EDP_TAILSCALE_API_URL")).rstrip("/")
    tailnet_name = str(settings.get("EDP_TAILSCALE_TAILNET") or "-")
    with net.client() as c:
        t = c.post(f"{api}/api/v2/oauth/token", data={
            "client_id": settings.get("EDP_TAILSCALE_OAUTH_CLIENT_ID"),
            "client_secret": settings.get("EDP_TAILSCALE_OAUTH_CLIENT_SECRET"),
            "grant_type": "client_credentials"})
        if t.status_code != 200:
            raise HTTPException(502, f"Tailscale refused the OAuth client (HTTP {t.status_code}); check the client "
                                     "id/secret and its auth_keys scope")
        access = t.json().get("access_token")
        body = {"capabilities": {"devices": {"create": {"reusable": False, "ephemeral": ephemeral,
                                                        "preauthorized": preauthorized, "tags": tags}}},
                "expirySeconds": expiry_s, "description": description[:50]}
        k = c.post(f"{api}/api/v2/tailnet/{tailnet_name}/keys", json=body,
                   headers={"Authorization": f"Bearer {access}"})
    if k.status_code != 200:
        try:
            msg = k.json().get("message")
        except ValueError:
            msg = k.text[:200]
        raise HTTPException(502, f"Tailscale refused the key (HTTP {k.status_code}): {msg}")
    out = k.json()
    return {"key": out.get("key"), "id": out.get("id"), "expires": out.get("expires"), "ephemeral": ephemeral,
            "reusable": False, "preauthorized": preauthorized, "tags": tags}


def router(ctx: AdminContext, admin_actor) -> APIRouter:
    r = APIRouter()

    def _facts(planned: bool = False) -> dict[str, Any]:
        humans = sorted(p.handle.lstrip("@") for p in ctx.board.store.query("participant", {}) if p.type == "human")
        return tailnet.gather(planned=planned, humans=humans, seats=_seat_handles())

    @r.get("/v1/admin/tailnet")
    def tailnet_status(a: Participant = Depends(admin_actor)):
        f = _facts()
        return {"ok": True, "value": {**tailnet.summary(f, tailnet.classify(f)),
                                      "auth_keys": {"configured": tailscale_configured()}}, "hint": ""}

    @r.post("/v1/admin/tailnet/apply")
    def tailnet_apply(b: ApplyIn | None = None, a: Participant = Depends(admin_actor)):
        try:
            out = tailnet.apply(_facts(planned=True), force=bool(b and b.force))
        except tailnet.TailnetError as e:
            raise HTTPException(409, str(e)) from None
        return {"ok": True, "value": out, "hint": "restart the board and mcp from Services to switch to public mode"}

    @r.post("/v1/admin/tailnet/remove")
    def tailnet_remove(a: Participant = Depends(admin_actor)):
        try:
            out = tailnet.remove(_facts())
        except tailnet.TailnetError as e:
            raise HTTPException(409, str(e)) from None
        return {"ok": True, "value": out, "hint": "restart the board and mcp from Services to return to trusted mode"}

    @r.post("/v1/admin/teammates/{handle}/tailscale-key")
    def tailscale_key(handle: str, b: KeyIn | None = None, a: Participant = Depends(admin_actor)):
        b = b or KeyIn()
        if not tailscale_configured():
            raise HTTPException(409, "Tailscale auth keys are off: set tailscale.oauth_client_id and "
                                     "tailscale.oauth_client_secret in Admin → Settings (Network) first")
        try:
            p = ctx.board.participant(handle)
        except BoardError as e:
            raise HTTPException(404, e.message) from None
        if p.type != "human":
            raise HTTPException(404, f"{handle!r} is not a teammate")
        tags = b.tags if b.tags is not None else list(settings.get("EDP_TAILSCALE_KEY_TAGS") or [])
        if not tags:
            raise HTTPException(400, "an OAuth-minted auth key must carry at least one tag (tailscale.key_tags)")
        try:
            out = mint_auth_key(description=f"heronry {p.handle.lstrip('@')}", ephemeral=b.ephemeral,
                                preauthorized=b.preauthorized, expiry_s=b.expiry_s, tags=tags)
        except httpx.HTTPError as e:
            raise HTTPException(502, f"could not reach the Tailscale API: {e}") from None
        return {"ok": True, "value": {"teammate": p.handle.lstrip("@"), **out},
                "hint": "shown once: hand it to the teammate for `tailscale up --auth-key=…`"}

    return r
