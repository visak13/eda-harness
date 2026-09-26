"""The admin console backend: every `/v1/admin/*` route (design-e963c656f5 §4.8, §4.10, §4.11; S5
s-8c6c81f596). One module per Admin panel; every route depends on the one admin gate in :mod:`.auth`."""

from __future__ import annotations

from fastapi import APIRouter

from .auth import is_admin, make_admin_actor
from .context import AdminContext, LastSeen

__all__ = ["AdminContext", "LastSeen", "admin_router", "is_admin", "make_admin_actor", "PUBLIC_ROUTES"]

#: routes under /v1 that the admin panels add but that are NOT admin-gated: the invite redeem (the one-time
#: code is the credential), and t-882e4d2eeb's sign out and request-access routes (edp8.admin.access)
PUBLIC_ROUTES = ("/v1/join", "/v1/signout", "/v1/access-requests", "/v1/access-requests/available",
                 "/v1/access-requests/claim")


def admin_router(ctx: AdminContext) -> APIRouter:
    from . import access, capacity, harnesses, integrations, models, remote, services, settings_api, setup_api, teammates, updates

    gate = make_admin_actor(ctx)
    r = APIRouter()
    for mod in (settings_api, services, capacity, teammates, access, remote, integrations, harnesses, models, updates,
                setup_api):
        r.include_router(mod.router(ctx, gate))
    r.include_router(access.public_router(ctx))
    return r
