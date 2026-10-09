"""Cron-heartbeat wakes per seat-hour across the seat transcripts (S8 BEFORE number: the denominator wake_costs lacks).

Turns come from eda-context's wake_costs.parse_session (imported, read-only), so "cron heartbeat" and "no_action"
mean exactly what wake_costs.txt reports: a heartbeat turn whose model made no write-class tool call is idle. A
seat-hour is wall time between a session's first and last record, counting only gaps <= 2 h (a longer gap is a parked
or dead seat, not a live one). Stdlib only.

Usage: python idle_wakes.py [--dir <projects dir>] [--scripts <eda-context/scripts>] [--json out.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime
from pathlib import Path

DEFAULT_DIR = Path.home() / "AppData/Local/heronry/data/claude-pool/projects"
DEFAULT_SCRIPTS = Path(__file__).resolve().parents[6] / "eda-context" / "scripts"
GAP_S = 2 * 3600


def span_hours(path: Path) -> float:
    last, span = None, 0.0
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                v = json.loads(raw).get("timestamp")
                t = datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() if v else None
            except (ValueError, AttributeError):
                continue
            if t is None:
                continue
            if last is not None and 0 < t - last <= GAP_S:
                span += t - last
            last = t
    return span / 3600


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--scripts", type=Path, default=DEFAULT_SCRIPTS)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location("wake_costs", a.scripts / "wake_costs.py")
    wc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wc)
    hours = turns = idle = cost = idle_cost = 0.0
    sessions = skipped = 0
    for p in a.dir.rglob("*.jsonl"):
        if "subagents" in p.parts:
            continue
        try:
            ts = wc.parse_session(p)
            h = span_hours(p)
        except OSError:
            skipped += 1
            continue
        sessions += 1
        hours += h
        for t in ts:
            if t["trigger"] == "cron heartbeat":
                turns += 1
                cost += t["cost"]
                if not t["acted"]:
                    idle += 1
                    idle_cost += t["cost"]
    out = {"sessions": sessions, "seat_hours": round(hours, 1), "heartbeat_turns": int(turns),
           "idle_heartbeat_turns": int(idle), "heartbeat_cost_usd": round(cost, 2),
           "idle_heartbeat_cost_usd": round(idle_cost, 2),
           "heartbeat_turns_per_seat_hour": round(turns / hours, 3) if hours else 0,
           "idle_heartbeat_turns_per_seat_hour": round(idle / hours, 3) if hours else 0,
           "skipped_unreadable_files": skipped}
    text = json.dumps(out, indent=1)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
