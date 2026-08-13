"""Service-startup wiring — co-launch the eda-base3 stack as PERSISTENT services.

The stack is three long-lived services that, until now, were brought up by hand
in three separate terminals (docs/design/components/integration/integration-HITL.md):

    1. edp-broker   (uvicorn, :9300)  — the durable message bus
    2. edp-pool     (uvicorn, :9301)  — the spawn-on-demand shell pool
    3. RuleSupervisor (edp_claude.reactive.registry supervise) — keeps every
       ENABLED registered rule subscribed by re-reading the durable registry on
       start, so the event plane's reflexes (e.g. the 6th-sense advisory watcher)
       SURVIVE a restart instead of dying with whatever shell created them.

This module wires the supervisor into the SAME startup as broker + pool so the
event plane is durable, not session-bound (s14 §b). It is the persistent-service
analogue of the manual run-order, with the safety properties the framework
mandates:

  * STRICT TRACKED-PID TEARDOWN, on clean exit AND on failure: we tear down ONLY
    the specific PIDs this launcher spawned (broker/pool/supervisor), graceful
    first (CTRL_BREAK on Windows / SIGTERM on POSIX, so the child's finally/
    atexit runs — the supervisor then tears down ITS OWN driver children and
    releases its singleton lock) then a hard kill if it overstays. We NEVER do a
    name/image-wide `python`/`node` kill (broker, pool, MCP, ml-server are all
    python; planner/worker shells the pool spawns are claude.exe/node) — those
    are out of scope and explicitly must not be touched.
  * FAIL-FAST: if any tracked service dies, the launcher tears the rest down and
    exits non-zero rather than leaving a half-up stack.
  * HEALTH-GATED ORDER: pool is started only after the broker's port answers,
    the supervisor only after the pool's — so the supervisor's rule drivers find
    a live broker to subscribe to.

The supervisor's own single-instance lock, re-subscribe-on-start, advisory-only
(Tier-2 DARK, driver phase=2) and tracked-PID teardown are unchanged here — this
file only LAUNCHES it alongside the other two.

Run:  python -m edp_claude.stack_launcher            (Ctrl-C to stop all three)
      python -m edp_claude.stack_launcher --no-supervisor   (broker+pool only)
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_IS_WINDOWS = os.name == "nt"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def stack_root() -> Path:
    """The eda-base3 root containing {claude, edp-broker, edp-pool}. This file
    is at <root>/claude/src/edp_claude/stack_launcher.py → parents[3] == root."""
    return Path(__file__).resolve().parents[3]


def venv_python(project_dir: Path) -> str:
    """The interpreter inside a sibling project's own `.venv` (broker/pool are
    separate uv projects with their own venvs). Falls back to the current
    interpreter if that project has no venv on disk."""
    candidate = (project_dir / ".venv" /
                 ("Scripts/python.exe" if _IS_WINDOWS else "bin/python"))
    return str(candidate) if candidate.exists() else sys.executable


# ── one service in the stack ────────────────────────────────────────────────
@dataclass
class ServiceSpec:
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    # health: a TCP port that must accept a connection before the next service
    # starts. None = no port to gate on (the supervisor) — a short settle only.
    health_host: str | None = None
    health_port: int | None = None


def default_services(root: Path, *, with_supervisor: bool = True,
                     broker_host: str = "127.0.0.1", broker_port: int = 9300,
                     pool_host: str = "127.0.0.1", pool_port: int = 9301
                     ) -> list[ServiceSpec]:
    """The eda-base3 stack: broker → pool → supervisor, each in its own project
    dir with its own venv. URLs are threaded through env so every service (and
    the rule drivers the supervisor spawns) agree on the same broker/pool."""
    broker_dir = root / "edp-broker"
    pool_dir = root / "edp-pool"
    claude_dir = root / "claude"
    broker_url = f"http://{broker_host}:{broker_port}"
    pool_url = f"http://{pool_host}:{pool_port}"

    services = [
        ServiceSpec(
            name="broker",
            cmd=[venv_python(broker_dir), "-m", "edp_broker.main"],
            cwd=broker_dir,
            env={"EDP_BROKER_HOST": broker_host,
                 "EDP_BROKER_PORT": str(broker_port),
                 "EDP_BROKER_DATA": str(broker_dir / ".broker-data")},
            health_host=broker_host, health_port=broker_port),
        ServiceSpec(
            name="pool",
            cmd=[venv_python(pool_dir), "-m", "edp_pool.main"],
            cwd=pool_dir,
            env={"EDP_POOL_HOST": pool_host, "EDP_POOL_PORT": str(pool_port),
                 "EDP_BROKER_URL": broker_url},
            health_host=pool_host, health_port=pool_port),
    ]
    if with_supervisor:
        services.append(ServiceSpec(
            name="supervisor",
            cmd=[venv_python(claude_dir), "-m",
                 "edp_claude.reactive.registry", "supervise"],
            cwd=claude_dir,
            # the supervisor re-reads <EDP_AGENT_HOME>/.reactive/registry and
            # spawns each rule's driver against THIS broker/pool.
            env={"EDP_AGENT_HOME": str(claude_dir),
                 "EDP_BROKER_URL": broker_url, "EDP_POOL_URL": pool_url}))
    return services


# ── the launcher (tracked-PID lifecycle for the whole stack) ─────────────────
class StackLauncher:
    """Brings the stack up in dependency order and keeps a tracked Popen per
    service. Teardown stops EVERY tracked PID (graceful → hard) on clean exit
    AND on failure — tracked PIDs only, never a name-wide kill. `spawn` and
    `health_probe` are injectable so the lifecycle is unit-tested with no real
    process, socket, or service."""

    def __init__(self, services: list[ServiceSpec], *,
                 pidfile: Path | None = None,
                 spawn: Callable[..., Any] | None = None,
                 health_probe: Callable[[str, int], bool] | None = None,
                 health_timeout_s: float = 30.0,
                 health_poll_s: float = 0.25,
                 settle_s: float = 0.5,
                 graceful_timeout_s: float = 8.0):
        self.services = services
        self.pidfile = pidfile or _default_pidfile()
        self._spawn = spawn or self._real_spawn
        self._health_probe = health_probe or _tcp_open
        self.health_timeout_s = health_timeout_s
        self.health_poll_s = health_poll_s
        self.settle_s = settle_s
        self.graceful_timeout_s = graceful_timeout_s
        self._procs: dict[str, Any] = {}
        self._stop = threading.Event()
        self._log_path = self.pidfile.with_suffix(".log.jsonl")

    # ---- structured log ----
    def log(self, event: str, **fields: Any) -> None:
        rec = {"ts": _utc(), "event": event, **fields}
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception:  # noqa: BLE001 — logging must never break teardown
            pass
        print(f"[stack] {event} {fields}", file=sys.stderr, flush=True)  # noqa: T201

    # ---- spawn one tracked service ----
    def _real_spawn(self, spec: ServiceSpec) -> subprocess.Popen:
        env = dict(os.environ)
        env.update(spec.env)
        kwargs: dict[str, Any] = {}
        if _IS_WINDOWS:
            # own process group so we can send CTRL_BREAK_EVENT for a GRACEFUL
            # stop (TerminateProcess would skip the child's atexit/finally — the
            # supervisor MUST run its finally to reap its driver children and
            # drop its lock).
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(spec.cmd, cwd=str(spec.cwd), env=env, **kwargs)

    def _wait_healthy(self, spec: ServiceSpec) -> None:
        if spec.health_host is None or spec.health_port is None:
            time.sleep(self.settle_s)  # no port to gate on (supervisor)
            return
        deadline = time.monotonic() + self.health_timeout_s
        while time.monotonic() < deadline:
            # the service must not have already crashed while we wait.
            proc = self._procs.get(spec.name)
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(
                    f"{spec.name} exited (rc={proc.returncode}) before its "
                    f"port {spec.health_port} came up")
            if self._health_probe(spec.health_host, spec.health_port):
                return
            time.sleep(self.health_poll_s)
        raise TimeoutError(
            f"{spec.name} port {spec.health_host}:{spec.health_port} did not "
            f"answer within {self.health_timeout_s}s")

    # ---- public lifecycle ----
    def start(self) -> None:
        """Launch every service in dependency order, health-gating each before
        the next. On ANY failure mid-bring-up, tear down what we already started
        (so we never leak a half-up stack) and re-raise."""
        try:
            for spec in self.services:
                proc = self._spawn(spec)
                self._procs[spec.name] = proc
                self.log("service_started", service=spec.name, pid=proc.pid,
                         cmd=spec.cmd)
                self._wait_healthy(spec)
                if spec.health_port is not None:
                    self.log("service_healthy", service=spec.name,
                             port=spec.health_port)
            self._write_pidfile()
        except BaseException:
            self.shutdown()
            raise

    def supervise(self, max_runtime: float | None = None) -> int:
        """Block until stop / max_runtime / a tracked service dies, then tear the
        whole stack down. Returns 0 on a clean requested stop, 1 if a service
        died unexpectedly (fail-fast)."""
        deadline = (time.monotonic() + max_runtime) if max_runtime else None
        rc = 0
        try:
            while not self._stop.is_set():
                dead = self._first_dead()
                if dead is not None:
                    name, proc = dead
                    self.log("service_died", service=name,
                             returncode=proc.returncode)
                    rc = 1
                    break
                if deadline is not None and time.monotonic() >= deadline:
                    break
                self._stop.wait(0.5)
            return rc
        finally:
            self.shutdown()

    def _first_dead(self) -> tuple[str, Any] | None:
        for name, proc in self._procs.items():
            if proc.poll() is not None:
                return name, proc
        return None

    # ---- teardown (tracked PIDs only; graceful → hard) ----
    def _signal_graceful(self, proc: Any) -> None:
        """Ask a tracked child to stop CLEANLY so its finally/atexit runs."""
        if _IS_WINDOWS:
            # to its own process group (CREATE_NEW_PROCESS_GROUP at spawn).
            os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
        else:
            proc.terminate()  # SIGTERM

    def _terminate_one(self, name: str, proc: Any) -> None:
        if proc.poll() is not None:
            return
        try:
            self._signal_graceful(proc)
        except Exception as e:  # noqa: BLE001 — fall through to hard kill
            self.log("service_graceful_signal_error", service=name,
                     error=f"{type(e).__name__}: {e}")
        try:
            proc.wait(timeout=self.graceful_timeout_s)
            self.log("service_stopped", service=name, pid=proc.pid,
                     returncode=proc.returncode, mode="graceful")
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            proc.kill()  # hard — THIS tracked PID only, never a name-wide kill
            proc.wait(timeout=self.graceful_timeout_s)
            self.log("service_stopped", service=name, pid=proc.pid,
                     returncode=proc.returncode, mode="hard")
        except Exception as e:  # noqa: BLE001 — never swallow silently
            self.log("service_teardown_error", service=name,
                     error=f"{type(e).__name__}: {e}")

    def shutdown(self) -> None:
        """Idempotent full teardown: stop, terminate EVERY tracked service by its
        own PID (graceful → hard) in REVERSE start order (supervisor first, so it
        reaps its drivers before its broker/pool go away), clear the pidfile.

        Ctrl-C-PROOF (operator finding 2026-08-13): the broker is torn down
        LAST, and a second Ctrl-C during the supervisor/pool legs used to
        KeyboardInterrupt this loop mid-way — pool dead, broker orphaned
        holding :9300 ("the broker doesn't shut down like the others").
        Each leg now retries through interrupts; a truly stuck teardown is
        escaped by a third interrupt AFTER the loop has had its chance."""
        self._stop.set()
        for name in reversed(list(self._procs.keys())):
            proc = self._procs.get(name)
            if proc is None:
                continue
            for _attempt in (1, 2, 3):
                try:
                    self._terminate_one(name, proc)
                    break
                except KeyboardInterrupt:
                    self.log("service_teardown_interrupted", service=name,
                             attempt=_attempt)
                    continue
        self._procs.clear()
        self._clear_pidfile()

    def tracked_pids(self) -> dict[str, int]:
        return {name: p.pid for name, p in self._procs.items()}

    # ---- durable pidfile (so an operator can see / verify the tracked PIDs) ----
    def _write_pidfile(self) -> None:
        rec = {"ts": _utc(), "pids": self.tracked_pids()}
        try:
            self.pidfile.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.pidfile.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(rec, indent=2, default=str),
                           encoding="utf-8")
            os.replace(tmp, self.pidfile)
        except Exception as e:  # noqa: BLE001
            self.log("pidfile_write_error", error=f"{type(e).__name__}: {e}")

    def _clear_pidfile(self) -> None:
        try:
            if self.pidfile.exists():
                self.pidfile.unlink()
        except Exception:  # noqa: BLE001
            pass


def _default_pidfile() -> Path:
    env = os.environ.get("EDP_STACK_PIDFILE")
    if env:
        return Path(env)
    return stack_root() / ".logs" / "stack-pids.json"


def _tcp_open(host: str, port: int, timeout: float = 1.0) -> bool:
    """True if a TCP connection to host:port is accepted (the service's uvicorn
    is listening). The most transport-agnostic health gate — no endpoint
    assumptions."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="edp-stack",
        description="Co-launch broker + pool + RuleSupervisor as persistent "
                    "services with tracked-PID teardown.")
    ap.add_argument("--no-supervisor", action="store_true",
                    help="broker + pool only (do not start the RuleSupervisor)")
    ap.add_argument("--broker-port", type=int, default=9300)
    ap.add_argument("--pool-port", type=int, default=9301)
    ap.add_argument("--max-runtime", type=float, default=None,
                    help="stop the whole stack after N seconds (smoke tests)")
    args = ap.parse_args(argv)

    root = stack_root()
    services = default_services(
        root, with_supervisor=not args.no_supervisor,
        broker_port=args.broker_port, pool_port=args.pool_port)
    launcher = StackLauncher(services)

    # a Ctrl-C / SIGTERM to the launcher itself triggers a clean stack teardown.
    def _on_signal(*_: Any) -> None:
        launcher._stop.set()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _on_signal)
        except Exception:  # noqa: BLE001 — not every signal exists everywhere
            pass

    launcher.start()
    launcher.log("stack_up", pids=launcher.tracked_pids(),
                 pidfile=str(launcher.pidfile))
    return launcher.supervise(max_runtime=args.max_runtime)


if __name__ == "__main__":
    raise SystemExit(main())
