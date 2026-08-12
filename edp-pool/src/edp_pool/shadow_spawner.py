"""ShadowSpawner — the pool launches SHADOWS, shadows launch shells (WS7).

Spawner-ABC-compatible, so everything upward (service.py, the engine, the
spawn tools) is untouched: same launch/alive/kill/knows/pid surface. Inside,
every HEADLESS launch becomes a ShellShadow (shadow.py) wired with the
production adapters:

  shell    → PtyLaunch, built exactly as SubprocessSpawner's headless
             branch builds it (argv/env/log), plus EDP_SHADOW_NONCE and
             EDP_SHADOW_DIR stamped into the env (provenance + reflex).
  driver   → the rx driver subprocess (edp_claude.reactive.driver) with
             the role's subscription spec — the SAME command observe()
             used to hand to the Monitor tool, now shadow-hosted: stdout
             NDJSON is read by a thread and becomes framed wakes.
  brief    → composed from the shell's OWN action record (description +
             injected grounding + acceptance), read-only from the plan
             JSON — the worker-close-nudge precedent. Kills the
             check_inbox/read_object boot turns.
  terminal → the same plan-JSON read: own action (worker/reviewer) or
             plan terminal_status (planner) recorded terminal.
  publish  → broker /v1/publish (ready to the parent, crashed flowback —
             wire-identical to the existing paths).
  release  → pool /v1/release/<sid> over localhost HTTP (the pool is its
             own client), so a clean shadow-close is a REAL release,
             never something the orphan sweep mistakes for a crash.

V1 DEVIATION FROM SHADOW.md §6 (recorded there too): shadows run as
threads INSIDE the pool process, not separate processes — so pool death
means shadow death. The restore story is unchanged in shape: ledgers are
durable, and on pool restart the supervisor rebirths non-closed handles
(park+resume) under fresh shadows. Process isolation is v2.

Staged rollout: EDP_SHADOW=1 (default ON) shadows EVERY spawn — both
modes. Headless shells get the ConPTY pipe (PtyLaunch.send_activation);
monitor shells (visible console, the operator's default) get their
activation+brief as claude's initial-prompt argv and later wakes via
console-input injection (console_input.inject_line — AttachConsole +
WriteConsoleInputW in a detached helper). EDP_SHADOW=0 restores the
legacy un-shadowed SubprocessSpawner for both modes.
"""

import json
import os
import subprocess
import threading
from pathlib import Path

import httpx

from .shadow import ShadowConfig, ShellShadow, safe_name
from .spawner import Spawner, SpawnMode, SubprocessSpawner

#: per-role subscription spec templates — the loop-and-heartbeat table as
#: POOL CONFIG DATA (the guide's table remains the human-readable source).
#: Placeholders: {me} = broker inbox handle, {plan_id}, {recipe_id}.
ROLE_SPECS: dict[str, str] = {
    "worker": "rx.broker(me)",
    "reviewer": "rx.broker(me)",
    "curiosity": "rx.broker(me)",
    # ("consult" row deleted 2026-08-12 with the retired consult shell role.)
    "specialist": "rx.broker(me)",
    "planner": ("rx.merge(rx.broker(me), rx.worklog(plan_id), "
                "rx.pool(scope=plan_id), rx.orphaned(plan_id), "
                "rx.recipe_events(recipe_id))"),
}

#: default heartbeat per role (seconds) — reflex(pace) overrides live.
ROLE_HEARTBEAT_S: dict[str, float] = {
    "worker": 300.0, "reviewer": 300.0, "curiosity": 300.0,
    "specialist": 600.0, "planner": 1800.0,
}


def shadow_enabled() -> bool:
    return os.environ.get("EDP_SHADOW", "1").strip().lower() not in (
        "0", "false", "no", "off")


def parent_of(handle: str) -> str:
    """worker `<plan>:<action>` → plan inbox; planner `<recipe>:<step>` →
    recipe inbox. No colon → self (nothing above to notify)."""
    head, _, _ = handle.rpartition(":")
    return head or handle


class _PtyShellAdapter:
    """ShellShadow's shell interface over PtyLaunch. send_line reuses
    send_activation (text + CR submit) — the proven typing path."""

    def __init__(self, launch) -> None:
        self.launch = launch
        self.log_path = getattr(launch, "log_path", None)

    def spawn(self) -> None:
        self.launch.spawn()

    def wait_ready(self) -> bool:
        return self.launch.wait_ready()

    def send_line(self, line: str) -> None:
        self.launch.send_activation(line)

    def is_alive(self) -> bool:
        return self.launch.is_alive()

    def terminate(self) -> None:
        self.launch.terminate()

    @property
    def pid(self):
        return self.launch.pid


class _ConsoleShellAdapter:
    """ShellShadow's shell interface over a VISIBLE console (monitor mode).

    First line: `prepare_first_line` stashes it pre-spawn; spawn() appends
    it to argv as claude's initial prompt (claude submits it when its
    session is ready — no readiness race, same as legacy monitor spawns).
    Later lines (the framed wakes): console-input injection into the
    child's console via the detached helper. wait_ready() is trivially
    True — argv delivery needs no marker, and an injected wake that lands
    before the TUI is ready just queues in the console input buffer."""

    log_path = None            # visible console: the window IS the output

    def __init__(self, argv: list, env: dict, cwd: str | None) -> None:
        self._argv = argv
        self._env = env
        self._cwd = cwd
        self._first: str | None = None
        self.launch = None

    def prepare_first_line(self, line: str) -> None:
        self._first = line

    def spawn(self) -> None:
        from .console_launcher import ConsoleLaunch

        argv = self._argv + ([self._first] if self._first else [])
        self.launch = ConsoleLaunch(argv=argv, env=self._env, cwd=self._cwd)
        self.launch.spawn()

    def wait_ready(self) -> bool:
        return True

    def send_line(self, line: str) -> None:
        from .console_input import inject_line

        pid = getattr(self.launch, "pid", None)
        if pid:
            inject_line(pid, line)

    def is_alive(self) -> bool:
        return bool(self.launch and self.launch.is_alive())

    def terminate(self) -> None:
        if self.launch is not None:
            self.launch.terminate()

    @property
    def pid(self):
        return getattr(self.launch, "pid", None)


class _RxDriverAdapter:
    """Hosts the rx driver subprocess; NDJSON stdout lines → on_event.
    The exact process observe()'s monitor_cmd describes, re-parented."""

    def __init__(self, *, python: str, agent_home: str, broker_url: str,
                 pool_url: str, spec: str, bindings: dict,
                 spec_dir: Path, name: str, on_event,
                 owner: str = "") -> None:
        self._on_event = on_event
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        spec_dir.mkdir(parents=True, exist_ok=True)
        self._spec_path = spec_dir / f"{name}.spec"
        self._spec_path.write_text(spec, encoding="utf-8")
        self._bindings_path = spec_dir / f"{name}.bindings.json"
        self._bindings_path.write_text(json.dumps(bindings),
                                       encoding="utf-8")
        self._argv = [python, "-m", "edp_claude.reactive.driver",
                      "--spec-file", str(self._spec_path),
                      "--bindings-file", str(self._bindings_path)]
        if owner:
            # WP3 (2026-08-12): sensory self-echo filter — the driver drops
            # events authored by the shell it wakes (the planner used to be
            # woken by every line its own tools appended to its worklog).
            self._argv += ["--owner", owner]
        self._env = {**os.environ,
                     "EDP_AGENT_HOME": agent_home,
                     "EDP_BROKER_URL": broker_url,
                     "EDP_POOL_URL": pool_url}
        self._agent_home = agent_home

    def start(self) -> None:
        # WP3 (2026-08-12): CREATE_NO_WINDOW — when the pool runs without a
        # console, a bare console-subsystem child ALLOCATES a visible one;
        # one window flash per driver (re)start was a major "shadow shell"
        # source. Precedent: service.py neuron-driver spawn.
        self._proc = subprocess.Popen(
            self._argv, env=self._env, cwd=self._agent_home,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                           | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)))
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            # WP3 (2026-08-12): UNWRAP the driver envelope. run() emits one
            # NDJSON object per emission with the payload nested under
            # "event" — forwarding the wrapper erased every kind (the shadow
            # read event["kind"] off the WRAPPER, so a broker `done` framed
            # as a contentless "mail" wake — the empty-tick defect).
            if isinstance(event, dict) and set(event) == {"event"}:
                event = event["event"]
            elif isinstance(event, dict) and (
                    "error" in event or "completed" in event):
                # driver lifecycle lines surface as alerts, not fake mail.
                event = {"kind": "alert", "body": event}
            try:
                self._on_event(event if isinstance(event, dict)
                               else {"body": event})
            except Exception:      # noqa: BLE001 — pump must not die on one
                continue

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()

    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


class ShadowSpawner(Spawner):
    """Drop-in Spawner: EVERY spawn gets a shadow — headless over ConPTY,
    monitor over argv-first-line + console-input injection. Only
    EDP_SHADOW=0 delegates to the wrapped legacy SubprocessSpawner."""

    def __init__(self, legacy: SubprocessSpawner,
                 shadow_dir: Path | None = None) -> None:
        self.legacy = legacy
        self.shadow_dir = shadow_dir or (
            Path(__file__).resolve().parents[2] / ".shadows")
        self._shadows: dict[str, ShellShadow] = {}

    # ── production adapters ────────────────────────────────────────────
    def _agent_python(self) -> str:
        home = self.legacy.cwd or "."
        return str(Path(home) / ".venv" / "Scripts" / "python.exe")

    def _plan_action(self, handle: str) -> dict | None:
        """Read the shell's OWN action record from the plan JSON —
        read-only, the worker-close-nudge precedent. None = unknown."""
        plan_id, _, action_id = handle.rpartition(":")
        if not plan_id:
            return None
        path = Path(self.legacy.cwd or ".") / ".plans" / f"{plan_id}.json"
        try:
            plan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for a in plan.get("actions", []):
            if a.get("action_id") == action_id:
                return a
        return None

    def _compose_brief(self, role: str, handle: str) -> str:
        if role in ("worker", "reviewer"):
            a = self._plan_action(handle)
            if not a:
                return ""
            parts = [f"action {handle}: {a.get('description', '')}"]
            acc = a.get("acceptance") or {}
            if acc.get("expected"):
                parts.append(f"acceptance: {acc['expected']}")
            inj = a.get("injected_context")
            if inj:
                parts.append("grounding: "
                             + json.dumps(inj, default=str)[:4000])
            if a.get("serves"):
                parts.append(f"serves: {a['serves']}")
            if a.get("concerns"):
                parts.append(f"concerns: {a['concerns']}")
            return "\n".join(parts)
        return ""          # planner/curiosity ground themselves (digest)

    def _terminal_check(self, role: str, handle: str):
        if role in ("worker", "reviewer"):
            def check() -> bool:
                a = self._plan_action(handle)
                return bool(a) and a.get("status") in (
                    "done", "failed", "skipped")
            return check
        if role == "planner":
            plan_id = handle.replace(":", "-")
            path = Path(self.legacy.cwd or ".") / ".plans" / f"{plan_id}.json"

            def check() -> bool:
                try:
                    plan = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return False
                return bool(plan.get("terminal_status"))
            return check
        return lambda: False       # curiosity/specialist self-close

    def _publish(self, handle: str):
        broker = self.legacy.broker_url

        def publish(kind: str, body: dict) -> None:
            if not broker:
                return
            import uuid
            from datetime import datetime, timezone
            try:
                httpx.post(f"{broker}/v1/publish", json={
                    "msg_id": str(uuid.uuid4()),
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "from": handle, "to": parent_of(handle),
                    "kind": kind, "body": body,
                }, timeout=5.0)
            except Exception:      # noqa: BLE001 — best-effort flowback
                pass
        return publish

    def _release(self, session_id: str):
        pool = self.legacy.pool_url

        def release() -> None:
            sh = self._shadows.get(session_id)
            if sh is not None and sh.shell is not None:
                sh.shell.terminate()
            if not pool:
                return
            try:
                httpx.post(f"{pool}/v1/release/{session_id}", timeout=5.0)
            except Exception:      # noqa: BLE001
                pass
        return release

    # ── Spawner surface ────────────────────────────────────────────────
    def launch(self, session_id: str, role: str, handle: str,
               mode: SpawnMode = "headless",
               claude_session: str | None = None,
               resume_session: str | None = None,
               model: str | None = None,
               activation: str | None = None) -> None:
        if not shadow_enabled():
            self.legacy.launch(session_id, role, handle, mode,
                               claude_session, resume_session, model,
                               activation)
            return

        from .pty_launcher import (
            PtyLaunch, activation_text, build_argv, build_env,
            build_session_args, ensure_claude_healthy, resolve_claude_bin,
        )
        from .spawner import seat_model_for

        # v7 live-drill fix: registry binds every shadowed role too.
        model = model or seat_model_for(role, self.legacy.cwd)

        cfg = ShadowConfig(
            handle=handle, role=role, ledger_dir=self.shadow_dir,
            spec=self._spec_for(role, handle),
            heartbeat_s=ROLE_HEARTBEAT_S.get(role, 300.0),
            brief=self._compose_brief(role, handle),
            activation=activation or activation_text(role),
        )

        bin_ = ensure_claude_healthy(resolve_claude_bin(
            self.legacy.claude_bin))
        env = build_env(session_id, role, handle, self.legacy.broker_url,
                        pool_url=self.legacy.pool_url,
                        agent_home=self.legacy.cwd,
                        log_dir=self.legacy.shell_log_dir)
        env["EDP_SHADOW_NONCE"] = cfg.nonce
        env["EDP_SHADOW_DIR"] = str(self.shadow_dir)
        sargs = build_session_args(claude_session, resume_session)
        safe = safe_name(session_id)
        log_path = (self.legacy.log_dir / f"{safe}.log"
                    if self.legacy.log_dir else None)

        if mode == "monitor":
            # Visible console (the operator's default): same permission
            # rule as the legacy monitor spawn — the operator can click-
            # approve, so autonomy is the explicit EDP_SKIP_PERMISSIONS
            # opt-in, never a shadow side effect.
            skip_perms = os.environ.get(
                "EDP_SKIP_PERMISSIONS", "0").lower() in ("1", "true", "yes")

            def shell_factory():
                return _ConsoleShellAdapter(
                    argv=build_argv(bin_, extra=sargs,
                                    skip_permissions=skip_perms,
                                    model=model),
                    env=env, cwd=self.legacy.cwd)
        else:
            def shell_factory():
                return _PtyShellAdapter(PtyLaunch(
                    argv=build_argv(bin_, extra=sargs,
                                    skip_permissions=True, model=model),
                    env=env, cwd=self.legacy.cwd, log_path=log_path))

        def driver_factory(on_event):
            return _RxDriverAdapter(
                python=self._agent_python(),
                agent_home=self.legacy.cwd or ".",
                broker_url=self.legacy.broker_url or "",
                pool_url=self.legacy.pool_url or "",
                spec=cfg.spec, bindings=self._bindings_for(role, handle),
                spec_dir=self.shadow_dir / "specs",
                name=safe, on_event=on_event,
                owner=handle)

        sh = ShellShadow(
            cfg, shell_factory=shell_factory,
            driver_factory=driver_factory if cfg.spec else None,
            terminal_check=self._terminal_check(role, handle),
            publish=self._publish(handle),
            release=self._release(session_id))
        self._shadows[session_id] = sh
        sh.start()

    def _spec_for(self, role: str, handle: str) -> str:
        return ROLE_SPECS.get(role, "rx.broker(me)")

    def _bindings_for(self, role: str, handle: str) -> dict:
        plan_id, _, _ = handle.rpartition(":")
        b = {"me": handle}
        if role == "planner":
            recipe_id, _, _ = handle.rpartition(":")
            b.update({"plan_id": handle.replace(":", "-"),
                      "recipe_id": recipe_id})
        elif plan_id:
            b["plan_id"] = plan_id
        return b

    def alive(self, session_id: str) -> bool:
        sh = self._shadows.get(session_id)
        if sh is not None:
            return bool(sh.shell and sh.shell.is_alive())
        return self.legacy.alive(session_id)

    def kill(self, session_id: str) -> None:
        sh = self._shadows.get(session_id)
        if sh is not None:
            sh.stop()
            if sh.shell is not None:
                sh.shell.terminate()
            return
        self.legacy.kill(session_id)

    def knows(self, session_id: str) -> bool:
        return session_id in self._shadows or self.legacy.knows(session_id)

    def pid(self, session_id: str) -> int | None:
        sh = self._shadows.get(session_id)
        if sh is not None and sh.shell is not None:
            return getattr(sh.shell, "pid", None)
        return self.legacy.pid(session_id)

    def last_output_ts(self, session_id: str) -> float | None:
        sh = self._shadows.get(session_id)
        if sh is not None and sh.shell is not None:
            log_path = getattr(sh.shell, "log_path", None)
            if log_path is None:
                return None
            try:
                return log_path.stat().st_mtime
            except OSError:
                return None
        return self.legacy.last_output_ts(session_id)
