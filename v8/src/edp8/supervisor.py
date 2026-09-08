"""Launcher supervisor — the framework's services are the launcher's to keep alive, not any
seat's (design §22). `start.*` leaves this process running. It probes each shared service over
ONE keep-alive connection every 15s, restarts a service after three consecutive failed probes
(or while its process is alive but its listener is gone — the §18.3 pool bug), and records one
`service_restarted {service, reason, by, git_rev}` event on the board. It never restarts on a
single miss and never kills a service that answers.

The probe rate is bounded (one connection, 15s) so the supervisor can never recreate the
ephemeral-port flood that lost the pool in §18.3.

The decision core (`Supervisor`) takes injected prober/alive/restart/emit callables so it is
unit-testable without real processes; `main()` wires the real ones.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Callable

from . import run_state
from .run_state import git_rev

FAIL_THRESHOLD = 3
PROBE_INTERVAL = 15.0
PROBE_TIMEOUT = 5.0  # > 2s so a slow-but-answering service (design test) is NOT counted as a miss


class Supervisor:
    def __init__(self, services: list[str], *, probe: Callable[[str], bool],
                 alive: Callable[[str], bool], restart: Callable[[str, str], None],
                 emit: Callable[[str, str], None], threshold: int = FAIL_THRESHOLD) -> None:
        self.services = services
        self._probe = probe
        self._alive = alive
        self._restart = restart
        self._emit = emit
        self.threshold = threshold
        self.fails: dict[str, int] = {s: 0 for s in services}

    def tick(self) -> None:
        """One probe round. Restart decision per service is: 3 consecutive failed probes.
        A single miss never restarts; a service that answers resets its counter."""
        for svc in self.services:
            ok = self._probe(svc)
            run_state.mark_probe(svc, ok)
            if ok:
                self.fails[svc] = 0
                continue
            self.fails[svc] += 1
            if self.fails[svc] >= self.threshold:
                # process alive while the listener is gone is the §18.3 failure; name it distinctly.
                reason = ("process alive without its listener" if self._alive(svc)
                          else f"{self.threshold} consecutive failed probes")
                self._restart(svc, reason)
                self._emit(svc, reason)
                self.fails[svc] = 0

    def run(self, *, interval: float = PROBE_INTERVAL, iterations: int | None = None,
            sleep: Callable[[float], None] = time.sleep) -> None:
        n = 0
        while iterations is None or n < iterations:
            self.tick()
            n += 1
            if iterations is not None and n >= iterations:
                break
            sleep(interval)


# --------------------------------------------------------------- real wiring


def _board_url() -> str:
    return os.environ.get("EDP8_BOARD_URL", "http://127.0.0.1:9400")


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
            return r.status_code < 400  # a 401/404 on the port is not the service answering
        except Exception:  # noqa: BLE001
            return False
    return probe


def real_alive(svc: str) -> bool:
    rec = run_state.read(svc)
    return run_state._process_alive(rec.get("pid")) if rec else False


def _launcher_cmd(svc: str) -> list[str]:
    """Restart goes through the platform launcher so there is ONE way to start a service
    (design §22 rule 2). start.ps1/start.sh --restart <svc> stops+starts just that service."""
    home = os.environ.get("EDP8_HOME", ".")
    if os.name == "nt":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", os.path.join(home, "start.ps1"), "-Restart", svc]
    return ["bash", os.path.join(home, "start.sh"), "--restart", svc]


def make_restart(by: str = "supervisor") -> Callable[[str, str], None]:
    def restart(svc: str, reason: str) -> None:
        try:
            subprocess.run(_launcher_cmd(svc), timeout=120,
                           cwd=os.environ.get("EDP8_HOME") or None,
                           capture_output=True, text=True)
        except Exception as e:  # noqa: BLE001
            print(f"supervisor: restart of {svc} failed to launch: {e}", file=sys.stderr)
        run_state.mark_restart(svc, reason, git_rev=git_rev())
    return restart


def make_emit(by: str = "supervisor") -> Callable[[str, str], None]:
    import httpx
    admin = os.environ.get("EDP8_ADMIN_TOKEN", "dev")

    def emit(svc: str, reason: str) -> None:
        try:
            httpx.post(f"{_board_url()}/v1/service_event",
                       json={"service": svc, "reason": reason, "by": by, "git_rev": git_rev()},
                       headers={"X-Admin": admin}, timeout=10.0)
        except Exception as e:  # noqa: BLE001
            print(f"supervisor: could not record service_restarted for {svc}: {e}", file=sys.stderr)
    return emit


def main() -> None:
    import httpx

    services = [s for s in run_state.SERVICES if run_state.SERVICES[s]["port"]]  # probe the four with a port
    run_state.write("supervisor", pid=os.getpid(), port=None, git_rev=git_rev())
    with httpx.Client() as client:  # ONE keep-alive connection for every probe (§22 rule 3)
        sup = Supervisor(services, probe=make_probe(client), alive=real_alive,
                         restart=make_restart(), emit=make_emit())
        print(f"supervisor up (pid {os.getpid()}); probing {services} every {int(PROBE_INTERVAL)}s",
              file=sys.stderr)
        try:
            sup.run()
        except KeyboardInterrupt:
            pass
        finally:
            run_state.clear("supervisor")


if __name__ == "__main__":
    main()
