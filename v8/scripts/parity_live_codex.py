"""parity_live_codex — run the parity oracle CASES through ONE live codex app-server seat (edp8.codex_seat),
board-less, mirroring every JSON-RPC message to <log-dir>/codex-seat.cases.jsonl.

    python scripts/parity_live_codex.py [--log-dir DIR] [--model gpt-6-astra] [--effort low] [case ...]

`parity_oracle.py --both-codex` calls this, then `capture_codex` + `diff` against the checked-in Claude
reference. Needs a codex ChatGPT login (`codex login`); exit 2 when the seat cannot start or run a turn.
Pinned against codex-cli 0.156.0. epic-6a8a6020fd · s-10a2b1f9ec.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
V8 = HERE.parent
sys.path.insert(0, str(V8 / "src"))
from edp8.codex_seat.seat import CodexSeat  # noqa: E402

SPEC = importlib.util.spec_from_file_location("parity_oracle", HERE / "parity_oracle.py")
po = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(po)  # type: ignore[union-attr]

PRE = ("You are running a parity probe. Use ONLY the named tools, exactly as instructed, with the exact "
       "command strings given; never paraphrase a command; do not explain. When told to end the turn, reply with the single word ok. ")


class Watch:
    """Turn-completion + last agent text from the seat's notifications."""

    def __init__(self, t0: float):
        self.t0 = t0
        self.completed = threading.Event()
        self.last = ""
        self.error: dict | None = None
        self.user_inputs: list[str] = []

    def on_event(self, method: str, p: dict) -> None:
        item = p.get("item") or {}
        if method == "item/completed" and item.get("type") == "agentMessage":
            self.last = item.get("text", "")
        elif method == "item/started" and item.get("type") in ("dynamicToolCall", "commandExecution"):
            what = item.get("command") or f"{item.get('tool')} {json.dumps(item.get('arguments'))}"
            print(f"  {round(time.time() - self.t0, 1)}s {item['type']} {str(what)[:120]}", flush=True)
        elif method == "item/completed" and item.get("type") == "userMessage":
            text = " ".join(c.get("text", "") for c in item.get("content") or [])
            self.user_inputs.append(text)
        elif method == "turn/completed":
            self.error = (p.get("turn") or {}).get("error")
            self.completed.set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log-dir", default=str(V8 / ".logs" / "codex-parity"))
    ap.add_argument("--model", default=os.environ.get("EDP_CODEX_MODEL", "gpt-6-astra"))
    ap.add_argument("--effort", default="low")
    ap.add_argument("cases", nargs="*", help="case names (default: every CASE except the accelerated-clock one)")
    a = ap.parse_args(argv)
    log = Path(a.log_dir).resolve()
    (log / "tasks").mkdir(parents=True, exist_ok=True)
    env = {
        "EDP_ROLE": "reviewer", "EDP_HANDLE": "cases", "EDP_CODEX_TASKS_DIR": str(log / "tasks"),
        "EDP_MONITOR_SHELL": os.environ.get("EDP_MONITOR_SHELL", "bash"),
        "EDP_PARITY_SEED": os.environ.get("EDP_PARITY_SEED", "oracle"),
        # the probe's blocking bash must run; read-only still executes commands
        "EDP_CODEX_SANDBOX": os.environ.get("EDP_CODEX_SANDBOX", "read-only"),
    }
    watch = Watch(time.time())
    seat = CodexSeat(cwd=V8, role="reviewer", handle="cases", log_dir=log, env=env, model=a.model, effort=a.effort,
                     board=False, ephemeral=True, on_event=lambda m, p: watch.on_event(m, p))
    try:
        seat.start()
    except Exception as e:  # noqa: BLE001
        print(f"codex seat cannot start: {e}", file=sys.stderr)
        return 2
    print(f"thread {seat.thread_id} disabled_mcp={','.join(seat.disabled_servers)} live={seat.live_mcp_servers()}", flush=True)
    only = set(a.cases)
    ran = 0
    try:
        for name, prompt in po.CASES:
            if only and name not in only:
                continue
            if name == "cron_expiry_accelerated" and not only:
                print(name, "SKIPPED live (controlled clock; covered by tests/test_codex_seat.py cron expiry)", flush=True)
                continue
            _wait_idle(seat, 400)
            watch.t0 = time.time()
            watch.completed.clear()
            seat.enqueue_turn(PRE + prompt)
            if not watch.completed.wait(400):
                print(f"{name}: no turn/completed in 400s", file=sys.stderr)
                return 2
            _wait_idle(seat, 400)  # an in-turn deferral (a cron due while busy) runs as its own follow-up turn
            print(f"{name}: {round(time.time() - watch.t0, 1)}s last={watch.last[:80]!r}", flush=True)
            if watch.error and watch.error.get("codexErrorInfo") in ("usageLimitExceeded", "rateLimitExceeded", "unauthorized"):
                print(f"codex capped/unauthorised: {json.dumps(watch.error)[:300]}", file=sys.stderr)
                return 2
            ran += 1
            n0 = len(watch.user_inputs)
            linger = 90 if name.startswith(("cron_oneshot", "monitor_idle")) else 8
            end = time.time() + linger
            while time.time() < end:  # let idle-time deliveries land as follow-up turns
                time.sleep(0.5)
            _wait_idle(seat, 400)
            for txt in watch.user_inputs[n0:]:
                print(f"  idle-delivery: {txt[:100]!r}", flush=True)
    finally:
        print("done; stopping", flush=True)
        seat.stop()
    return 0 if ran else 2


def _wait_idle(seat: CodexSeat, timeout: float) -> None:
    end = time.time() + timeout
    while time.time() < end:
        d = seat.delivery
        if d.is_idle() and not d.pending and not getattr(d, "_outbox", None):
            time.sleep(0.3)
            if d.is_idle() and not d.pending:
                return
        time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
