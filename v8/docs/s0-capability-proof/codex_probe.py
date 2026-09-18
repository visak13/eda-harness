"""Read-only S0 rate-limit probe. No prompts, credential reads, or raw RPC logging.

Run with --codex-exe pointing at the installed native codex executable. This
starts and terminates ONLY its own stdio child. Output omits account identity.
"""
import argparse
import datetime as dt
import json
import math
import queue
import subprocess
import threading
import time


def safe_snapshot(result):
    """Allowlist only documented numeric windows; never echo arbitrary errors."""
    snapshot = result.get("rateLimits") or {}
    windows = []
    for name in ("primary", "secondary"):
        raw = snapshot.get(name)
        if not isinstance(raw, dict):
            continue
        window = {"slot": name}
        for key in ("usedPercent", "windowDurationMins", "resetsAt"):
            value = raw.get(key)
            window[key] = value if (type(value) in (int, float) and math.isfinite(value)) else None
        windows.append(window)
    by_id = result.get("rateLimitsByLimitId") or {}
    additional = []
    if isinstance(by_id, dict):
        for index, (key, value) in enumerate(by_id.items()):
            if isinstance(value, dict):
                additional.append({
                    "scope": "codex" if key == "codex" else f"other-{index}",
                    "windows": safe_snapshot({"rateLimits": value})["windows"],
                })
    return {"source": "account/rateLimits/read", "windows": windows,
            "by_limit": additional}


def probe(executable, timeout=30):
    process = subprocess.Popen(
        [executable, "app-server", "--stdio"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8",
    )
    incoming = queue.Queue()

    def receive():
        for line in process.stdout:
            try:
                incoming.put(json.loads(line))
            except ValueError:
                pass
        incoming.put(None)

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message):
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()

    def response(identifier):
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            try:
                message = incoming.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError from None
            if message is None:
                raise RuntimeError("child_exited")
            if message.get("id") == identifier:
                return message

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "s0_readonly_probe", "version": "1.0"}}})
        if "error" in response(1):
            return {"status": "error", "reason": "initialize_rejected"}
        send({"method": "initialized", "params": {}})
        send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        reply = response(2)
        if "error" in reply:
            return {"status": "error", "reason": "rate_limits_rejected"}
        result = safe_snapshot(reply.get("result") or {})
        result.update(status="sample_received", received_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                      observed_at=None, account_binding="unverified_not_exported")
        return result
    except (TimeoutError, OSError, RuntimeError):
        return {"status": "error", "reason": "timeout_or_transport_failure"}
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass  # Broken pipe must never skip reaping our owned child.
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        reader.join(timeout=1)
        process.stdout.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-exe", required=True)
    args = parser.parse_args()
    print(json.dumps(probe(args.codex_exe), indent=2, allow_nan=False))
