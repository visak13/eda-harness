"""`python -m edp8.codex_seat.run` — the resident Astra seat process the pool spawns (s-10a2b1f9ec).

Env contract = pi_seat.run's (EDP_ROLE, EDP_HANDLE, EDP_SPAWN_SESSION_ID, EDP8_TOKEN, EDP_AGENT_HOME,
EDP_LOG_DIR) plus:
  EDP_CODEX_BIN       codex executable (default: `codex` on PATH)
  EDP_CODEX_MODEL     default gpt-6-astra
  EDP_CODEX_EFFORT    optional reasoning effort (low|medium|high)
  EDP_CODEX_SANDBOX   optional override of the per-role sandbox (seat.ROLE_SANDBOX)
  EDP_ACTIVATION      explicit first prompt (park/resume path); default = the role card
  EDP_CODEX_RESUME    "1" → thread/resume the thread recorded in <log_dir>/codex-sessions/<handle>.json
  EDP_CODEX_CONSOLE   "1" → a visible seat (pool mode "monitor"): the NATIVE codex TUI joins this seat's
                      thread and owns the console, exactly as `claude` does for a Claude seat (owner
                      rulings m-0259072d19, m-0e7b8fdd7f); the runner keeps the wake plane behind it
Boot = the role card as the first user turn; whoami → subscribe → Monitor → CronCreate → context are
the card's own steps, run by the model. The agent home's CLAUDE.md (a Claude seat's standing context)
is the thread's developer instructions when no AGENTS.md exists, so both harnesses read the same rules.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from .jobobj import bind_to_kill_job
from .seat import CodexSeat


def role_card(agent_home: Path, role: str) -> str:
    p = agent_home / ".claude" / "commands" / f"{role}.md"
    return p.read_text(encoding="utf-8") if p.is_file() else f"/{role}"


def standing_context(agent_home: Path) -> str | None:
    """CLAUDE.md for codex when the home has no AGENTS.md (codex reads AGENTS.md itself)."""
    if (agent_home / "AGENTS.md").is_file():
        return None
    p = agent_home / "CLAUDE.md"
    return p.read_text(encoding="utf-8") if p.is_file() else None


def resume_prompt(handle: str) -> str:
    return (f"You were resumed: this seat ({handle}) restarted and its Monitor watches and cron jobs are gone "
            "(they are session-only). Call resume_self() first and follow its steps.")


def main(argv: list[str] | None = None) -> int:
    env = os.environ
    role = env.get("EDP_ROLE", "owner")
    handle = env.get("EDP_HANDLE", f"{role}.codex")
    agent_home = Path(env.get("EDP_AGENT_HOME") or os.getcwd()).resolve()
    log_dir = Path(env.get("EDP_LOG_DIR") or (agent_home / ".logs"))
    console_mode = env.get("EDP_CODEX_CONSOLE") == "1"
    state = log_dir / "codex-sessions" / f"{handle}.json"
    # an explicit resume is honoured or refused, never downgraded to a fresh thread: a missing state
    # file makes seat.start(resume=True) raise below (qa adversary #9)
    resume = env.get("EDP_CODEX_RESUME") == "1"
    if not resume and state.is_file():
        # a fresh boot must not continue the previous (closed) thread (memory: pi-respawn-continues-closed-session)
        stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
        os.replace(state, state.with_name(f"{handle}.{stamp}.{os.getpid()}.{time.time_ns() % 10**9}.json"))
    # resume=True with a missing state file or one without a valid threadId makes seat.start() raise
    # (never a silent fresh thread under a "You were resumed" activation); the pool sees the exit
    # every child (app-server, Monitor commands) is born into a kill-on-close job: a runner-only crash
    # takes them down with it (qa adversary #5)
    jobbed = bind_to_kill_job()
    if os.name == "nt" and not jobbed:  # fail-closed: a runner-only crash would orphan its children
        print(f"{time.strftime('%H:%M:%S')} codex seat {handle} refused to start: "
              "could not bind the kill-on-close job object", flush=True)
        return 2

    # monitor mode: the app-server listens on an authenticated loopback websocket (the runner and the TUI
    # are its two clients); its own console output stays off the seat's console
    seat = CodexSeat(cwd=agent_home, role=role, handle=handle, log_dir=log_dir, ws=console_mode,
                     developer_instructions=standing_context(agent_home),
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if console_mode else 0)
    if console_mode and os.name == "nt":
        os.system(f"title {handle} (codex seat)")
    try:
        seat.start(resume=resume)  # fail-closed: uncontained MCP set or invalid resume state raise here
    except Exception as e:  # noqa: BLE001
        print(f"{time.strftime('%H:%M:%S')} codex seat {handle} refused to start: {e}", flush=True)
        seat.tools.shutdown()
        return 2
    print(f"codex seat {handle} role={role} pid={seat.pid} thread={seat.thread_id} resume={resume} kill_job={jobbed} "
          f"disabled_mcp={','.join(seat.disabled_servers)}", flush=True)
    print(f"live mcp servers: {seat.live_servers}", flush=True)  # verified ⊆ {edp8} before the first turn

    def _stop(*_a):
        seat.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    # monitor mode: Ctrl-C belongs to the TUI (it interrupts the model's turn there), never to the runner
    signal.signal(signal.SIGINT, signal.SIG_IGN if console_mode else _stop)

    activation = env.get("EDP_ACTIVATION") or (resume_prompt(handle) if resume else role_card(agent_home, role))
    seat.enqueue_turn(activation)
    if console_mode:
        return run_tui(seat, handle)
    seat.wait()
    code = seat.server.exit_code if seat.server else 1
    print(f"{time.strftime('%H:%M:%S')} app-server exited {code}", flush=True)
    seat.tools.shutdown()
    return code or 0


def run_tui(seat: CodexSeat, handle: str, materialize_s: float = 120.0) -> int:
    """Monitor mode (owner ruling m-0e7b8fdd7f): the native codex TUI, joined to the seat's thread, owns
    this console; the runner prints nothing after its boot banner. `codex resume <thread>` needs the
    thread's rollout, which exists once the first input has landed, so the TUI starts after that witness
    (and never without it: the seat stops instead).
    The seat lives as long as the TUI: quitting it (or closing the window) ends the seat, and the job
    object takes the app-server and every Monitor child with it."""
    end = time.time() + materialize_s
    while time.time() < end and seat.alive() and not seat.delivery.seen_any():
        time.sleep(0.2)
    if not seat.alive():
        print(f"{time.strftime('%H:%M:%S')} app-server exited {seat.server.exit_code if seat.server else '?'} "
              "before the TUI could join", flush=True)
        seat.tools.shutdown()
        return 1
    if not seat.delivery.seen_any():  # no rollout yet: `codex resume` could not join (second opinion #3)
        print(f"{time.strftime('%H:%M:%S')} codex seat {handle}: the first turn never landed in {materialize_s:.0f} s; "
              "stopping without a TUI", flush=True)
        seat.stop()
        seat.tools.shutdown()
        return 1
    tui = subprocess.Popen(seat.tui_argv(), cwd=seat.cwd, env=seat.tui_env())
    code: int | None = None
    while code is None:
        code = tui.poll()
        if code is None and not seat.alive():  # the thread is gone: nothing left for the TUI to show
            tui.terminate()
            code = tui.wait()
        time.sleep(0.2)
    seat.stop()
    print(f"{time.strftime('%H:%M:%S')} codex seat {handle}: TUI exited {code}", flush=True)
    return code or 0


if __name__ == "__main__":
    raise SystemExit(main())
