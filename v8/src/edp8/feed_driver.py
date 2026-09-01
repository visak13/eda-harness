"""edp8 feed driver — CLI that tails the board feed (SSE) and, when a broker is
configured, the participant's edp-broker inbox (SSE) — merged into one NDJSON
stream. Meant to run under the Monitor tool: every printed line wakes the shell.

One line per item: `{"event": {...}}` (board) or `{"broker_msg": {...}}`
(broker inbox). Each stream reconnects on loss with backoff 1s -> 30s, resuming
from its own cursor (board seq / broker since_ts). Prints `{"error": "..."}` on
a failure it cannot recover from within a reconnect attempt, then keeps
retrying.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time

import httpx

_out_lock = threading.Lock()


def _print(obj: dict) -> None:
    with _out_lock:
        sys.stdout.write(json.dumps(obj, default=str) + "\n")
        sys.stdout.flush()


def _stream_board_once(board: str, participant: str, since: int) -> int:
    """Stream board events; returns the last seen seq (or `since` if none arrived)."""
    last = since
    headers = {"X-Participant": participant}
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
