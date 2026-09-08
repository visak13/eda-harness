"""Launcher run-state: one pid file per shared service under `v8/.run/`.

Design §22 rule 4: "Each service writes a pid file with its port and git rev under
`v8/.run/`; `preflight()` reports the services block so any seat sees infrastructure state
without touching it." The launcher (`start.*`) and its supervisor own these files; seats
only READ them (never stop/restart a shared service — §22 rule 1).

A pid file is JSON: {service, pid, port, git_rev, started_at, last_probe, last_ok,
last_restart_reason, restarts}. Times are ISO-8601 local. Missing/garbage file = the
service was never started by the launcher (or the file was cleaned) → reported "down".
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

# The five shared services the launcher owns (design §22 rule 1). `port` is the listener the
# supervisor probes; the bridge has no port (matched by command line) so its port is None.
SERVICES: dict[str, dict[str, Any]] = {
    "board": {"port": 9400, "health": "/v1/health"},
    "broker": {"port": 9300, "health": "/v1/health"},
    "pool": {"port": 9301, "health": "/v1/limits"},
    "mcp": {"port": 9402, "health": "/healthz"},
    "bridge": {"port": None, "health": None},
}


def git_rev() -> str:
    """Short git rev of the running tree, read straight from `.git` files (no shelling out —
    tool modules never execute code; test_no_code_execution). EDP8_GIT_REV overrides (the
    launcher injects it). Used by /v1/health, the pid files and the service_restarted event (§22)."""
    env = os.environ.get("EDP8_GIT_REV")
    if env:
        return env.strip()[:12] or "unknown"
    start = Path(os.environ.get("EDP8_HOME", ".")).resolve()
    gitdir = None
    for base in (start, *start.parents):  # the repo root is v8's parent (eda-base3)
        if (base / ".git").exists():
            gitdir = base / ".git"
            break
    if gitdir is None:
        return "unknown"
    try:
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if not head.startswith("ref:"):
        return head[:7] or "unknown"  # detached HEAD holds the sha directly
    ref = head.split(" ", 1)[1].strip()
    try:
        return (gitdir / ref).read_text(encoding="utf-8").strip()[:7] or "unknown"
    except OSError:
        pass
    try:  # packed-refs fallback
        for line in (gitdir / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref) or line.endswith("\t" + ref):
                return line.split(" ", 1)[0][:7]
    except OSError:
        return "unknown"
    return "unknown"


def run_dir() -> Path:
    d = Path(os.environ.get("EDP8_RUN_DIR", str(Path(os.environ.get("EDP8_HOME", ".")) / ".run")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(service: str) -> Path:
    return run_dir() / f"{service}.json"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write(service: str, *, pid: int, port: int | None, git_rev: str) -> dict[str, Any]:
    """Called by the launcher when it starts a service. Overwrites any stale file."""
    rec = {"service": service, "pid": int(pid), "port": port, "git_rev": git_rev,
           "started_at": now_iso(), "last_probe": None, "last_ok": None,
           "last_restart_reason": None, "restarts": 0}
    _path(service).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def read(service: str) -> dict[str, Any] | None:
    try:
        return json.loads(_path(service).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def update(service: str, **fields: Any) -> dict[str, Any] | None:
    rec = read(service)
    if rec is None:
        return None
    rec.update(fields)
    _path(service).write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return rec


def mark_probe(service: str, ok: bool) -> None:
    """Supervisor records each probe outcome so `edp8 status` and preflight show freshness."""
    ts = now_iso()
    fields: dict[str, Any] = {"last_probe": ts}
    if ok:
        fields["last_ok"] = ts
    update(service, **fields)


def mark_restart(service: str, reason: str, *, pid: int | None = None, git_rev: str | None = None) -> None:
    rec = read(service) or {"service": service, "port": SERVICES.get(service, {}).get("port")}
    rec["last_restart_reason"] = reason
    rec["restarts"] = int(rec.get("restarts", 0)) + 1
    rec["started_at"] = now_iso()
    if pid is not None:
        rec["pid"] = int(pid)
    if git_rev is not None:
        rec["git_rev"] = git_rev
    _path(service).write_text(json.dumps(rec, indent=2), encoding="utf-8")


def clear(service: str) -> None:
    try:
        _path(service).unlink()
    except OSError:
        pass


def _uptime(rec: dict[str, Any]) -> str:
    try:
        started = datetime.fromisoformat(rec["started_at"])
        secs = int((datetime.now().astimezone() - started).total_seconds())
    except Exception:  # noqa: BLE001
        return "?"
    if secs < 90:
        return f"{secs}s"
    if secs < 5400:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60}m"


def snapshot() -> list[dict[str, Any]]:
    """One row per known service (in start order) for `edp8 status` and preflight's services
    block. `up` is best-effort from the pid file's freshness — a fresh pid file whose process is
    gone still reads its recorded fields; live liveness is the supervisor's probe, recorded here."""
    rows: list[dict[str, Any]] = []
    for name, spec in SERVICES.items():
        rec = read(name)
        if rec is None:
            # No pid file (never launcher-started, or the file was cleaned): a listening port still
            # means the service is up — the live fleet's board/pool/broker/mcp answer without a file
            # (S17 c-c0f2ceea9b). A port-less service (the bridge) with no file is genuinely down.
            listening = _port_listening(spec["port"])
            rows.append({"service": name, "state": "up" if listening else "down",
                         "port": spec["port"], "pid": None,
                         "note": "listener up (not launcher-started)" if listening else None})
            continue
        port = rec.get("port", spec["port"])
        up = _process_alive(rec.get("pid")) or _port_listening(port)  # a live listener means up even
        rows.append({                                                  # if pid bookkeeping is off (Git Bash winpid)
            "service": name,
            "state": "up" if up else "down",
            "pid": rec.get("pid"),
            "port": rec.get("port", spec["port"]),
            "git_rev": rec.get("git_rev"),
            "uptime": _uptime(rec),
            "last_probe": rec.get("last_probe"),
            "last_ok": rec.get("last_ok"),
            "last_restart_reason": rec.get("last_restart_reason"),
            "restarts": rec.get("restarts", 0),
        })
    return rows


def _port_listening(port: int | None) -> bool:
    if not port:
        return False
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        try:
            return s.connect_ex(("127.0.0.1", int(port))) == 0
        except OSError:
            return False


def listener_pid(port: int | None) -> int | None:
    """The pid that owns the LISTEN socket on 127.0.0.1:port, or None. This is the reliable pid on
    Git Bash / MSYS, where a shell's `$!` is the bash shim rather than the Windows child process
    (S17 c-c0f2ceea9b): the launcher records THIS so `edp8 status` and pid-kills hit the real
    process, not a defunct MSYS shim pid."""
    if not port:
        return None
    try:
        import psutil
        for c in psutil.net_connections(kind="inet"):
            if (getattr(c, "status", None) == psutil.CONN_LISTEN and c.laddr
                    and getattr(c.laddr, "port", None) == int(port) and c.pid):
                return int(c.pid)
    except Exception:  # noqa: BLE001 — psutil absent or unprivileged; caller falls back to its own pid
        return None
    return None


def process_pid_matching(needle: str) -> int | None:
    """The NEWEST running process whose command line contains `needle` — used for the port-less
    Slack bridge (S17 c-c0f2ceea9b). Newest wins so the launcher records the child it just spawned,
    never an older unrelated one. Fleet SCOPING is the caller's job (it reads its own run dir and
    verifies the recorded pid); this is only ever called to learn the pid of a just-started child."""
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return None
    best: tuple[float, int] | None = None
    me = os.getpid()
    try:
        for p in psutil.process_iter(["pid", "cmdline", "create_time"]):
            pid = p.info.get("pid")
            if pid == me:
                continue  # skip THIS process — the launcher's `-c` resolver carries the needle itself
            # Match `needle` as a DISCRETE argv element (`python -m edp8.slack_bridge`), never a
            # substring — so a shell/`-c` command line that merely quotes the string is not a false
            # positive (that bit the resolver: its own `-c` argument contained the needle).
            if needle in (p.info.get("cmdline") or []):
                ct = float(p.info.get("create_time") or 0.0)
                if best is None or ct > best[0]:
                    best = (ct, int(pid))
    except Exception:  # noqa: BLE001
        return None
    return best[1] if best else None


def pid_cmdline_matches(pid: int | None, needle: str) -> bool:
    """True when `pid` is a live process whose command line contains `needle`. The launcher uses
    this to verify a bridge pid it recorded is still the bridge (not a reused pid) before treating
    the service as already running — scoped detection, never a machine-global scan (c-c0f2ceea9b)."""
    if not pid:
        return False
    try:
        import psutil
        return needle in psutil.Process(int(pid)).cmdline()  # discrete argv element, not a substring
    except Exception:  # noqa: BLE001 — no such pid / no privilege / no psutil
        return False


def _process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil
        return psutil.pid_exists(int(pid))
    except Exception:  # noqa: BLE001
        pass
    # Fallback without psutil: os.kill(pid, 0) on POSIX; assume unknown->True on Windows.
    try:
        os.kill(int(pid), 0)
        return True
    except (PermissionError, ProcessLookupError):
        return isinstance(pid, int)
    except (OSError, TypeError, ValueError):
        return os.name == "nt"  # can't cheaply check on Windows without psutil; trust the file
