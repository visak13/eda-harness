"""CODEX shell backend (s-10a2b1f9ec, epic-6a8a6020fd): a resident GPT-6 Astra seat under `codex app-server`.

PiSpawner's shape (Spawner ABC + the optional hooks service.py probes with getattr): the pool launches
`<agent_home>/.venv/Scripts/python.exe -m edp8.codex_seat.run`, which owns one `codex app-server`
thread, hosts the Claude-parity Monitor/TaskStop/Cron* tools as its dynamic tools, boots the role
card and stays up; Monitor lines and cron fires re-wake the model from inside the runner, so
"alive" == the runner process is running, exactly like a Claude shell. Identity reaches the board by
header from env (codex `env_http_headers` names EDP_HANDLE / EDP_SPAWN_SESSION_ID / EDP8_TOKEN) —
never on argv.

Arming: EDP_CODEX_ROLES="reviewer,qa" routes those roles here (main.py); empty = zero behaviour
change. Per spawn, a models.json seat whose harness is `codex` (e.g. "astra-codex") or a `codex/<id>`
model lands here too.

Modes (owner steer m-0259072d19: "the gpt shell opens like other shells and isnt headless"): the
default pool mode "monitor" runs the seat in its OWN console window (CREATE_NEW_CONSOLE) with the
conversation echoed and typed lines delivered as user turns (EDP_CODEX_CONSOLE=1); "headless" runs
the same runner silently with stdout to the pool log (parity oracle, tests).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .pi_launcher import _CLAUDE_ONLY, seat_python
from .pty_launcher import build_env

#: codex reasoning efforts a spawn's `effort` may select
CODEX_EFFORTS = ("low", "medium", "high")
_PASS_THROUGH = ("EDP_CODEX_BIN", "EDP_CODEX_MODEL", "EDP_CODEX_EFFORT", "EDP_CODEX_SANDBOX", "EDP8_MCP_URL",
                 "EDP8_HOME", "EDP_MONITOR_VARIANT", "EDP_MONITOR_SHELL")


def build_argv_codex(agent_home: str | None) -> list[str]:
    return [seat_python(agent_home), "-m", "edp8.codex_seat.run"]


def codex_seat_named(name: str | None, agent_home: str | None):
    """A models.json SEAT NAME whose harness is `codex` (e.g. "astra-codex") → that Seat; else None."""
    if not name or not agent_home:
        return None
    try:
        from edp_contracts.seats import load
        seats, _roles = load(agent_home)
        seat = seats.get(name)
        return seat if seat is not None and getattr(seat, "harness", None) == "codex" else None
    except Exception:  # noqa: BLE001 — registry trouble never blocks spawn
        return None


def is_codex_model(model: str | None, agent_home: str | None) -> bool:
    """Routing predicate for CompositeSpawner: a `codex/<id>` model, or a `harness: codex` seat name."""
    if not model:
        return False
    return model.startswith("codex/") or codex_seat_named(model, agent_home) is not None


def build_env_codex(session_id: str, role: str, handle: str, broker_url: str | None, *,
                    resume: bool = False, activation: str | None = None, console: bool = False, **kw) -> dict:
    """The pool's env contract verbatim (pty_launcher.build_env), minus claude-only keys and the pool's
    own python selectors, plus EDP_HARNESS=codex and the seat's resume/activation/console flags."""
    env = build_env(session_id, role, handle, broker_url, **kw)
    for k in _CLAUDE_ONLY:
        env.pop(k, None)
    for k in list(env):
        if k in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME") or k.startswith("UV_"):
            env.pop(k, None)
    env["EDP_HARNESS"] = "codex"
    env["EDP_CODEX_RESUME"] = "1" if resume else "0"
    env["EDP_CODEX_CONSOLE"] = "1" if console else "0"
    if activation:
        env["EDP_ACTIVATION"] = activation
    else:
        env.pop("EDP_ACTIVATION", None)
    for k in _PASS_THROUGH:
        v = os.environ.get(k)
        if v:
            env[k] = v
    env.setdefault("EDP_CODEX_MODEL", "gpt-6-astra")
    return env


class _Launch:
    __slots__ = ("proc", "log_path", "mirror_path", "started")

    def __init__(self, proc, log_path, mirror_path):
        self.proc = proc
        self.log_path = log_path
        self.mirror_path = mirror_path  # the runner's RPC mirror: moves on every model/tool event
        self.started = time.time()


class CodexSpawner:
    """Spawner-ABC-compatible backend for resident codex app-server seats."""

    def __init__(self, log_dir: str | None = None, broker_url: str | None = None,
                 pool_url: str | None = None, agent_home: str | None = None):
        self._log_dir = log_dir
        self._broker_url = broker_url
        self._pool_url = pool_url
        self._agent_home = agent_home
        self._launches: dict[str, _Launch] = {}

    # -- Spawner ABC --------------------------------------------------------
    def launch(self, session_id, role, handle, mode="headless",
               claude_session=None, resume_session=None, model=None,
               activation=None, parent=None, extra_env=None) -> None:
        console = mode != "headless"
        env = build_env_codex(session_id, role, handle, self._broker_url,
                              resume=bool(resume_session), activation=activation, console=console,
                              pool_url=self._pool_url, agent_home=self._agent_home,
                              log_dir=self._log_dir, parent=parent)
        if extra_env:  # S20: the per-seat EDP8_TOKEN the service mints — merged AFTER build_env's
            env.update({str(k): str(v) for k, v in extra_env.items()})  # secret strip; env only
        named = codex_seat_named(model, self._agent_home)
        if named is not None:
            env["EDP_CODEX_MODEL"] = named.model.split("/", 1)[-1]
            if named.thinking and not os.environ.get("EDP_CODEX_EFFORT"):
                env["EDP_CODEX_EFFORT"] = named.thinking
        elif model and model.startswith("codex/"):
            env["EDP_CODEX_MODEL"] = model.split("/", 1)[1]
        effort = str((extra_env or {}).get("EDP_SEAT_EFFORT") or "").strip().lower()
        if effort in CODEX_EFFORTS:  # the spawn's own effort wins over the seat default
            env["EDP_CODEX_EFFORT"] = effort
        log_path = None
        if self._log_dir:
            Path(self._log_dir).mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
            log_path = Path(self._log_dir) / f"{safe}.log"
        argv = build_argv_codex(self._agent_home)
        assert not any(env.get("EDP8_TOKEN") and env["EDP8_TOKEN"] in a for a in argv), "token on argv"
        cwd = self._agent_home or os.getcwd()
        if console:
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            proc = subprocess.Popen(argv, cwd=cwd, env=env, creationflags=flags)
        else:
            stdout = open(log_path, "ab") if log_path else subprocess.DEVNULL
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout,
                                    stderr=subprocess.STDOUT, creationflags=flags)
        mirror = Path(env.get("EDP_LOG_DIR") or self._log_dir or cwd) / f"codex-seat.{handle}.jsonl"
        self._launches[session_id] = _Launch(proc, log_path, mirror)

    def alive(self, session_id) -> bool:
        rec = self._launches.get(session_id)
        return rec is not None and rec.proc.poll() is None

    def kill(self, session_id) -> None:
        rec = self._launches.get(session_id)
        if rec and rec.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(rec.proc.pid), "/T", "/F"], capture_output=True)
            else:
                rec.proc.terminate()

    def knows(self, session_id) -> bool:
        return session_id in self._launches

    def pid(self, session_id):
        rec = self._launches.get(session_id)
        return rec.proc.pid if rec and rec.proc.poll() is None else None

    def last_output_ts(self, session_id):
        """Newest of the pool log (headless stdout) and the runner's RPC mirror (both modes), counting
        only writes by THIS incarnation (both files are appended across respawns of one handle)."""
        rec = self._launches.get(session_id)
        if not rec:
            return None
        ts = [t for p in (rec.log_path, rec.mirror_path) if p and p.exists()
              if (t := p.stat().st_mtime) >= rec.started - 1.0]  # 1 s slack: coarse filesystem mtimes
        return max(ts) if ts else None

    # -- optional hooks service.py probes with getattr ------------------------
    def exit_code(self, session_id):
        rec = self._launches.get(session_id)
        return rec.proc.poll() if rec else None

    def close_viewport(self, session_id):
        return None

    def viewport_died(self, session_id) -> bool:
        return False

    def pins_session_id(self, session_id) -> bool:
        """codex ignores the pool's claude pin (it resumes its own thread id)."""
        return False

    def session_token(self, session_id):
        """The thread id lives in `<log_dir>/codex-sessions/<handle>.json`, selected by EDP_CODEX_RESUME=1."""
        return None

    def closed_session_token(self, session_id, handle) -> str | None:
        """resume_closed seam: a closed codex seat resumes its recorded thread when the state file exists."""
        f = Path(self._log_dir or self._agent_home or os.getcwd()) / "codex-sessions" / f"{handle}.json"
        return str(f) if f.is_file() else None
