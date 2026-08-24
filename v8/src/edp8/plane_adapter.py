"""edp8 Plane CE mirror adapter — one-way push (board -> Plane) + webhook sink (Plane -> board).

The board stays the source of truth (FRAMEWORK-V8-DRAFT-v2 §4: Plane as ticket
store/portal — our adapter mirrors, it never leads). `PlaneMirror.on_event`
turns board events into best-effort Plane REST calls; `PlaneSync.run_forever`
polls `board.store.events_since` and feeds them in. A small `plane_map` sqlite
table (kept in the board's own connection) tracks ticket_id -> Plane issue id.

The webhook sink is the only path back: an issue comment not authored by our
own mirror becomes a `note` Message on the mapped ticket, created_by="plane".
Nothing else flows back — Plane never drives status, assignment, or docs.
"""

from __future__ import annotations

import hashlib
import hmac
import html as html_mod
import json
import logging
import os
import re
import threading
import time
from typing import Any

import httpx
from fastapi import APIRouter, Request

from .board import Board
from .schemas import DocType, Event, EventKind, Message, MessageKind, TicketStatus
from .store import Store, new_id

logger = logging.getLogger("edp8.plane_adapter")

DEFAULT_STATE_MAP: dict[str, str] = {s.value: s.value for s in TicketStatus}


# ----------------------------------------------------------------------------- Plane REST client


class PlaneClient:
    def __init__(self, base_url: str, api_key: str, workspace_slug: str, project_id: str,
                 http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.workspace_slug = workspace_slug
        self.project_id = project_id
        self.http = http or httpx.Client(headers={"X-API-Key": api_key}, timeout=15.0)

    def _url(self, suffix: str = "") -> str:
        return f"{self.base_url}/api/v1/workspaces/{self.workspace_slug}/projects/{self.project_id}/issues/{suffix}"

    def create_issue(self, name: str, description_html: str = "", parent: str | None = None,
                      state: str | None = None, labels: list[str] | None = None) -> str:
        body: dict[str, Any] = {"name": name, "description_html": description_html}
        if parent:
            body["parent"] = parent
        if state:
            body["state"] = state
        if labels:
            body["labels"] = labels
        r = self.http.post(self._url(), json=body)
        r.raise_for_status()
        return r.json()["id"]

    def update_issue(self, issue_id: str, **fields: Any) -> None:
        r = self.http.patch(self._url(f"{issue_id}/"), json=fields)
        r.raise_for_status()

    def add_comment(self, issue_id: str, comment_html: str) -> None:
        r = self.http.post(self._url(f"{issue_id}/comments/"), json={"comment_html": comment_html})
        r.raise_for_status()

    def list_states(self) -> dict[str, str]:
        url = f"{self.base_url}/api/v1/workspaces/{self.workspace_slug}/projects/{self.project_id}/states/"
        r = self.http.get(url)
        r.raise_for_status()
        data = r.json()
        rows = data.get("results", data) if isinstance(data, dict) else data
        return {row["name"]: row["id"] for row in rows}


# ----------------------------------------------------------------------------- ticket <-> issue map


def _ensure_map_table(board: Board) -> None:
    with board.store._lock, board.store._conn:
        board.store._conn.execute(
            "CREATE TABLE IF NOT EXISTS plane_map (ticket_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL)")


def _map_get(board: Board, ticket_id: str | None) -> str | None:
    if not ticket_id:
        return None
    with board.store._lock:
        row = board.store._conn.execute(
            "SELECT issue_id FROM plane_map WHERE ticket_id=?", (ticket_id,)).fetchone()
    return row["issue_id"] if row else None


def _map_put(board: Board, ticket_id: str, issue_id: str) -> None:
    with board.store._lock, board.store._conn:
        board.store._conn.execute(
            "INSERT OR REPLACE INTO plane_map(ticket_id, issue_id) VALUES(?,?)", (ticket_id, issue_id))


def _ticket_for_issue(board: Board, issue_id: str) -> str | None:
    with board.store._lock:
        row = board.store._conn.execute(
            "SELECT ticket_id FROM plane_map WHERE issue_id=?", (issue_id,)).fetchone()
    return row["ticket_id"] if row else None


# ----------------------------------------------------------------------------- mirror


class PlaneMirror:
    """board Event -> Plane REST call. Every call is best-effort: errors are logged
    and appended to `self.errors`, never raised."""

    def __init__(self, board: Board, client: PlaneClient, state_map: dict[str, str] | None = None):
        self.board = board
        self.client = client
        self.state_map = state_map or dict(DEFAULT_STATE_MAP)
        self.errors: list[str] = []
        self._states: dict[str, str] | None = None
        _ensure_map_table(board)

    def _states_cache(self) -> dict[str, str]:
        if self._states is None:
            try:
                self._states = self.client.list_states()
            except httpx.HTTPError as e:
                self.errors.append(f"list_states: {e}")
                self._states = {}
        return self._states

    def on_event(self, event: Event) -> None:
        try:
            self._dispatch(event)
        except Exception as e:  # best-effort: mirroring never raises out
            logger.warning("plane mirror error on %s %s: %s", event.kind, event.subject_id, e)
            self.errors.append(f"{event.kind}:{event.subject_id}: {e}")

    def _dispatch(self, event: Event) -> None:
        if event.kind == EventKind.ticket_created:
            self._on_ticket_created(event)
        elif event.kind == EventKind.status_changed:
            self._on_status_changed(event)
        elif event.kind == EventKind.message_sent:
            self._on_message_sent(event)
        elif event.kind == EventKind.doc_updated:
            self._on_doc_updated(event)
        elif event.kind == EventKind.assigned:
            self._on_assigned(event)

    def _on_ticket_created(self, event: Event) -> None:
        ticket = self.board.ticket(event.subject_id)
        parent_issue = self._map_get(ticket.parent_id) if ticket.parent_id else None
        state_id = self._states_cache().get(self.state_map.get(ticket.status.value, ""))
        issue_id = self.client.create_issue(ticket.title, f"<p>{ticket.kind.value} / {ticket.work_type.value}</p>",
                                             parent=parent_issue, state=state_id)
        _map_put(self.board, ticket.id, issue_id)

    def _on_status_changed(self, event: Event) -> None:
        issue_id = self._map_get(event.subject_id)
        plane_state_name = self.state_map.get(event.data.get("to", ""))
        state_id = self._states_cache().get(plane_state_name) if plane_state_name else None
        if issue_id and state_id:
            self.client.update_issue(issue_id, state=state_id)

    def _on_message_sent(self, event: Event) -> None:
        issue_id = self._map_get(event.subject_id)
        if issue_id:
            kind, frm, text = event.data.get("kind", "note"), event.data.get("from", ""), event.data.get("text", "")
            self.client.add_comment(issue_id, f"<p>[edp8:{kind}] from {html_mod.escape(frm)}: {html_mod.escape(text)}</p>")

    def _on_doc_updated(self, event: Event) -> None:
        doc = self.board.store.get("doc", event.subject_id)
        if doc is None or doc.doc_type != DocType.design:
            return
        issue_id = self._map_get(doc.scope)
        if issue_id:
            self.client.add_comment(issue_id, f"<p>[edp8:doc] {doc.id} v{doc.version}</p>")

    def _on_assigned(self, event: Event) -> None:
        issue_id = self._map_get(event.subject_id)
        if issue_id:
            self.client.add_comment(issue_id, f"<p>[edp8:assigned] {html_mod.escape(str(event.data.get('assignee')))}</p>")

    def _map_get(self, ticket_id: str | None) -> str | None:
        return _map_get(self.board, ticket_id)


# ----------------------------------------------------------------------------- polling sync


class PlaneSync:
    def __init__(self, board: Board, mirror: PlaneMirror, poll_interval: float = 2.0):
        self.board = board
        self.mirror = mirror
        self.poll_interval = poll_interval
        self._stop = threading.Event()

    def run_forever(self, since_seq: int = 0) -> None:
        seq = since_seq
        while not self._stop.is_set():
            events = self.board.store.events_since(seq, limit=200)
            for s, ev in events:
                self.mirror.on_event(ev)
                seq = s
            if not events:
                time.sleep(self.poll_interval)

    def stop(self) -> None:
        self._stop.set()


# ----------------------------------------------------------------------------- env wiring


def build_from_env(board: Board) -> tuple[PlaneMirror, PlaneSync] | None:
    url = os.environ.get("EDP8_PLANE_URL")
    if not url:
        return None
    api_key = os.environ.get("EDP8_PLANE_API_KEY", "")
    workspace = os.environ.get("EDP8_PLANE_WORKSPACE", "")
    project = os.environ.get("EDP8_PLANE_PROJECT", "")
    raw_states = os.environ.get("EDP8_PLANE_STATES")
    state_map = json.loads(raw_states) if raw_states else dict(DEFAULT_STATE_MAP)
    client = PlaneClient(url, api_key, workspace, project)
    mirror = PlaneMirror(board, client, state_map)
    sync = PlaneSync(board, mirror)
    return mirror, sync


def start_mirror_thread(board: Board) -> PlaneSync | None:
    """Start the mirror as a daemon thread inside the board process. No-op (returns None)
    when EDP8_PLANE_URL is unset."""
    built = build_from_env(board)
    if built is None:
        return None
    _, sync = built
    since = board.store.max_seq()
    t = threading.Thread(target=sync.run_forever, args=(since,), daemon=True, name="plane-sync")
    t.start()
    logger.info("plane mirror thread started (since seq %s)", since)
    return sync


# ----------------------------------------------------------------------------- webhook sink


def webhook_router(board: Board) -> APIRouter:
    _ensure_map_table(board)
    r = APIRouter()

    @r.post("/v1/plane/webhook")
    async def plane_webhook(req: Request):
        raw = await req.body()
        secret = os.environ.get("EDP8_PLANE_WEBHOOK_SECRET", "")
        if secret:
            sig = req.headers.get("X-Plane-Signature", "")
            want = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, want):
                return {"ok": False, "error": {"code": "auth", "message": "webhook signature mismatch"},
                        "hint": "EDP8_PLANE_WEBHOOK_SECRET must match the secret configured on the Plane webhook"}
        _handle_webhook(board, json.loads(raw or b"{}"))
        return {"ok": True}

    return r


def _handle_webhook(board: Board, payload: dict[str, Any]) -> None:
    event_type = str(payload.get("event", ""))
    data = payload.get("data") or {}
    if "comment" not in event_type.lower():
        return
    comment_html = data.get("comment_html") or data.get("comment_stripped") or ""
    stripped = re.sub(r"<[^>]+>", "", comment_html).strip()
    if not stripped or stripped.startswith("[edp8:"):
        return  # empty, or our own mirrored comment — never echo it back as a note
    issue_id = data.get("issue") or data.get("issue_id")
    if not issue_id:
        return
    ticket_id = _ticket_for_issue(board, issue_id)
    if not ticket_id:
        return
    m = Message(id=new_id("m"), ticket_id=ticket_id, to=None, kind=MessageKind.note, text=comment_html,
                created_by="plane")
    board.store.put("message", m)


# ----------------------------------------------------------------------------- standalone process


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    db = os.environ.get("EDP8_DB", "edp8.db")
    board = Board(Store(db))
    built = build_from_env(board)
    if built is None:
        logger.error("EDP8_PLANE_URL not set; nothing to mirror")
        return
    _, sync = built
    logger.info("plane sync starting (since seq %s)", board.store.max_seq())
    sync.run_forever(board.store.max_seq())


if __name__ == "__main__":
    _main()
