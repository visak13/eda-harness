"""PI shell backend (epic-6a8a6020fd S2): a resident GPT-6 Astra seat under pi.dev's coding agent.

Mirrors opencode_launcher's shape (Spawner ABC + the optional hooks service.py probes with getattr),
minus opencode's one-shot/TUI machinery: a Pi seat is a RESIDENT process — the pool launches
`<agent_home>/.venv/Scripts/python.exe -m edp8.pi_seat.run`, which owns `pi --mode rpc` (JSONL on
stdio), boots the role card, and stays up; Monitor lines and cron fires re-wake the model inside
Pi (v8/.pi/extensions/edp8.ts), so "alive" == the runner process is running, exactly like a Claude
shell. Identity reaches the board by header (X-Participant/X-Session/X-Token) from env, as
`.mcp.json` does for Claude — never on argv.

Arming: EDP_PI_ROLES="reviewer,qa" routes those roles here (main.py); empty = zero behaviour change.

Modes (owner steer m-0259072d19, 2026-09-14: "ensure that the gpt shell opens like other shells and
isnt headless"): the default pool mode "monitor" opens Pi's INTERACTIVE TUI in its own console
window (CREATE_NEW_CONSOLE) with the extension loaded, the role card as the first message and the
seat's session file for resume — the owner watches and can type into it exactly like a Claude
shell. mode="headless" keeps the RPC runner (`edp8.pi_seat.run`) for the parity oracle and tests.
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
    """Headless runner argv (RPC mode under the agent home's python)."""
    return [seat_python(agent_home), "-m", "edp8.pi_seat.run"]


def pi_bin_argv() -> list[str]:
    """argv prefix for Pi itself: EDP_PI_BIN (a cli.js → under node, or an exe), else `pi` on PATH."""
    cand = os.environ.get("EDP_PI_BIN", "").strip()
    if cand.lower().endswith(".js"):
        return ["node", cand]
    if cand:
        return [cand]
    # durable default: <edp-pool>/.pi-harness (package.json + lockfile committed, node_modules ignored)
    harness = Path(os.environ.get("EDP_PI_HARNESS", "").strip() or Path(__file__).resolve().parents[2] / ".pi-harness")
    cli = harness / "node_modules" / "@earendil-works" / "pi-coding-agent" / "dist" / "cli.js"
    if cli.is_file():
        return ["node", str(cli)]
    return ["pi"]


def build_argv_pi_tui(agent_home: str | None, role: str, handle: str, *, model: str | None,
                      session_file: str, first_message: str | None, thinking: str | None = None) -> list[str]:
    """Interactive Pi in a visible console: extension + session file + the role card (or the
    activation text) as the first message. Mirrors what the RPC runner does, on the TUI."""
    home = Path(agent_home or os.getcwd())
    argv = [*pi_bin_argv(), "--approve", "-e", str(home / ".pi" / "extensions" / "edp8.ts"),
            "--session", session_file, "--name", handle]
    if model:
        argv += ["--model", model]
    if thinking:
        argv += ["--thinking", thinking]
    if first_message:
        argv += ["--", first_message]
    return argv


def openai_seat_for(role: str, agent_home: str | None):
    """The `roles_openai` column of models.json (an OPTION next to the Claude `roles` column,
    owner m-e6ef892737): the Pi seat's model + thinking for `role`. None → launcher defaults."""
    if not agent_home:
        return None
    try:
        from edp_contracts.seats import seat_for_role
        return seat_for_role(agent_home, role, column="roles_openai")
    except Exception:  # noqa: BLE001 — registry trouble never blocks spawn
        return None


def role_card_text(agent_home: str | None, role: str) -> str:
    p = Path(agent_home or os.getcwd()) / ".claude" / "commands" / f"{role}.md"
    return p.read_text(encoding="utf-8") if p.is_file() else f"/{role}"


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
    env.setdefault("EDP_PI_MODEL", "openai-codex/gpt-6-astra")  # the authenticated route (Codex login); openai/… with a key
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
        seat = openai_seat_for(role, self._agent_home)
        if seat is not None and not os.environ.get("EDP_PI_MODEL"):
            env["EDP_PI_MODEL"] = seat.model
            if seat.thinking and not os.environ.get("EDP_PI_THINKING"):
                env["EDP_PI_THINKING"] = seat.thinking
        if model and model.startswith(("openai/", "openai-codex/")):  # explicit per-spawn override wins
            env["EDP_PI_MODEL"] = model
        log_path = None
        if self._log_dir:
            Path(self._log_dir).mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in session_id)
            log_path = Path(self._log_dir) / f"{safe}.log"
        if mode == "headless":
            argv = build_argv_pi(self._agent_home)
            assert not any(env.get("EDP8_TOKEN") and env["EDP8_TOKEN"] in a for a in argv), "token on argv"
            stdout = open(log_path, "ab") if log_path else subprocess.DEVNULL
            proc = subprocess.Popen(argv, cwd=self._agent_home or os.getcwd(), env=env,
                                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=subprocess.STDOUT)
        else:
            # visible seat: Pi's own TUI in a new console (like a Claude shell). The session file is
            # the same one the headless runner would use, so park/resume works across both modes.
            sess_dir = Path(self._log_dir or self._agent_home or os.getcwd()) / "pi-sessions"
            sess_dir.mkdir(parents=True, exist_ok=True)
            session_file = str(sess_dir / f"{handle}.jsonl")
            first = activation or (None if (resume_session and Path(session_file).is_file())
                                   else role_card_text(self._agent_home, role))
            argv = build_argv_pi_tui(self._agent_home, role, handle, model=env.get("EDP_PI_MODEL"),
                                     session_file=session_file, first_message=first,
                                     thinking=env.get("EDP_PI_THINKING") or None)
            assert not any(env.get("EDP8_TOKEN") and env["EDP8_TOKEN"] in a for a in argv), "token on argv"
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            proc = subprocess.Popen(argv, cwd=self._agent_home or os.getcwd(), env=env, creationflags=flags)
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
