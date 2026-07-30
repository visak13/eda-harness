"""W14 (DESIGN-v6) — pool doctor: pre-flight stack health + self-repair.

`python -m edp_pool.doctor` runs five checks, in order:

  1. claude binary — health-check the resolved spawn binary and, if it is a
     broken auto-update stub, REPAIR it (REUSES pty_launcher.repair_claude_
     install — the same mechanical restore the pre-spawn guard runs; the
     logic is NOT duplicated here).
  2. broker :9300 — GET /v1/health (per d5 the broker health route is
     /v1/health).
  3. pool :9301 — GET /v1/health (the pool exposes the same uniform route
     edp_contracts.mount gives every microservice).
  4. Phoenix :6006 — reachability. DEGRADES GRACEFULLY: Phoenix is the OTel
     substrate and is currently DOWN (d4); an unreachable Phoenix is a
     WARNING, never a failure.
  5. stale-lock sweep — DIAGNOSTIC report of pool locks whose holder is dead
     (a phantom lock the deliberate reap() would clear). Reporting only —
     doctor does not reap (reaping stays a reasoned, orchestrator-invoked
     act, not an eager loop).

The same checks back the service.py `GET /v1/doctor` endpoint (for the
future W12 panel), which passes the live lock table in directly so it does
not self-HTTP for locks.

Each check returns a flat dict {name, status, detail, elapsed_ms} where
status is one of "ok" | "warn" | "error"; the overall report is healthy
(`ok=True`) when NO check is "error" (a "warn" — e.g. Phoenix down — is
tolerated). Per-check HTTP timeouts are short so a healthy stack finishes
well under the 10s budget (a down local host connection-refuses instantly).
"""

import json
import os
import sys
import time

import httpx

from .pty_launcher import (
    ClaudeInstallError,
    claude_bin_needs_repair,
    repair_claude_install,
    resolve_claude_bin,
)

# Short per-check network timeout. A healthy broker/pool answers in a few
# ms; a down LOCAL host connection-refuses immediately (not a full timeout),
# so five checks stay far under the 10s acceptance budget even if one host
# is down. Overridable for slow/remote deployments.
_DEFAULT_TIMEOUT_S = 3.0

# Default endpoints — every value honors an env override so an operator can
# redirect a port. Broker/pool mirror main.py's defaults; Phoenix mirrors
# the OTel collector endpoint pty_launcher stamps into spawned shells.
_DEFAULT_BROKER_URL = "http://127.0.0.1:9300"
_DEFAULT_POOL_URL = "http://127.0.0.1:9301"
_DEFAULT_PHOENIX_URL = "http://localhost:6006"


def _now() -> float:
    return time.monotonic()


def _elapsed_ms(start: float) -> int:
    return int((_now() - start) * 1000)


def _timeout() -> float:
    try:
        return float(os.environ.get("EDP_DOCTOR_TIMEOUT_S", _DEFAULT_TIMEOUT_S))
    except ValueError:
        return _DEFAULT_TIMEOUT_S


def _http_get(url: str, timeout: float):
    """Single HTTP-probe seam (monkeypatched in tests). Returns
    (reachable, status_code, error): reachable=True means we got an HTTP
    response of ANY status; reachable=False means the host was unreachable
    (connection refused / timeout / DNS)."""
    try:
        r = httpx.get(url, timeout=timeout)
        return True, r.status_code, None
    except Exception as exc:  # noqa: BLE001 — any transport failure = down
        return False, None, str(exc)


def _result(name: str, status: str, detail: str, start: float) -> dict:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "elapsed_ms": _elapsed_ms(start),
    }


# ── individual checks ──────────────────────────────────────────────────────
def check_claude_binary(claude_bin: str | None = None) -> dict:
    """Health-check the resolved spawn binary; repair a broken auto-update
    stub via the SHARED repair_claude_install (no duplicated logic). A
    healthy bin is a no-op ("ok"); a repaired stub is "ok" (detail notes the
    restore); a repair that cannot complete is "error" carrying the
    refuse-and-explain message (the fix the neuron relays, never runs)."""
    start = _now()
    resolved = resolve_claude_bin(claude_bin)
    if not claude_bin_needs_repair(resolved):
        return _result("claude_binary", "ok", f"healthy: {resolved}", start)
    try:
        repair_claude_install(resolved)
    except ClaudeInstallError as exc:
        return _result("claude_binary", "error", str(exc), start)
    return _result(
        "claude_binary", "ok",
        f"repaired stubbed binary from versions cache: {resolved}", start)


def check_http_health(name: str, url: str, timeout: float) -> dict:
    """A REQUIRED service (broker / pool): reachable with HTTP 200 is "ok";
    any other outcome is "error" (unreachable or a non-200 health code)."""
    start = _now()
    health_url = url.rstrip("/") + "/v1/health"
    reachable, code, err = _http_get(health_url, timeout)
    if reachable and code == 200:
        return _result(name, "ok", f"{health_url} -> 200", start)
    if reachable:
        return _result(name, "error", f"{health_url} -> HTTP {code}", start)
    return _result(name, "error", f"{health_url} unreachable: {err}", start)


def check_phoenix(url: str, timeout: float) -> dict:
    """OTel substrate: reachability only, DEGRADES GRACEFULLY. ANY HTTP
    response means Phoenix is up ("ok"); an unreachable Phoenix is a "warn"
    (the stack still runs, only measurement is unavailable) — NEVER an
    "error" that would fail the doctor (d4: Phoenix is currently down)."""
    start = _now()
    reachable, code, err = _http_get(url, timeout)
    if reachable:
        return _result("phoenix", "ok", f"{url} -> HTTP {code}", start)
    return _result(
        "phoenix", "warn",
        f"{url} unreachable ({err}) — OTel measurement degraded; "
        "stack otherwise healthy", start)


def check_stale_locks(locks: list[dict]) -> dict:
    """DIAGNOSTIC sweep: report pool locks whose holder is DEAD (a phantom
    lock a deliberate reap() would clear). "ok" when none are stale, "warn"
    naming the stale handles otherwise. Reporting only — doctor never reaps.
    `locks` is the pool's lock_list() shape [{handle, session_id,
    liveness}]."""
    start = _now()
    stale = [lk.get("handle") for lk in locks if lk.get("liveness") == "dead"]
    if not stale:
        return _result(
            "stale_locks", "ok",
            f"{len(locks)} lock(s), none stale", start)
    return _result(
        "stale_locks", "warn",
        f"{len(stale)} stale lock(s) held by a dead holder "
        f"(run reap): {stale}", start)


def _fetch_locks(pool_url: str, timeout: float) -> tuple[list[dict], str | None]:
    """Standalone (CLI) path: read the pool's lock table over HTTP so the
    stale-lock sweep has data without an in-process PoolService. Returns
    (locks, error): on an unreachable pool, ([], reason)."""
    try:
        r = httpx.get(pool_url.rstrip("/") + "/v1/locks", timeout=timeout)
        r.raise_for_status()
        data = r.json()
        return (data if isinstance(data, list) else []), None
    except Exception as exc:  # noqa: BLE001
        return [], str(exc)


# ── orchestration ──────────────────────────────────────────────────────────
def run_doctor(
    *,
    claude_bin: str | None = None,
    broker_url: str | None = None,
    pool_url: str | None = None,
    phoenix_url: str | None = None,
    locks: list[dict] | None = None,
    timeout: float | None = None,
) -> dict:
    """Run all five checks in order and return the aggregate report:
    {ok, checks:[...], elapsed_ms}. `ok` is True when no check is "error"
    (a "warn" is tolerated). When `locks` is provided (the service endpoint
    passes the live lock_list()), the stale-lock sweep uses it directly;
    otherwise it fetches the pool's /v1/locks over HTTP (the CLI path)."""
    start = _now()
    broker_url = broker_url or os.environ.get(
        "EDP_BROKER_URL", _DEFAULT_BROKER_URL)
    pool_url = pool_url or os.environ.get("EDP_POOL_URL", _DEFAULT_POOL_URL)
    phoenix_url = phoenix_url or os.environ.get(
        "EDP_PHOENIX_URL", _DEFAULT_PHOENIX_URL)
    to = timeout if timeout is not None else _timeout()

    checks = [
        check_claude_binary(claude_bin),
        check_http_health("broker", broker_url, to),
        check_http_health("pool", pool_url, to),
        check_phoenix(phoenix_url, to),
    ]

    if locks is None:
        fetched, err = _fetch_locks(pool_url, to)
        if err is not None:
            checks.append(_result(
                "stale_locks", "warn",
                f"could not read pool locks ({err}) — sweep skipped",
                start))
        else:
            checks.append(check_stale_locks(fetched))
    else:
        checks.append(check_stale_locks(locks))

    ok = all(c["status"] != "error" for c in checks)
    return {"ok": ok, "checks": checks, "elapsed_ms": _elapsed_ms(start)}


def _format_report(report: dict) -> str:
    lines = []
    icon = {"ok": "OK  ", "warn": "WARN", "error": "FAIL"}
    for c in report["checks"]:
        lines.append(
            f"[{icon.get(c['status'], '????')}] {c['name']:<14} "
            f"({c['elapsed_ms']}ms) {c['detail']}")
    verdict = "HEALTHY" if report["ok"] else "UNHEALTHY"
    lines.append(f"\n{verdict} in {report['elapsed_ms']}ms "
                 f"(exit {0 if report['ok'] else 1})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """`python -m edp_pool.doctor`. Prints a human summary + the JSON report
    (the same payload the /v1/doctor endpoint returns). Exit 0 when healthy
    (no "error" check), 1 otherwise. `--json` prints only the JSON."""
    argv = sys.argv[1:] if argv is None else argv
    report = run_doctor()
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        print(_format_report(report))
        print("\n" + json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
