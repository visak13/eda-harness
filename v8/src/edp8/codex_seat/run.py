"""`python -m edp8.codex_seat.run` — the resident Astra seat process the pool spawns (s-10a2b1f9ec).

Env contract = pi_seat.run's (EDP_ROLE, EDP_HANDLE, EDP_SPAWN_SESSION_ID, EDP8_TOKEN, EDP_AGENT_HOME,
EDP_LOG_DIR) plus:
  EDP_CODEX_BIN       codex executable (default: `codex` on PATH)
  EDP_CODEX_MODEL     default gpt-6-astra
  EDP_CODEX_EFFORT    optional reasoning effort (low|medium|high)
  EDP_CODEX_SANDBOX   optional override of the per-role sandbox (seat.ROLE_SANDBOX)
  EDP_ACTIVATION      explicit first prompt (park/resume path); default = the role card
  EDP_CODEX_RESUME    "1" → thread/resume the thread recorded in <log_dir>/codex-sessions/<handle>.json
  EDP_CODEX_CONSOLE   "1" → a visible seat: the conversation is echoed to this console and every line
                      typed into it becomes a user turn (pool mode "monitor", owner steer m-0259072d19)
Boot = the role card as the first user turn; whoami → subscribe → Monitor → CronCreate → context are
the card's own steps, run by the model. The agent home's CLAUDE.md (a Claude seat's standing context)
is the thread's developer instructions when no AGENTS.md exists, so both harnesses read the same rules.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
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


class Console:
    """Echo of the conversation for a visible seat + typed lines as user turns."""

    def __init__(self, seat: CodexSeat):
        self.seat = seat

    def on_event(self, method: str, p: dict) -> None:
        item = p.get("item") or {}
        t = item.get("type")
        stamp = time.strftime("%H:%M:%S")
        if method == "item/completed" and t == "agentMessage":
            print(f"\n{stamp} astra> {item.get('text', '')}", flush=True)
        elif method == "item/completed" and t == "userMessage":
            text = " ".join(c.get("text", "") for c in item.get("content") or [])
            print(f"\n{stamp} input> {text[:400]}{'…' if len(text) > 400 else ''}", flush=True)
        elif method == "item/started" and t in ("commandExecution", "mcpToolCall", "dynamicToolCall", "fileChange"):
            what = item.get("command") or f"{item.get('server', '')}/{item.get('tool', '')}".strip("/")
            print(f"{stamp}   · {t}: {str(what)[:160]}", flush=True)
        elif method == "turn/completed" and (p.get("turn") or {}).get("error"):
            print(f"{stamp} turn error: {p['turn']['error'].get('message')}", flush=True)

    def read_stdin(self) -> None:
        for line in sys.stdin:
            line = line.rstrip("\r\n")
            if line.strip():
                self.seat.enqueue_turn(line)


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

    console: Console | None = None
    seat = CodexSeat(cwd=agent_home, role=role, handle=handle, log_dir=log_dir,
                     developer_instructions=standing_context(agent_home),
                     on_event=lambda m, p: console.on_event(m, p) if console else None)
    if console_mode:
        console = Console(seat)
        if os.name == "nt":
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
    signal.signal(signal.SIGINT, _stop)

    activation = env.get("EDP_ACTIVATION") or (resume_prompt(handle) if resume else role_card(agent_home, role))
    seat.enqueue_turn(activation)
    if console:
        threading.Thread(target=console.read_stdin, name="console-input", daemon=True).start()
    seat.wait()
    code = seat.server.exit_code if seat.server else 1
    print(f"{time.strftime('%H:%M:%S')} app-server exited {code}", flush=True)
    seat.tools.shutdown()
    return code or 0


if __name__ == "__main__":
    raise SystemExit(main())
