"""Durable rule registry + supervisor — the reactive plane's *reflexes*
(EVENT-PLANE-UPGRADE-DESIGN.md §4C, Phase 3-C).

Today an `observe()` subscription lives only inside the session that created it:
when the shell exits, the wiring is gone. This module turns "I set up a monitor
in my session" into "the system has a standing reflex." A **registered rule** is
a NAMED, PERSISTENT triple:

    rule = (an observe() spec  +  a governed EffectSpec  +  owner)

stored DURABLY on disk (one JSON file per rule under the sanctioned reactive
state dir, alongside `.reactive/sub-*.spec` and `.reactive/effect_audit/`). A
small **supervisor** loads every ENABLED rule on startup and keeps it subscribed
by spawning the EXISTING `edp_claude.reactive.driver` for each — so a
shell/process restart RE-SUBSCRIBES all rules from disk with no session memory.
The 6th-sense watcher becomes ONE registered rule rather than a bespoke daemon.

DESIGN INVARIANTS HELD (do NOT weaken):
  * We REUSE the existing runtime + driver + the Phase-2 governed-effect path —
    no parallel mechanism is forked. The supervisor only spawns the driver CLI
    with `--effect-file/--owner`; all allowlist / idempotency / rate / audit /
    advisory-by-default logic stays in `effects.EffectDispatcher`.
  * `compile_spec`'s restricted-builtins sandbox is untouched. Registration
    VALIDATES a rule's observe spec by compiling it against a NO-I/O provider
    (`rx.never()` placeholders) — composition only, no subscribe, no transport.
  * Advisory-by-default: the driver runs the dispatcher at `phase=2`, so Tier-2
    mutating effects stay FULLY DARK (validate-only) here. Phase 3-C delivers the
    registry/supervisor; it does NOT flip Tier-2 on (that is a later, explicit
    opt-in milestone).
  * LOCAL-only; file-based state; strict tracked-PID teardown on exit AND
    failure (graceful terminate -> hard kill, by the specific PIDs we spawned —
    NEVER a name/image-wide `python`/`node` kill).
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import reactivex as rx
from reactivex import Observable

from .effects import EffectSpec
from .runtime import RxRuntime, compile_spec

try:  # liveness evidence for teardown; degrade gracefully if absent
    import psutil
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore


def _pid_alive(pid: int) -> bool:
    """Liveness probe that is SAFE on Windows. The old fallback was
    `os.kill(pid, 0)` — but on Windows signal 0 is CTRL_C_EVENT, so that
    call BROADCASTS CTRL_C to the target's console process GROUP instead
    of probing it. With a stale/self pid in supervisor.lock it killed the
    whole console (pytest, the parent shell, the harness session). Probe
    with psutil when present, else OpenProcess on Windows, else the POSIX
    os.kill(pid, 0) idiom (which IS a probe there)."""
    if pid <= 0:
        return False
    if psutil is not None:
        return psutil.pid_exists(pid)
    if os.name == "nt":
        import ctypes
        import ctypes.wintypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── errors (consumable, never a silent no-op) ──────────────────────────────
class RegistryError(ValueError):
    """Base for registry rejections."""


class RuleNotFound(RegistryError):
    """No rule with that name is registered."""


class RuleExists(RegistryError):
    """A rule with that name already exists (use update/remove first)."""


# ── the durable rule record ────────────────────────────────────────────────
@dataclass(frozen=True)
class RegisteredRule:
    """A named, persistent reactive rule. `spec`/`bindings` compile to the
    observe() Observable; `effect` (optional) is the governed EffectSpec dict
    (advisory-by-default) the driver dispatches per emission. `owner` is the
    provenance inbox (echo-loop filter). A rule with no `effect` is a pure
    SENSORY rule (wake-only)."""

    name: str
    spec: str
    owner: str
    bindings: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] | None = None
    enabled: bool = True
    created_ts: str = field(default_factory=_utc)
    updated_ts: str = field(default_factory=_utc)

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "spec": self.spec, "owner": self.owner,
            "bindings": self.bindings, "effect": self.effect,
            "enabled": self.enabled, "created_ts": self.created_ts,
            "updated_ts": self.updated_ts,
        }

    @staticmethod
    def from_json(d: dict[str, Any]) -> "RegisteredRule":
        return RegisteredRule(
            name=d["name"], spec=d["spec"], owner=d.get("owner", ""),
            bindings=d.get("bindings") or {}, effect=d.get("effect"),
            enabled=bool(d.get("enabled", True)),
            created_ts=d.get("created_ts") or _utc(),
            updated_ts=d.get("updated_ts") or _utc())


# ── validation: compose the spec with a NO-I/O provider (no subscribe) ──────
def _novalidate_provider(name: str, **kw: Any) -> Observable:
    """A source provider used ONLY at registration to prove the observe spec
    COMPILES to an Observable. Every source resolves to `rx.never()` — a real
    Observable that never emits and performs no I/O — so composition is checked
    without touching the broker/pool/filesystem."""
    return rx.never()


def validate_spec(spec: str, bindings: dict[str, Any] | None) -> None:
    """Raise SpecError if the observe spec does not compile to an Observable.
    Pure composition check (NO subscribe / NO transport)."""
    runtime = RxRuntime(_novalidate_provider)
    compile_spec(spec, runtime, bindings or {})  # raises SpecError on failure


# ── the durable registry (one JSON file per rule) ──────────────────────────
class RuleRegistry:
    """Persists registered rules as one JSON file per rule under
    `<root>/<name>.json` (default root = `<EDP_AGENT_HOME>/.reactive/registry`).
    Per-file + atomic write (write-temp -> os.replace) mirrors how the rest of
    the framework persists per-entity state and makes enable/disable a single
    durable file rewrite. The registry is the SOURCE OF TRUTH; the supervisor's
    driver-input files are regenerated artifacts."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_registry_root()
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- paths ----
    def _path(self, name: str) -> Path:
        if not name or "/" in name or "\\" in name or name.startswith("."):
            raise RegistryError(f"illegal rule name {name!r}")
        return self.root / f"{name}.json"

    # ---- durable IO (atomic) ----
    def _write(self, rule: RegisteredRule) -> None:
        path = self._path(rule.name)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rule.to_json(), indent=2, default=str),
                       encoding="utf-8")
        os.replace(tmp, path)  # atomic on Windows + POSIX

    # ---- CRUD ----
    def register_rule(self, name: str, spec: str,
                      effect: dict[str, Any] | None, owner: str,
                      enabled: bool = True,
                      bindings: dict[str, Any] | None = None,
                      *, replace: bool = False) -> RegisteredRule:
        """Register (or, with replace=True, overwrite) a named persistent rule.
        VALIDATES the observe spec (compiles, no I/O) AND the EffectSpec
        (allowlist + opt-in, at compile time) BEFORE anything is persisted, so
        an invalid rule never reaches disk. The effect's `rule_id` is forced to
        the rule NAME so the audit trail is keyed by rule identity."""
        if self._path(name).exists() and not replace:
            raise RuleExists(
                f"rule {name!r} already exists (use replace=True to overwrite)")
        # 1. observe spec must compile to an Observable (composition only).
        validate_spec(spec, bindings)
        # 2. effect (if any) must pass the governed allowlist/opt-in at COMPILE
        #    time — exactly the same gate the driver applies. rule_id := name.
        eff: dict[str, Any] | None = None
        if effect is not None:
            eff = {**effect, "rule_id": name}
            EffectSpec.compile(eff)  # raises EffectError on a bad/un-opted effect
        now = _utc()
        existing = self.get(name) if self._path(name).exists() else None
        rule = RegisteredRule(
            name=name, spec=spec, owner=owner, bindings=bindings or {},
            effect=eff, enabled=enabled,
            created_ts=(existing.created_ts if existing else now),
            updated_ts=now)
        self._write(rule)
        return rule

    def get(self, name: str) -> RegisteredRule:
        path = self._path(name)
        if not path.exists():
            raise RuleNotFound(f"no registered rule {name!r}")
        return RegisteredRule.from_json(
            json.loads(path.read_text(encoding="utf-8")))

    def list_rules(self) -> list[RegisteredRule]:
        out: list[RegisteredRule] = []
        for p in sorted(self.root.glob("*.json")):
            try:
                out.append(RegisteredRule.from_json(
                    json.loads(p.read_text(encoding="utf-8"))))
            except Exception:  # noqa: BLE001 — a corrupt file must not hide the rest
                continue
        return out

    def enabled_rules(self) -> list[RegisteredRule]:
        return [r for r in self.list_rules() if r.enabled]

    def set_enabled(self, name: str, enabled: bool) -> RegisteredRule:
        rule = self.get(name)
        updated = RegisteredRule(
            name=rule.name, spec=rule.spec, owner=rule.owner,
            bindings=rule.bindings, effect=rule.effect, enabled=enabled,
            created_ts=rule.created_ts, updated_ts=_utc())
        self._write(updated)
        return updated

    def enable(self, name: str) -> RegisteredRule:
        return self.set_enabled(name, True)

    def disable(self, name: str) -> RegisteredRule:
        return self.set_enabled(name, False)

    def remove(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False


def default_registry_root() -> Path:
    home = Path(os.environ.get("EDP_AGENT_HOME", "."))
    return home / ".reactive" / "registry"


# ── the supervisor (keeps enabled rules subscribed; reuses the driver) ──────
@dataclass
class SupervisorConfig:
    broker_url: str = field(
        default_factory=lambda: os.environ.get(
            "EDP_BROKER_URL", "http://127.0.0.1:9300"))
    pool_url: str = field(
        default_factory=lambda: os.environ.get(
            "EDP_POOL_URL", "http://127.0.0.1:9301"))
    agent_home: Path = field(
        default_factory=lambda: Path(os.environ.get("EDP_AGENT_HOME", ".")))
    driver_python: str = field(
        default_factory=lambda: os.environ.get("EDP_DRIVER_PY", sys.executable))
    # bounded auto-restart of a child that dies WITHIN a supervisor run (a
    # transient driver/SSE drop) — distinct from the durable cross-PROCESS
    # restart, which is a fresh supervisor re-reading the registry from disk.
    max_child_restarts: int = field(
        default_factory=lambda: int(
            os.environ.get("EDP_SUP_MAX_CHILD_RESTARTS", "5")))
    # F36 R4#13: sustained healthy uptime REFUNDS the restart budget —
    # without this the lifetime counter turned isolated crashes days apart
    # into a permanently driverless enabled rule.
    restart_reset_secs: float = field(
        default_factory=lambda: float(
            os.environ.get("EDP_SUP_RESTART_RESET_SECS", "600")))
    monitor_poll_s: float = 1.0


class RuleSupervisor:
    """Loads enabled rules on start() and keeps each subscribed by spawning the
    existing reactive driver (one tracked subprocess per rule). On a fresh
    process start it re-reads the registry from disk, so rules survive a
    shell/supervisor restart (the durability guarantee). enable()/disable()
    spawn/tear-down a single child live. Teardown stops EVERY tracked PID
    (graceful then hard) on clean exit AND on failure — tracked PIDs only,
    never a name-wide kill."""

    def __init__(self, registry: RuleRegistry,
                 cfg: SupervisorConfig | None = None):
        self.registry = registry
        self.cfg = cfg or SupervisorConfig()
        self._children: dict[str, subprocess.Popen] = {}
        self._restarts: dict[str, int] = {}
        self._child_started: dict[str, float] = {}   # monotonic start ts
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._active_dir = self.registry.root / "_active"
        self._active_dir.mkdir(parents=True, exist_ok=True)
        self._lockfile = self.registry.root / "supervisor.lock"
        self._log_path = self.registry.root / "supervisor.log.jsonl"

    # ---- structured log ----
    def log(self, event: str, **fields: Any) -> None:
        rec = {"ts": _utc(), "event": event, **fields}
        try:
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        except Exception:  # noqa: BLE001
            pass
        # daemon liveness to stderr (a parent capturing the proc sees progress);
        # the durable record is the JSONL above.
        print(f"[supervisor] {event} {fields}", file=sys.stderr, flush=True)  # noqa: T201

    # ---- single instance ----
    def _acquire_singleton(self) -> None:
        if self._lockfile.exists():
            try:
                old = int(self._lockfile.read_text(encoding="utf-8").strip() or "0")
            except Exception:  # noqa: BLE001
                old = 0
            # NOTE: never `os.kill(old, 0)` here — on Windows that is a
            # CTRL_C broadcast to old's console group, not a probe (it took
            # down the whole test console). _pid_alive is the safe probe.
            alive = _pid_alive(old)
            if alive:
                raise RuntimeError(
                    f"another rule supervisor is already running (pid {old}); "
                    "single-instance refused")
        self._lockfile.write_text(str(os.getpid()), encoding="utf-8")

    def _release_singleton(self) -> None:
        try:
            if (self._lockfile.exists() and self._lockfile.read_text(
                    encoding="utf-8").strip() == str(os.getpid())):
                self._lockfile.unlink()
        except Exception:  # noqa: BLE001
            pass

    # ---- at-least-once replay guard: advance the broker `since` cursor ----
    def _advance_bindings(self, rule: RegisteredRule) -> dict[str, Any]:
        """Return the rule's bindings with its broker `since` cursor ADVANCED to
        the moment of this (re)subscribe.

        WHY: a rule's governed-effect dedup seen-set lives IN-PROCESS inside the
        driver's `EffectDispatcher` (effects.py) — it is EMPTY on every fresh
        driver start. So the only thing standing between a cross-restart broker
        REPLAY (the broker re-streams still-retained events to a reconnecting
        recipient) and a RE-FIRED advisory is the broker `since_ts` the driver
        reconnects with. If we replayed the rule's original (registration-time)
        `since`, a restarted supervisor would re-stream — and, with an empty
        seen-set, RE-DISPATCH — every advisory already emitted before the bounce
        (proven in s13/a6: 3 wire advisories for a 2-trigger run across a
        restart). Advancing `since` to NOW on each (re)subscribe means a fresh
        driver only ever sees events from this subscription forward → no replay,
        no re-fire. The durable registry record keeps the original `since` for
        provenance; only this REGENERATED driver-input artifact is advanced.

        SCOPE (deliberately narrow): we advance ONLY when the rule actually binds
        `since` (the broker/topic reconnect cursor). This is the advisory-safe
        mitigation the s14/a2 action calls for. The FULL fix — persisting a
        PER-RULE dedup seen-set so no event is ever lost OR re-fired across a
        restart — remains the explicitly DEFERRED cross-restart-replay-
        persistence item and is a HARD BLOCKER for any Tier-2 live-enable; until
        it lands Tier-2 stays DARK (driver phase=2)."""
        binds = dict(rule.bindings)
        if "since" in binds:
            advanced = _utc()
            self.log("rule_cursor_advanced", rule=rule.name,
                     since_was=binds.get("since"), since_now=advanced)
            binds["since"] = advanced
        return binds

    # ---- materialize the driver inputs for one rule (regenerated artifacts) ----
    def _materialize(self, rule: RegisteredRule) -> dict[str, Path]:
        d = self._active_dir / rule.name
        d.mkdir(parents=True, exist_ok=True)
        spec_file = d / "spec"
        bind_file = d / "bindings.json"
        spec_file.write_text(rule.spec, encoding="utf-8")
        bind_file.write_text(
            json.dumps(self._advance_bindings(rule), default=str),
            encoding="utf-8")
        out = {"spec": spec_file, "bindings": bind_file}
        if rule.effect is not None:
            eff_file = d / "effect.json"
            eff_file.write_text(json.dumps(rule.effect, default=str),
                                encoding="utf-8")
            out["effect"] = eff_file
        return out

    def _spawn(self, rule: RegisteredRule) -> subprocess.Popen:
        files = self._materialize(rule)
        cmd = [self.cfg.driver_python, "-m", "edp_claude.reactive.driver",
               "--spec-file", str(files["spec"]),
               "--bindings-file", str(files["bindings"])]
        if "effect" in files:
            # REUSE the Phase-2 governed-effect path: the driver wires the
            # EffectDispatcher at phase=2 (Tier-2 DARK), advisory-by-default.
            cmd += ["--effect-file", str(files["effect"]),
                    "--owner", rule.owner]
        env = dict(os.environ)
        env["EDP_AGENT_HOME"] = str(self.cfg.agent_home)
        env["EDP_BROKER_URL"] = self.cfg.broker_url
        env["EDP_POOL_URL"] = self.cfg.pool_url
        # Redirect the child's NDJSON wake stream + stderr to per-rule files
        # (append). The supervisor governs effects via the durable audit FILE,
        # not the child's stdout, so we must NOT leave an unread PIPE — a full
        # OS pipe buffer would deadlock a long-running driver. Files give a
        # durable per-rule trace and never block.
        d = self._active_dir / rule.name
        out_f = (d / "driver.stdout.ndjson").open("a", encoding="utf-8")
        err_f = (d / "driver.stderr.log").open("a", encoding="utf-8")
        # On Windows, give each driver its OWN process group so a CTRL_BREAK
        # sent to the SUPERVISOR's group (the graceful stop the stack launcher
        # uses) does NOT cascade-kill the drivers out from under us — the
        # supervisor must reap its OWN tracked driver PIDs (graceful teardown +
        # rule_torn_down audit + lock release), not have them die in a group
        # break. We still tear them down by their specific PID via _terminate.
        popen_kw: dict[str, Any] = {}
        if os.name == "nt":
            # CREATE_NO_WINDOW: when the supervisor itself has no console
            # (WMI/detached launch), a bare console-subsystem child ALLOCATES
            # a fresh visible console — one window flash per driver (re)start.
            # (WP0/WP3 shadow-shell fix; precedent: pool service.py neuron
            # driver spawn.)
            popen_kw["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP
                | getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            proc = subprocess.Popen(
                cmd, stdout=out_f, stderr=err_f, text=True, bufsize=1,
                env=env, cwd=str(self.cfg.agent_home), **popen_kw)
        finally:
            # the child holds its own dup'd fds; the parent closes its copies.
            out_f.close()
            err_f.close()
        self.log("rule_subscribed", rule=rule.name, pid=proc.pid,
                 has_effect=("effect" in files), owner=rule.owner)
        import time as _time
        self._child_started[rule.name] = _time.monotonic()  # F36 R4#13
        return proc

    # ---- public lifecycle ----
    def start(self) -> None:
        """Acquire the singleton, register teardown on exit AND failure, then
        subscribe every ENABLED rule from disk (the re-subscribe-on-restart
        path: a fresh supervisor process re-reads the registry with no session
        memory)."""
        self._acquire_singleton()
        atexit.register(self.shutdown)
        # SIGBREAK = the Windows CTRL_BREAK_EVENT the stack launcher uses for a
        # GRACEFUL stop; treat it like SIGINT/SIGTERM so a launcher-driven stop
        # runs the full teardown (reap tracked drivers + release the lock)
        # rather than dying abruptly and orphaning the singleton lockfile.
        _sigs = [signal.SIGINT, signal.SIGTERM]
        _sigbreak = getattr(signal, "SIGBREAK", None)
        if _sigbreak is not None:
            _sigs.append(_sigbreak)
        for s in _sigs:
            try:
                signal.signal(s, lambda *_: self._stop.set())
            except Exception:  # noqa: BLE001 — not all signals exist on Windows
                pass
        rules = self.registry.enabled_rules()
        self.log("supervisor_started", pid=os.getpid(),
                 n_enabled=len(rules), root=str(self.registry.root))
        for rule in rules:
            with self._lock:
                self._children[rule.name] = self._spawn(rule)

    def supervise(self, max_runtime: float | None = None) -> int:
        """Block until stop / max_runtime, restarting (bounded) any enabled
        child that dies within this run. Always tears down on exit AND failure."""
        deadline = (time.monotonic() + max_runtime) if max_runtime else None
        try:
            while not self._stop.is_set():
                self._reap_and_restart()
                if deadline is not None and time.monotonic() >= deadline:
                    break
                self._stop.wait(self.cfg.monitor_poll_s)
            return 0
        finally:
            self.shutdown()

    def _reap_and_restart(self) -> None:
        import time as _time
        with self._lock:
            for name, proc in list(self._children.items()):
                if proc.poll() is None:
                    # F36 R4#13: sustained HEALTHY uptime refunds the
                    # restart budget. The counter was lifetime-cumulative,
                    # so isolated crashes days apart eventually exhausted
                    # it and left an enabled rule permanently driverless.
                    started = self._child_started.get(name)
                    if (started is not None
                            and self._restarts.get(name, 0) > 0
                            and _time.monotonic() - started
                            >= self.cfg.restart_reset_secs):
                        self.log("rule_restart_budget_reset", rule=name,
                                 healthy_secs=int(
                                     _time.monotonic() - started))
                        self._restarts[name] = 0
                    continue  # still alive
                rc = proc.returncode
                # was this rule disabled meanwhile? then leave it down.
                try:
                    rule = self.registry.get(name)
                except RuleNotFound:
                    self._children.pop(name, None)
                    continue
                if not rule.enabled or self._stop.is_set():
                    self._children.pop(name, None)
                    continue
                n = self._restarts.get(name, 0)
                if n >= self.cfg.max_child_restarts:
                    self.log("rule_restart_exhausted", rule=name,
                             attempts=n, returncode=rc)
                    self._children.pop(name, None)
                    continue
                self._restarts[name] = n + 1
                self.log("rule_child_died_restarting", rule=name,
                         returncode=rc, attempt=n + 1)
                self._children[name] = self._spawn(rule)

    # ---- live enable/disable ----
    def enable(self, name: str) -> None:
        rule = self.registry.enable(name)
        with self._lock:
            if name not in self._children or self._children[name].poll() is not None:
                self._restarts[name] = 0
                self._children[name] = self._spawn(rule)

    def disable(self, name: str) -> None:
        self.registry.disable(name)
        with self._lock:
            proc = self._children.pop(name, None)
        if proc is not None:
            self._terminate(name, proc)

    # ---- teardown (tracked PIDs only; graceful then hard) ----
    def _terminate(self, name: str, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            self.log("rule_torn_down", rule=name, pid=proc.pid,
                     returncode=proc.returncode)
        except Exception as e:  # noqa: BLE001 — never swallow silently
            self.log("rule_teardown_error", rule=name,
                     error=f"{type(e).__name__}: {e}")

    def shutdown(self) -> None:
        """Idempotent full teardown: stop, terminate EVERY tracked child by its
        own PID (graceful -> hard), release the singleton. Safe to call from
        atexit + finally + signal."""
        self._stop.set()
        with self._lock:
            children = list(self._children.items())
            self._children.clear()
        for name, proc in children:
            self._terminate(name, proc)
        self._release_singleton()

    def tracked_pids(self) -> dict[str, int]:
        with self._lock:
            return {name: p.pid for name, p in self._children.items()}


# ── CLI ─────────────────────────────────────────────────────────────────────
def _print(obj: Any) -> None:
    # CLI output — print IS this subcommand's interface (like scripts/).
    print(json.dumps(obj, indent=2, default=str))  # noqa: T201


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="edp-rule-registry")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_reg = sub.add_parser("register", help="register a rule from a JSON file "
                           "{name,spec,owner,bindings?,effect?,enabled?}")
    p_reg.add_argument("--file", required=True)
    p_reg.add_argument("--replace", action="store_true")

    sub.add_parser("list", help="list registered rules")

    for verb in ("enable", "disable", "remove"):
        pp = sub.add_parser(verb)
        pp.add_argument("name")

    p_sup = sub.add_parser("supervise",
                           help="load enabled rules and keep them subscribed")
    p_sup.add_argument("--max-runtime", type=float, default=None)

    args = ap.parse_args(argv)
    registry = RuleRegistry()

    if args.cmd == "register":
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        rule = registry.register_rule(
            name=raw["name"], spec=raw["spec"], effect=raw.get("effect"),
            owner=raw.get("owner", ""), enabled=bool(raw.get("enabled", True)),
            bindings=raw.get("bindings"), replace=bool(args.replace))
        _print({"registered": rule.to_json()})
        return 0
    if args.cmd == "list":
        _print({"rules": [r.to_json() for r in registry.list_rules()]})
        return 0
    if args.cmd in ("enable", "disable"):
        rule = (registry.enable(args.name) if args.cmd == "enable"
                else registry.disable(args.name))
        _print({args.cmd: rule.to_json()})
        return 0
    if args.cmd == "remove":
        _print({"removed": registry.remove(args.name), "name": args.name})
        return 0
    if args.cmd == "supervise":
        sup = RuleSupervisor(registry)
        sup.start()
        return sup.supervise(max_runtime=args.max_runtime)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
