"""Library topic routes (S-SME-SURFACE, s-698224fca8). The only routes an expert's token reaches: its own
topic's page, docs and thread (`topic_actor` admits experts; every other route's `actor` refuses them).
The owner opens/closes topics, edits tags and adds/removes experts; the topic's sme researches and
proposes (also over MCP: topic_research / topic_propose)."""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Callable, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import topics
from .board import Board, BoardError
from .schemas import DocType, MessageKind, Participant, Role


class TopicIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    tags: list[str] = Field(default_factory=list)
    seed_url: str | None = None
    description: str = ""
    words: str | None = None                                  # the topic's purpose, verbatim (t-f5bf848f0f)
    model: str | None = None                                  # the sme's model, from GET /v1/models role sme
    effort: Literal["low", "medium", "high"] | None = None    # capped for a Claude seat at spawn


class TagsIn(BaseModel):
    tags: list[str]


class ExpertIn(BaseModel):
    handle: str
    name: str = ""


class TopicMessageIn(BaseModel):
    text: str
    kind: MessageKind = MessageKind.note
    to: str | None = None
    reply_to: str | None = None


class ResearchIn(BaseModel):
    query: str | None = None
    url: str | None = None


class ProposeIn(BaseModel):
    title: str
    body_md: str
    source_url: str
    doc_type: DocType = DocType.strategy_hl
    tags: list[str] = Field(default_factory=list)
    proposes: str | None = None


def _ok(value: Any, hint: str = "") -> dict[str, Any]:
    return {"ok": True, "value": value, "hint": hint}


class ExpertSessionIn(BaseModel):
    code: str


EXPERT_CODE_TTL_S = 24 * 3600  # an unredeemed expert link dies after a day; the owner re-adds the expert


def topics_router(board: Board, actor: Callable[..., Participant], topic_actor: Callable[..., Participant],
                  mint_human: Callable[[str], str | None], revoke_human: Callable[[str], None]) -> APIRouter:
    r = APIRouter()
    # t-3e246b5e32 (e): the expert's link carries a one-time CODE, never the token (history, referrers and
    # proxy logs keep query strings). code -> (handle, token, expires); in memory only, popped on first use,
    # so a board restart also kills an unredeemed link.
    codes: dict[str, tuple[str, str, float]] = {}
    codes_lock = threading.Lock()

    def _scoped(topic_id: str, a: Participant) -> None:
        """An expert reaches only the topic it is linked to (403 elsewhere, and for a missing topic)."""
        if a.role == Role.expert and topics.expert_topic(board, a) != topic_id:
            raise HTTPException(403, f"expert {a.handle!r} is not on {topic_id}")
        try:
            topics.topic(board, topic_id)
        except BoardError as e:
            raise HTTPException(404, e.message) from e

    @r.post("/v1/topics")
    def topic_create(b: TopicIn, a: Participant = Depends(actor)):
        out = topics.create(board, a, title=b.title, tags=b.tags, seed_url=b.seed_url, description=b.description,
                            words=b.words, model=b.model, effort=b.effort)
        return _ok({"topic": out["topic"].model_dump(mode="json"), "seat": out["seat"]},
                   "the sme seat is queued; it wakes on every message on the topic's thread")

    @r.get("/v1/topics")
    def topic_list(a: Participant = Depends(actor)):
        return _ok(topics.list_view(board))

    @r.get("/v1/topics/{topic_id}")
    def topic_page(topic_id: str, a: Participant = Depends(topic_actor)):
        _scoped(topic_id, a)
        return _ok({**topics.page(board, topic_id), "viewer": {"id": a.id, "role": a.role.value}})

    @r.get("/v1/topics/{topic_id}/docs/{doc_id}")
    def topic_doc(topic_id: str, doc_id: str, a: Participant = Depends(topic_actor)):
        _scoped(topic_id, a)
        try:
            d = topics.doc_for(board, topic_id, doc_id)
        except BoardError as e:
            raise HTTPException(404, e.message) from e
        return _ok(d.model_dump(mode="json"))

    @r.post("/v1/topics/{topic_id}/messages")
    def topic_post(topic_id: str, b: TopicMessageIn, a: Participant = Depends(topic_actor)):
        _scoped(topic_id, a)
        m = topics.post(board, a, topic_id, text=b.text, kind=b.kind, to=b.to, reply_to=b.reply_to)
        return _ok(m.model_dump(mode="json"))

    @r.patch("/v1/topics/{topic_id}/tags")
    def topic_tags(topic_id: str, b: TagsIn, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        return _ok(topics.set_tags(board, a, topic_id, b.tags).model_dump(mode="json"))

    @r.post("/v1/topics/{topic_id}/experts")
    def expert_add(topic_id: str, b: ExpertIn, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        p, token = topics.add_expert(board, a, topic_id, handle=b.handle, name=b.name, mint=mint_human)
        code, now = secrets.token_urlsafe(24), time.time()
        with codes_lock:
            for c in [c for c, v in codes.items() if v[2] < now]:
                codes.pop(c)
            codes[code] = (p.handle, token, now + EXPERT_CODE_TTL_S)
        link = f"/ui/library/topics/{topic_id}?as={quote(p.handle)}&code={code}"
        return _ok({"expert": p.model_dump(mode="json"), "link": link},
                   "hand the link to the expert now: it works once, within a day, and signs them in")

    @r.post("/v1/expert-session")
    def expert_session(b: ExpertSessionIn):
        """Redeem an expert link's one-time code for the expert's handle + token (the SPA keeps the token in
        the tab's session storage). No credential: the code is the credential, and it dies on first use."""
        with codes_lock:
            hit = codes.pop(b.code, None)
        if hit is None or hit[2] < time.time():
            raise HTTPException(401, "this expert link was already used or has expired; ask the owner for a new one")
        return _ok({"as": hit[0], "token": hit[1]}, "signed in: this link no longer works")

    @r.delete("/v1/topics/{topic_id}/experts/{expert_id}")
    def expert_remove(topic_id: str, expert_id: str, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        topics.remove_expert(board, a, topic_id, expert_id, revoke=revoke_human)
        return _ok({"removed": expert_id})

    @r.post("/v1/topics/{topic_id}/close")
    def topic_close(topic_id: str, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        return _ok(topics.close(board, a, topic_id).model_dump(mode="json"))

    @r.post("/v1/topics/{topic_id}/research")
    def topic_research(topic_id: str, b: ResearchIn, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        return _ok(topics.research(board, a, topic_id, query=b.query, url=b.url))

    @r.post("/v1/topics/{topic_id}/proposals")
    def topic_propose(topic_id: str, b: ProposeIn, a: Participant = Depends(actor)):
        _scoped(topic_id, a)
        out = topics.propose(board, a, topic_id, title=b.title, body_md=b.body_md, source_url=b.source_url,
                             doc_type=b.doc_type, tags=b.tags, proposes=b.proposes)
        return _ok({"doc": out["doc"].model_dump(mode="json"), "receipt": out["receipt"]},
                   "proposed: the owner approves or rejects it in the Library")

    return r
