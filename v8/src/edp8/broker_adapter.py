"""edp8 broker adapter — mirror addressed board traffic into edp-broker inboxes.

The board is the system of record; the broker (:9300) is the DELIVERY plane it
always was: the pool's resume watchdog wakes a parked shell when its broker
inbox grows, and every shell's feed monitor also tails its broker inbox. So a
board message/gate addressed to a participant is republished, best-effort, as a
broker message to that participant's handle. Broker down never fails a board
write — delivery degrades to the feed + the cron heartbeat fallback.

Kinds are mapped onto the broker's CORE kind registry (edp-contracts): an
unregistered kind is rejected by the broker process, so only registered ones
are used here.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

log = logging.getLogger("edp8.broker")

# board MessageKind -> broker CORE kind (edp_contracts.broker.CORE_KINDS).
# "alert" and "crashed" are also passed through raw (shell-death notices).
KIND_MAP = {
    "question": "question",
    "answer": "answer",
    "steer": "steer",
    "status": "progress",
    "finding": "observation",
    "deviation": "alert",
    "note": "fyi",
    "crashed": "crashed",
}


def broker_url() -> str | None:
    return os.environ.get("EDP_BROKER_URL") or None


def publish(from_: str, to: str, kind: str, body: dict[str, Any]) -> bool:
    """Best-effort publish; never raises. Returns False when undelivered.
    `kind` may be a board MessageKind (mapped) or already a broker CORE kind."""
    url = broker_url()
    if not url or not to:
        return False
    broker_kind = kind if kind in KIND_MAP.values() else KIND_MAP.get(kind, "fyi")
    msg = {
        "msg_id": str(uuid.uuid4()),
        "ts": datetime.now(UTC).isoformat(),
        "from": from_,
        "to": to,
        "kind": broker_kind,
        "body": body,
    }
    try:
        r = httpx.post(f"{url}/v1/publish", json=msg, timeout=5.0)
        if r.status_code >= 400:
            log.warning("broker publish %s -> %s refused: %s", kind, to, r.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        log.warning("broker unreachable (%s); %s -> %s rides the feed only", e, kind, to)
        return False
