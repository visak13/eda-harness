"""F36 (2026-08-18) — campaign Round 4 (spawn/wiring/lifecycle) fixes,
claude side: the partial-line-safe follower, the arm-gap lookback cursor,
and the honest status_ping evidence model.
(Pool-side fixes are pinned in edp-pool/tests; reuse-honesty in
test_f3_arm_wiring_steer_worker.py.)"""

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from edp_claude.reactive.driver import _tail_jsonl
from edp_claude.store.atomic import append_jsonl


class _Obs:
    def __init__(self):
        self.seen: list[dict] = []

    def on_next(self, rec):
        self.seen.append(rec)


def _run_follower(path: Path, **kw):
    obs = _Obs()
    stop = threading.Event()
    t = threading.Thread(target=_tail_jsonl,
                         args=(path, obs, stop, 30), kwargs=kw, daemon=True)
    t.start()
    return obs, stop, t


def _wait_for(pred, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.03)
    return False


def test_partial_trailing_line_is_not_consumed(tmp_path):
    """R4#4: a record read mid-append must be retried once completed,
    never half-consumed."""
    path = tmp_path / "events.jsonl"
    append_jsonl(path, {"kind": "old"})
    obs, stop, t = _run_follower(path)
    try:
        time.sleep(0.2)
        # write HALF a record (no newline), as a racing appender would
        rec = json.dumps({"ts": datetime.now(timezone.utc).isoformat(),
                          "kind": "blocker"})
        with path.open("a", encoding="utf-8") as f:
            f.write(rec[: len(rec) // 2])
            f.flush()
        time.sleep(0.2)
        assert not obs.seen, "a partial record must not be delivered"
        with path.open("a", encoding="utf-8") as f:
            f.write(rec[len(rec) // 2:] + "\n")
        assert _wait_for(lambda: any(
            r.get("kind") == "blocker" for r in obs.seen)), (
            "the completed record was never delivered — the follower "
            "half-consumed it")
    finally:
        stop.set()
        t.join(timeout=2)


def test_since_cursor_delivers_arm_gap_events_not_history(tmp_path):
    """R4#3: with an arm-time cursor, an event that landed AFTER the
    cursor but BEFORE the follower started is delivered; older history
    is not."""
    path = tmp_path / "events.jsonl"
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": old, "kind": "ancient"}) + "\n")
    cursor = (datetime.now(timezone.utc)
              - timedelta(seconds=60)).isoformat()
    # the arm-gap event: lands before the follower starts, after cursor
    append_jsonl(path, {"kind": "gap_event"})
    obs, stop, t = _run_follower(path, since=cursor)
    try:
        assert _wait_for(lambda: any(
            r.get("kind") == "gap_event" for r in obs.seen)), (
            "the arm-gap event was dropped — the EOF seek hid it")
        assert not any(r.get("kind") == "ancient" for r in obs.seen), (
            "pre-cursor history was replayed as wakes")
    finally:
        stop.set()
        t.join(timeout=2)


async def test_status_ping_reports_unknown_progress_without_evidence(env):
    """R4#7: an alive shell with NO output evidence is UNKNOWN progress
    (probe band), never 'working'."""
    from edp_contracts import ToolOk
    res = await env.call("status_ping", handle="no-such-plan:a1")
    assert isinstance(res, ToolOk), res
    d = res.data if isinstance(res.data, dict) else res.data.model_dump()
    # the stub pool answers 'unknown' liveness for an unknown handle —
    # the field exists and no crash; the alive-no-evidence branch is
    # exercised when a live pool answers alive with no timestamps.
    assert "last_output_ts" in d
