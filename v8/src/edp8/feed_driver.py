"""edp8 feed driver — CLI that tails GET /v1/feed (SSE) and prints NDJSON.

One line per event: `{"event": {...}}`. Reconnects on connection loss with
backoff 1s -> 30s, resuming from the last seen seq. Prints `{"error": "..."}"
on a failure it cannot recover from within a reconnect attempt, then keeps
retrying. Meant to run under the Monitor tool.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def _print(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, default=str) + "\n")
    sys.stdout.flush()


def _stream_once(board: str, participant: str, since: int) -> int:
    """Stream events; returns the last seen seq (or `since` if none arrived)."""
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


def run() -> None:
    p = argparse.ArgumentParser(description="tail an edp8 board's event feed as NDJSON")
    p.add_argument("--participant", required=True)
    p.add_argument("--board", default="http://127.0.0.1:9400")
    p.add_argument("--since", type=int, default=-1)
    args = p.parse_args()

    since = args.since
    backoff = 1.0
    while True:
        try:
            since = _stream_once(args.board, args.participant, since)
            backoff = 1.0
        except Exception as e:
            _print({"error": f"{type(e).__name__}: {e}"})
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


if __name__ == "__main__":
    run()
