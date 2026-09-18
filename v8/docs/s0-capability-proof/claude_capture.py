"""Owner-approved one-session statusline capture; never a provider request.

Activated only by dedicated --settings file, not global/project configuration.
Reads at most 1 MiB from stdin, retains only four rate fields and receipt time.
"""
import datetime as dt
import json
import math
import os
from pathlib import Path
import sys
import tempfile

MAX_INPUT = 1024 * 1024
OUTPUT_DIR = Path.home() / "AppData/Local/Temp/edp8-s0-claude"


def project(payload):
    rate = payload.get("rate_limits")
    rate = rate if isinstance(rate, dict) else {}
    result = {}
    for name in ("five_hour", "seven_day"):
        raw = rate.get(name)
        raw = raw if isinstance(raw, dict) else {}
        used, reset = raw.get("used_percentage"), raw.get("resets_at")
        result[name] = {
            "used_percentage": used if (type(used) in (int, float)
                and math.isfinite(used) and 0 <= used <= 100) else None,
            "resets_at": reset if type(reset) is int and reset > 0 else None,
        }
    return {"rate_limits": result,
            "received_at": dt.datetime.now(dt.timezone.utc).isoformat()}


def is_link(path):
    return path.is_symlink() or path.is_junction()


def capture(stream, directory):
    data = stream.read(MAX_INPUT + 1)
    if len(data) > MAX_INPUT:
        raise ValueError("input_too_large")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("input_not_object")
    snapshot = project(payload)
    # Setup creates this dedicated directory exclusively. Never create/redirect it here.
    target = directory / "sample.json"
    if not directory.is_dir() or is_link(directory) or is_link(target):
        raise ValueError("unsafe_output")
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".sample-", suffix=".tmp", delete=False) as file:
            staged = Path(file.name)
            json.dump(snapshot, file, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(staged, target)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
    return snapshot


if __name__ == "__main__":
    try:
        snapshot = capture(sys.stdin.buffer, OUTPUT_DIR)
        complete = all(all(value is not None for value in bucket.values())
                       for bucket in snapshot["rate_limits"].values())
        print("S0 usage capture: " + ("both windows received" if complete else "windows incomplete"))
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        # Never print raw stdin, exception text, paths or account/session identifiers.
        print("S0 usage capture unavailable")
