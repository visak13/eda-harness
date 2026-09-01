"""Pool liveness hooks for spawned shells (fail-open, silent, fast).

Registered in edp-pool/.claude-pool/settings.json:
  PostToolUse + Stop  -> `pool-ping.py`        (busy heartbeat: POST /v1/turn_ping/<sid>)
  SessionEnd          -> `pool-ping.py end`    (honest exit:    POST /v1/session_end/<sid>)

A monitor-mode console has no output the pool can read; these pings are the only
busy/exit signals close_when_idle and dead_reason can trust. Shells not spawned
by the pool (no EDP_SPAWN_SESSION_ID) exit instantly. Never blocks, never fails
the hook chain: any error exits 0 with no output.
"""

import json
import os
import sys
import urllib.request


def main() -> int:
    sid = os.environ.get("EDP_SPAWN_SESSION_ID", "").strip()
    pool = os.environ.get("EDP_POOL_URL", "").strip() or "http://127.0.0.1:9301"
    if not sid:
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "end":
        reason = "session ended"
        try:
            payload = json.load(sys.stdin)
            reason = str(payload.get("reason") or payload.get("hook_event_name") or reason)
        except Exception:
            pass
        url = f"{pool}/v1/session_end/{sid}"
        data = json.dumps({"reason": reason}).encode()
    else:
        url = f"{pool}/v1/turn_ping/{sid}"
        data = b"{}"
    try:
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=1.5).read(0)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
