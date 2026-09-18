"""Opt-in source collectors, invoked ONLY by an approving operator, never by HTTP.

Claude: dedicated statusline command reads stdin; no model request/login/config edit.
Codex: owned stdio App Server, account binding checked before publishing readings.
Only projected numeric quota fields and receipt time are written, never credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time

from .usage import MAX_BYTES


def number(value):
    # Bound integers before math.isfinite (huge JSON ints overflow its float conversion).
    return value if (type(value) in (int, float) and 0 <= value <= 253402300799
                     and math.isfinite(value)) else None


def project(provider: str, payload: dict, binding_id: str, status: str = "available") -> dict:
    """Reconstruct the receipt, never persist arbitrary statusline/RPC contents."""
    result = {"provider": provider, "binding_id": binding_id, "status": status,
              "received_at": datetime.now(timezone.utc).isoformat(), "observed_at": None}
    if provider == "claude":
        rates = payload.get("rate_limits")
        rates = rates if isinstance(rates, dict) else {}
        result["rate_limits"] = {}
        for name in ("five_hour", "seven_day"):
            raw = rates.get(name)
            raw = raw if isinstance(raw, dict) else {}
            result["rate_limits"][name] = {key: number(raw.get(key)) for key in ("used_percentage", "resets_at")}
    else:
        def windows(raw):
            raw = raw if isinstance(raw, dict) else {}
            return {name: {key: number(raw[name].get(key)) for key in
                          ("usedPercent", "windowDurationMins", "resetsAt")}
                    for name in ("primary", "secondary") if isinstance(raw.get(name), dict)}
        result["rateLimits"] = windows(payload.get("rateLimits"))
        pools = payload.get("rateLimitsByLimitId")
        if isinstance(pools, dict) and "codex" in pools:
            result["rateLimitsByLimitId"] = {"codex": windows(pools["codex"])}
    return result


def publish(path: Path, receipt: dict):
    """Atomic replacement in an operator-created private directory, no link redirection."""
    def linked(p):
        return p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
    if not path.is_absolute() or any(linked(p) for p in (path, *path.parents)) or not path.parent.is_dir():
        raise ValueError("unsafe_output")
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".usage-", suffix=".tmp", delete=False) as stream:
            staged = Path(stream.name)
            json.dump(receipt, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def capture_claude(stream, path: Path, binding_id: str):
    data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("input_too_large")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("input_not_object")
    publish(path, project("claude", payload, binding_id))


class SourceError(Exception):
    """Safe source failure; raw provider errors are deliberately never included."""


class Rpc:
    """Bounded owned subprocess transport; all handles reaped even after timeout/error."""
    def __init__(self, executable: str):
        self.process = subprocess.Popen([executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self.messages = queue.Queue(maxsize=128)
        self.stopped = threading.Event()
        self.failed = threading.Event()
        self.serial = 0
        self.changed = False
        self.pending_rates = []
        self.reader = threading.Thread(target=self._receive, daemon=True)
        self.reader.start()

    def _receive(self):
        try:
            while not self.stopped.is_set():
                line = self.process.stdout.readline(MAX_BYTES + 1)
                if not line or len(line) > MAX_BYTES:
                    break
                message = json.loads(line)
                if not isinstance(message, dict):
                    break
                self.messages.put_nowait(message)
        except (OSError, ValueError, queue.Full):
            pass
        finally:
            self.failed.set()

    def send(self, message):
        try:
            self.process.stdin.write(json.dumps(message) + "\n")
            self.process.stdin.flush()
        except OSError:
            raise SourceError("transport_failure") from None

    def next(self, timeout: float):
        try:
            return self.messages.get(timeout=max(0, timeout))
        except queue.Empty:
            if self.failed.is_set():
                raise SourceError("transport_closed") from None
            return None

    def call(self, method: str):
        self.serial += 1
        identifier = self.serial
        self.send({"id": identifier, "method": method, "params": {}} if method != "initialize" else
                  {"id": identifier, "method": method, "params": {
                      "clientInfo": {"name": "edp8_usage", "version": "1.0"}}})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            message = self.next(min(1, deadline - time.monotonic()))
            if message is None:
                continue
            if message.get("method") == "account/updated":
                self.changed = True
            if message.get("method") == "account/rateLimits/updated":
                if len(self.pending_rates) >= 128:
                    raise SourceError("notification_overflow")
                self.pending_rates.append(message.get("params"))
            if message.get("id") != identifier:
                continue
            if "error" in message or not isinstance(message.get("result"), dict):
                raise SourceError("source_rejected")
            if method == "account/rateLimits/read":
                # This response supersedes earlier notifications in transport order.
                # Notifications during the following identity RPC remain queued.
                self.pending_rates.clear()
            return message["result"]
        raise SourceError("source_timeout")

    def latest_rate_update(self, fallback):
        """Drain deferred notifications in receive order; each replaces the prior snapshot."""
        result = fallback
        for payload in self.pending_rates:
            if not isinstance(payload, dict):
                self.pending_rates.clear()
                raise SourceError("invalid_notification")
            result = payload
        self.pending_rates.clear()
        return result

    def close(self):
        self.stopped.set()
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.reader.join(timeout=2)
        self.process.stdout.close()


def fingerprint(account_result: dict) -> str | None:
    account = account_result.get("account")
    if (not isinstance(account, dict) or account.get("type") != "chatgpt"
            or not isinstance(account.get("email"), str) or not account["email"].strip()):
        return None  # API-key identity is not subscription telemetry
    # Installed 0.153.4 account/read exposes type/email/planType, NOT an account id.
    # Email is used only for this private equality pin; never persist/export it.
    return hashlib.sha256(("codex-chatgpt-email:" + account["email"].strip().casefold()).encode()).hexdigest()


def collect_codex(rpc: Rpc, path: Path, binding_id: str, expected: str, *, once: bool = False):
    """Prefer events, with 60s recovery reads. Account changes fail closed until revalidated."""
    def receipt(payload, status="available"):
        publish(path, project("codex", payload, binding_id, status))

    def authorized():
        rpc.changed = False
        actual = fingerprint(rpc.call("account/read"))
        return actual is not None and actual == expected and not rpc.changed

    failures = 0
    while True:
        try:
            if not authorized():
                receipt({}, "auth_required")
                if once:
                    return
                time.sleep(30)
                continue
            payload = rpc.call("account/rateLimits/read")
            if rpc.changed or not authorized():
                receipt({}, "auth_required")
            else:
                receipt(rpc.latest_rate_update(payload))
            failures = 0
            if once:
                return
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                message = rpc.next(min(1, deadline - time.monotonic()))
                if message is None:
                    continue
                method = message.get("method")
                if method == "account/updated":
                    receipt({}, "auth_required")
                    break
                if method == "account/rateLimits/updated":
                    payload = message.get("params")
                    if isinstance(payload, dict) and authorized():
                        receipt(rpc.latest_rate_update(payload))
                    else:
                        receipt({}, "auth_required")
        except SourceError:
            receipt({}, "error")
            failures = min(failures + 1, 4)
            if once or rpc.failed.is_set():
                return
            time.sleep(min(30 * 2 ** (failures - 1), 300))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=("claude", "codex"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--binding-id")
    parser.add_argument("--codex-exe")
    parser.add_argument("--account-fingerprint")
    parser.add_argument("--print-account-fingerprint", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.print_account_fingerprint and args.provider != "codex":
        parser.error("fingerprint is Codex only")
    if not args.print_account_fingerprint and (not args.output or not args.binding_id
            or not re.fullmatch(r"[a-zA-Z0-9_-]{8,80}", args.binding_id)):
        parser.error("absolute --output and opaque --binding-id (8-80 safe characters) required")
    if args.provider == "codex" and (not args.codex_exe or (not args.print_account_fingerprint
            and not re.fullmatch(r"[0-9a-f]{64}", args.account_fingerprint or ""))):
        parser.error("--codex-exe and --account-fingerprint required")
    rpc = None
    try:
        if args.provider == "claude":
            capture_claude(sys.stdin.buffer, args.output, args.binding_id)
            print("Usage receipt captured (observation time unknown)")
        else:
            rpc = Rpc(args.codex_exe)
            rpc.call("initialize")
            rpc.send({"method": "initialized", "params": {}})
            if args.print_account_fingerprint:
                value = fingerprint(rpc.call("account/read"))
                if value is None:
                    raise SourceError("subscription_account_required")
                print(value)  # opaque local setup value, never a raw account ID or credential
            else:
                collect_codex(rpc, args.output, args.binding_id, args.account_fingerprint, once=args.once)
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, TypeError, OverflowError, SourceError, RecursionError):
        if args.output and args.binding_id:
            try:
                publish(args.output, project(args.provider, {}, args.binding_id, "error"))
            except (OSError, ValueError):
                pass
        print("Usage source unavailable", file=sys.stderr)
        return 1
    finally:
        if rpc is not None:
            rpc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
