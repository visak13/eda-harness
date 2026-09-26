"""The one launcher code path (design-e963c656f5 §4.4, S3 s-870e401942).

Every channel starts, stops and restarts services through this module: the `heronry` CLI, the
supervisor (its restarts and its loopback control port) and the legacy wrappers (`edp.ps1`, `start.*`,
`stop.*`, the `.bat` files), which only call the CLI.

* **One argv builder.** :func:`service_argv` returns ``[python, -m, <module>]`` for a uv/venv install
  (dev mode keeps each package's own venv), and ``[app_exe, --heronry-service, <svc>]`` inside a
  frozen bundle, where ``sys.executable`` is the app stub (strategyhl-5af811e7bd §3). No service is
  ever launched through a uv bin shim or a shell.
* **Process identity** is S2's ``edp_contracts.proc``: a service is started out of the caller's tree
  with :func:`~edp_contracts.proc.detach`, joined to a named Windows job, recorded as a ProcId in the
  run dir, and stopped with a snapshot-first ``kill_tree`` plus ``terminate_job``. No taskkill, WMI or
  powershell (epic criterion 3).
* **Every path and port** comes from the settings registry (S1); a changed port also moves the URLs
  the other services are given, unless a URL is set explicitly.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edp_contracts.proc import ProcId, assign_job, detach, job_name, kill_tree, terminate_job

from . import run_state, settings

#: Start order; stop runs it backwards.
ORDER = ("board", "broker", "pool", "mcp", "bridge")
SUPERVISOR = "supervisor"
#: The flag a frozen bundle's entry point dispatches on, before any GUI import (strategyhl-5af811e7bd §3).
SERVICE_FLAG = "--heronry-service"


@dataclass(frozen=True)
class Svc:
    name: str
    module: str
    port_env: str | None     # the settings key of its port; None = port-less (the Slack bridge)
    url_env: str | None      # the settings key other services reach it by
    health: str | None


SPECS: dict[str, Svc] = {
    "board": Svc("board", "edp8.service", "EDP8_PORT", "EDP8_BOARD_URL", "/v1/health"),
    "broker": Svc("broker", "edp_broker.main", "EDP_BROKER_PORT", "EDP_BROKER_URL", "/v1/health"),
    "pool": Svc("pool", "edp_pool.main", "EDP_POOL_PORT", "EDP_POOL_URL", "/v1/health"),
    "mcp": Svc("mcp", "edp8.mcp_server", "EDP8_MCP_PORT", "EDP8_MCP_URL", "/healthz"),
    "bridge": Svc("bridge", "edp8.slack_bridge", None, None, None),
    SUPERVISOR: Svc(SUPERVISOR, "edp8.supervisor", None, None, None),
}
#: module per service; the supervisor's relaunch reads the same map (tests patch it here).
MODULES: dict[str, str] = {k: v.module for k, v in SPECS.items()}


class LaunchError(RuntimeError):
    """A service could not be started or stopped; the message is one plain line for the user."""


# ------------------------------------------------------------------------------------------ settings

def port(svc: str) -> int | None:
    """The service's port: run_state's table (the same settings, read once per process, and the one
    `status` and the supervisor's probe use), else the setting."""
    spec = SPECS[svc]
    if spec.port_env is None:
        return None
    known = run_state.SERVICES.get(svc, {}).get("port")
    return int(known) if known else int(settings.get(spec.port_env))


def url(svc: str) -> str | None:
    """The URL a user or another service reaches `svc` at: the explicit setting, else loopback + port."""
    spec = SPECS[svc]
    if spec.url_env is None:
        return None
    if settings.is_set(spec.url_env):
        return str(settings.get(spec.url_env)).rstrip("/")
    return f"http://127.0.0.1:{port(svc)}"


def bundled() -> bool:
    """True inside a frozen app bundle (Briefcase/PyInstaller), where sys.executable is the app stub.

    PyInstaller sets ``sys.frozen``; a Briefcase stub does not (measured on Windows, S8), so the test is also
    structural: the running executable is not a Python interpreter (``python``, ``python3.12``, ``pythonw``)."""
    if getattr(sys, "frozen", False):
        return True
    return not Path(sys.executable or "python").name.lower().startswith("python")


#: Windows bundles ship the console CLI stub beside the GUI stub (S8): services and helpers launch through it,
#: so their stdout/stderr reach the log and a seat's Monitor, which a GUI-subsystem stub would not give.
CONSOLE_EXE = "heronry.exe"


def bundle_exe() -> str:
    """The executable a bundle re-enters: the console CLI stub beside the app stub on Windows, else the stub."""
    if sys.platform == "win32":
        console = Path(sys.executable).with_name(CONSOLE_EXE)
        if console.is_file():
            return str(console)
    return sys.executable


def _venv_python(d: Path) -> Path:
    return d / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def service_python(svc: str) -> str:
    """EDP_<SVC>_PYTHON, else (dev mode) the venv the source tree keeps for that package, else this
    interpreter (an installed tool venv holds all four packages)."""
    if svc in ("board", "broker", "pool", "mcp", "bridge"):
        configured = settings.env_raw(f"EDP_{svc.upper()}_PYTHON")
        if configured:
            return configured
    if settings.dev_mode():
        home = settings.home()
        own = {"pool": settings.get("EDP_POOL_DIR"),
               "broker": home.parent / "edp-broker" if home else None}.get(svc)
        if own is not None and _venv_python(Path(own)).is_file():
            return str(_venv_python(Path(own)))
    return sys.executable


def service_argv(svc: str) -> list[str]:
    """THE argv every channel starts `svc` with (one launcher code path)."""
    if svc not in MODULES:
        raise LaunchError(f"unknown service {svc!r} (board|broker|pool|mcp|bridge)")
    if bundled():
        return [bundle_exe(), SERVICE_FLAG, svc]
    return [service_python(svc), "-m", MODULES[svc]]


def service_cwd(svc: str) -> Path:
    """Dev mode: the checkout (the broker runs from its own project dir, as `uv run --directory` did);
    installed: the data dir, so a relative default never lands in the user's shell cwd."""
    home = settings.home()
    if settings.dev_mode() and home is not None:
        if svc == "broker" and (home.parent / "edp-broker").is_dir():
            return home.parent / "edp-broker"
        return home
    d = settings.data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bind_host() -> str:
    explicit = settings.get("EDP8_HOST")
    if explicit:
        return str(explicit)
    return "0.0.0.0" if settings.get("EDP8_PUBLIC_URL") else "127.0.0.1"


def child_env(svc: str) -> dict[str, str]:
    """The environment `svc` runs with: this process's environment, the one home and run dir, the URLs of
    the other services derived from their ports, and the per-service values today's launchers set. A value
    already in the environment always wins (env > config.toml > default)."""
    env = settings.environ_copy()
    home = settings.home()
    if home is not None:
        env["EDP_HOME"] = env["EDP8_HOME"] = str(home)
    env["EDP8_RUN_DIR"] = str(settings.run_dir())
    for other in ("board", "broker", "pool", "mcp"):
        spec = SPECS[other]
        if spec.url_env and not settings.is_set(spec.url_env):
            env[spec.url_env] = f"http://127.0.0.1:{port(other)}"

    def default(name: str, value: str) -> None:
        if not settings.is_set(name):
            env[name] = value

    data = settings.data_dir()
    if svc == "board":
        default("EDP8_HOST", _bind_host())
    elif svc == "broker":
        default("EDP_BROKER_HOST", _bind_host())
    elif svc == "pool":
        default("EDP_POOL_LOG_DIR", str(data / "pool-logs"))
        default("EDP_POOL_STATE", str(data / "pool-logs" / "pool-state.json"))
        # a pool seat never waits on a permission prompt nobody answers, and keeps its session file
        default("EDP_SKIP_PERMISSIONS", "1")
        env.setdefault("CLAUDE_CODE_FORCE_SESSION_PERSISTENCE", "1")
        # seats never self-update mid-run (design §4.10); the pool also sets it per claude seat
        env.setdefault("DISABLE_AUTOUPDATER", "1")
    return env


# ------------------------------------------------------------------------------------------ probing

def healthy(svc: str, *, timeout: float = 2.0) -> bool:
    spec = SPECS[svc]
    if spec.health is None:
        return running(svc)
    import httpx
    try:
        r = httpx.get(f"http://127.0.0.1:{port(svc)}{spec.health}", timeout=timeout)
        return r.status_code < 400
    except httpx.HTTPError:
        return False


def _root(rec: dict[str, Any] | None) -> ProcId | None:
    return ProcId.from_json((rec or {}).get("root"))


def running(svc: str) -> bool:
    """A process this launcher recorded for `svc` is still the process it recorded (ProcId)."""
    rec = run_state.read(svc)
    if rec is None:
        return False
    if run_state.record_alive(rec):
        return True
    root = _root(rec)
    return bool(root and root.live())


def _record_supervisor_alive() -> bool:
    return running(SUPERVISOR)


# ------------------------------------------------------------------------------------------ start

def _log_path(svc: str) -> Path:
    d = settings.logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{svc}.log"


def _job(svc: str) -> str:
    return job_name("svc", f"{svc}-{port(svc) or 'x'}")


def enabled(svc: str) -> bool:
    """The bridge runs only where Slack is configured (a slack map); the rest always."""
    if svc == "bridge":
        return Path(settings.get("EDP8_SLACK_MAP")).is_file()
    return True


def start(svc: str, *, wait_s: float = 90.0) -> dict[str, Any]:
    """Start `svc` unless it already runs. Returns {service, state: started|already_running|skipped, pid,
    url}. Idempotent: a service that answers its health route is adopted, never started twice."""
    if svc not in SPECS:
        raise LaunchError(f"unknown service {svc!r} (board|broker|pool|mcp|bridge)")
    if not enabled(svc):
        return {"service": svc, "state": "skipped", "reason": "no slack map configured", "pid": None, "url": None}
    p = port(svc)
    if (p and healthy(svc)) or (not p and running(svc)):
        rec = run_state.adopt(svc, port=p) if p else run_state.read(svc)
        return {"service": svc, "state": "already_running", "pid": (rec or {}).get("pid"), "url": url(svc)}
    if p and run_state._port_listening(p):
        raise LaunchError(f"{svc}: port {p} is taken by another program (pid {run_state.listener_pid(p)}); "
                          f"free it or set another port ({SPECS[svc].port_env}) and re-run")
    argv = service_argv(svc)
    log = _log_path(svc)
    ident, _ = detach(argv, cwd=str(service_cwd(svc)), env=child_env(svc), log=str(log))
    job = _job(svc)
    assign_job(job, ident.pid)  # Windows: the job also reaches orphans at stop; False (no-op) elsewhere
    pid = ident.pid
    if p:
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline and ident.live():
            lp = run_state.listener_pid(p)
            if lp and healthy(svc):
                pid = lp
                break
            time.sleep(0.25)
    else:
        time.sleep(2.0)  # port-less (the bridge): still alive after 2 s is started
    if not ident.live() and not (p and healthy(svc)):
        raise LaunchError(f"{svc} exited during start; see {log}")
    if p and not healthy(svc):
        rep = kill_tree(ident, job=job)
        raise LaunchError(f"{svc} did not answer {SPECS[svc].health} on :{p} within {int(wait_s)} s "
                          f"(stopped it again{'' if rep.ok else ', survivors ' + str(rep.survivors)}); see {log}")
    run_state.write(svc, pid=pid, port=p, git_rev=run_state.git_rev())
    run_state.update(svc, root=ident.to_json(), job=job, argv=argv, log=str(log))
    if svc == "board":
        register_defaults()
    return {"service": svc, "state": "started", "pid": pid, "url": url(svc)}


def register_defaults() -> None:
    """The default participants (the owner under its handle, and one of each agent role), as the old
    launchers did after a board start; idempotent, and quiet when the board refuses."""
    import contextlib
    import io

    from . import bootstrap
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            # `--x=value`: a generated token may start with "-", which argparse would take for a flag
            bootstrap.main([f"--board=http://127.0.0.1:{port('board')}", f"--admin={settings.admin_token()}",
                            f"--owner={settings.get('EDP8_OWNER')}"])
    except (Exception, SystemExit):  # noqa: BLE001 — registration is a convenience; the board is up either way
        pass


# ------------------------------------------------------------------------------------------ stop

def _targets(svc: str) -> list[ProcId]:
    rec = run_state.read(svc) or {}
    out: list[ProcId] = []
    for ident in (_root(rec), run_state._ident(rec)):
        if ident is not None and ident.live() and all(t.pid != ident.pid for t in out):
            out.append(ident)
    p = rec.get("port") or port(svc)
    lp = run_state.listener_pid(int(p)) if p else None
    lid = ProcId.try_of(lp) if lp else None
    if lid is not None and _ours(svc, lid) and all(t.pid != lid.pid for t in out):
        out.append(lid)
    return out


def _ours(svc: str, ident: ProcId) -> bool:
    """A port listener counts as this service only when it runs the service's module (a port is only a
    number: another program, or another checkout's service with another home, is never stopped)."""
    p = ident.live()
    if p is None:
        return False
    try:
        cmd = p.cmdline()
        env_home = p.environ().get("EDP_HOME") or p.environ().get("EDP8_HOME")
    except Exception:  # noqa: BLE001 — unreadable: not provably ours
        return False
    if MODULES[svc] not in cmd and SERVICE_FLAG not in cmd and not any(c.endswith(("edp8-board", "edp8-board.exe"))
                                                                          for c in cmd):
        return False
    mine = settings.home()
    if mine is None or env_home is None:
        return True
    try:
        return Path(env_home).resolve() == mine
    except OSError:
        return False


def _pool_chain(ident: ProcId) -> list[ProcId]:
    """The pool's own processes (stub + interpreter), never its seats: a pool restart leaves the seat shells
    running for the new pool to re-adopt (the fleet's contract, edp.ps1 SAFE RESTART)."""
    root = ident.live()
    if root is None:
        return []
    chain = [ident]
    try:
        for c in root.children(recursive=True):
            if MODULES["pool"] in (c.cmdline() or []):
                chain.append(ProcId(c.pid, c.create_time(), c.name()))
    except Exception:  # noqa: BLE001
        pass
    return chain


def live_seats() -> list[str] | None:
    """Active seats on this pool ("handle (pid N)"), [] when none, None when the pool cannot say."""
    if not run_state._port_listening(port("pool")):
        return []
    import httpx
    try:
        rows = httpx.get(f"http://127.0.0.1:{port('pool')}/v1/sessions", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        return None
    if isinstance(rows, dict):
        rows = rows.get("sessions") or rows.get("value") or []
    return [f"{r.get('handle')} (pid {(r.get('proc') or {}).get('pid')})" for r in rows
            if isinstance(r, dict) and r.get("state") == "active"]


def stop(svc: str, *, keep_seats: bool = False, grace: float = 4.0) -> dict[str, Any]:
    """Stop `svc` and verify it is gone: snapshot-first kill_tree of every recorded identity plus its
    listener, and its named job (Windows). `keep_seats` (pool restart) stops only the pool's own chain.
    Returns {service, state: stopped|not_running, killed, survivors}; survivors non-empty = failure."""
    rec = run_state.read(svc)
    targets = _targets(svc)
    if not targets:
        if rec is not None:
            terminate_job(rec.get("job"))
            run_state.clear(svc)
        return {"service": svc, "state": "not_running", "killed": 0, "survivors": []}
    job = (rec or {}).get("job")
    killed, survivors = 0, []
    if svc == "pool" and keep_seats:
        chain = [c for t in targets for c in _pool_chain(t)]
        for c in chain:
            proc = c.live()
            if proc is None:
                continue
            try:
                proc.kill()
                killed += 1
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.5)
        survivors = [c for c in chain if c.live()]
    else:
        for t in targets:
            rep = kill_tree(t, grace=grace, job=job)
            killed += rep.killed
            survivors.extend(rep.survivors)
            job = None  # terminated once
    p = (rec or {}).get("port") or port(svc)
    if p and run_state._port_listening(int(p)):
        lp = run_state.listener_pid(int(p))
        lid = ProcId.try_of(lp) if lp else None
        if lid is not None and _ours(svc, lid) and all(s.pid != lid.pid for s in survivors):
            survivors.append(lid)
    if not survivors:
        run_state.clear(svc)
    return {"service": svc, "state": "stopped", "killed": killed, "survivors": [s.to_json() for s in survivors]}


# ------------------------------------------------------------------------------------------ supervisor

def supervisor_running() -> bool:
    return _record_supervisor_alive()


def ensure_supervisor(*, wait_s: float = 20.0) -> dict[str, Any]:
    """Start the supervisor daemon unless one runs for this home (it re-adopts live services itself)."""
    if supervisor_running():
        rec = run_state.read(SUPERVISOR) or {}
        return {"service": SUPERVISOR, "state": "already_running", "pid": rec.get("pid")}
    argv = [bundle_exe(), SERVICE_FLAG, SUPERVISOR] if bundled() else [sys.executable, "-m", MODULES[SUPERVISOR]]
    log = _log_path(SUPERVISOR)
    env = settings.environ_copy()
    home = settings.home()
    if home is not None:
        env["EDP_HOME"] = env["EDP8_HOME"] = str(home)
    env["EDP8_RUN_DIR"] = str(settings.run_dir())
    ident, _ = detach(argv, cwd=str(service_cwd("board")), env=env, log=str(log))
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline and ident.live():
        rec = run_state.read(SUPERVISOR)
        if rec and rec.get("control_port"):
            break
        time.sleep(0.2)
    if not ident.live():
        raise LaunchError(f"the supervisor exited during start; see {log}")
    run_state.update(SUPERVISOR, root=ident.to_json())
    # the recorded pid is the interpreter itself (a venv's python.exe is a launcher stub around it)
    return {"service": SUPERVISOR, "state": "started", "pid": (run_state.read(SUPERVISOR) or {}).get("pid") or ident.pid}


def stop_supervisor() -> dict[str, Any]:
    """Ask the supervisor to exit (control port), then make sure: kill_tree of its identity."""
    from . import control
    was = supervisor_running()
    if was:
        try:
            control.call("/shutdown")
        except Exception:  # noqa: BLE001 — unreachable: the kill below is the floor
            pass
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and supervisor_running():
            time.sleep(0.2)
    out = stop(SUPERVISOR)
    if was and not out["survivors"]:
        out["state"] = "stopped"
    return out


# ------------------------------------------------------------------------------------------ status

def status_rows() -> list[dict[str, Any]]:
    rows = run_state.snapshot()
    for r in rows:
        r["url"] = url(r["service"]) if r["service"] in SPECS else None
    sup = run_state.read(SUPERVISOR)
    rows.append({"service": SUPERVISOR, "state": "up" if supervisor_running() else "down",
                 "pid": (sup or {}).get("pid") if supervisor_running() else None,
                 "port": (sup or {}).get("control_port") if supervisor_running() else None,
                 "url": None, "uptime": run_state._uptime(sup) if sup and supervisor_running() else None})
    return rows


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)
