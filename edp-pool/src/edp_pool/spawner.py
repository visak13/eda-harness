"""Spawner seam (HLD §2).

- `FakeSpawner` — in-memory; tests + this component's automated S4.
- `SubprocessSpawner` — real claude shell via the ported PTY launcher
  (`pty_launcher`). This is the manual-HITL surface (#9): it produces a
  real interactive claude process, judgeable only by a human.
"""

import logging
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

SpawnMode = str  # "headless" (drained ConPTY) | "monitor" (visible console)


class Spawner(ABC):
    @abstractmethod
    def launch(
        self,
        session_id: str,
        role: str,
        handle: str,
        mode: SpawnMode = "headless",
        claude_session: str | None = None,
        resume_session: str | None = None,
        model: str | None = None,
        activation: str | None = None,
    ) -> None:
        """`activation` (DESIGN-v7 1.5.4): the one line typed into the ready
        shell. None (the default, every normal spawn) means the role's slash
        activator (`pty_launcher.activation_text`). The park/resume path
        passes an explicit line instead — a resumed shell must NOT re-run its
        role activator (its transcript already holds the activated persona);
        it must reground and continue."""
        ...

    @abstractmethod
    def alive(self, session_id: str) -> bool: ...

    @abstractmethod
    def kill(self, session_id: str) -> None: ...

    @abstractmethod
    def knows(self, session_id: str) -> bool:
        """Is `session_id` something THIS spawner instance launched
        (i.e. has an in-memory record for)? Distinguishes 'I launched
        it and observed it die' from 'I have no record of it' — the
        latter happens after a pool restart, since launches aren't
        persisted across processes. Truthful answer: 'unknown', not
        'dead'. Without this, the recipe-FSM liveness sweep mass-
        reincarnates every previously-spawned shell on pool restart."""
        ...

    def pid(self, session_id: str) -> int | None:
        """OS pid of a launched session's process, or None if unknown.
        The pool persists this (with create_time) as a fingerprint so it
        can RE-ESTABLISH liveness for sessions re-loaded after a restart
        — instead of leaving every still-running shell permanently
        'unknown' (the 2026-05-31 restart-blackout bug). Default None;
        SubprocessSpawner overrides with the real pid."""
        return None

    def last_output_ts(self, session_id: str) -> float | None:
        """W7 busyness signal: epoch mtime of the session's PTY-drain log
        — the file the ConPTY drain thread appends every output chunk to
        (`<log_dir>/<safe(session_id)>.log`). A recently-grown log means
        'alive AND busy' even inside a 20-40 min reasoning block that
        writes nothing to the event-driven worklog, so a heads-down shell
        becomes visible. None when there is no drain log (monitor mode /
        no log_dir) or the launch is not known to this instance (e.g. a
        session re-loaded after a pool restart — the mtime is genuinely
        unknown, mirroring liveness()'s conservatism). Default None;
        SubprocessSpawner overrides with the real mtime."""
        return None


class FakeSpawner(Spawner):
    """A launched session is 'alive' until killed. Lets the pool LOGIC
    (locks, capacity, liveness, alias) be fully unit-tested."""

    def __init__(self) -> None:
        self._alive: set[str] = set()
        # `_known` is the set of session_ids THIS instance has ever
        # launched — sticky across kill(), only empty for a brand-new
        # spawner (the pool-restart case). Mirrors SubprocessSpawner's
        # `_launches` dict (which also persists after termination).
        self._known: set[str] = set()
        self.launched: list[dict] = []  # observable by tests (phase 5)
        # W7: simulated PTY-drain-log mtime per session. The real
        # SubprocessSpawner reads a file's st_mtime; the fake lets a test
        # set the "output timestamp" directly via set_output_ts().
        self._output_ts: dict[str, float] = {}

    def launch(
        self, session_id: str, role: str, handle: str,
        mode: SpawnMode = "headless",
        claude_session: str | None = None,
        resume_session: str | None = None,
        model: str | None = None,
        activation: str | None = None,
    ) -> None:
        self._alive.add(session_id)
        self._known.add(session_id)
        self.launched.append({
            "session_id": session_id, "role": role, "handle": handle,
            "claude_session": claude_session,
            "resume_session": resume_session,
            # s17 FA3: per-spawn model tier (None → host default / Opus).
            "model": model,
            # DESIGN-v7 park/resume: custom activation line (None → the
            # role activator) — observable by park/resume tests.
            "activation": activation,
        })

    def alive(self, session_id: str) -> bool:
        return session_id in self._alive

    def kill(self, session_id: str) -> None:
        self._alive.discard(session_id)
        # `_known` deliberately retained — a session this instance
        # killed is "known dead", NOT "unknown".

    def knows(self, session_id: str) -> bool:
        return session_id in self._known

    def set_output_ts(self, session_id: str, ts: float) -> None:
        """Test helper: simulate a PTY-drain-log write at epoch `ts`, so
        last_output_ts(session_id) returns it (stands in for the real
        log file's st_mtime advancing on output)."""
        self._output_ts[session_id] = ts

    def last_output_ts(self, session_id: str) -> float | None:
        return self._output_ts.get(session_id)


def seat_model_for(role: str, agent_home: str | None) -> str | None:
    """v7 WS4/live-drill fix (2026-08-07): resolve the seat registry AT THE
    SPAWN SEAM — the single chokepoint every role passes through. The first
    drill ran planners/curiosity on the config-dir default model (Opus 5)
    because only SOME engine tools pass `model` down; now an explicit None
    is resolved from models.json here, so the registry binds EVERY spawned
    role. Absent registry / unmapped role → None (legacy host default)."""
    if not agent_home:
        return None
    try:
        from edp_contracts.seats import seat_for_role
        seat = seat_for_role(agent_home, role)
    except Exception:      # noqa: BLE001 — registry trouble never blocks spawn
        return None
    return seat.model if seat is not None else None


class SubprocessSpawner(Spawner):
    """Real claude-shell launch via the ported ConPTY mechanics
    (`pty_launcher`). Headless: no human proxy. The shell talks to the
    system through the edp-broker MCP tools driven by its `/agentic-plan`
    or `/worker` activator (env-driven), NOT via PTY-injected messages.
    """

    def __init__(
        self,
        broker_url: str | None = None,
        cwd: str | None = None,
        log_dir: Path | None = None,
        claude_bin: str | None = None,
        pool_url: str | None = None,
        shell_log_dir: str | None = None,
    ):
        self.broker_url = broker_url
        # cwd = the agent home (claude repo) so the spawned claude finds
        # .claude/commands/ (/worker, /agentic-plan) AND .mcp.json (the
        # edp-claude MCP tools). Falls back to EDP_AGENT_HOME env, then
        # the caller's cwd. main.py passes this EXPLICITLY (computed from
        # the pool's own location) so a clone never resolves to a stray
        # EDP_AGENT_HOME pointing at the wrong repo (the eda-base3 leak).
        self.cwd = cwd or os.environ.get("EDP_AGENT_HOME")
        self.log_dir = Path(log_dir) if log_dir else None
        self.claude_bin = claude_bin
        # 2026-05-28 stack-pinning: passed to every spawned shell's env so
        # it runs entirely on THIS pool's stack (same pool for
        # pool_close_self/liveness; same .logs), not inherited strays.
        self.pool_url = pool_url
        # the spawned shell's EDP_LOG_DIR (where its edp-claude tool log
        # lands) — the claude repo's .logs, NOT the pool's PTY-drain dir.
        self.shell_log_dir = shell_log_dir
        self._launches: dict[str, object] = {}  # session_id -> PtyLaunch

    def launch(
        self, session_id: str, role: str, handle: str,
        mode: SpawnMode = "headless",
        claude_session: str | None = None,
        resume_session: str | None = None,
        model: str | None = None,
        activation: str | None = None,
    ) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "SubprocessSpawner needs Windows (ConPTY / CREATE_NEW_"
                "CONSOLE). On other platforms use FakeSpawner / a future "
                "POSIX launcher."
            )
        from .pty_launcher import (
            activation_text,
            build_argv,
            build_env,
            build_session_args,
            ensure_claude_healthy,
            resolve_claude_bin,
        )

        # v7 live-drill fix: the seat registry binds EVERY role at this
        # seam (see seat_model_for above) — an unpassed model no longer
        # falls to the config-dir default.
        model = model or seat_model_for(role, self.cwd)
        bin_ = resolve_claude_bin(self.claude_bin)
        # W14: pre-spawn health gate at the single resolved-bin chokepoint —
        # covers BOTH the monitor (ConsoleLaunch) and headless (PtyLaunch)
        # routes. Self-repairs a stubbed claude binary or REFUSES the spawn
        # with a self-healing message (ClaudeInstallError) — never launches
        # a doomed shell, and the neuron never runs Bash repair.
        bin_ = ensure_claude_healthy(bin_)
        env = build_env(
            session_id, role, handle, self.broker_url,
            pool_url=self.pool_url,
            agent_home=self.cwd,
            log_dir=self.shell_log_dir,
        )
        # phase 5: snapshot/branch flags (pin id / resume+fork a base).
        sargs = build_session_args(claude_session, resume_session)

        # 2026-05-31: VISIBLE shells (operator watches the agents).
        # `monitor` → a real console window; `headless` → drained ConPTY.
        # skip-permissions: HEADLESS has no window to approve a prompt, so
        # it's required there; VISIBLE monitor lets the operator
        # click-approve, so it's OFF by default (opt into autonomy with
        # EDP_SKIP_PERMISSIONS=1). The guard hook blocks stack-kills in
        # either mode regardless.
        skip_perms = (mode != "monitor") or os.environ.get(
            "EDP_SKIP_PERMISSIONS", "0").lower() in ("1", "true", "yes")
        # DESIGN-v7 1.5.4: the activation seam — an explicit line (the
        # park/resume path) wins over the role activator.
        activation_line = activation or activation_text(role)
        if mode == "monitor":
            # Visible console: claude's native TUI in its own window. The
            # role activator rides argv as the initial prompt (claude
            # submits it when ready — not a PTY-keystroke race). No drain
            # log (the window is the output).
            from .console_launcher import ConsoleLaunch

            launch = ConsoleLaunch(
                argv=build_argv(bin_, extra=[*sargs, activation_line],
                                skip_permissions=skip_perms, model=model),
                env=env,
                cwd=self.cwd,
            )
            launch.spawn()
        else:
            # headless: ConPTY drained to a per-session log; readiness-
            # gated activation. session_id is "<role>:<uuid>"; ':' is
            # illegal in a Windows filename AND silently becomes an NTFS
            # alternate-data-stream — so sanitize. Log carries a UTF-8 BOM.
            from .pty_launcher import PtyLaunch

            safe = "".join(c if c.isalnum() or c in "-._" else "_"
                           for c in session_id)
            log_path = (
                self.log_dir / f"{safe}.log" if self.log_dir else None
            )
            launch = PtyLaunch(
                argv=build_argv(bin_, extra=sargs,
                                skip_permissions=skip_perms, model=model),
                env=env,
                cwd=self.cwd,
                log_path=log_path,
            )
            launch.spawn()
            # F36 R4#12 (2026-08-18): REGISTER the process the moment it
            # exists. Readiness/activation below can raise (e.g. a bad
            # EDP_SUBMIT_DELAY_MS), and an unregistered live process was a
            # true orphan — invisible to kill/alive/reap. Registered first,
            # a failed activation is terminated instead of leaked.
            self._launches[session_id] = launch
            try:
                self._activate_pty(launch, session_id, handle,
                                   activation_line, log_path)
            except BaseException:
                try:
                    launch.kill()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
                self._launches.pop(session_id, None)
                raise
            return

        self._launches[session_id] = launch

    def _activate_pty(self, launch, session_id: str, handle: str,
                      activation_line: str, log_path) -> None:
        if not launch.wait_ready():
            # DESIGN-v7 fix C (verified live): a ready-timeout used to be
            # SILENT — activation was typed into a shell that may never
            # have booted. Log the failure loudly, name the drain log,
            # and say whether the drain shows the Bypass Permissions
            # acceptance dialog (a FRESH config dir shows it before the
            # TUI; the pool deliberately does NOT auto-accept it — that
            # is the operator's one-time manual act). Then proceed
            # fail-open: the widened ready markers make a false timeout
            # rare, and killing a slow-but-healthy shell is worse.
            bypass = (" The drain log shows the Bypass Permissions "
                      "acceptance dialog — this CLAUDE_CONFIG_DIR needs "
                      "a one-time manual accept; the pool will not "
                      "auto-accept it."
                      if launch.bypass_dialog_seen else "")
            logging.getLogger(__name__).error(
                "ready-timeout for %s (%s): no ready marker within %ss; "
                "drain log: %s.%s Sending the activation anyway "
                "(fail-open).",
                session_id, handle, launch.ready_timeout,
                log_path, bypass,
            )
        launch.send_activation(activation_line)

    def alive(self, session_id: str) -> bool:
        lp = self._launches.get(session_id)
        return bool(lp and lp.is_alive())

    def kill(self, session_id: str) -> None:
        # 2026-05-26: do NOT pop the entry — keep it so `knows(sid)`
        # still returns True for sessions THIS instance launched-and-
        # killed. A killed session is "known dead", which the FSM
        # treats as crash-recovery-eligible; an UNKNOWN session is one
        # this spawner never saw (pool restart) and the FSM waits on
        # conservatively. Popping conflated the two.
        lp = self._launches.get(session_id)
        if lp is not None:
            lp.terminate()

    def knows(self, session_id: str) -> bool:
        # True iff THIS spawner instance launched it (in-memory). After
        # a pool restart this is empty even for sessions whose lock is
        # still in the on-disk pool state — the truthful answer about
        # those is "unknown", not "dead". See spawner.knows docstring.
        return session_id in self._launches

    def pid(self, session_id: str) -> int | None:
        lp = self._launches.get(session_id)
        return lp.pid if lp is not None else None

    def last_output_ts(self, session_id: str) -> float | None:
        # W7 busyness signal: mtime of the exact PTY-drain log this launch
        # writes to. Read the path straight off the launch object (the
        # single source of truth for where the drain thread appends) rather
        # than recomputing the safe-name — a monitor-mode ConsoleLaunch has
        # no log_path, so getattr(..., None) yields None there. None on a
        # missing file / unreadable stat / unknown session (post-restart).
        lp = self._launches.get(session_id)
        log_path = getattr(lp, "log_path", None)
        if log_path is None:
            return None
        try:
            return log_path.stat().st_mtime
        except OSError:
            return None
