"""GET/PUT /v1/me/settings — a person's profile, notification and Slack preferences
(epic-44a0576511 · s-7f663c6322). Humans only: an agent seat has no Slack to ring."""
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from .schemas import Participant
from .user_settings import load_settings, public, save_settings


def settings_router(actor: Callable[..., Participant]) -> APIRouter:
    router = APIRouter()

    def _human(a: Participant) -> Participant:
        if a.type != "human":
            raise HTTPException(403, "settings belong to people; an agent seat has none")
        return a

    @router.get("/v1/me/settings")
    def get_settings(response: Response, a: Participant = Depends(actor)):
        response.headers["Cache-Control"] = "private, no-store"
        a = _human(a)
        return {"ok": True, "value": public(load_settings(a.handle)), "hint": ""}

    @router.put("/v1/me/settings")
    def put_settings(response: Response, body: dict[str, Any] = Body(...),
                     a: Participant = Depends(actor)):
        response.headers["Cache-Control"] = "private, no-store"
        a = _human(a)
        stored = save_settings(a.handle, body)
        return {"ok": True, "value": public(stored),
                "hint": "saved; the Slack bridge picks the change up within a minute"}

    return router
