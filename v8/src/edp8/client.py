"""edp8 board client — a thin sync httpx wrapper, one method per HTTP route.

Every call returns the parsed JSON envelope unchanged: `{ok, value, hint}` or
`{ok: false, error: {code, message}, hint}`. Never raises on 4xx/409 — those are
data, not exceptions. Only a connection failure raises, with a clear message.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class BoardUnreachable(Exception):
    pass


class BoardClient:
    """One method per /v1 route on edp8.service. Sync; safe to call from tool handlers."""

    def __init__(self, base_url: str | None = None, participant: str | None = None,
                 admin_token: str | None = None, client: httpx.Client | None = None):
        self.base_url = (base_url or os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400")).rstrip("/")
        self.participant = participant or os.environ.get("EDP8_PARTICIPANT") or os.environ.get("EDP_HANDLE")
        self.admin_token = admin_token if admin_token is not None else os.environ.get("EDP8_ADMIN_TOKEN")
        self._client = client

    # ------------------------------------------------------------------ transport
    def _headers(self, admin: bool = False) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.participant:
            h["X-Participant"] = self.participant
        token = os.environ.get("EDP8_TOKEN")
        if token:  # human identities on a board with tokens.json need their secret
            h["X-Token"] = token
        if admin and self.admin_token:
            h["X-Admin"] = self.admin_token
        return h

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 json: dict[str, Any] | None = None, admin: bool = False) -> dict[str, Any]:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            if self._client is not None:
                resp = self._client.request(method, path, params=params, json=json, headers=self._headers(admin))
            else:
                resp = httpx.request(method, f"{self.base_url}{path}", params=params, json=json,
                                     headers=self._headers(admin), timeout=30.0)
        except httpx.HTTPError as e:
            raise BoardUnreachable(f"board unreachable at {self.base_url}: {e}") from e
        try:
            return resp.json()
        except ValueError as e:
            raise BoardUnreachable(f"board unreachable at {self.base_url}: non-JSON response ({e})") from e

    # ------------------------------------------------------------------ identity
    def whoami(self) -> dict[str, Any]:
        return self._request("GET", "/v1/whoami")

    def describe(self, type_: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/describe/{type_}")

    def context(self, ticket_id: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/context", params={"ticket_id": ticket_id})

    # ------------------------------------------------------------------ registry
    def participant_create(self, type: str, role: str, handle: str, location: str | None = None,
                           model: str | None = None, id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/participants", admin=bool(self.admin_token),
                             json={"type": type, "role": role, "handle": handle, "location": location,
                                   "model": model, "id": id})

    def participants(self, role: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/participants", params={"role": role})

    def participant_get(self, id_: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/participants/{id_}")

    # ------------------------------------------------------------------ tickets
    def ticket_create(self, kind: str, work_type: str, title: str, parent_id: str | None = None,
                      assignee: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/tickets",
                             json={"kind": kind, "work_type": work_type, "title": title,
                                   "parent_id": parent_id, "assignee": assignee})

    def ticket_read(self, id_: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/tickets/{id_}")

    def ticket_query(self, kind: str | None = None, work_type: str | None = None, parent_id: str | None = None,
                     status: str | None = None, assignee: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/tickets", params={"kind": kind, "work_type": work_type,
                                                            "parent_id": parent_id, "status": status,
                                                            "assignee": assignee})

    def ticket_update(self, id_: str, status: str | None = None, assignee: str | None = None,
                      design_ref: str | None = None) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/tickets/{id_}",
                             json={"status": status, "assignee": assignee, "design_ref": design_ref})

    # ------------------------------------------------------------------ criteria
    def criterion_create(self, ticket_id: str, text: str, check: str, checked_by: str) -> dict[str, Any]:
        return self._request("POST", "/v1/criteria",
                             json={"ticket_id": ticket_id, "text": text, "check": check, "checked_by": checked_by})

    def criterion_query(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", "/v1/criteria", params={"ticket_id": ticket_id})

    def criterion_update(self, id_: str, evidence_ref: str | None = None,
                         verdict: str | None = None, text: str | None = None) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/criteria/{id_}",
                             json={"evidence_ref": evidence_ref, "verdict": verdict, "text": text})

    # ------------------------------------------------------------------ docs / links / artifacts
    def doc_create(self, doc_type: str, title: str, body_md: str, scope: str) -> dict[str, Any]:
        return self._request("POST", "/v1/docs",
                             json={"doc_type": doc_type, "title": title, "body_md": body_md, "scope": scope})

    def doc_read(self, id_: str, version: int | None = None) -> dict[str, Any]:
        return self._request("GET", f"/v1/docs/{id_}", params={"version": version})

    def doc_query(self, doc_type: str | None = None, scope: str | None = None,
                  owner_role: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/docs", params={"doc_type": doc_type, "scope": scope,
                                                         "owner_role": owner_role})

    def doc_update(self, id_: str, body_md: str | None = None, title: str | None = None) -> dict[str, Any]:
        return self._request("PATCH", f"/v1/docs/{id_}", json={"body_md": body_md, "title": title})

    def link_create(self, from_id: str, to_id: str, relation: str) -> dict[str, Any]:
        return self._request("POST", "/v1/links", json={"from_id": from_id, "to_id": to_id, "relation": relation})

    def link_query(self, from_id: str | None = None, to_id: str | None = None,
                   relation: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/links", params={"from_id": from_id, "to_id": to_id, "relation": relation})

    def link_delete(self, id_: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/links/{id_}")

    def artifact_create(self, form: str, uri: str, note: str = "", ticket_id: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/artifacts",
                             json={"form": form, "uri": uri, "note": note, "ticket_id": ticket_id})

    def artifact_read(self, id_: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/artifacts/{id_}")

    # ------------------------------------------------------------------ messages / gates
    def message_send(self, ticket_id: str, kind: str, text: str, to: str | None = None,
                     reply_to: str | None = None) -> dict[str, Any]:
        return self._request("POST", "/v1/messages",
                             json={"ticket_id": ticket_id, "to": to, "kind": kind, "text": text,
                                   "reply_to": reply_to})

    def message_query(self, ticket_id: str | None = None, to: str | None = None, kind: str | None = None,
                      limit: int = 50) -> dict[str, Any]:
        return self._request("GET", "/v1/messages", params={"ticket_id": ticket_id, "to": to, "kind": kind,
                                                             "limit": limit})

    def gate_open(self, ticket_id: str, gate: str, note: str = "") -> dict[str, Any]:
        return self._request("POST", f"/v1/gates/{ticket_id}/{gate}/open", json={"note": note})

    def gate_answer(self, ticket_id: str, gate: str, answer: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/gates/{ticket_id}/{gate}/answer", json={"answer": answer})

    def gates(self, ticket_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/gates/{ticket_id}")

    # ------------------------------------------------------------------ board / events / find
    def board(self, epic_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/board/{epic_id}")

    def events_query(self, subject_id: str | None = None, since: int = 0, limit: int = 200) -> dict[str, Any]:
        return self._request("GET", "/v1/events", params={"subject_id": subject_id, "since": since, "limit": limit})

    def find(self, q: str, k: int = 10, types: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/find", params={"q": q, "k": k, "types": types})

    # ------------------------------------------------------------------ sessions (pool, admin)
    def session_upsert(self, id_: str, participant_id: str, pool_id: str, state: str,
                       ticket_id: str | None = None, resume_token: str = "", reason: str = "") -> dict[str, Any]:
        return self._request("PUT", f"/v1/sessions/{id_}", admin=True,
                             json={"participant_id": participant_id, "ticket_id": ticket_id, "pool_id": pool_id,
                                   "state": state, "resume_token": resume_token, "reason": reason})

    def session_query(self, participant_id: str | None = None, ticket_id: str | None = None,
                      state: str | None = None) -> dict[str, Any]:
        return self._request("GET", "/v1/sessions", params={"participant_id": participant_id,
                                                             "ticket_id": ticket_id, "state": state})

    def healthz(self) -> dict[str, Any]:
        return self._request("GET", "/healthz")
