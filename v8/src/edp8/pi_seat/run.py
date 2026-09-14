"""`python -m edp8.pi_seat.run` — the resident Astra seat process the pool spawns (design §6 fleet wiring).

Reads the pool's env contract (EDP_ROLE, EDP_HANDLE, EDP_SPAWN_SESSION_ID, EDP8_TOKEN, EDP_AGENT_HOME,
EDP_LOG_DIR) plus:
  EDP_PI_BIN        <pi-coding-agent>/dist/cli.js (run under node) or a pi executable
  EDP_PI_MODEL      default openai-codex/gpt-6-astra (Codex-subscription login; openai/gpt-6-astra with OPENAI_API_KEY)
  EDP_PI_THINKING   optional thinking level
  EDP_ACTIVATION    explicit first prompt (park/resume path); default = the role card `.claude/commands/<role>.md`
  EDP_PI_RESUME     "1" → resume the seat's session file instead of starting fresh
Boot = the role card as the first user prompt (whoami → subscribe → Monitor → CronCreate → context are the
card's own steps, executed by the model through the bridged tools). Then the process stays resident: Pi
wakes itself from Monitor lines and cron fires (extension), this runner only mirrors events and dies with Pi.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path

from .driver import PiSeat


def role_card(agent_home: Path, role: str) -> str:
    p = agent_home / ".claude" / "commands" / f"{role}.md"
    if not p.is_file():
        return f"/{role}"
    return p.read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    env = os.environ
    role = env.get("EDP_ROLE", "owner")
    handle = env.get("EDP_HANDLE", f"{role}.pi")
    agent_home = Path(env.get("EDP_AGENT_HOME") or os.getcwd()).resolve()
    log_dir = Path(env.get("EDP_LOG_DIR") or (agent_home / ".logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    session_dir = log_dir / "pi-sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_file = session_dir / f"{handle}.jsonl"
    resume = env.get("EDP_PI_RESUME") == "1" and session_file.is_file()

    seat = PiSeat(
        cwd=agent_home,
        model=env.get("EDP_PI_MODEL", "openai-codex/gpt-6-astra"),
        extension=str(agent_home / ".pi" / "extensions" / "edp8.ts"),
        session_file=str(session_file),
        log_dir=log_dir,
        handle=handle,
        thinking=env.get("EDP_PI_THINKING") or None,
    )
    seat.start()
    print(f"pi seat {handle} role={role} pid={seat.pid} resume={resume}", flush=True)

    def _stop(*_a):
        seat.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    activation = env.get("EDP_ACTIVATION") or (None if resume else role_card(agent_home, role))
    if activation:
        seat.prompt(activation)
    # resident: mirror events until Pi exits. `events()` returns at agent_settled — loop again; the
    # extension re-wakes Pi on its own (Monitor line / cron), this loop just keeps the process alive.
    while seat.alive():
        for ev in seat.events(timeout=60, until="process_exit"):
            t = ev.get("type")
            if t in ("agent_settled", "process_exit", "extension_error"):
                print(f"{time.strftime('%H:%M:%S')} {t} {ev.get('code', '')}".rstrip(), flush=True)
    return seat.exit_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
