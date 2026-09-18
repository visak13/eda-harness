"""Pure S0 fixture contract; not a production account-authorized adapter.

Input is an allowlisted Codex snapshot from codex_probe.safe_snapshot.
Each source update REPLACES the previous snapshot; do not merge missing windows.
"""
import math


def core_windows(snapshot):
    """Classify core buckets by duration without any persistent presence flag."""
    candidates = snapshot.get("windows", [])
    for pool in snapshot.get("by_limit", []):
        if pool.get("scope") == "codex":
            candidates = pool.get("windows", [])
            break
    result = []
    for duration in (300, 10080):
        matches = [w for w in candidates if w.get("windowDurationMins") == duration]
        raw = matches[0] if len(matches) == 1 else {}
        used, reset = raw.get("usedPercent"), raw.get("resetsAt")
        valid = (type(used) in (int, float) and math.isfinite(used) and 0 <= used <= 100
                 and type(reset) is int and reset > 0)
        result.append({"window_minutes": duration,
                       "used_percent": used if valid else None,
                       "resets_at": reset if valid else None,
                       "observed_at": None,
                       "status": "sample_received" if valid else "unavailable"})
    return result
