"""The admin tier (design-e963c656f5 §4.8; decision dec-9c292f88a4).

An admin is a HUMAN participant with the `admin` flag, or the init human (handle == `EDP8_OWNER`, the
epic owner on this host). Creating an epic grants nothing. Every `/v1/admin/*` route depends on
:func:`make_admin_actor`: `X-Participant` plus an `X-Token` equal to that human's secret in the tokens
file. There is no header-only path (trusted mode included), the machine `X-Admin` token is not accepted,
agents and experts never pass, and every refusal is 403.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable

from fastapi import Header, HTTPException

from .. import settings
from ..board import BoardError
from ..schemas import Participant, Role
from .context import AdminContext


def owner_handle() -> str:
    return str(settings.get("EDP8_OWNER") or "owner").lstrip("@")


def is_admin(p: Participant) -> bool:
    if p.type != "human" or p.role == Role.expert:
        return False
    return bool(getattr(p, "admin", False)) or p.handle.lstrip("@") == owner_handle()


def make_admin_actor(ctx: AdminContext) -> Callable[..., Participant]:
    def admin_actor(x_participant: str | None = Header(default=None),
                    x_token: str | None = Header(default=None)) -> Participant:
        if not x_participant or not x_token:
            raise HTTPException(403, "admin routes need an admin human's X-Participant and X-Token")
        try:
            p = ctx.board.participant(x_participant)
        except BoardError:
            raise HTTPException(403, "admin routes need an admin human's X-Participant and X-Token") from None
        if p.type != "human":
            raise HTTPException(403, f"{p.handle!r} is an agent; only an admin human reaches /v1/admin")
        secret = ctx.tokens()[0].get(p.handle.lstrip("@"))
        if not secret or not hmac.compare_digest(secret.encode(), x_token.encode()):
            raise HTTPException(403, f"X-Token invalid for {p.handle!r}")
        if not is_admin(p):
            raise HTTPException(403, f"{p.handle!r} is not an admin")
        ctx.last_seen.touch(p.id)
        return p

    return admin_actor
