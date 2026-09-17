"""parity_live_pi — run the parity oracle CASES through ONE live Pi/Astra seat (`pi --mode rpc`), mirroring
RPC events to <log-dir>/pi-seat.cases.jsonl and provider payloads to <log-dir>/tasks/provider-payloads.jsonl.

    python scripts/parity_live_pi.py [--log-dir DIR] [--model openai-codex/gpt-6-astra] [case ...]

`parity_oracle.py --both` calls this, then `capture_pi` + `diff` against the checked-in Claude reference.
The seat needs the Pi login (`~/.pi/agent/auth.json`) or OPENAI_API_KEY; without either it exits 2.
Pinned against Pi 0.85.1 (edp-pool/.pi-harness). epic-6a8a6020fd · s-e1260012b9.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
V8 = HERE.parent
sys.path.insert(0, str(V8 / "src"))
from edp8.pi_seat.driver import PiSeat, find_pi  # noqa: E402

SPEC = importlib.util.spec_from_file_location("parity_oracle", HERE / "parity_oracle.py")
po = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(po)  # type: ignore[union-attr]

PRE = ("You are running a parity probe. Use ONLY the named tools, exactly as instructed, with the exact "
       "command strings given; never paraphrase a command; do not explain. When told to end the turn, reply with the single word ok. ")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(V8 / ".pi" / "parity"))
    ap.add_argument("--model", default=os.environ.get("EDP_PI_MODEL", "openai-codex/gpt-6-astra"))
    ap.add_argument("--thinking", default="low")
    ap.add_argument("cases", nargs="*", help="case names (default: every CASE except the accelerated-clock one)")
    a = ap.parse_args(argv)
    log = Path(a.log_dir).resolve()  # the extension writes <output-file> paths from EDP_PI_TASKS_DIR verbatim
    (log / "tasks").mkdir(parents=True, exist_ok=True)
    try:
        pi_argv = find_pi()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    env = {
        "EDP_ROLE": os.environ.get("EDP_ROLE", "architect"), "EDP_HANDLE": os.environ.get("EDP_HANDLE", "parity.probe"),
        "EDP_PI_TASKS_DIR": str(log / "tasks"), "EDP8_LANE_DIR": str(log / "lane"), "EDP8_LANE_REPORT": "0",
        "EDP_PARITY_CAPTURE": "1", "EDP_MONITOR_SHELL": os.environ.get("EDP_MONITOR_SHELL", "bash"),
        "EDP_PARITY_SEED": os.environ.get("EDP_PARITY_SEED", "oracle"),
    }
    seat = PiSeat(cwd=str(V8), model=a.model, extension=str(V8 / ".pi" / "extensions" / "edp8.ts"),
                  session_file=str(log / f"session-{int(time.time())}.jsonl"), env=env, log_dir=str(log), handle="cases",
                  thinking=a.thinking, pi_bin=pi_argv[-1] if pi_argv[0] == "node" else pi_argv[0])
    seat.start()
    only = set(a.cases)
    ran = 0
    try:
        for name, prompt in po.CASES:
            if only and name not in only:
                continue
            if name == "cron_expiry_accelerated" and not only:
                print(name, "SKIPPED live (controlled clock; covered by tests/pi_ext/fake_pi_harness.ts '7-day expiry')", flush=True)
                continue
            # drain stale events (an idle-delivery turn's agent_settled must not end THIS case early)
            while True:
                got = sum(1 for _ in seat.events(timeout=1.5, until="__never__"))
                if got == 0:
                    break
            for _ in range(120):  # and wait until Pi is really idle
                st = seat.get_state()
                if not (st.get("data") or st).get("isStreaming"):
                    break
                time.sleep(1)
            t0 = time.time()
            seat.prompt(PRE + prompt)
            last, seen_turn_end = "", False
            for ev in seat.events(timeout=400, until="__never__"):
                t = ev.get("type")
                if t == "turn_end":
                    seen_turn_end = True
                if t == "agent_settled" and seen_turn_end:
                    break
                if t == "process_exit":
                    print("pi exited", file=sys.stderr)
                    return 2
                if t == "message_end" and (ev.get("message") or {}).get("role") == "assistant":
                    c = ev["message"].get("content")
                    last = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
                if t == "tool_execution_start":
                    print(f"  {round(time.time() - t0, 1)}s tool {ev.get('toolName')} {json.dumps(ev.get('args'))[:120]}", flush=True)
            print(f"{name}: {round(time.time() - t0, 1)}s last={last[:80]!r}", flush=True)
            if "No API key" in last or "not logged in" in last.lower():
                print("no credentials for the Pi seat", file=sys.stderr)
                return 2
            ran += 1
            time.sleep(3)  # let idle-time deliveries land as follow-up turns
            for ev in seat.events(timeout=90 if name.startswith(("cron_oneshot", "monitor_idle")) else 8):
                if ev.get("type") == "message_end" and (ev.get("message") or {}).get("role") == "user":
                    c = ev["message"].get("content")
                    txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    print(f"  idle-delivery: {txt[:100]!r}", flush=True)
    finally:
        print("done; stopping", flush=True)
        seat.stop()
    return 0 if ran else 2


if __name__ == "__main__":
    raise SystemExit(main())
