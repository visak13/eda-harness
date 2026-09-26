"""Settings declared for broker (see keys_common for shared ones)."""
from __future__ import annotations

from ._core import data_dir, declare

declare("broker.data_dir", "EDP_BROKER_DATA", "path", lambda: data_dir() / "broker-data", "Paths",
        "The broker's message store dir.", default_doc="<data>/broker-data", restart_required="broker")
declare("broker.access_log", "EDP_BROKER_ACCESS_LOG", "bool", False, "Limits/tuning",
        "uvicorn access log for the broker (floods: rx inbox polls every ~2 s).", restart_required="broker")
declare("broker.shutdown_grace_secs", "EDP_BROKER_SHUTDOWN_GRACE_SECS", "int", 5, "Limits/tuning",
        "Seconds uvicorn waits for open SSE streams at shutdown before cancelling them.",
        restart_required="broker")
