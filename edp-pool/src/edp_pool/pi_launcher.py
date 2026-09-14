"""PI shell backend (epic-6a8a6020fd S2): a resident GPT-6 Astra seat under pi.dev's coding agent.

Mirrors opencode_launcher's shape (Spawner ABC + the optional hooks service.py probes with getattr),
minus opencode's one-shot/TUI machinery: a Pi seat is a RESIDENT process — the pool launches
`<agent_home>/.venv/Scripts/python.exe -m edp8.pi_seat.run`, which owns `pi --mode rpc` (JSONL on
stdio), boots the role card, and stays up; Monitor lines and cron fires re-wake the model inside
Pi (v8/.pi/extensions/edp8.ts), so "alive" == the runner process is running, exactly like a Claude
shell. Identity reaches the board by header (X-Participant/X-Session/X-Token) from env, as
`.mcp.json` does for Claude — never on argv.

Arming: EDP_PI_ROLES="reviewer,qa" routes those roles here (main.py); empty = zero behaviour change.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .pty_launcher import build_env

_CLAUDE_ONLY = ("CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
                "CLAUDE_CODE_MAX_OUTPUT_TOKENS")


def seat_python(agent_home: str | None) -> str:
    """The AGENT HOME's own venv python (edp8 is installed there), never the pool's."""
    override = os.environ.get("EDP_PI_SEAT_PYTHON", "").strip()
    if override:
        return override
    home = Path(agent_home or os.getcwd())
    cand = home / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(cand) if cand.is_file() else sys.executable


def build_argv_pi(agent_home: str | None) -> list[str]:
    return [seat_python(agent_home), "-m", "edp8.pi_seat.run"]


def build_env_pi(session_id: str, role: str, handle: str, broker_url: str | None, *,
                 resume: bool = False, activation: str | None = None, **kw) -> dict:
    """The pool's env contract verbatim (pty_launcher.build_env), minus claude-only keys and the
    pool's own python selectors, plus EDP_HARNESS=pi and the seat's resume/activation flags."""
    env = build_env(session_id, role, handle, broker_url, **kw)
    for k in _CLAUDE_ONLY:
        env.pop(k, None)
    for k in list(env):
        if k in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME") or k.startswith("UV_"):
            env.pop(k, None)
    env["EDP_HARNESS"] = "pi"
    env["EDP_PI_RESUME"] = "1" if resume else "0"
    if activation:
        env["EDP_ACTIVATION"] = activation
    else:
        env.pop("EDP_ACTIVATION", None)
    for k in ("EDP_PI_BIN", "EDP_PI_MODEL", "EDP_PI_THINKING", "EDP8_LANE_DIR", "EDP8_HOME"):
        v = os.environ.get(k)
        if v:
            env[k] = v
    return env


class _Launch:
    __slots__ = ("proc", "log_path", "started")

    def __init__(self, proc, log_path):
        self.proc = proc
        self.log_path = log_path
        self.started = time.time()


class PiSpawner:
    """Spawner-ABC-compatible backend for resident Pi seats."""

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
               activation=None, parent=None) -> None:
        env = build_env_pi(session_id, role, handle, self._broker_url,
                           resume=bool(resume_session), activation=activation,
                           pool_url=self._pool_url, agent_home=self._agent_home,
                           log_dir=self._log_dir, parent=parent)
        if model:
            env["EDP_PI_MODEL"] = model if model.startswith("openai/") else env.get("EDP_PI_MODEL", "openai/gpt-6-astra")
        argv = build_argv_pi(self._agent_home)
        assert not any(env.get("EDP8_TOKEN") and env["EDP8_TOKEN"] in a for a in argv), "token on argv"
        log_path = None
        stdout = subprocess.DEVNULL
        if self._log_dir:
            Path(self._log_dir).mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
            log_path = Path(self._log_dir) / f"{safe}.log"
            stdout = open(log_path, "ab")
        proc = subprocess.Popen(argv, cwd=self._agent_home or os.getcwd(), env=env,
                                stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.STDOUT)
        self._launches[session_id] = _Launch(proc, log_path)

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
        rec = self._launches.get(session_id)
        if rec and rec.log_path and rec.log_path.exists():
            return rec.log_path.stat().st_mtime
        return None

    # -- optional hooks service.py probes with getattr ------------------------
    def exit_code(self, session_id):
        rec = self._launches.get(session_id)
        return rec.proc.poll() if rec else None

    def close_viewport(self, session_id):
        return None

    def viewport_died(self, session_id) -> bool:
        return False

    def session_token(self, session_id):
        """Pi resumes from the seat's own session file (`<log_dir>/pi-sessions/<handle>.jsonl`),
        selected by EDP_PI_RESUME=1 on relaunch — no token to hand back."""
        return None
