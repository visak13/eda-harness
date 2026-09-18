"""JSON API over the pure view derivations (design §4.1, was S3).

`views_router(board, actor)` returns a FastAPI router that exposes every derivation in
`views.py` as JSON under the same `{ok, value, hint}` envelope the rest of the service uses.
`create_app` includes it AHEAD of the dynamic `/v1/tickets/{id}` and `/v1/docs/{id}` routes so
its static sub-paths (`/v1/tickets/table`, `/v1/epics/{id}/page`, `/v1/docs/{id}/html`) win the
match — Starlette resolves in registration order. Each endpoint is a thin adapter: it
authenticates through the shared `actor` dependency (except the raw avatar SVG, which an <img>
tag loads header-less) and returns a `views.*` result verbatim, so the legacy HTML renderer and
this API can never drift (both call the same function).

The sign-off write path (POST /v1/me/verdict), evidence_version and the stale-verdict refusal
ride `board.criterion_update`'s evidence_version/stale_ok kwargs (design §14 finding 3).
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel

from . import views
from .avatar_preferences import save_avatar_preference
from .avatars import (
    _HUMAN_NAMES,
    HUMAN_AVATAR_IDS,
    avatar_id_for,
    human_avatar_svg,
    role_avatar_svg,
    system_avatar_svg,
)
from .board import Board
from .schemas import Participant


def ok(value: Any, hint: str = "") -> dict[str, Any]:
    return {"ok": True, "value": value, "hint": hint}


class AvatarIn(BaseModel):
    model_config = {"extra": "forbid"}
    avatar_id: str


class VerdictIn(BaseModel):
    model_config = {"extra": "forbid"}
    criterion_id: str
    verdict: str
    note: str = ""
    ticket_id: str | None = None
    evidence_version: int  # §14 finding 2: a sign-off must name the doc version it read — required, no bypass
    stale_ok: bool = False


def _catalog() -> list[dict[str, str]]:
    """The pickable human avatars — id, display name and the inline SVG — the source the
    avatar picker renders (parity with avatars.avatar_picker_html, as JSON)."""
    return [{"id": aid, "name": _HUMAN_NAMES[i], "svg": human_avatar_svg(aid, 48)}
            for i, aid in enumerate(HUMAN_AVATAR_IDS)]


def views_router(board: Board, actor: Callable[..., Participant]) -> APIRouter:
    r = APIRouter()

    @r.get("/v1/me/notifications")
    def me_notifications(since: int = Query(default=-1, ge=-1), request: str | None = None,
                         a: Participant = Depends(actor)):
        from .notifications import attention
        return ok(attention(board, a, since=since, request=request))

    # -------------------------------------------------------------- me (Decisions home)
    @r.get("/v1/me/decisions")
    def me_decisions(a: Participant = Depends(actor)):
        return ok(views.decisions_for(board, a),
                  "sign-offs you must rule, questions in your inbox, open gates you can answer")

    @r.get("/v1/me/decisions/resolved")
    def me_resolved(limit: int = 30, a: Participant = Depends(actor)):
        return ok(views.resolved_for(board, a, limit=limit))

    @r.get("/v1/me/people")
    def me_people(a: Participant = Depends(actor)):
        return ok(views.people_for(board, a), "who you can reach — humans and live agent seats")

    @r.get("/v1/seats")
    def seats(a: Participant = Depends(actor)):
        """The Seats page (design §4.2, §18.3): agent seats with presence signals + closed seats
        with their reason, and a People block of humans. The client applies the 60s presence rule."""
        return ok(views.seats_for(board, a),
                  "agent seats (closed included) + humans; client reads presence age, never death from silence")

    @r.get("/v1/me/conversations")
    def me_conversations(a: Participant = Depends(actor)):
        return ok(views.conversations_for(board, a))

    @r.get("/v1/me/replies")
    def me_replies(limit: int = 30, a: Participant = Depends(actor)):
        """Replies to the viewer, newest first, each with the words it answers (human report
        m-3d3a36455f: a person could not tell whether anyone replied)."""
        return ok(views.replies_for(board, a, limit=limit))

    @r.get("/v1/me/summary")
    def me_summary(a: Participant = Depends(actor)):
        return ok(views.summary_for(board, a))

    @r.post("/v1/me/verdict")
    def me_verdict(b: VerdictIn, a: Participant = Depends(actor)):
        """One-click sign-off (design §14): record the verdict for the doc version named, and,
        when a note is given, post '[sign-off pass|fail] note' to the ticket's assignee. The
        board refuses an older version than the doc's current one unless stale_ok."""
        out = views.record_verdict(board, a, criterion_id=b.criterion_id, verdict=b.verdict,
                                   note=b.note, ticket_id=b.ticket_id,
                                   evidence_version=b.evidence_version, stale_ok=b.stale_ok)
        return ok(out, "verdict recorded" + (" and the assignee was told" if out["message"] else ""))

    # -------------------------------------------------------------- avatars
    @r.get("/v1/me/avatar")
    def me_avatar_get(a: Participant = Depends(actor)):
        ident = views.avatar_for(board, a.id)
        return ok({"avatar_id": ident["avatar_id"], "kind": ident["kind"],
                   "catalog": _catalog() if a.type == "human" else []})

    @r.put("/v1/me/avatar")
    def me_avatar_put(b: AvatarIn, a: Participant = Depends(actor)):
        if a.type != "human" or b.avatar_id not in HUMAN_AVATAR_IDS:
            return {"ok": False, "error": {"code": "bad_request",
                    "message": f"choose one of {list(HUMAN_AVATAR_IDS)} (humans only)"},
                    "hint": "GET /v1/me/avatar lists the catalog"}
        save_avatar_preference(a.id, b.avatar_id)
        ident = views.avatar_for(board, a.id)
        return ok({"avatar_id": ident["avatar_id"], "kind": ident["kind"]},
                  "saved; the mtime bump makes it show without a board restart")

    @r.get("/v1/avatars/catalog")
    def avatars_catalog(a: Participant = Depends(actor)):
        return ok({"avatars": _catalog()})

    @r.get("/v1/avatars/{pid}.svg")
    def avatar_svg(request: Request, pid: str, size: int = 36, palette: str | None = Query(default=None)):
        """The inline identity SVG for a participant — served header-less so an <img src>
        can load it, image/svg+xml. Cached by CONTENT (ETag + no-cache: the browser revalidates
        every time and gets a 304 unless the chosen avatar changed) — a fixed max-age served the
        previous face after a reload or a second pick (adversary round 2 #15, 2026-09-10).
        `palette=human-0N` overrides with a specific human avatar (the picker previews a choice
        before it is saved)."""
        if palette in HUMAN_AVATAR_IDS:
            svg = human_avatar_svg(palette, size)
        else:
            p = views._participant(board, pid)
            if p is None:
                svg = system_avatar_svg(size, unknown=True)
            elif p.type == "human":
                svg = human_avatar_svg(avatar_id_for(p, views._prefs()), size)
            else:
                svg = role_avatar_svg(p.role, p.model, size)
        etag = '"' + hashlib.sha1(svg.encode("utf-8")).hexdigest()[:20] + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
        return Response(content=svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "no-cache", "ETag": etag})

    # -------------------------------------------------------------- epics / tickets
    @r.get("/v1/epics/summary")
    def epics_summary(status: str | None = None, q: str | None = None, a: Participant = Depends(actor)):
        return ok(views.epics_summary(board, a, status=status, q=q))

    @r.get("/v1/epics/{epic_id}/page")
    def epic_page(epic_id: str, include: str | None = None, a: Participant = Depends(actor)):
        return ok(views.epic_page(board, epic_id, include=include))

    @r.get("/v1/tickets/table")
    def tickets_table(epic: str | None = None, status: str | None = None, kind: str | None = None,
                      work_type: str | None = None, assignee: str | None = None, tag: str | None = None,
                      q: str | None = None, a: Participant = Depends(actor)):
        return ok(views.tickets_table(board, epic=epic, status=status, kind=kind, work_type=work_type,
                                      assignee=assignee, tag=tag, q=q))

    @r.get("/v1/tickets/{ticket_id}/page")
    def ticket_page(ticket_id: str, include: str | None = None, a: Participant = Depends(actor)):
        # ?include=m-… keeps a deep-linked message in the thread even outside the newest-100 window
        return ok(views.ticket_page(board, ticket_id, include=include))

    @r.get("/v1/tickets/{ticket_id}/thread")
    def ticket_thread(ticket_id: str, before: int | None = Query(default=None, ge=1, le=9223372036854775807),
                      a: Participant = Depends(actor)):
        return ok(views.thread_page(board, ticket_id, before=before))

    @r.get("/v1/tickets/{ticket_id}/transitions")
    def ticket_transitions(ticket_id: str, a: Participant = Depends(actor)):
        # The status edges offered to THIS viewer, each allowed/blocked with the board's own reason
        # (S16 status control). Legality comes from the board's single rule source, never the client.
        return ok(board.legal_transitions(a, ticket_id))

    # -------------------------------------------------------------- docs / activity / library
    @r.get("/v1/docs/{doc_id}/html")
    def doc_html(doc_id: str, version: int | None = None, a: Participant = Depends(actor)):
        return ok(views.doc_page(board, doc_id, viewer=a, version=version))

    @r.get("/v1/activity")
    def activity(limit: int = 120, a: Participant = Depends(actor)):
        return ok(views.activity_for(board, a, limit=limit))

    @r.get("/v1/library")
    def library(epic: str | None = None, a: Participant = Depends(actor)):
        return ok(views.library_for(board, epic))

    return r
