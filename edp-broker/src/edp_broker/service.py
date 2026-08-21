"""BrokerService (Microservice ABC) + FastAPI app (LLD §3)."""

import asyncio
import time
from datetime import datetime
from pathlib import Path

from edp_contracts import HealthStatus, Microservice, Tool, get_logger, mount
from edp_contracts.errors import ErrorCode
from pydantic import ValidationError

from .store import BadRecipient, InboxStore

# 2026-05-26: per-request logging (publish/inbox routing) — the broker
# logged only at startup, so a dropped/misrouted message left no trace.
# Writes to the daily-rolling edp-broker.log under EDP_LOG_DIR.
_log = get_logger("edp-broker")

_VERSION = "1.0.0"
# S3b: extracted. 409 = "the request is well-formed but the broker refuses
# it" (unregistered kind / unroutable recipient) — distinct from a 500.
_ENVELOPE_HTTP_STATUS = 409


class BrokerService(Microservice):
    name = "edp-broker"
    version = _VERSION

    def __init__(self, store: InboxStore):
        self.store = store

    async def startup(self) -> None:  # nothing to warm
        return None

    async def shutdown(self) -> None:
        return None

    async def health(self) -> HealthStatus:
        return HealthStatus(status="ready", version=_VERSION)


def _parse_since(raw: str | None) -> datetime | None:
    if not raw:
        return None
    return datetime.fromisoformat(raw)


# Default keep-alive tick for a live SSE stream. The client (rx driver)
# treats a `: keep-alive` comment as proof the connection is healthy.
_SSE_KEEPALIVE_S = 15.0


class StreamHub:
    """In-process push notifier for the live `/v1/events` stream. The
    broker is one process — every `/v1/publish` lands here — so an
    asyncio.Event per recipient is enough to wake a waiting SSE generator
    the instant a message is appended (no busy-poll). Events are
    level-triggered: a notify that fires between a read and the next wait
    is not lost (the flag stays set until the waiter clears it)."""

    def __init__(self) -> None:
        self._events: dict[str, asyncio.Event] = {}

    def _event(self, recipient: str) -> asyncio.Event:
        return self._events.setdefault(recipient, asyncio.Event())

    def notify(self, recipient: str) -> None:
        self._event(recipient).set()

    async def wait(self, recipient: str, timeout: float) -> bool:
        """Block until notified or `timeout`. Returns True if notified,
        False on timeout. Clears the flag so the next wait blocks again."""
        ev = self._event(recipient)
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            ev.clear()


def create_app(data_dir: Path):
    from fastapi import FastAPI, Request
    from fastapi import Query as _Query
    from fastapi.responses import JSONResponse, StreamingResponse

    store = InboxStore(Path(data_dir))
    svc = BrokerService(store)
    hub = StreamHub()
    app = FastAPI()
    mount(app, svc)  # /v1/health + structured logging + envelope handler

    def _err(code: ErrorCode, message: str):
        e = Tool.propagate(source="edp-broker", code=code, message=message)
        return JSONResponse(
            status_code=_ENVELOPE_HTTP_STATUS,
            content=e.model_dump(mode="json"),
        )

    @app.post("/v1/publish")
    async def publish(request: Request):
        body = await request.json()
        try:
            from edp_contracts import BrokerMessage

            msg = BrokerMessage.model_validate(body)
        except ValidationError as exc:
            _log.warning("publish_invalid", str(exc)[:200])
            return _err(ErrorCode.BROKER_UNREGISTERED_KIND, str(exc))
        try:
            # F36 R4#10 (2026-08-18): store IO runs OFF the event loop — a
            # large-inbox scan or slow disk on the loop stalled every
            # publish, poll, and SSE subscriber at once (fleet-wide
            # deafness). Same discipline on every endpoint below.
            await asyncio.to_thread(store.append, msg)
        except BadRecipient as exc:
            # the dead-letter case — a message to an unroutable recipient
            # (the bug class where replies vanished). Log it loudly.
            _log.warning("publish_no_route", str(exc)[:200],
                         to=msg.to, sender=msg.from_, msg_kind=msg.kind)
            return _err(ErrorCode.BROKER_NO_ROUTE, str(exc))
        _log.info("publish", msg.to, to=msg.to,
                  sender=msg.from_, msg_kind=msg.kind, msg_id=msg.msg_id)
        # wake any live /v1/events stream on the resolved target so the
        # push is instantaneous (not heartbeat-latency).
        target = store.aliases.resolve(msg.to) or msg.to
        hub.notify(target)
        if target != msg.to:
            hub.notify(msg.to)
        return {"msg_id": msg.msg_id}

    @app.get("/v1/inbox/{recipient}")
    async def inbox(recipient: str, since_ts: str | None = None):
        try:
            msgs = await asyncio.to_thread(
                store.read, recipient, _parse_since(since_ts))
        except BadRecipient as exc:
            _log.warning("inbox_no_route", str(exc)[:200], to=recipient)
            return _err(ErrorCode.BROKER_NO_ROUTE, str(exc))
        # log-volume fix (2026-06-10): rx subscriptions + heartbeats poll
        # this endpoint every ~2s PER subscriber, so an info line per poll
        # produced ~1 write/sec to stderr + the rotating file. An EMPTY
        # poll is pure noise — log it at debug (invisible at the default
        # EDP_LOG_LEVEL=info); an actual delivery stays info.
        if msgs:
            _log.info("inbox", recipient, to=recipient, count=len(msgs))
        else:
            _log.debug("inbox", recipient, to=recipient, count=0)
        return [m.model_dump(mode="json", by_alias=True) for m in msgs]

    @app.put("/v1/channels/{name}")
    async def channel_put(name: str, request: Request):
        """Create/update a channel: {"members": [...], "topic": "..."}.
        Registry only — the inbox appears with its first message."""
        body = await request.json()
        try:
            row = store.channels.put(name, list(body.get("members", [])),
                                     str(body.get("topic", "")))
        except BadRecipient as exc:
            return _err(ErrorCode.BROKER_NO_ROUTE, str(exc))
        _log.info("channel_put", name, channel=name,
                  members=len(row["members"]))
        return row

    @app.patch("/v1/channels/{name}")
    async def channel_merge(name: str, request: Request):
        """F45#7 — atomic delta: {"add": [...], "remove": [...],
        "topic": "..."} merged against the CURRENT row inside the store's
        critical section. Callers must prefer this over GET→PUT (which
        races: two concurrent spawns each replaying a stale member list
        erased each other's registration)."""
        body = await request.json()
        try:
            row = store.channels.merge(
                name,
                add=list(body.get("add", [])),
                remove=list(body.get("remove", [])),
                topic=(str(body["topic"])
                       if "topic" in body and body["topic"] is not None
                       else None))
        except BadRecipient as exc:
            return _err(ErrorCode.BROKER_NO_ROUTE, str(exc))
        _log.info("channel_merge", name, channel=name,
                  members=len(row["members"]))
        return row

    @app.get("/v1/channels/{name}")
    async def channel_get(name: str):
        row = store.channels.get(name)
        if row is None:
            return _err(ErrorCode.BROKER_NO_ROUTE,
                        f"no channel {name!r}")
        return row

    @app.get("/v1/channels")
    async def channel_list(member: str | None = None):
        return store.channels.list(member)

    @app.delete("/v1/channels/{name}")
    async def channel_delete(name: str):
        return {"deleted": store.channels.delete(name), "channel": name}

    @app.get("/v1/messages")
    async def messages(
        to: str | None = None,
        from_: str | None = _Query(default=None, alias="from"),
        kind: str | None = None,
        since_ts: str | None = None,
    ):
        """GET-only cross-inbox inspection (OBJECT-MODEL.md increment 3).
        Powers query_objects('message', where={to?, from?, kind?, since?}).
        All filters optional — no `to` means scan every inbox."""
        msgs = await asyncio.to_thread(
            store.query, to=to, from_=from_, kind=kind,
            since=_parse_since(since_ts))
        # same volume discipline as /v1/inbox: empty result → debug.
        if msgs:
            _log.info("messages", to or "*", to=to, sender=from_,
                      msg_kind=kind, count=len(msgs))
        else:
            _log.debug("messages", to or "*", to=to, sender=from_,
                       msg_kind=kind, count=0)
        return [m.model_dump(mode="json", by_alias=True) for m in msgs]

    @app.get("/v1/message/{msg_id}")
    async def message(msg_id: str):
        """Team-architecture Phase 2 (2026-05-21) — supports the
        `reply()` MCP tool which routes answers by msg_id."""
        m = await asyncio.to_thread(store.get_message, msg_id)
        if m is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail=f"no msg {msg_id!r}")
        return m.model_dump(mode="json", by_alias=True)

    @app.get("/v1/events")
    async def events(
        recipient: str,
        since_ts: str | None = None,
        max_seconds: float | None = None,
    ):
        """Live SSE stream (object-model reactive layer). Replays the
        backlog newer than `since_ts`, then holds the connection open and
        PUSHES each new message the instant it's published (woken by the
        StreamHub — no busy-poll). `max_seconds` caps the stream lifetime
        (the rx driver reconnects with the last `since_ts` it saw —
        replay is idempotent). Omit `max_seconds` for an unbounded stream.

        Validation: a bad recipient name is surfaced as the standard 409
        envelope BEFORE streaming starts (never a path escape / 500)."""
        since = _parse_since(since_ts)
        try:
            await asyncio.to_thread(
                store.read, recipient, since)  # validates recipient name
        except BadRecipient as exc:
            _log.warning("events_no_route", str(exc)[:200], to=recipient)
            return _err(ErrorCode.BROKER_NO_ROUTE, str(exc))

        async def _gen():
            start = time.monotonic()
            cursor = since
            while True:
                for m in await asyncio.to_thread(
                        store.read, recipient, cursor):
                    yield f"data: {m.model_dump_json(by_alias=True)}\n\n"
                    cursor = m.ts
                if (max_seconds is not None
                        and time.monotonic() - start >= max_seconds):
                    yield ": keep-alive\n\n"   # final flush, then close
                    return
                remaining = _SSE_KEEPALIVE_S
                if max_seconds is not None:
                    remaining = min(
                        remaining, max_seconds - (time.monotonic() - start))
                if remaining <= 0:
                    yield ": keep-alive\n\n"
                    return
                if not await hub.wait(recipient, timeout=remaining):
                    yield ": keep-alive\n\n"   # idle tick (connection live)

        return StreamingResponse(_gen(), media_type="text/event-stream")

    @app.post("/v1/alias")
    async def alias(request: Request):
        b = await request.json()
        owner = b.get("owner_session")
        # s16: an absolute (ownerless) mapping — owner_session "*"/""/null —
        # registers a bare `alias → target` identity bridge (the pool uses
        # this for a planner's colon EDP_HANDLE → dash inbox). A real
        # owner_session keeps the relative `owner/alias → target` form.
        if owner in (None, "", "*"):
            store.aliases.put_absolute(b["alias"], b["target"])
        else:
            store.aliases.put(owner, b["alias"], b["target"])
        return {"ok": True}

    return app
