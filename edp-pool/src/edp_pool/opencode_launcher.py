"""OPENCODE shell backend (PORT-OPENCODE M1).

The one-shot turn model: `opencode run <message> --agent edp-<role>` reads its
activation from ARGV, executes ONE turn against the same edp-claude MCP server
(EDP_* injected via process env — M0 probe 1 verified inheritance into MCP
stdio children), and EXITS at turn end. No ConPTY, no readiness markers, no
keystroke activation, no npm self-repair — that entire pty_launcher subsystem
does not apply here.

Session identity (M0 probes 2-3): opencode REFUSES caller-minted session ids,
so the pool's `claude_session` pin is ignored on launch; instead the generated
id is CAPTURED from the fleet store's sqlite `session` table by the unique
`--title` this launcher stamps (`edp-<pool-session-id>`). The fleet store is
isolated via XDG_DATA_HOME (auth.json must be seeded into it once — M0 probe
4/5) so fleet sessions never pollute the operator's own opencode store.

Roles map to `.opencode/agents/edp-*.md` wrappers in the fleet workspace,
which point at the SAME `.claude/commands/*.md` guides Claude shells load —
files win; no re-authored protocols.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path

from .pty_launcher import build_env

#: pool role -> opencode agent name (mirrors _ROLE_ACTIVATOR's role set).
ROLE_AGENTS = {
    "worker": "edp-worker",
    "planner": "edp-agentic-plan",
    "reviewer": "edp-reviewer",
    "specialist": "edp-specialist",
    "consult": "edp-consult",
    "curiosity": "edp-curiosity",
    "goal_keeper": "edp-goal-keeper",
    "pattern_observer": "edp-pattern-observer",
    "neuron": "edp-neuron",
}

#: default kickoff when the pool passes activation=None. The agent wrapper
#: already carries the role protocol pointer; this line just starts the turn
#: (the Claude analog is typing the role's slash command).
DEFAULT_ACTIVATION = (
    "Begin your role turn now: follow your role protocol file IN FULL, "
    "starting with check_inbox / your Step 1."
)


def resolve_opencode_bin() -> str:
    """EDP_OPENCODE_BIN override, else PATH. No self-repair machinery —
    opencode is a single binary without claude's npm-stub failure mode."""
    override = os.environ.get("EDP_OPENCODE_BIN", "").strip()
    if override:
        return override
    found = shutil.which("opencode")
    if not found:
        raise FileNotFoundError(
            "opencode not found on PATH and EDP_OPENCODE_BIN unset")
    # NEVER launch the npm .CMD/.ps1 shim: the cmd->node->exe double-hop
    # breaks opencode's internal server bootstrap under a python parent
    # ("Unexpected server error", M1 bisect 2026-07-18). Resolve the real
    # platform binary that the shim wraps.
    p = Path(found)
    if p.suffix.lower() in (".cmd", ".ps1", ".bat", ""):
        for exe in sorted(p.parent.glob(
                "node_modules/opencode-ai/node_modules/"
                "opencode-windows-*/bin/opencode.exe")):
            return str(exe)
    return found


def monitor_roles() -> set[str]:
    """Roles whose opencode shells open a VISIBLE console (operator ruling
    2026-07-19: "whats the point of me testing if I cant see what
    happens"). Default mirrors the claude harness's visible seats (consult
    converses, the SME trains, curiosity interrogates) — set
    EDP_OPENCODE_MONITOR_ROLES="*" to watch EVERY role, or "" for none."""
    raw = os.environ.get("EDP_OPENCODE_MONITOR_ROLES",
                         "consult,curiosity,specialist")
    if raw.strip() == "*":
        return set(ROLE_AGENTS)
    return {r.strip() for r in raw.split(",") if r.strip()}


def fleet_workspace() -> str:
    # default: <repo root>/opencode-fleet, derived from this package's location
    # so a clone anywhere (or a rename of the repo folder) keeps working
    return os.environ.get(
        "EDP_OPENCODE_WORKSPACE",
        str(Path(__file__).resolve().parents[3] / "opencode-fleet"))


def fleet_data_home() -> str:
    """XDG_DATA_HOME for the fleet store (…/opencode/{opencode.db,auth.json})."""
    return os.environ.get(
        "EDP_OPENCODE_DATA", str(Path(fleet_workspace()) / ".fleet-data"))


def map_model(model: str | None) -> str | None:
    """MODEL_TIERS translation (1:1 parity, 2026-07-19): the engine's tier
    formula is UNCHANGED — this only translates the tier it already chose
    into the gpt-5.6 family. None/host-default → None (the role wrapper's
    pinned model rules, the exact analog of a Claude shell's host default);
    the Sonnet tier → terra; a Haiku-class tier → luna (reserved — no
    current MODEL_TIERS row uses it); an explicit Opus ask → sol. Env
    overrides re-point without a code edit, mirroring
    EDP_WORKER_SONNET_MODEL."""
    if not model:
        return None
    m = model.lower()
    if "sonnet" in m:
        return os.environ.get("EDP_OPENCODE_MODEL_SONNET",
                              "openai/gpt-5.6-terra")
    if "haiku" in m:
        return os.environ.get("EDP_OPENCODE_MODEL_HAIKU",
                              "openai/gpt-5.6-luna")
    if "opus" in m:
        # The Opus tier is the DEFAULT tier — the role wrapper's pinned
        # model IS the operator's per-role ruling (planner=terra,
        # judgment=sol), so defer to it (None) unless explicitly
        # re-pointed. Mapping it to sol here overrode the planner wrapper
        # (observed live 2026-07-20: planner ran sol, ruling says terra).
        return os.environ.get("EDP_OPENCODE_MODEL_OPUS") or None
    if m.startswith("openai/"):
        return model            # already family-native (explicit caller)
    return None                 # unknown tier: wrapper default, never guess


def build_argv_opencode(role: str, message: str, *,
                        title: str,
                        resume_session: str | None = None,
                        effort: str = "medium",
                        model: str | None = None) -> list[str]:
    """The full one-shot argv. Message rides ARGV (the codex-exec precedent);
    `--variant` pins effort per spawn; `--session + --continue` resumes an
    existing captured session (M2 path) — never a caller-minted id (M0)."""
    agent = ROLE_AGENTS.get(role, f"edp-{role}")
    # --auto: unattended runs auto-approve non-denied permissions.
    # --dir: opencode resolves its PROJECT from the PWD env var, not the
    # process cwd — under a python parent PWD is stale, the fleet project
    # (and its agents) is never found, and the unknown agent dies as an
    # opaque "UnknownError" (M1 root cause, 2026-07-18). Pin it explicitly.
    # --print-logs WARN is DIAGNOSTIC-LOAD-BEARING (2026-07-20): without
    # it, provider failures (stream errors, API errors, throttles) are
    # retried SILENTLY and a starved fleet is indistinguishable from a
    # thinking one — three multi-hour "stuck harness" incidents traced to
    # exactly this. With it, every shell's log names the provider error.
    argv = [resolve_opencode_bin(), "run", message,
            "--agent", agent, "--variant", effort, "--title", title,
            "--auto", "--print-logs", "--log-level", "WARN",
            "--dir", fleet_workspace()]
    mapped = map_model(model)
    if mapped:
        argv += ["--model", mapped]
    if resume_session:
        argv += ["--session", resume_session, "--continue"]
    return argv


def build_env_opencode(session_id: str, role: str, handle: str,
                       broker_url: str | None, **kw) -> dict:
    """The pool's env contract (EDP_ROLE/HANDLE/stack pins) verbatim via
    pty_launcher.build_env, minus claude-only keys, plus the fleet-store pin."""
    env = build_env(session_id, role, handle, broker_url, **kw)
    for k in ("CLAUDE_CONFIG_DIR", "DISABLE_AUTOUPDATER"):
        env.pop(k, None)
    # build_env stamps EDP_HARNESS=claude (it is the claude spawner's path);
    # correct it here. This is what re-enables the park hint for opencode
    # planners — a park keeps the TUI window and the resume forks back into
    # it, so parking is cheap here and expensive on claude.
    env["EDP_HARNESS"] = "opencode"
    # PYTHON-PARENT POISONING (M1 bisect, 2026-07-18): the pool itself runs
    # under edp-pool's uv venv; inherited VIRTUAL_ENV/UV_*/PYTHONPATH make the
    # `uv run` that opencode uses to spawn the edp-claude MCP server resolve
    # the WRONG project env -> MCP child dies -> opencode reports an opaque
    # "Unexpected server error". Strip every python-env selector.
    for k in list(env):
        if k in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME") or k.startswith("UV_"):
            env.pop(k, None)
    env["XDG_DATA_HOME"] = fleet_data_home()
    # PWD belt-and-suspenders with --dir (see build_argv_opencode): shells
    # maintain PWD; python parents leave it stale and opencode trusts it.
    env["PWD"] = fleet_workspace()
    return env


def capture_session_id(title: str, *, retries: int = 10,
                       delay: float = 0.5) -> str | None:
    """The opencode-generated session id for a launch, found by its unique
    title in the fleet store (M0 probe 3: sqlite `session` table). Retries
    briefly — the row appears as soon as the run bootstraps."""
    db_path = Path(fleet_data_home()) / "opencode" / "opencode.db"
    for _ in range(retries):
        if db_path.exists():
            try:
                con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                row = con.execute(
                    "SELECT id FROM session WHERE title=? "
                    "ORDER BY time_created DESC LIMIT 1", (title,)).fetchone()
                con.close()
                if row:
                    return row[0]
            except sqlite3.Error:
                pass
        time.sleep(delay)
    return None


class _Launch:
    __slots__ = ("proc", "log_path", "opencode_session", "started",
                 "tui_proc", "url", "window_dismissed")

    def __init__(self, proc, log_path, tui_proc=None, url=None):
        self.proc = proc                 # the current TURN client
        self.log_path = log_path
        self.opencode_session: str | None = None
        self.started = time.time()
        self.tui_proc = tui_proc         # persistent TUI window (cmd tree)
        self.url = url                   # the shell's own server url
        # operator closed the window -> STAYS closed for this shell
        # (2026-07-20: reopening on every turn was whack-a-mole).
        self.window_dismissed = False


def _free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _port_up(url: str, timeout: float = 20.0) -> bool:
    import socket
    import urllib.parse
    port = urllib.parse.urlparse(url).port
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), 1):
                return True
        except OSError:
            time.sleep(0.4)
    return False


class OpencodeSpawner:
    """Spawner-ABC-compatible backend for opencode one-shot shells.

    Deliberate semantic: a finished turn (process exited) reports NOT alive —
    the pool's existing model treats that as terminal for workers (exit ==
    done, like arm_close_when_idle) and as parked-awaiting-resume for
    planners (M2: ResumeWatchdog re-launches with resume_session)."""

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
               activation=None) -> None:
        title = f"edp-{session_id}"
        # Identity IN the activation (2026-07-20): a worker probed env
        # with bash syntax in the PowerShell tool ($EDP_ROLE = always
        # empty), concluded "no brief", and refused real work. The pool
        # KNOWS role+handle — state them; env stays as the backup.
        message = activation or (
            f"Your identity: role={role}, handle={handle} "
            f"(also in $env:EDP_ROLE / $env:EDP_HANDLE — PowerShell "
            f"syntax; a bare $EDP_ROLE is always empty and proves "
            f"nothing). {DEFAULT_ACTIVATION}")
        argv = build_argv_opencode(role, message, title=title,
                                   resume_session=resume_session,
                                   model=model)
        env = build_env_opencode(session_id, role, handle, self._broker_url,
                                 pool_url=self._pool_url,
                                 agent_home=self._agent_home,
                                 log_dir=self._log_dir)
        # MONITOR MODE = A REAL TUI WINDOW ON THE SHELL'S SESSION
        # (operator ruling 2026-07-19: "these external shells are opening
        # as a chat in cmd instead of in tui like my main app" + "opens as
        # a default shell... nothing inside it"). The window is the ROOT
        # opencode TUI launched with --session <this shell's session> and
        # --port <its own server>, in the SHELL'S env (per-shell env is
        # LOAD-BEARING: a shared server would collapse every shell's
        # EDP_ROLE/EDP_HANDLE into one). It opens directly ON the
        # transcript — no picker, no home screen. Later turns are fired
        # with --attach into ITS port, so park/resume rounds render live
        # in the same open window. The window is the operator's viewport:
        # kill() never touches it; if they close it, the next turn simply
        # reopens one. Turn 1 executes headless first (the session id
        # must exist before a TUI can open on it) — its transcript is on
        # screen seconds later.
        monitor = (mode == "monitor" or role in monitor_roles()) \
            and os.name == "nt"
        prev = self._launches.get(session_id)
        tui_proc, url = (prev.tui_proc, prev.url) if prev else (None, None)
        # window_dismissed is set ONLY by the pool's own close_viewport.
        # An operator-closed window is NOT a dismissal — it is a KILL
        # (viewport_died → the watchdog's crash sweep ends this shell and
        # crash recovery spawns a REPLACEMENT, which gets a fresh window).
        dismissed = bool(prev and prev.window_dismissed)
        tui_live = (tui_proc is not None and tui_proc.poll() is None
                    and url and _port_up(url, timeout=3))
        if monitor and dismissed:
            monitor = False
        if monitor and not tui_live:
            # LIVE-FROM-TURN-ONE (2026-07-20, operator: "I cant see it
            # live"): the window server starts FIRST (root TUI serving on
            # its own port, shell's env — per-shell identity is
            # load-bearing), and the turn below executes ON it via
            # --attach, so the TUI's own SSE bus renders every token as
            # it happens. The reconciler thread snaps the window onto the
            # session the moment it exists (~1s in) and re-snaps if a
            # later fallback mints a new session. The window is also the
            # OPERATOR'S UNBLOCK LEVER: a full TUI on the live session —
            # type into it to drive a stuck shell by hand. Server boot
            # failure degrades to headless, loudly, never blocks a spawn.
            port = _free_port()
            url = f"http://127.0.0.1:{port}"
            # shell_tui.cmd = background `serve` + foreground ATTACH TUI in
            # one console. ATTACH is load-bearing: a root TUI (workspace
            # defined) IGNORES tui.session.select on v1.18.3 (handler gates
            # on workspace equality; the event carries none) — an attach
            # client obeys it. Source + live event-bus verified 2026-07-20.
            tui_proc = subprocess.Popen(
                ["cmd", "/k",
                 str(Path(fleet_workspace()) / "shell_tui.cmd"),
                 resolve_opencode_bin(), str(port), role, handle],
                cwd=fleet_workspace(), env=env,
                creationflags=subprocess.CREATE_NEW_CONSOLE)
            if not _port_up(url, timeout=25):
                try:
                    subprocess.run(["taskkill", "/PID", str(tui_proc.pid),
                                    "/T", "/F"], capture_output=True)
                except Exception:  # noqa: BLE001
                    pass
                tui_proc, url = None, None
        if url:
            argv += ["--attach", url]
        if monitor and url:
            threading.Thread(
                target=self._focus_session_when_known,
                args=(session_id,), daemon=True).start()
        log_path = None
        stdout = subprocess.DEVNULL
        if self._log_dir:
            Path(self._log_dir).mkdir(parents=True, exist_ok=True)
            safe = "".join(c if c.isalnum() or c in "-_." else "_"
                           for c in session_id)
            log_path = Path(self._log_dir) / f"{safe}.log"
            stdout = open(log_path, "ab")
        proc = subprocess.Popen(
            argv, cwd=fleet_workspace(), env=env,
            stdin=subprocess.DEVNULL,           # opencode hangs on open stdin
            stdout=stdout, stderr=subprocess.STDOUT)
        rec = _Launch(proc, log_path, tui_proc=tui_proc, url=url)
        if prev:
            rec.opencode_session = prev.opencode_session
        rec.window_dismissed = dismissed
        self._launches[session_id] = rec

    def alive(self, session_id) -> bool:
        rec = self._launches.get(session_id)
        return rec is not None and rec.proc.poll() is None

    def kill(self, session_id) -> None:
        rec = self._launches.get(session_id)
        if rec and rec.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(rec.proc.pid), "/T", "/F"],
                           capture_output=True)

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

    def exit_code(self, session_id):
        """The turn client's exit code once it has ended, else None. A
        NONZERO code with the row still active is the pool's crash signal
        (a normal opencode turn exits 0; a provider death / kill exits
        nonzero) — consumed by service.sweep_crashed."""
        rec = self._launches.get(session_id)
        return rec.proc.poll() if rec else None

    def close_viewport(self, session_id):
        """Kill the shell's TUI window tree (terminal close only — the
        pool calls this from `release(park=False)`; a park never does).
        Flags the kill as POOL-initiated so viewport_died() never reads
        it as an operator action."""
        rec = self._launches.get(session_id)
        if rec is not None:
            rec.window_dismissed = True      # pool-initiated, not operator
        if rec and rec.tui_proc is not None and rec.tui_proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(rec.tui_proc.pid),
                            "/T", "/F"], capture_output=True)

    def viewport_died(self, session_id) -> bool:
        """True when the OPERATOR closed the shell's window (the window
        process ended and the pool didn't end it). 1:1 semantic with
        killing a Claude monitor console (operator ruling 2026-07-20):
        closing the window IS killing the shell — the watchdog turns this
        into a `crashed` event and crash recovery replaces the shell."""
        rec = self._launches.get(session_id)
        return bool(rec and rec.tui_proc is not None
                    and rec.tui_proc.poll() is not None
                    and not rec.window_dismissed)

    def turn_runtime(self, session_id):
        """Seconds the CURRENT turn client has been running, or None when
        no turn is in flight. The watchdog's turn-timeout reads this: a
        turn stuck past the bound (provider retrying silently forever) is
        KILLED, which turns the invisible stall into a nonzero exit the
        crash plane announces to the parent."""
        rec = self._launches.get(session_id)
        if rec and rec.proc.poll() is None:
            return time.time() - rec.started
        return None

    def _focus_session_when_known(self, session_id: str) -> None:
        """Background: the moment the turn's session exists in the store
        (~1s after the turn starts ON the window's server), snap the
        window onto it via ITS OWN /tui/select-session — the operator
        watches the turn render live from the first token (turns execute
        server-side under --attach, and the TUI's SSE bus broadcasts all
        sessions; both source-verified). Re-runs per launch, so a
        crash-fallback that mints a new session gets re-snapped too.
        Best-effort: a viewport must never break a spawn."""
        try:
            import json as _json
            import urllib.request as _rq
            token = None
            for _ in range(120):
                token = capture_session_id(f"edp-{session_id}", retries=1,
                                           delay=0.1)
                if token:
                    break
                time.sleep(1)
            if not token:
                return
            rec = self._launches.get(session_id)
            if rec is None or not rec.url:
                return
            rec.opencode_session = token
            body = _json.dumps({"sessionID": token}).encode()
            # PATIENT SNAP (2026-07-20): a fresh TUI can take >10s to boot
            # its event client; giving up early left windows on the HOME
            # face forever — read as "just a default shell starts up".
            # ~90s of retries, plus one confirm re-snap 5s after the first
            # success (idempotent; covers a TUI that ate the event while
            # still routing).
            # PERSISTENT RE-SNAP (2026-07-20 #2): a select event is NOT
            # replayed — POSTing 200 while the attach TUI is still
            # booting its event client means the event evaporates and
            # the window sits on HOME forever (observed live twice).
            # There is no API to read the TUI's current route, so don't
            # guess: re-post the (idempotent) select every 10s for as
            # long as this window+launch record live. A TUI already on
            # the session treats it as a no-op navigation.
            while True:
                cur = self._launches.get(session_id)
                if (cur is not rec or rec.tui_proc is None
                        or rec.tui_proc.poll() is not None):
                    return
                try:
                    req = _rq.Request(
                        f"{rec.url}/tui/select-session", data=body,
                        headers={"Content-Type": "application/json"})
                    _rq.urlopen(req, timeout=5)
                except Exception:  # noqa: BLE001 — TUI still booting
                    pass
                time.sleep(10)
        except Exception:  # noqa: BLE001
            pass

    # -- extras -------------------------------------------------------------
    def opencode_session_id(self, session_id) -> str | None:
        """Captured opencode session id (resume token) for a launch."""
        rec = self._launches.get(session_id)
        if rec and rec.opencode_session is None:
            rec.opencode_session = capture_session_id(f"edp-{session_id}",
                                                      retries=1)
        return rec.opencode_session if rec else None

    def session_token(self, session_id) -> str | None:
        """The pool's resume seam (service.resume): the REAL resumable id.
        Full retries — at resume time the store row exists; the wait only
        matters right after a fresh launch. Unknown launches (pool restart)
        fall back to a title lookup so parked shells survive restarts."""
        rec = self._launches.get(session_id)
        if rec and rec.opencode_session:
            return rec.opencode_session
        token = capture_session_id(f"edp-{session_id}")
        if rec:
            rec.opencode_session = token
        return token


class CompositeSpawner:
    """Mixed fleet: routes launches by role (EDP_OPENCODE_ROLES, default
    'worker'), delegates lifecycle calls to whichever backend knows the id."""

    def __init__(self, claude_spawner, opencode_spawner,
                 opencode_roles: set[str] | None = None):
        self._claude = claude_spawner
        self._oc = opencode_spawner
        roles = opencode_roles if opencode_roles is not None else {
            r.strip() for r in os.environ.get(
                "EDP_OPENCODE_ROLES", "worker").split(",") if r.strip()}
        self._oc_roles = roles

    def _owner(self, session_id):
        if self._oc.knows(session_id):
            return self._oc
        return self._claude

    def launch(self, session_id, role, handle, mode="headless",
               claude_session=None, resume_session=None, model=None,
               activation=None) -> None:
        backend = self._oc if role in self._oc_roles else self._claude
        backend.launch(session_id, role, handle, mode=mode,
                       claude_session=claude_session,
                       resume_session=resume_session, model=model,
                       activation=activation)

    def alive(self, session_id):
        return self._owner(session_id).alive(session_id)

    def kill(self, session_id):
        return self._owner(session_id).kill(session_id)

    def knows(self, session_id):
        return self._claude.knows(session_id) or self._oc.knows(session_id)

    def pid(self, session_id):
        return self._owner(session_id).pid(session_id)

    def last_output_ts(self, session_id):
        return self._owner(session_id).last_output_ts(session_id)

    def close_viewport(self, session_id):
        if self._oc.knows(session_id):
            self._oc.close_viewport(session_id)

    def exit_code(self, session_id):
        oc_code = getattr(self._oc, "exit_code", lambda _s: None)(session_id)
        if oc_code is not None:
            return oc_code
        return getattr(self._claude, "exit_code", lambda _s: None)(session_id)

    def session_token(self, session_id):
        """Resume-token seam: only the opencode backend has one; claude rows
        resume via their minted claude_session_id (service default path)."""
        if self._oc.knows(session_id):
            return self._oc.session_token(session_id)
        # after a pool restart neither backend knows the id; try the
        # opencode store anyway — a hit means it was an opencode shell.
        return self._oc.session_token(session_id) if not self._claude.knows(
            session_id) else None
