"""edp8 feed driver — CLI that tails the board feed (SSE) and, when a broker is
configured, the participant's edp-broker inbox (SSE) — merged into one NDJSON
stream. Meant to run under the Monitor tool: every printed line wakes the shell.

One line per item: `{"event": {...}}` (board) or `{"broker_msg": {...}}`
(broker inbox). Each stream reconnects on loss with backoff 1s -> 30s, resuming
from its own cursor (board seq / broker since_ts). Prints `{"error": "..."}` on
a failure it cannot recover from within a reconnect attempt, then keeps
retrying.

Every line is byte-capped (EDP8_FEED_EVENT_B, default 2000): an over-long line has its longest
strings clipped and carries `omitted` with the call that fetches the full item (S20 token-cost
rework: each line becomes a seat's turn input verbatim).
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import threading
import time
from typing import Any

import httpx

_out_lock = threading.Lock()
_EVENT_BUDGET_B = 2_000     # default byte cap per printed line (env-overridable)
_OMITTED_RESERVE = 300      # room for the `omitted` receipt the cut adds


def _event_budget() -> int:
    try:
        return max(600, int(os.environ.get("EDP8_FEED_EVENT_B", _EVENT_BUDGET_B)))
    except ValueError:
        return _EVENT_BUDGET_B


def _dumps(obj: dict) -> str:
    return json.dumps(obj, default=str)


def _fetch_hint(obj: dict) -> str:
    """The call that returns the full item a capped line was cut from."""
    ev = obj.get("event")
    if isinstance(ev, dict):
        data = ev.get("data") or {}
        if data.get("message"):
            return f"message_read(id={data['message']!r})"
        return f"events_query(subject_id={ev.get('subject_id')!r}, since={max(0, int(ev.get('seq') or 1) - 1)})"
    msg = obj.get("broker_msg")
    if isinstance(msg, dict):
        body = msg.get("body") if isinstance(msg.get("body"), dict) else {}
        if body.get("ticket_id"):
            return f"inbox(), or message_query(ticket_id={body['ticket_id']!r}) for the full text"
    return "inbox()"


def cap_line(obj: dict, budget: int | None = None) -> dict:
    """obj unchanged when its JSON line fits `budget` bytes; else a copy whose longest strings are
    clipped (`…[+N chars]`) until it fits, plus `omitted` naming the cap and the fetch call."""
    budget = budget or _event_budget()
    if len(_dumps(obj).encode()) <= budget:
        return obj
    out = copy.deepcopy(obj)
    target = budget - _OMITTED_RESERVE
    for _ in range(64):
        leaves: list[tuple[Any, Any, str]] = []

        def walk(node: Any) -> None:
            items = node.items() if isinstance(node, dict) else enumerate(node) if isinstance(node, list) else ()
            for k, v in items:
                if isinstance(v, str):
                    leaves.append((node, k, v))
                else:
                    walk(v)

        walk(out)
        excess = len(_dumps(out).encode()) - target
        if excess <= 0 or not leaves:
            break
        node, key, text = max(leaves, key=lambda leaf: len(_dumps({"": leaf[2]})))
        # JSON bytes per char of this string (escapes, multi-byte) so one clip lands under target
        per_char = max(1.0, (len(_dumps({"": text})) - 6) / max(1, len(text)))
        keep = max(0, len(text) - int(excess / per_char) - 24)  # 24 ≈ the marker's own bytes
        if keep >= len(text) or len(text) <= 24:
            break
        node[key] = f"{text[:keep]}…[+{len(text) - keep} chars]"
    out["omitted"] = {"why": f"line capped at EDP8_FEED_EVENT_B={budget} bytes", "fetch": _fetch_hint(obj)[:200]}
    return out


def _print(obj: dict) -> None:
    line = _dumps(cap_line(obj))
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _headers(participant: str) -> dict[str, str]:
    """Identity headers for the board: the seat handle plus its per-seat secret (S20 mints
    EDP8_TOKEN into the spawn env; a tokened board 401s a bare X-Participant)."""
    h = {"X-Participant": participant}
    token = os.environ.get("EDP8_TOKEN")
    if token:
        h["X-Token"] = token
    return h


def _stream_board_once(board: str, participant: str, since: int) -> int:
    """Stream board events; returns the last seen seq (or `since` if none arrived)."""
    last = since
    headers = _headers(participant)
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)) as client:
        with client.stream("GET", f"{board}/v1/feed", params={"since": last}, headers=headers) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                try:
                    ev = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                last = ev.get("seq", last)
                _print({"event": ev})
    return last


def _stream_broker_once(broker: str, participant: str, since_ts: str | None) -> str | None:
    """Stream the participant's broker inbox; returns the last seen msg ts."""
    last = since_ts
    params: dict[str, str] = {"recipient": participant}
    if last:
        params["since_ts"] = last
    with httpx.Client(timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)) as client:
        with client.stream("GET", f"{broker}/v1/events", params=params) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                payload = line[len("data: "):]
                try:
                    msg = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                last = msg.get("ts", last)
                _print({"broker_msg": msg})
    return last


def _broker_loop(broker: str, participant: str) -> None:
    from datetime import UTC, datetime

    # start at "now": the inbox file is append-only and never consumed, so a
    # fresh monitor must not replay the whole historic backlog
    since_ts: str | None = datetime.now(UTC).isoformat()
    backoff = 1.0
    while True:
        try:
            since_ts = _stream_broker_once(broker, participant, since_ts)
            backoff = 1.0
        except Exception as e:
            _print({"error": f"broker: {type(e).__name__}: {e}"})
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def run() -> None:
    p = argparse.ArgumentParser(description="tail an edp8 board's event feed (and broker inbox) as NDJSON")
    p.add_argument("--participant", required=True)
    p.add_argument("--board", default="http://127.0.0.1:9400")
    p.add_argument("--broker", default=None, help="edp-broker base url; when set, the participant's inbox is merged in")
    p.add_argument("--since", type=int, default=-1)
    args = p.parse_args()

    # line 1 is the listening contract (design §16.2 rule 5): what wakes this seat, before any
    # event arrives. Best-effort — an old board without the route just omits it.
    try:
        with httpx.Client(timeout=10.0) as c:
            r = c.get(f"{args.board}/v1/listening", headers=_headers(args.participant))
            if r.status_code == 200 and r.json().get("ok"):
                _print({"listening": r.json()["value"]})
    except Exception as e:  # noqa: BLE001 — the stream is the job; the contract line is a courtesy
        _print({"listening_error": f"{type(e).__name__}: {e}"})

    if args.broker:
        threading.Thread(target=_broker_loop, args=(args.broker, args.participant),
                         name="broker-inbox", daemon=True).start()

    since = args.since
    backoff = 1.0
    while True:
        try:
            since = _stream_board_once(args.board, args.participant, since)
            backoff = 1.0
        except Exception as e:
            _print({"error": f"board: {type(e).__name__}: {e}"})
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


if __name__ == "__main__":
    run()
