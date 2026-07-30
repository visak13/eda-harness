"""uvicorn entrypoint.

Run via the console script (`uv run edp-broker`) or
`python -m edp_broker.main`. Both reach `run()` — the missing
`__main__` guard was why `python -m edp_broker.main` "did nothing"
(it imported the module and exited without starting uvicorn).
"""

import os
from pathlib import Path

from edp_contracts import get_logger

from .service import create_app

_log = get_logger("edp-broker")

app = create_app(Path(os.environ.get("EDP_BROKER_DATA", ".broker-data")))


def run() -> None:
    import uvicorn

    host = os.environ.get("EDP_BROKER_HOST", "127.0.0.1")
    # eda-base3 stack default — 9300 (the old eda-base stack uses 9100;
    # both run side by side). Override with EDP_BROKER_PORT.
    port = int(os.environ.get("EDP_BROKER_PORT", "9300"))
    data = os.environ.get("EDP_BROKER_DATA", ".broker-data")
    # rx subscriptions + heartbeats poll GET /v1/inbox (and /v1/events
    # reconnects) every ~2s PER subscriber, so uvicorn's access log floods
    # the console with one line per request. Disable it by default (same
    # fix the pool already ships); the meaningful events (publish /
    # delivery / no-route) still log via `_log`. Re-enable for debugging
    # with EDP_BROKER_ACCESS_LOG=1.
    access_log = os.environ.get("EDP_BROKER_ACCESS_LOG", "0").lower() in (
        "1", "true", "yes", "on")
    # Structured startup line (stderr) so the operator sees the service
    # come up even before the first request.
    _log.info(
        "startup",
        f"edp-broker listening on http://{host}:{port}",
        host=host,
        port=port,
        data_dir=data,
        access_log=access_log,
    )
    # timeout_graceful_shutdown is LOAD-BEARING (operator finding
    # 2026-07-19: "the broker doesnt shutdown if a live connection is
    # open. it just freezes"): /v1/events holds UNBOUNDED SSE streams
    # (the rx push plane), and uvicorn's default graceful shutdown waits
    # for open connections FOREVER — Ctrl-C appeared to hang. After this
    # many seconds the remaining streams are force-cancelled; every SSE
    # consumer (rx drivers, neuron_heartbeat) already reconnects with
    # backoff + since_ts, so a cancelled stream costs nothing.
    uvicorn.run(app, host=host, port=port, log_level="info",
                access_log=access_log,
                timeout_graceful_shutdown=int(
                    os.environ.get("EDP_BROKER_SHUTDOWN_GRACE_SECS", "5")))


if __name__ == "__main__":
    run()
