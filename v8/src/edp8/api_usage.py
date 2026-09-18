"""Authenticated, participant-scoped subscription widget endpoint."""
from typing import Callable

from fastapi import APIRouter, Depends, Response

from .schemas import Participant
from .usage import UsageCache


def usage_router(actor: Callable[..., Participant], cache: UsageCache | None = None) -> APIRouter:
    router = APIRouter()
    cache = cache or UsageCache()

    @router.get("/v1/me/usage")
    def usage(response: Response, a: Participant = Depends(actor)):
        response.headers["Cache-Control"] = "private, no-store"
        return {"ok": True, "value": cache.read(a.id), "hint": ""}

    return router
