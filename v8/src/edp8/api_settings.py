"""GET/PUT /v1/me/settings — a person's profile, notification and Slack preferences
(epic-44a0576511 · s-7f663c6322). Humans only: an agent seat has no Slack to ring."""
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.responses import JSONResponse

from .schemas import Participant
from .slack_bridge import send_test_ping
from .user_settings import load_settings, public, save_settings, webhook_rejection


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
        # Finding 22: reject an invalid/off-list webhook with a 422 + field error, so the SPA can
        # show it and the previously stored (valid) webhook is left untouched — never silently wiped.
        rejection = webhook_rejection(body)
        if rejection:
            return JSONResponse(status_code=422, headers={"Cache-Control": "private, no-store"},
                                content={"ok": False,
                                         "error": {"code": "invalid_webhook", "message": rejection,
                                                   "field": "slack.webhook_url"},
                                         "hint": rejection})
        stored = save_settings(a.handle, body)
        return {"ok": True, "value": public(stored),
                "hint": "saved; the Slack bridge picks the change up within a minute"}

    @router.post("/v1/me/settings/slack/test")
    def slack_test_ping(response: Response, a: Participant = Depends(actor)):
        """Ring the caller's OWN Slack with a test message. The destination is read from stored
        settings server-side — the masked webhook the SPA holds is never accepted or echoed — and
        the webhook host is re-validated before sending (findings 3/10/17)."""
        response.headers["Cache-Control"] = "private, no-store"
        a = _human(a)
        slack = load_settings(a.handle)["slack"]
        if not slack["enabled"] or not (slack["slack_id"] or slack["webhook_url"]):
            raise HTTPException(400, "enable Slack and set a member id or webhook URL first")
        ok, detail = send_test_ping(a.handle, slack)
        if not ok:
            raise HTTPException(502, detail)
        return {"ok": True, "value": {"delivered": True}, "hint": detail}

    return router
