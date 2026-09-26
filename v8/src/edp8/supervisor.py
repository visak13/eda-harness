"""Launcher supervisor — the framework's services are the launcher's to keep alive, not any
seat's (design §22). `heronry start` leaves this process running (detached). It probes each shared
service over ONE keep-alive connection every 15s, restarts a service after three consecutive failed
probes (or while its process is alive but its listener is gone — the §18.3 pool bug), and records one
`service_restarted {service, reason, by, git_rev}` event on the board. It never restarts on a
single miss and never kills a service that answers.

The probe rate is bounded (one connection, 15s) so the supervisor can never recreate the
ephemeral-port flood that lost the pool in §18.3.

S3 adds (strategyll-3b8f4033e0 §3.3, §5): a loopback control port (`edp8.control`) through which the CLI
and S5's service-control API start, stop and restart services; a service an admin stopped is never
restarted until it is started again; more than 5 restarts in 10 minutes marks a service failed
(`crash_loop`) instead of restarting it forever; the main loop waits on an Event, so /shutdown (or a
POSIX SIGTERM) is served at once. Every (re)start goes through `launcher` — one code path.

The decision core (`Supervisor`) takes injected prober/alive/restart/emit callables so it is
unit-testable without real processes; `main()` wires the real ones.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from typing import Callable

from . import launcher, run_state, settings
from .run_state import git_rev

FAIL_THRESHOLD = 3
PROBE_INTERVAL = 15.0
PROBE_TIMEOUT = 5.0  # > 2s so a slow-but-answering service (design test) is NOT counted as a miss
CRASH_LOOP_MAX = 5
CRASH_LOOP_WINDOW_S = 600.0


class Supervisor:
    def __init__(self, services: list[str], *, probe: Callable[[str], bool],
                 alive: Callable[[str], bool], restart: Callable[[str, str], None],
                 emit: Callable[[str, str], None], threshold: int = FAIL_THRESHOLD,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.services = services
        self._probe = probe
        self._alive = alive
        self._restart = restart
        self._emit = emit
        self._clock = clock
        self.threshold = threshold
        self.fails: dict[str, int] = {s: 0 for s in services}
        self.paused: set[str] = set()     # stopped by an admin: never restarted until started again
        self.failed: set[str] = set()     # crash loop: given up on until started again
        self.restarts: dict[str, list[float]] = {s: [] for s in services}
        self.lock = threading.RLock()     # the control port acts between ticks, never during one
        self.stop_event = threading.Event()

    def tick(self) -> None:
        """One probe round. Restart decision per service is: 3 consecutive failed probes.
        A single miss never restarts; a service that answers resets its counter. A service an admin
        stopped is not probed; more than CRASH_LOOP_MAX restarts inside CRASH_LOOP_WINDOW_S marks it
        failed (one `crash_loop` event) instead of restarting it forever."""
        with self.lock:
            for svc in list(self.services):
                if svc in self.paused or svc in self.failed:
                    continue
                ok = self._probe(svc)
                run_state.mark_probe(svc, ok)
                if ok:
                    self.fails[svc] = 0
                    continue
                self.fails[svc] = self.fails.get(svc, 0) + 1
                if self.fails[svc] < self.threshold:
                    continue
                now = self._clock()
                recent = [t for t in self.restarts.get(svc, []) if now - t < CRASH_LOOP_WINDOW_S]
                if len(recent) >= CRASH_LOOP_MAX:
                    self.failed.add(svc)
                    run_state.update(svc, state="failed", last_restart_reason="crash_loop")
                    self._emit(svc, "crash_loop")
                    continue
                # process alive while the listener is gone is the §18.3 failure; name it distinctly.
                reason = ("process alive without its listener" if self._alive(svc)
                          else f"{self.threshold} consecutive failed probes")
                self._restart(svc, reason)
                self._emit(svc, reason)
                self.restarts[svc] = [*recent, now]
                self.fails[svc] = 0

    def resume(self, svc: str) -> None:
        """An admin started `svc`: supervise it again (clears paused and failed)."""
        with self.lock:
            self.paused.discard(svc)
            self.failed.discard(svc)
            self.fails[svc] = 0
            self.restarts[svc] = []
            if svc not in self.services:
                self.services.append(svc)

    def run(self, *, interval: float = PROBE_INTERVAL, iterations: int | None = None,
            sleep: Callable[[float], None] | None = None) -> None:
        """Probe every `interval` until `stop_event` (a signal or the control port's /shutdown) is set.
        The wait is `Event.wait`, never one long sleep, so a stop request is served at once."""
        n = 0
        while not self.stop_event.is_set() and (iterations is None or n < iterations):
            self.tick()
            n += 1
            if iterations is not None and n >= iterations:
                break
            if sleep is not None:
                sleep(interval)
            else:
                self.stop_event.wait(interval)


# --------------------------------------------------------------- real wiring


def _board_url() -> str:
    return launcher.url("board") or settings.get("EDP8_BOARD_URL")


def make_probe(client) -> Callable[[str], bool]:
    def probe(svc: str) -> bool:
        spec = run_state.SERVICES.get(svc, {})
        health = spec.get("health")
        rec = run_state.read(svc) or {}
        port = rec.get("port") or spec.get("port")  # the port the launcher actually started it on (qa: private fleets)
        if not health or not port:
            # portless service (bridge): liveness is process-only, handled by `alive`.
            return real_alive(svc)
        try:
            r = client.get(f"http://127.0.0.1:{port}{health}", timeout=PROBE_TIMEOUT)
            if r.status_code >= 400:  # a 401/404 on the port is not the service answering
                return False
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:  # noqa: BLE001
            return False
        # another home's service on our port is not ours answering (t-596660619c); no id = an older build
        hid = body.get("home_id") if isinstance(body, dict) else None
        return not hid or hid == launcher.my_home_id()
    return probe


def real_alive(svc: str) -> bool:
    return run_state.record_alive(run_state.read(svc))


# ------------------------------------------------------------- relaunch (one launcher code path, S3)
# A dead service is started again the way every channel starts it: `launcher.start`, i.e.
# `launcher.service_argv` (`<python> -m <module>`, or the bundle's --heronry-service re-entry), detached
# out of this process's tree, recorded by ProcId. Never through a shell (S2), never powershell.


def service_argv(svc: str) -> list[str]:
    return launcher.service_argv(svc)


def relaunch(svc: str, *, wait_s: float = 60.0) -> dict:
    """Stop what is left of `svc` (recorded identities + the port's listener, by ProcId; a pool keeps its
    seats), start it again outside this process's tree, wait for its listener, and record it."""
    old = run_state.read(svc) or {}
    stopped = launcher.stop(svc, keep_seats=True)
    if stopped["survivors"]:
        raise RuntimeError(f"{svc}: could not stop {stopped['survivors']}")
    launcher.start(svc, wait_s=wait_s)
    return run_state.update(svc, restarts=int(old.get("restarts") or 0) + 1) or {}


def make_restart(by: str = "supervisor") -> Callable[[str, str], None]:
    def restart(svc: str, reason: str) -> None:
        try:
            relaunch(svc)
        except Exception as e:  # noqa: BLE001
            print(f"supervisor: restart of {svc} failed: {e}", file=sys.stderr)
        run_state.update(svc, last_restart_reason=reason)
    return restart


def make_emit(by: str = "supervisor") -> Callable[..., None]:
    import httpx

    def emit(svc: str, reason: str, who: str | None = None) -> None:
        try:
            httpx.post(f"{_board_url()}/v1/service_event",
                       json={"service": svc, "reason": reason, "by": who or by, "git_rev": git_rev()},
                       headers={"X-Admin": settings.admin_token()}, timeout=10.0)
        except Exception as e:  # noqa: BLE001
            print(f"supervisor: could not record service_restarted for {svc}: {e}", file=sys.stderr)
    return emit


# --------------------------------------------------------------- control port (S3; S5 calls it)

def start_update(body: dict, who: str) -> tuple[int, dict]:
    """S5 Admin → Updates → Apply: `heronry update` detached OUT of the supervisor's tree, because it stops
    the supervisor and every service (backup → stop → the detached install helper → start). The request and
    its outcome are files in the run dir (update-request.json; the helper's update-result.json)."""
    import json

    from edp_contracts.proc import detach

    argv = [sys.executable, "-m", "edp8.cli", "update"]
    if isinstance(body.get("release_url"), str) and body["release_url"]:
        argv += ["--release-url", body["release_url"]]
    for flag in ("force", "skip_compat"):
        if body.get(flag):
            argv.append("--" + flag.replace("_", "-"))
    run = settings.run_dir()
    run.mkdir(parents=True, exist_ok=True)
    (run / "update-result.json").unlink(missing_ok=True)
    log = settings.logs_dir() / "update-run.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        pid: int | None = detach(argv, cwd=str(run), env=settings.environ_copy(), log=str(log))[0].pid
    except Exception:  # noqa: BLE001 — gone before it could be fingerprinted: it ran (and wrote its log)
        pid = None
    req = {"by": who, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "argv": argv[3:],
           "pid": pid, "log": str(log)}
    (run / "update-request.json").write_text(json.dumps(req), encoding="utf-8")
    return 202, {"ok": True, "state": "updating", **req}


def make_dispatch(sup: Supervisor, emit: Callable[..., None]) -> Callable[[str, dict], tuple[int, dict]]:
    """Route one control request: /services/<svc>/{start,stop,restart}, /status, /update, /shutdown."""

    def dispatch(path: str, body: dict) -> tuple[int, dict]:
        parts = [p for p in path.split("?", 1)[0].split("/") if p]
        who = str(body.get("by") or "admin")
        if parts == ["shutdown"]:
            sup.stop_event.set()
            return 200, {"ok": True, "state": "stopping"}
        if parts == ["status"]:
            return 200, {"ok": True, "services": launcher.status_rows(), "paused": sorted(sup.paused),
                         "failed": sorted(sup.failed)}
        if parts == ["update"]:
            return start_update(body, who)
        if len(parts) != 3 or parts[0] != "services" or parts[2] not in ("start", "stop", "restart"):
            return 404, {"ok": False, "error": f"no route {path}"}
        svc, verb = parts[1], parts[2]
        if svc not in launcher.ORDER:
            return 404, {"ok": False, "error": f"unknown service {svc!r}"}
        if svc == "pool" and verb in ("stop", "restart") and not body.get("force") and not body.get("keep_seats"):
            seats = launcher.live_seats()
            if seats:
                return 409, {"ok": False, "error": f"pool {verb} takes {len(seats)} live seat(s) offline; "
                             "repeat with force", "seats": seats}
        # every admin action is recorded as service_restarted {by} (S5, design §4.8), start and stop included
        with sup.lock:
            if verb == "stop":
                sup.paused.add(svc)
                out = launcher.stop(svc, keep_seats=bool(body.get("keep_seats")))
                if not out["survivors"]:
                    emit(svc, f"stop via the control port by {who}", who)
                return (200 if not out["survivors"] else 500), {"ok": not out["survivors"], **out}
            sup.resume(svc)
            if verb == "start":
                out = launcher.start(svc)
                emit(svc, f"start via the control port by {who}", who)
                return 200, {"ok": True, **out}
            rec = relaunch(svc)
            run_state.update(svc, last_restart_reason=f"restart by {who}")
        emit(svc, f"restart via the control port by {who}", who)
        return 200, {"ok": True, "service": svc, "state": "restarted", "pid": (rec or {}).get("pid"),
                     "url": launcher.url(svc)}

    return dispatch


def main() -> None:
    import httpx

    from . import control

    services = [s for s in run_state.SERVICES if run_state.SERVICES[s]["port"]]  # the four with a port
    # Supervise the port-less Slack bridge too — but ONLY when THIS fleet actually started one (a
    # run-dir record naming a live slack_bridge). A fleet with no bridge never adopts or restarts a
    # machine-global one, so a private fleet cannot resurrect/kill the LIVE bridge (S17
    # c-c0f2ceea9b / adversary #9). Its liveness is process-only (make_probe → real_alive).
    if run_state.pid_cmdline_matches((run_state.read("bridge") or {}).get("pid"), "edp8.slack_bridge"):
        services.append("bridge")
    emit = make_emit()
    with httpx.Client() as client:  # ONE keep-alive connection for every probe (§22 rule 3)
        sup = Supervisor(services, probe=make_probe(client), alive=real_alive,
                         restart=make_restart(), emit=emit)
        # a signal handler only sets the Event (POSIX SIGTERM; a Windows stop comes through /shutdown)
        for sig in (getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)):
            if sig is not None:
                try:
                    signal.signal(sig, lambda *_a: sup.stop_event.set())
                except (ValueError, OSError):
                    pass
        srv, cport = control.serve(make_dispatch(sup, emit))
        threading.Thread(target=srv.serve_forever, name="control", daemon=True).start()
        run_state.write("supervisor", pid=os.getpid(), port=None, git_rev=git_rev())
        run_state.update("supervisor", control_port=cport)
        print(f"supervisor up (pid {os.getpid()}, control 127.0.0.1:{cport}); probing {services} every "
              f"{int(PROBE_INTERVAL)}s", file=sys.stderr)
        try:
            sup.run()
        except KeyboardInterrupt:
            pass
        finally:
            srv.shutdown()
            run_state.clear("supervisor")
            control.secret_path().unlink(missing_ok=True)


if __name__ == "__main__":
    main()
