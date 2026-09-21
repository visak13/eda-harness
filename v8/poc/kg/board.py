"""Read-only board REST client for the KG PoC.

Reads only: tickets, criteria, docs, messages, links, artifacts. Uses the
stdlib (urllib) so the PoC adds no dependency. Auth is the X-Participant
header (reads need no token on this board).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BASE = os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400").rstrip("/")
PARTICIPANT = os.environ.get("EDP8_PARTICIPANT", os.environ.get("EDP_HANDLE", "engineer.s-ade90aa0de"))


def _get(path: str, **params) -> object:
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{BASE}{path}" + (f"?{qs}" if qs else "")
    req = urllib.request.Request(url, headers={"X-Participant": PARTICIPANT})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.loads(r.read().decode("utf-8"))
    if isinstance(body, dict) and body.get("ok") is False:
        raise RuntimeError(f"board error on {path}: {body.get('error')}")
    return body.get("value", body) if isinstance(body, dict) else body


def tickets(epic_id: str) -> list[dict]:
    return list(_get("/v1/tickets", epic_id=epic_id))


def criteria(ticket_id: str) -> list[dict]:
    v = _get("/v1/criteria", ticket_id=ticket_id)
    return v.get("criteria", v) if isinstance(v, dict) else list(v)


def docs(scope: str) -> list[dict]:
    v = _get("/v1/docs", scope=scope)
    return v.get("docs", v) if isinstance(v, dict) else list(v)


def doc(doc_id: str) -> dict:
    return _get(f"/v1/docs/{doc_id}")


def messages(epic_id: str, since_seq: int = 0, limit: int = 5000) -> list[dict]:
    v = _get("/v1/messages", epic_id=epic_id, since_seq=since_seq, limit=limit)
    return v.get("messages", v) if isinstance(v, dict) else list(v)


def links(ticket_id: str) -> list[dict]:
    try:
        v = _get("/v1/links", ticket_id=ticket_id)
    except Exception:
        return []
    return v.get("links", v) if isinstance(v, dict) else list(v)


if __name__ == "__main__":
    import sys
    epic = sys.argv[1] if len(sys.argv) > 1 else "epic-44a0576511"
    ts = tickets(epic)
    print(f"tickets: {len(ts)}")
    ms = messages(epic)
    print(f"messages: {len(ms)}")
