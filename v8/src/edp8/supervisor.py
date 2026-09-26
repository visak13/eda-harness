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
import sys
import time
from pathlib import Path
from typing import Callable

from edp_contracts.proc import detach

from . import run_state, settings
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
    return settings.get("EDP8_BOARD_URL")


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
    return run_state.record_alive(run_state.read(svc))


# ------------------------------------------------------------- relaunch (S2: no shell, sys.executable)
# A dead service is started again the way the launcher started it, minus the shell: `<python> -m
# <module>` in the launcher's working dir, with the launcher's environment (this process inherited it
# from start.*). Before S2 this went through `powershell start.ps1 -Restart`, which only ran on Windows.
_MODULES = {"board": "edp8.service", "broker": "edp_broker.main", "pool": "edp_pool.main",
            "mcp": "edp8.mcp_server", "bridge": "edp8.slack_bridge"}


def _venv_python(d: Path) -> Path:
    return d / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _home() -> Path:
    return Path(settings.home() or os.getcwd())


def service_python(svc: str) -> str:
    """EDP_<SVC>_PYTHON, else the venv the launcher uses for it, else this interpreter."""
    configured = settings.env_raw(f"EDP_{svc.upper()}_PYTHON")
    if configured:
        return configured
    own = {"pool": settings.get("EDP_POOL_DIR"), "broker": _home().parent / "edp-broker"}.get(svc)
    if own is not None and _venv_python(Path(own)).is_file():
        return str(_venv_python(Path(own)))
    return sys.executable


def service_cwd(svc: str) -> Path:
    # uv run --directory <edp-broker> is how start.* runs the broker; everything else runs in the home
    if svc == "broker" and (_home().parent / "edp-broker").is_dir():
        return _home().parent / "edp-broker"
    return _home()


def service_argv(svc: str) -> list[str]:
    return [service_python(svc), "-m", _MODULES[svc]]


def relaunch(svc: str, *, wait_s: float = 60.0) -> dict:
    """Stop what is left of `svc` (recorded pid tree + the port's listener, by ProcId), start it again
    outside this process's tree, wait for its listener, and record it. Returns the new record."""
    old = run_state.read(svc) or {}
    port = old.get("port") or run_state.SERVICES.get(svc, {}).get("port")
    stopped = run_state.stop_service(svc)
    if stopped["still_running"]:
        raise RuntimeError(f"{svc}: could not stop {stopped['still_running']}")
    data = settings.data_dir()
    data.mkdir(parents=True, exist_ok=True)
    ident, _ = detach(service_argv(svc), cwd=str(service_cwd(svc)), env=settings.environ_copy(),
                      log=str(data / f"{svc}.log"))
    pid = ident.pid
    deadline = time.monotonic() + wait_s
    while port and time.monotonic() < deadline:
        lp = run_state.listener_pid(int(port))
        if lp:
            pid = lp
            break
        if not ident.live():
            break
        time.sleep(0.25)
    run_state.write(svc, pid=pid, port=port, git_rev=git_rev())
    return run_state.update(svc, restarts=int(old.get("restarts") or 0) + 1) or {}


def make_restart(by: str = "supervisor") -> Callable[[str, str], None]:
    def restart(svc: str, reason: str) -> None:
        try:
            relaunch(svc)
        except Exception as e:  # noqa: BLE001
            print(f"supervisor: restart of {svc} failed: {e}", file=sys.stderr)
        run_state.update(svc, last_restart_reason=reason)
    return restart


def make_emit(by: str = "supervisor") -> Callable[[str, str], None]:
    import httpx
    admin = settings.admin_token()

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

    services = [s for s in run_state.SERVICES if run_state.SERVICES[s]["port"]]  # the four with a port
    # Supervise the port-less Slack bridge too — but ONLY when THIS fleet actually started one (a
    # run-dir record naming a live slack_bridge). A fleet with no bridge never adopts or restarts a
    # machine-global one, so a private fleet cannot resurrect/kill the LIVE bridge (S17
    # c-c0f2ceea9b / adversary #9). Its liveness is process-only (make_probe → real_alive).
    if run_state.pid_cmdline_matches((run_state.read("bridge") or {}).get("pid"), "edp8.slack_bridge"):
        services.append("bridge")
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
