"""The admin console backend: every `/v1/admin/*` route (design-e963c656f5 §4.8, §4.10, §4.11; S5
s-8c6c81f596). One module per Admin panel; every route depends on the one admin gate in :mod:`.auth`."""

from __future__ import annotations

from fastapi import APIRouter

from .auth import is_admin, make_admin_actor
from .context import AdminContext, LastSeen

__all__ = ["AdminContext", "LastSeen", "admin_router", "is_admin", "make_admin_actor", "PUBLIC_ROUTES"]

#: routes under /v1 that the admin panels add but that are NOT admin-gated (the invite redeem: the
#: one-time code is the credential)
PUBLIC_ROUTES = ("/v1/join",)


def admin_router(ctx: AdminContext) -> APIRouter:
    from . import remote, services, settings_api, teammates

    gate = make_admin_actor(ctx)
    r = APIRouter()
    for mod in (settings_api, services, teammates, remote):
        r.include_router(mod.router(ctx, gate))
    return r
