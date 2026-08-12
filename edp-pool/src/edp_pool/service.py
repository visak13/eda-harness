"""PoolService (Microservice ABC) + FastAPI app (HLD §3)."""

import asyncio
import ipaddress
import json
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from edp_contracts import HealthStatus, Microservice, Tool, get_logger, mount
from edp_contracts.errors import ErrorCode

from .spawner import FakeSpawner, Spawner

# 2026-05-26: per-request step logging (the pool logged only at startup,
# so a hung/slow spawn left no trace). Writes to the daily-rolling
# edp-pool.log under EDP_LOG_DIR.
_log = get_logger("edp-pool")

_VERSION = "1.0.0"


def _env_int(name: str, default: int) -> int:
    """An int env knob that degrades to its default on garbage — a typo in
    a .bat file must never crash the pool or (worse) zero a capacity cap."""
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# ── DESIGN-v7 1.2: the capacity model, split into THREE knobs ──────────────
#
# The old single EDP_MAX_WORKERS=3 was an early safety net doing two jobs at
# once: throughput throttle AND host-resource guard. v7 separates them:
#
#   EDP_MAX_WORKERS      (6)  — concurrent role="worker" shells. Throughput.
#   EDP_MAX_PLANNERS     (4)  — concurrent role="planner" shells. New: the
#                               old capacity branch guarded workers ONLY, so
#                               the v7 parallel-planner frontier (1.5.1)
#                               would have been UNCAPPED.
#   EDP_MAX_TOTAL_SHELLS (10) — every role, the TRUE resource guard (each
#                               live shell is a full claude process, ~GBs).
#
# role="reviewer" is deliberately EXEMPT from the per-role caps and counts
# under the total only: a reviewer blocking a builder slot is how DESIGN-v6
# ran with ~2 effective builders (plan 1.2 root cause). Every refusal message
# NAMES its env knob so the operator can raise it without reading this file.

def _max_workers() -> int:
    # 2026-05-25: env-configurable so live dev can raise parallelism.
    # DESIGN-v7 1.2: default raised 3 → 6 (the 3 was an early safety net;
    # EDP_MAX_TOTAL_SHELLS is the real resource guard now).
    return _env_int("EDP_MAX_WORKERS", 6)


def _max_planners() -> int:
    return _env_int("EDP_MAX_PLANNERS", 4)


def _max_total_shells() -> int:
    return _env_int("EDP_MAX_TOTAL_SHELLS", 10)


_ENVELOPE_HTTP_STATUS = 409


def _utc_now_iso() -> str:
    """tz-aware UTC ISO-8601 (never a naive local timestamp — the registry
    is read back after a restart, possibly on the other side of a DST edge)."""
    return datetime.now(timezone.utc).isoformat()


def _split_handle(handle: str) -> tuple[str | None, str | None]:
    """`<prefix>:<suffix>` on the LAST ':' (uuids/handles may contain ':').
    (None, None) when there is no ':' — e.g. a bare specialist handle."""
    idx = handle.rfind(":")
    if idx <= 0:
        return None, None
    return handle[:idx], handle[idx + 1:]


def _row_matches_recipe(row: dict, recipe_id: str) -> bool:
    """Does a session row belong to `recipe_id`?

    Normally the stored `recipe_id` answers it. But a worker whose planner
    row was already reaped (a crash — exactly W11's suspend path) stored
    None, and suspend must still FIND it to reap it: an unseen worker keeps
    running against a suspended recipe. So also PREFIX-match the handle —
    `<recipe>:<step>` for a planner, `<recipe>-<step>:<action>` for its
    worker. Prefix-matching a KNOWN recipe id followed by its separator is
    unambiguous; the dash ambiguity only bites when SPLITTING an unknown id.
    Legacy rows (no `recipe_id` key) fall through to the handle test."""
    if row.get("recipe_id") == recipe_id:
        return True
    handle = row.get("handle") or ""
    return handle.startswith(f"{recipe_id}-") or handle.startswith(f"{recipe_id}:")


def _proc_fingerprint(pid: int | None) -> dict | None:
    """Reuse-proof fingerprint (pid + create_time) of a spawned shell's
    process, persisted with the session so liveness can be RE-ESTABLISHED
    after a pool restart (the in-memory PTY handle doesn't survive). None
    if pid is unknown. create_time defeats pid-reuse; None when psutil
    can't read it (best-effort pid-only)."""
    if not pid:
        return None
    try:
        import psutil
        return {"pid": pid, "create_time": psutil.Process(pid).create_time()}
    except Exception:  # noqa: BLE001 — psutil missing / process already gone
        return {"pid": pid, "create_time": None}


def _proc_alive(fp: dict | None) -> bool | None:
    """Is the fingerprinted process still alive? True / False, or None
    when we genuinely can't tell (no fingerprint / psutil unavailable) —
    the caller maps None to 'unknown' so the FSM stays conservative."""
    if not fp or not fp.get("pid"):
        return None
    pid = fp["pid"]
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return None
    if not psutil.pid_exists(pid):
        return False
    ct = fp.get("create_time")
    if ct is None:
        return True  # pid exists; no create_time to defeat reuse (best effort)
    try:
        return abs(psutil.Process(pid).create_time() - ct) < 1.0
    except psutil.NoSuchProcess:
        return False              # vanished between the two checks — truly gone
    except Exception:  # noqa: BLE001 — AccessDenied / OSError: can't tell
        # A probe that FAILS is not a process that DIED. `reconcile_sessions`
        # writes "done" over any row this reports False for, so a transient
        # failure must degrade to "unknown", never to a death verdict.
        return None


def _proc_kill_allowed(fp: dict | None) -> tuple[bool, str]:
    """May we SIGNAL the process a persisted fingerprint names? Fail-closed.

    True only when the LIVE process at `pid` still carries the `create_time`
    the registry stored for it at spawn. Every other case — no fingerprint,
    no stored create_time, psutil unavailable, pid gone, create_time mismatch
    — is a REFUSAL, and the reason is returned for the caller to surface.

    Deliberately stricter than `_proc_alive`, which answers "is it alive?" and
    may fall back to pid-only when create_time is missing. Authorizing a KILL
    never guesses: pids are recycled, and killing a recycled pid is how a
    blanket kill took down the broker and pool mid-run (2026-05-31). The
    stored create_time exists for exactly this check.
    """
    if not fp or not fp.get("pid"):
        return False, "no persisted pid"
    ct = fp.get("create_time")
    if ct is None:
        return False, "no persisted create_time — cannot defeat pid reuse"
    pid = fp["pid"]
    try:
        import psutil
    except Exception:  # noqa: BLE001
        return False, "psutil unavailable — cannot verify the fingerprint"
    try:
        live_ct = psutil.Process(pid).create_time()
    except Exception:  # noqa: BLE001 — NoSuchProcess / bad pid
        return False, f"pid {pid} is already gone"
    if abs(live_ct - ct) >= 1.0:
        return False, (
            f"pid {pid} create_time mismatch (stored {ct!r}, live {live_ct!r})"
            " — the pid was reused by a different process"
        )
    return True, f"pid {pid} fingerprint matched"


# ══ W12 panel guards ══════════════════════════════════════════════════════
#
# THE THREE GUARDS ARE NOT THREE LAYERS OF THE SAME FENCE. Keep them distinct:
#
#   A2 (loopback bind)  — stops the pool from EXPOSING the panel off-host.
#   A3 (Origin/Host)    — stops a page the user already has open in a browser
#                         from POSTing to localhost (CSRF). The browser sets
#                         `Origin` itself and page script cannot override it. A
#                         non-browser client sends none, and is allowed through.
#   A1 (channel stamp)  — records, on every message the panel forwards, WHICH
#                         CHANNEL it arrived on and that the channel is
#                         UNAUTHENTICATED.
#
# WHAT A1 DOES NOT DO, stated here because the field name is where this defect
# would hide: THE STAMP CERTIFIES THE PATH A MESSAGE TRAVELLED, AND NOTHING
# ABOUT WHO SENT IT. The panel listens on loopback with no auth (the user's
# deliberate choice — he is the only user and the app is never exposed). Any
# local process can reach it exactly as the browser can, and its message is
# then stamped `via=panel` truthfully. Separately, `broker_send` takes `from_`
# as a parameter, so the `from` field is self-asserted by every sender in this
# system. NO MESSAGE FIELD HERE CERTIFIES ITS AUTHOR — that is a pre-existing
# property of the broker and of the no-auth decision, not something W12 adds,
# and W12 does not repair it. Authorship is established out-of-band or not at
# all. Hence the stamp says `via`/`channel`/`authenticated=false`, never
# anything that reads as authorship.
#
# ── DELIBERATELY UNGUARDED ────────────────────────────────────────────────
# `/v1/spawn`, `/v1/release/{sid}`, `/v1/close_when_idle/{sid}`,
# `/v1/park/{handle}`, `/v1/resume/{handle}`, `/v1/reap/{handle}`,
# `/v1/sessions`, `/v1/locks`, `/v1/liveness/{handle}`,
# `/v1/doctor` carry NO Origin/Host check, ON PURPOSE. They are the MCP tool
# surface: every pool-spawned shell calls them over plain HTTP with no `Origin`
# header, and an A3 check there would refuse every live shell in the fleet.
# An endpoint left unguarded on purpose and one left unguarded by accident look
# identical to the next reader — so this list is the record that these are the
# former. The guards below are applied to the PANEL surface only.

_LOOPBACK_NAMES = frozenset({"localhost"})


class PanelRefused(Exception):
    """A panel-surface request was refused by a guard. Carries the HTTP status
    and a LOUD reason — a silent 404 would look like a routing bug."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _hostname_only(host: str) -> str:
    """`127.0.0.1:9301` → `127.0.0.1`; `[::1]:9301` → `::1`."""
    h = (host or "").strip().lower()
    if h.startswith("["):
        end = h.find("]")
        return h[1:end] if end > 0 else h.strip("[]")
    if h.count(":") == 1:
        h = h.split(":", 1)[0]
    return h


def is_loopback_host(host: str | None) -> bool:
    """True only for `localhost` / an address in a loopback range. `0.0.0.0`
    is NOT loopback — it is the exact value that makes this guard necessary."""
    h = _hostname_only(host or "")
    if not h:
        return False
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def require_loopback_bind() -> None:
    """A2 — FAIL CLOSED OFF LOOPBACK.

    Read at REQUEST time, not import time, and read from the same env var the
    server actually binds with: `main.py` reads `EDP_POOL_HOST` (default
    `127.0.0.1`) straight into `uvicorn.run(host=host)`. LOOPBACK IS A DEFAULT,
    NOT AN INVARIANT — one env var makes this pool reachable from the network,
    and the panel's mutating endpoints suspend processes and forward messages.
    So the panel refuses to serve at all rather than trust the default held.
    """
    host = os.environ.get("EDP_POOL_HOST", "127.0.0.1")
    if not is_loopback_host(host):
        raise PanelRefused(403, (
            f"REFUSED: the W12 panel serves on loopback ONLY, but this pool is "
            f"bound to EDP_POOL_HOST={host!r}. The panel's endpoints suspend "
            f"process trees and forward broker messages, and the surface is "
            f"unauthenticated by design. Rebind to 127.0.0.1 to use the panel."
        ))


def require_local_origin(request) -> None:
    """A3 — ORIGIN / HOST CHECK (CSRF + DNS-rebinding).

    A page the user already has open can POST to `http://127.0.0.1:9301` from
    the browser without ever reading the response, which is enough to pause a
    fleet. The browser sets `Origin` on such a POST and page script cannot
    override it, so a mismatched `Origin` is refused.

    `Host` is checked too: a rebinding attack resolves an attacker domain to
    127.0.0.1, so the socket is loopback while `Host` names the attacker.

    A REQUEST WITH NO `Origin` IS ALLOWED. That is correct for a non-browser
    client (curl, a test, a script) and it is precisely why A3 is not a guard
    against a local process — it never was. See the block comment above.
    """
    host_hdr = request.headers.get("host")
    if not is_loopback_host(host_hdr):
        raise PanelRefused(403, (
            f"REFUSED: Host header {host_hdr!r} is not a loopback name. The "
            f"panel is same-origin, loopback-only; a non-loopback Host is a "
            f"DNS-rebinding attempt."
        ))
    origin = request.headers.get("origin")
    if origin is None:
        return
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not is_loopback_host(parts.netloc):
        raise PanelRefused(403, (
            f"REFUSED: cross-origin request from Origin {origin!r}. The panel "
            f"accepts same-origin loopback requests only."
        ))
    if parts.netloc.lower() != (host_hdr or "").lower():
        raise PanelRefused(403, (
            f"REFUSED: Origin {origin!r} does not match Host {host_hdr!r}."
        ))


#: The `from` address every panel-forwarded message carries. It names the
#: CHANNEL, not a person and not a shell.
PANEL_SENDER = "panel"


def stamp_panel_channel(payload: dict, *, remote: str | None = None) -> dict:
    """A1 — CHANNEL STAMPING. The single chokepoint every panel-submitted
    message passes through on its way to the broker.

    Records TWO TRUE FACTS and no others: the message arrived over the panel's
    HTTP channel, and that channel is UNAUTHENTICATED. `from` is overwritten
    with `PANEL_SENDER`, so a panel message cannot present itself as originating
    from some other handle.

    THE STAMP IS AN UNCONDITIONAL OVERWRITE, NOT A MERGE, and that single fact
    is what makes it a stamp: whatever the caller put under `channel` is
    replaced wholesale, so no part of it survives into the record. (An earlier
    draft also `pop`ped the key first. The pop was dead code — the assignment
    below already discards the caller's value — and a mutation test caught it
    passing while guarding nothing. A line that reads as a security control and
    has no effect is worse than no line, so it is gone.)

    The stamp lets a reader distinguish a message that came over this channel
    from one that did not. It says nothing about who composed it: the channel
    is open to any local process, `from` is self-asserted broker-wide, and no
    field added here could change either fact. Anything load-bearing must be
    confirmed with the human out-of-band.
    """
    body = payload.get("body")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise PanelRefused(400, "message `body` must be a JSON object")
    body["channel"] = {          # overwrite, never merge: see the docstring
        "via": "panel",
        "channel": "panel-http",
        "authenticated": False,
        "stamped_at": _utc_now_iso(),
        "remote_addr": remote,
    }
    payload["body"] = body
    payload["from"] = PANEL_SENDER
    return payload


def _pause_token_dir(state_path: Path | None) -> Path:
    d = os.environ.get("EDP_POOL_PAUSE_TOKENS")
    if d:
        return Path(d)
    base = state_path.parent if state_path else Path(".pool-logs")
    return base / "pause-tokens"


def _pause_deadline_secs() -> float:
    """The auto-resume deadline handed to the watchdog. A freeze that outlives
    it is resumed by the net, not left holding a pool lock forever."""
    try:
        return float(os.environ.get("EDP_PAUSE_MAX_SECS", "1800"))
    except ValueError:
        return 1800.0


class PoolService(Microservice):
    name = "edp-pool"
    version = _VERSION

    def __init__(
        self, spawner: Spawner, broker_url: str | None = None,
        state_path: str | Path | None = None,
    ):
        self.spawner = spawner
        self.broker_url = broker_url
        # cross-restart-recovery (2026-05-21): persist locks+sessions so
        # a pool restart doesn't lose them. Reloaded sessions are
        # orphaned — the new spawner has no handle on their processes —
        # so liveness() reports them dead, and stale-lock reaping +
        # claude-side crash-recovery clean them up on next acquire /
        # next_action. (Caveat: if a pre-restart shell is STILL alive,
        # this can double-execute — but operators restart shells + pool
        # together per the 2026-05-21 lesson. Lost locks = infinite
        # wait, which is worse.)
        self.state_path = Path(state_path) if state_path else None
        self.sessions: dict[str, dict] = {}
        self.locks: dict[str, str] = {}  # handle -> session_id
        # Operator-set cap overrides (panel /v1/limits, 2026-07-19): take
        # precedence over the EDP_MAX_* env knobs, persisted with the
        # registry so a pool restart keeps the operator's setting.
        self.limit_overrides: dict[str, int] = {}
        # s26 item 1: session_id -> the one-shot deferred-reap task armed for
        # it. In-memory ONLY and deliberately not persisted: an arm is a
        # promise about a LIVE shell this pool is watching. A pool restart
        # kills the watcher, and the restart's own orphan handling
        # (release/reap → fingerprint-gated kill) is the correct owner then.
        self._close_timers: dict[str, object] = {}
        # DESIGN-v7 park/resume: one mutex guards every parked/resuming
        # state TRANSITION. Service methods run via asyncio.to_thread, so
        # two threads (the resume watchdog + the neuron's backstop tool, or
        # a park racing a resume) can genuinely interleave — the mutex makes
        # check-then-set atomic. Held across the whole park op (watermark →
        # state flip → flush-wait → kill) so a resume can never fork a shell
        # whose parked predecessor is still being torn down; resume holds it
        # only for the parked→resuming CAS, never across the ~30s spawn.
        self._transition_lock = threading.Lock()
        # started by startup() (the uvicorn/mount lifecycle), never by tests
        # that construct the service directly — see _start_resume_watchdog.
        self._resume_watchdog = None
        # ── PANEL APPROVALS (v7 follow-up, 2026-07-12) ─────────────────────
        # A shell's PreToolUse hook (panel-approval.py, gated by
        # EDP_PANEL_APPROVALS=1) parks a tool call here and long-polls for
        # the operator's verdict; the panel's Approvals view renders the
        # queue and decides. IN-MEMORY ONLY, deliberately: an approval is a
        # promise about a LIVE, blocked tool call — a pool restart kills the
        # waiter, whose hook then times out and FALLS BACK to the shell's
        # own permission flow (fail-open by design: the panel ACCELERATES
        # approvals; its absence can never strand a shell).
        self._approvals: dict[str, dict] = {}
        self._approval_events: dict[str, threading.Event] = {}
        self._approval_seq = 0
        # v7: pool-owned drivers for EXTERNAL neurons (recipe_id -> row).
        # PERSISTED: a registration is the operator's standing intent that
        # this recipe's neuron gets woken; the process is respawned on pool
        # startup (respawn_neuron_drivers).
        self.neuron_drivers: dict[str, dict] = {}
        self._reload()

    # ── external neuron drivers (v7 follow-up, 2026-07-13) ───────────────
    # A CLAUDE neuron arms its own CronCreate heartbeat + Monitor wakes at
    # activation. An EXTERNAL neuron (codex/Sol) has neither tool — so
    # arming became a TOOL CALL: the neuron's activation calls the MCP verb
    # `arm_external_driver`, which lands here; the POOL (the always-on
    # process) then runs scripts/neuron_heartbeat.py for that recipe as a
    # detached child (timer backstop + SSE wake -> `<resume_cmd>` per turn).
    # Registrations PERSIST in the pool state and are respawned on pool
    # restart, so cadence survives everything short of the host dying —
    # strictly more durable than a cron armed inside a shell.

    def arm_neuron_driver(self, recipe_id: str, cmd: str,
                          heartbeat_secs: float = 1800) -> dict:
        if not recipe_id or not cmd:
            return {"ok": False, "refused": "recipe_id and cmd are required"}
        self.disarm_neuron_driver(recipe_id)   # idempotent re-arm
        pid = spawn_neuron_driver(recipe_id, cmd, heartbeat_secs,
                                  self.broker_url)
        if pid is None:
            return {"ok": False,
                    "refused": "driver process failed to launch — see pool "
                               "log; cadence NOT armed"}
        self.neuron_drivers[recipe_id] = {
            "recipe_id": recipe_id, "cmd": cmd,
            "heartbeat_secs": heartbeat_secs,
            "pid": pid, "armed_at": _utc_now_iso(),
        }
        self._persist()
        return {"ok": True, "recipe_id": recipe_id, "pid": pid,
                "note": (f"pool-owned driver armed: one neuron turn every "
                         f"{heartbeat_secs:.0f}s + instantly on broker "
                         "traffic for this recipe. Survives pool restarts "
                         "(re-spawned from the persisted registration); "
                         "disarm via disarm_external_driver / DELETE "
                         "/v1/neuron-driver/{recipe_id}.")}

    def disarm_neuron_driver(self, recipe_id: str) -> dict:
        row = self.neuron_drivers.pop(recipe_id, None)
        self._persist()
        if row is None:
            return {"ok": True, "note": "no driver was armed"}
        try:
            import psutil
            p = psutil.Process(int(row["pid"]))
            for c in p.children(recursive=True):
                c.kill()
            p.kill()
            note = f"driver pid {row['pid']} stopped"
        except Exception as e:  # noqa: BLE001 — already dead is fine
            note = f"driver pid {row['pid']} not running ({e})"
        return {"ok": True, "note": note}

    def respawn_neuron_drivers(self) -> None:
        """Pool startup: re-arm every persisted registration whose process
        did not survive (it never does — drivers die with the pool's host
        session). Best-effort per row."""
        for rid, row in list(self.neuron_drivers.items()):
            # DUPLICATE-DRIVER GUARD (2026-07-21, observed live: FOUR
            # drivers firing for two recipes — survivors of an older pool
            # generation plus this respawn). The registration row carries
            # the exact old pid: reap that tree before spawning its
            # replacement. Precise-PID kill, never name-wide.
            try:
                import psutil
                p = psutil.Process(int(row["pid"]))
                if "neuron_heartbeat" in " ".join(p.cmdline()):
                    for c in p.children(recursive=True):
                        c.kill()
                    p.kill()
                    _log.info("stale_neuron_driver_reaped", rid,
                              recipe_id=rid, pid=row["pid"])
            except Exception:  # noqa: BLE001 — already dead is the norm
                pass
            pid = spawn_neuron_driver(rid, row["cmd"],
                                      float(row.get("heartbeat_secs", 1800)),
                                      self.broker_url)
            if pid is not None:
                row["pid"] = pid
                row["armed_at"] = _utc_now_iso()
        self._persist()

    # ── panel approvals ──────────────────────────────────────────────────
    def approval_request(self, req: dict) -> dict:
        """Queue one blocked tool call for the operator. Returns {id}."""
        with self._transition_lock:
            self._approval_seq += 1
            aid = f"appr-{self._approval_seq}"
        self._approvals[aid] = {
            "id": aid,
            "ts": _utc_now_iso(),
            "handle": str(req.get("handle") or ""),
            "role": str(req.get("role") or ""),
            "tool_name": str(req.get("tool_name") or "?"),
            # bounded: the panel renders a summary, never an unbounded blob
            "summary": str(req.get("summary") or "")[:2000],
            "decision": None,
            "reason": "",
        }
        self._approval_events[aid] = threading.Event()
        return {"id": aid}

    def approval_pending(self) -> list[dict]:
        return [r for r in self._approvals.values() if r["decision"] is None]

    def approval_decide(self, aid: str, decision: str, reason: str) -> dict:
        row = self._approvals.get(aid)
        if row is None:
            return {"refused": f"unknown approval {aid!r}"}
        if decision not in ("allow", "deny"):
            return {"refused": "decision must be allow|deny"}
        row["decision"] = decision
        row["reason"] = str(reason or "")[:500]
        ev = self._approval_events.get(aid)
        if ev is not None:
            ev.set()
        return {"id": aid, "decision": decision}

    def approval_wait(self, aid: str, timeout_s: float) -> dict:
        """Block (worker-thread side; routed via asyncio.to_thread) until the
        operator decides or the timeout lapses. A lapse returns decision=None
        and the HOOK falls back to the shell's own permission prompt — the
        panel can only ever speed things up, never gate them shut."""
        ev = self._approval_events.get(aid)
        row = self._approvals.get(aid)
        if row is None:
            return {"id": aid, "decision": None,
                    "note": "unknown approval (pool restarted?) — fall back"}
        if ev is not None and row["decision"] is None:
            ev.wait(timeout=max(0.0, min(timeout_s, 120.0)))
        out = dict(row)
        # a DECIDED row is consumed on delivery; an undecided one stays
        # listed so the operator can see what timed out into a console prompt
        if out["decision"] is not None:
            self._approvals.pop(aid, None)
            self._approval_events.pop(aid, None)
        return out

    def _reload(self) -> None:
        if self.state_path and self.state_path.exists():
            try:
                data = json.loads(
                    self.state_path.read_text(encoding="utf-8")
                )
                self.sessions = data.get("sessions", {})
                self.locks = data.get("locks", {})
                self.neuron_drivers = data.get("neuron_drivers", {})
                self.limit_overrides = data.get("limit_overrides", {})
            except (json.JSONDecodeError, OSError):
                self.sessions, self.locks = {}, {}
                self.neuron_drivers = {}
                self.limit_overrides = {}

    # ── operator-settable caps (panel /v1/limits, 2026-07-19) ──────────────
    # Precedence: panel override → EDP_MAX_* env → code default. The
    # override persists with the registry across pool restarts.
    def max_workers(self) -> int:
        return int(self.limit_overrides.get("max_workers", _max_workers()))

    def max_planners(self) -> int:
        return int(self.limit_overrides.get("max_planners", _max_planners()))

    def max_total_shells(self) -> int:
        return int(self.limit_overrides.get(
            "max_total_shells", _max_total_shells()))

    def set_limits(self, updates: dict) -> dict:
        """Apply {max_workers|max_planners|max_total_shells: int|None};
        None clears an override back to the env/default. Values are clamped
        to >=1 (a 0 cap would deadlock dispatch, not pause it — pausing is
        the pause framework's job). Returns the effective limits."""
        for key in ("max_workers", "max_planners", "max_total_shells"):
            if key not in updates:
                continue
            val = updates[key]
            if val is None:
                self.limit_overrides.pop(key, None)
            else:
                self.limit_overrides[key] = max(1, int(val))
        self._persist()
        _log.info("limits_set", "", overrides=dict(self.limit_overrides))
        return self.effective_limits()

    def effective_limits(self) -> dict:
        return {
            "max_workers": self.max_workers(),
            "max_planners": self.max_planners(),
            "max_total_shells": self.max_total_shells(),
            "overrides": dict(self.limit_overrides),
        }

    def _persist(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.state_path.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(
                    {"sessions": self.sessions, "locks": self.locks,
                     "neuron_drivers": self.neuron_drivers,
                     "limit_overrides": self.limit_overrides}, f
                )
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    async def startup(self) -> None:
        # DESIGN-v7 1.5.3: the resume watchdog is part of the SERVICE
        # lifecycle (mount() wires startup/shutdown to the app), not of the
        # constructor — unit tests that build a PoolService directly get no
        # background thread polling a broker that isn't there.
        self._start_resume_watchdog()
        # v7: external-neuron drivers are standing operator intent — put
        # them back after a pool restart (their processes died with us).
        try:
            self.respawn_neuron_drivers()
        except Exception as e:  # noqa: BLE001 — cadence loss is loud, not fatal
            _log.warning("neuron_driver_respawn_failed", str(e))
        return None

    async def shutdown(self) -> None:
        if self._resume_watchdog is not None:
            self._resume_watchdog.stop()
            self._resume_watchdog = None
        # Stop driver PROCESSES on pool shutdown, keep their REGISTRATIONS
        # (2026-07-20): startup's respawn_neuron_drivers re-arms them, so
        # cadence survives the restart while no orphaned driver outlives
        # the pool firing turns at a stack that is going down.
        for rid, row in list(self.neuron_drivers.items()):
            try:
                import psutil
                p = psutil.Process(int(row["pid"]))
                for c in p.children(recursive=True):
                    c.kill()
                p.kill()
                _log.info("neuron_driver_stopped", rid,
                          recipe_id=rid, pid=row["pid"])
            except Exception:  # noqa: BLE001 — already dead is fine
                pass
        return None

    def _start_resume_watchdog(self) -> None:
        """Start the parked-handle resume watchdog (daemon thread). Gated by
        EDP_RESUME_WATCHDOG (default ON) so an operator can fall back to the
        neuron-heartbeat backstop alone while debugging."""
        if os.environ.get("EDP_RESUME_WATCHDOG", "1").lower() not in (
                "1", "true", "yes", "on"):
            _log.info("resume_watchdog_disabled",
                      "EDP_RESUME_WATCHDOG is off")
            return
        from .resume_watchdog import ResumeWatchdog
        self._resume_watchdog = ResumeWatchdog(self)
        self._resume_watchdog.start()

    async def health(self) -> HealthStatus:
        return HealthStatus(status="ready", version=_VERSION)

    # ── W11 fork-resume registry ──────────────────────────────────────────
    def _touch(self, sid: str) -> None:
        """Refresh `last_seen` on a row we just CONFIRMED alive. In-memory
        only: liveness is read on hot polls (/v1/locks, /v1/liveness, doctor)
        and a disk write per poll buys nothing — the next spawn/release/reap
        flushes it. No new timer (W11).

        So the PERSISTED `last_seen` can lag a crash by one flush. Nothing
        makes a safety decision on it: suspend/reap read live `liveness()`.
        It is an observability field, not a liveness verdict."""
        s = self.sessions.get(sid)
        if s is not None:
            s["last_seen"] = _utc_now_iso()

    def _recipe_id_for(self, role: str, handle: str) -> str | None:
        """The recipe a session belongs to, resolved ONCE at spawn (stored
        explicitly, never reparsed at read time).

        A planner handle is `<recipe_id>:<step_id>`, so the prefix IS the
        recipe. A worker handle is `<plan_id>:<action_id>` whose plan_id is
        the DASH form of `<recipe>:<step>` — unsplittable, since recipe ids
        contain dashes — so inherit it from the planner row that owns the
        plan. Anything else (bare specialist/consult handle, or no planner
        row) → None: a session with no recipe is normal, not an error."""
        prefix, _suffix = _split_handle(handle)
        if prefix is None:
            return None
        if role == "planner":
            return prefix
        for s in self.sessions.values():
            if s.get("role") != "planner":
                continue
            p, step = _split_handle(s.get("handle") or "")
            if p is not None and f"{p}-{step}" == prefix:
                return s.get("recipe_id")
        return None

    # ── liveness + teardown (one resolver, read by every caller) ──────────
    def _session_alive(self, sid: str) -> bool | None:
        """True / False / None ("genuinely can't tell") for `sid`'s shell.

        The liveness resolver: the in-memory PTY handle when this spawner
        launched the session, else the persisted process fingerprint (a shell
        orphaned across a pool restart — the handle didn't survive, the process
        did).

        WHO READS IT — an ENUMERATION, not a universal (s26/a5). This docstring
        previously asserted "every caller reads it". Nothing pinned that, and it
        was false by one: `spawn`'s stale-lock reap still asked
        `spawner.alive`, which answers False for every session THIS spawner did
        not launch. So a restart-orphaned but still-running worker had its lock
        freed and a second worker launched on its action, while `liveness()`
        reported "alive". An unpinned universal in a docstring is exactly as
        unverified as an unpinned universal in a report — and more dangerous,
        because the next reader takes it as ground truth about the code it sits
        in. So: name the callers, name the exceptions, and pin the list.

          READS `_session_alive`  (the four liveness questions)
            * reconcile_sessions  — may I write "done" over this row?
            * _active_count       — does this row still hold a capacity slot?
                                    (active_workers is its worker-scoped
                                    wrapper — DESIGN-v7 role-parametrized it)
            * spawn               — may I free this handle's lock and dispatch?
            * liveness            — what do I report to the FSM?

          DELIBERATELY DOES NOT (not liveness questions)
            * _kill_session — asks "by WHICH MECHANISM do I kill?" It reads
              `spawner.knows` to choose PTY-handle vs fingerprint, then gates
              the kill on `_proc_kill_allowed`, which is STRICTER than this
              (fail-closed on a missing/mismatched create_time). Authorizing a
              kill must never fall back to pid-only the way this may.
            * _close_when_idle — reads the session's own `state` and the
              spawner's output timestamp. It reaps only a session that ARMED
              itself, and releases through `_kill_session`'s guard anyway.

        `test_no_new_caller_of_spawner_alive` pins the enumeration: exactly one
        call of `spawner.alive(` may exist in this module — the one below.
        """
        if self.spawner.knows(sid):
            # this pool launched it → the live PTY handle is authoritative.
            return self.spawner.alive(sid)
        sess = self.sessions.get(sid)
        if sess is None or sess.get("state") != "active":
            return False   # already released/closed — don't resurrect
        return _proc_alive(sess.get("proc"))

    def _kill_session(self, sid: str) -> str:
        """Kill `sid`'s shell: through the PTY handle when this spawner
        launched it, else through the persisted process fingerprint. Returns
        a human-readable note (the refusal reason when nothing was signalled).

        A pool restart destroys every in-memory PTY handle, so `spawner.kill`
        silently no-ops on a pre-restart shell — `release`/`reap` "succeeded"
        while the shell kept running. d2 mandates a restart per phase, so
        every phase boundary stranded its shells (12 live, 2 tracked).

        The fallback NEVER kills by bare pid. `_proc_kill_allowed` must match
        the live process's create_time against the one stored at spawn, so a
        recycled pid is refused rather than signalled. A refusal is logged and
        returned, never swallowed.
        """
        if self.spawner.knows(sid):
            self.spawner.kill(sid)
            return "killed via the spawner's PTY handle"
        fp = (self.sessions.get(sid) or {}).get("proc")
        allowed, why = _proc_kill_allowed(fp)
        if not allowed:
            _log.info("orphan_kill_refused", sid, sid=sid, reason=why)
            return f"orphan NOT signalled: {why}"
        from .proctree import kill_process_tree
        signalled = kill_process_tree(fp["pid"])
        _log.info("orphan_kill", sid, sid=sid, pid=fp["pid"],
                  signalled=signalled)
        if not signalled:
            return f"orphan pid {fp['pid']} vanished before it was signalled"
        return (f"killed orphaned pid {fp['pid']} + {signalled - 1} "
                f"descendant(s) ({why})")

    # ── core logic (unit-tested directly) ─────────────────────────────────
    def reconcile_sessions(self) -> int:
        """Mark every ACTIVE row whose process is PROVABLY dead as done, free
        any lock it still holds, and return how many rows changed.

        On-demand (driven by `active_workers`), never a background reaper.
        Covers EVERY role: the old sweep lived inside the worker count, so a
        dead planner's row read "active" indefinitely (nine such rows). Rows
        whose liveness is UNKNOWN are left untouched — only a `False` verdict
        may write "done" over a row, never a guess.

        PARKED rows are NEVER reaped here (DESIGN-v7 1.5.2): the `state !=
        "active"` gate below skips them, and that is load-bearing, not
        incidental — a parked shell's process is dead BY DESIGN while its row
        is the resume token. Writing "done" over one would strand the plan.
        """
        changed = 0
        for sid, s in self.sessions.items():
            if s.get("state") != "active":
                continue
            if self._session_alive(sid) is not False:
                continue
            s["state"] = "done"  # phantom — reconcile
            if self.locks.get(s.get("handle")) == sid:
                del self.locks[s["handle"]]
            changed += 1
        if changed:
            self._persist()
        return changed

    def _active_count(self, role: str | None = None) -> int:
        # 2026-05-25: count only sessions that are active AND ACTUALLY
        # ALIVE. A worker that died without calling pool_close_self
        # (crash / manual close / /clear-exit / force-kill) kept state
        # "active" forever and ate a slot → phantom "3/3 occupied" with
        # one live worker. Reconcile first, then count what survives.
        #
        # Counting reads `_session_alive`, so a worker orphaned across a pool
        # restart but STILL RUNNING now holds its slot instead of reading dead
        # (the old `spawner.alive` said False for every pre-restart shell, so
        # the pool would hand its lock to a second worker on the same action).
        # An UNKNOWN row (no fingerprint) stays uncounted, as it always has —
        # a lost lock is recoverable, an infinite wait is not.
        #
        # DESIGN-v7 1.2/1.5: role-parametrized (None = every role, for the
        # EDP_MAX_TOTAL_SHELLS guard). A PARKED row does not count anywhere:
        # its state is "parked", not "active", so the `state` gate below
        # excludes it — parked planners are exactly the shells whose slots
        # the park/resume mechanism exists to free.
        self.reconcile_sessions()
        n = 0
        for sid, s in self.sessions.items():
            if s.get("state") != "active":
                continue
            if role is not None and s.get("role") != role:
                continue
            if self._session_alive(sid):
                self._touch(sid)  # W11: liveness already probed → last_seen
                n += 1
        return n

    def active_workers(self) -> int:
        return self._active_count("worker")

    def spawn(
        self, role: str, handle: str, parent: str | None,
        # VISIBLE BY DEFAULT (user ruling 2026-07-12): an invisible shell
        # burning tokens is the failure mode; headless is the deliberate
        # opt-in (spawn body / panel toggle / EDP_SPAWN_MODE), never a
        # silent fallback.
        mode: str = "monitor",
        claude_session: str | None = None,
        resume_session: str | None = None,
        model: str | None = None,
    ):
        # ── DESIGN-v7 1.2 capacity model ───────────────────────────────────
        # Per-role throughput caps first (workers, planners), then the
        # all-roles EDP_MAX_TOTAL_SHELLS resource guard. role="reviewer" is
        # exempt from the per-role caps ON PURPOSE (a reviewer must never
        # block a builder slot) and is counted under the total only. Every
        # refusal NAMES its env knob — the operator's fix is one env var.
        if role == "worker":
            active = self.active_workers()  # liveness-reconciled count
            cap = self.max_workers()
            if active >= cap:
                return Tool.propagate(
                    source="edp-pool",
                    code=ErrorCode.POOL_CAPACITY_EXCEEDED,
                    message=f"max workers = {cap} (EDP_MAX_WORKERS / panel "
                    f"limits); {active} alive; cannot spawn another",
                )
        elif role == "planner":
            active = self._active_count("planner")
            cap = self.max_planners()
            if active >= cap:
                return Tool.propagate(
                    source="edp-pool",
                    code=ErrorCode.POOL_CAPACITY_EXCEEDED,
                    message=f"max planners = {cap} (EDP_MAX_PLANNERS / panel "
                    f"limits); {active} alive; cannot spawn another",
                )
        total = self._active_count()
        total_cap = self.max_total_shells()
        if total >= total_cap:
            return Tool.propagate(
                source="edp-pool",
                code=ErrorCode.POOL_CAPACITY_EXCEEDED,
                message=f"max total shells = {total_cap} "
                f"(EDP_MAX_TOTAL_SHELLS); {total} alive across all roles; "
                "cannot spawn another",
            )
        if handle in self.locks:
            holder = self.locks[handle]
            # DESIGN-v7 park/resume: a PARKED (or mid-resume) holder is
            # neither alive nor dead — its lock is deliberately kept so a
            # concurrent cold spawn cannot double-dispatch the handle. The
            # correct verb is resume, so say so instead of reaping the row
            # (the `_session_alive(holder)` branch below would read the
            # parked row as dead and steal its lock).
            holder_state = (self.sessions.get(holder) or {}).get("state")
            if holder_state in ("parked", "resuming"):
                return Tool.propagate(
                    source="edp-pool",
                    code=ErrorCode.POOL_UNKNOWN_HANDLE,
                    message=f"handle {handle!r} is {holder_state}; call "
                    f"POST /v1/resume/{handle} instead of spawning cold",
                )
            # Read the SHARED resolver, not `spawner.alive`. The spawner
            # answers False for every session it did not itself launch, so a
            # shell orphaned across a pool restart but STILL RUNNING read
            # "dead" here — and the branch below then freed the lock its
            # action was executing under and launched a second worker on it.
            # That is the double-dispatch precondition (inventory C7 / R6):
            # the re-dispatch path manufacturing the phantom dispatch.
            if self._session_alive(holder):
                return Tool.propagate(
                    source="edp-pool",
                    code=ErrorCode.POOL_UNKNOWN_HANDLE,
                    message=f"handle {handle!r} already locked by an "
                    f"active session; release it first",
                )
            # Liveness-aware lock reaping (2026-05-21): the holder is dead
            # (crashed/killed) or UNKNOWN but never released its lock. A lock
            # held by a dead process is phantom — reap it so the
            # crash-recovery re-dispatch (claude Phase 7) can proceed.
            # Without this, a crashed worker permanently blocks re-spawn
            # of its action until the lock-reaper timer fires.
            #
            # UNKNOWN still reaps, per the 2026-05-26 ruling this path was
            # written under (a lost lock is recoverable; an infinite wait is
            # not) and the test that pins it. That is a narrower risk than it
            # looks: only a row with NO persisted pid probes unknown, and a
            # real SubprocessSpawner always persists one. See
            # test_spawn_still_reaps_an_unprovable_holders_lock.
            stale = self.sessions.get(holder)
            if stale is not None:
                stale["state"] = "done"
            del self.locks[handle]
        sid = f"{role}:{uuid.uuid4()}"
        # WP2 provenance (2026-08-12): resolve the seat model HERE, before
        # the ledger write — the df971d post-mortem found all 63 session rows
        # carried no model at all (resolution happened below this seam, in
        # the spawner), so which model wrote each artifact was unrecoverable.
        # The spawner's own seat lookup remains as a no-op fallback.
        from .spawner import seat_model_for
        resolved_model = model or seat_model_for(
            role, os.environ.get("EDP_AGENT_HOME"))
        # STEP log AROUND the launch — it's the blocking part (PTY spawn
        # + wait_ready); a slow/hung launch now shows launch_start with no
        # launch_done in edp-pool.log.
        _log.info("launch_start", handle, role=role, handle=handle,
                  sid=sid, mode=mode, resume=bool(resume_session),
                  model=resolved_model)
        self.spawner.launch(
            sid, role, handle, mode,
            claude_session=claude_session, resume_session=resume_session,
            model=resolved_model,
        )
        _log.info("launch_done", handle, role=role, handle=handle, sid=sid)
        self._register_channel_membership(role, handle)
        now = _utc_now_iso()
        self.sessions[sid] = {
            "session_id": sid, "role": role, "handle": handle,
            "parent": parent, "state": "active",
            # process fingerprint → survives a pool restart so liveness can
            # be re-established for a still-running shell (2026-05-31).
            "proc": _proc_fingerprint(self.spawner.pid(sid)),
            # W11 fork-resume: what a later resume needs to re-launch a
            # suspended recipe's planners. `claude_session_id` is the id the
            # shell was launched WITH — `resume_session` is a different arg
            # (resume an existing base) and is deliberately not folded in.
            "claude_session_id": claude_session,
            "recipe_id": self._recipe_id_for(role, handle),
            "spawned_at": now,
            "last_seen": now,   # starts == spawned_at; refreshed by _touch
            # W12: the spawn mode is recorded so the panel can EXPLAIN a
            # missing `last_output_ts` instead of rendering a plausible
            # substitute — a monitor-mode shell has no PTY drain log at all.
            # Rows written by an older pool have no `mode` key; every reader
            # uses `.get`, so a legacy row degrades to "reason unknown".
            "mode": mode,
            # WP2 provenance: the RESOLVED model this shell actually launched
            # with (None only when no seat registry resolves — host default).
            "model": resolved_model,
        }
        self.locks[handle] = sid  # lock-by-spawn-lifetime
        self._persist()
        return sid

    def release(self, sid: str, park: bool = False) -> None:
        # DESIGN-v7 1.5.2: `park=True` turns the close into a park — the
        # shell dies but the row stays resumable and the lock stays held.
        if park:
            self.park_session(sid)
            return
        s = self.sessions.get(sid)
        if not s or s["state"] != "active":
            return  # idempotent
        _log.info("release", sid, sid=sid, handle=s.get("handle"))
        s["state"] = "done"
        # fingerprint-gated: also closes a shell orphaned across a pool restart
        self._kill_session(sid)
        # TERMINAL close ends the shell's VIEWPORT too (2026-07-20,
        # operator: "pool close self park false doesnt close tui") — a
        # park keeps the window (same session resumes into it); a
        # terminal release means this shell will never speak again, so
        # its window closing IS the truthful signal.
        getattr(self.spawner, "close_viewport", lambda _s: None)(sid)
        if self.locks.get(s["handle"]) == sid:
            del self.locks[s["handle"]]
        self._persist()

    # ── DESIGN-v7 1.5.2-1.5.4: park / resume ──────────────────────────────
    #
    # PARK is the planner fleet's zero-cost wait: the shell's process dies
    # (0 tokens, 0 RAM), but the session row survives as `state="parked"`
    # with the resume token (`claude_session_id`) and a broker-inbox
    # WATERMARK, and — crucially — the handle LOCK stays pointing at the
    # parked row, so nothing can cold-spawn the handle underneath it.
    #
    # `parked` is a THIRD liveness answer, deliberately neither alive nor
    # dead: `reconcile_sessions` must not reap it (it only touches "active"
    # rows), capacity counts must not count it (`_active_count` gates on
    # "active"), and `liveness()` reports the state by name so the FSM can
    # distinguish "waiting, resumable" from "crashed, re-dispatch".
    #
    # RESUME is a FORK-resume (verified live 2026-07-12): the parked base
    # session stays pristine and the new shell runs under a fresh fork id
    # (`--resume <base> --session-id <fork> --fork-session`), so a crashed
    # resume can always fork the same base again.

    #: Activation line for a resumed shell — NOT the role activator. The
    #: transcript it reloads holds dead observe() subscriptions and a stale
    #: world-view; reconcile(reground=true) is the re-arm (plan 1.5.4).
    PARK_RESUME_ACTIVATION = (
        "You were parked and resumed. Call reconcile(reground=true) first, "
        "then continue driving your plan."
    )

    def _ensure_channel(self, name: str, members: list[str]) -> None:
        """Merge-create a channel row (existing members/topic kept)."""
        try:
            cur = httpx.get(f"{self.broker_url}/v1/channels/{name}",
                            timeout=5.0)
            existing = (cur.json().get("members", [])
                        if cur.status_code == 200 else [])
            merged = sorted(set(existing) | set(members))
            if merged != sorted(existing):
                httpx.put(f"{self.broker_url}/v1/channels/{name}",
                          json={"members": merged}, timeout=5.0)
        except Exception:  # noqa: BLE001 — registry down never blocks
            pass

    def _register_channel_membership(self, role: str, handle: str) -> None:
        """CHANNELS (2026-07-21): every spawn seeds the broker registry —
        worker/reviewer join their plan's #team channel; a planner joins
        #leads (the recipe inbox) and its own #team. Merge-write (existing
        members kept). Best-effort: registry down never blocks a spawn."""
        if not self.broker_url:
            return
        chans: list[str] = []
        if role in ("worker", "reviewer") and ":" in handle:
            chans = [handle.split(":", 1)[0]]
        elif role == "planner" and ":" in handle:
            recipe, step = handle.rsplit(":", 1)
            chans = [recipe, f"{recipe}-{step}"]
            # #product seeds with the recipe's FIRST planner: the operator
            # room exists before anyone needs it. Merge-safe like the rest.
            self._ensure_channel(f"{recipe}-product",
                                 ["@operator", recipe])
        elif role in ("specialist", "consult"):
            chans = ["experts"]
        for ch in chans:
            try:
                cur = httpx.get(f"{self.broker_url}/v1/channels/{ch}",
                                timeout=5.0)
                members = (cur.json().get("members", [])
                           if cur.status_code == 200 else [])
                if handle in members:
                    continue
                httpx.put(f"{self.broker_url}/v1/channels/{ch}",
                          json={"members": members + [handle]},
                          timeout=5.0)
            except Exception:  # noqa: BLE001
                return

    def sweep_crashed(self) -> list[str]:
        """CRASH FLOWBACK (2026-07-19, operator finding: "if the child
        shell crashes then there is no event received by neuron role").
        Liveness was PULL-only — the pool answered "dead" when asked but
        published nothing, so a parked planner / driver-woken neuron never
        learned a child died. This sweep converts a crashed turn client
        (NONZERO exit while the row is still active and not close-armed —
        a normal opencode turn exits 0; park/reap set state first) into
        the CORE `crashed` broker kind addressed to the PARENT handle
        (worker `plan:action` → plan inbox wakes the parked planner;
        planner `recipe:step` → recipe inbox rides the neuron driver's
        SSE plane). The row is marked dead so the FSM's crash-recovery
        (reset to pending, re-dispatch) takes over on the parent's turn.

        DETECT-AND-MARK ONLY: the broker publish belongs to the
        ResumeWatchdog (the pinned single-publish-call-site invariant of
        this module guards the panel channel stamp). Returns the crash
        records for the watchdog to announce."""
        crashed: list[dict] = []
        for sid, s in list(self.sessions.items()):
            if s.get("state") not in ("active", "parked") \
                    or sid in self._close_timers:
                continue
            # Two death signals: (1) the turn client exited NONZERO;
            # (2) the OPERATOR closed the shell's window — 1:1 with
            # killing a Claude monitor console (ruling 2026-07-20:
            # "i closed a few shells but the crash didnt register").
            code = getattr(self.spawner, "exit_code", lambda _s: None)(sid)
            op_kill = getattr(self.spawner, "viewport_died",
                              lambda _s: False)(sid)
            if code in (None, 0) and not op_kill:
                continue
            if s.get("state") == "parked" and not op_kill:
                continue    # parked rows die only by operator window-close
            if op_kill:
                getattr(self.spawner, "kill", lambda _s: None)(sid)
            handle = s.get("handle") or ""
            s["state"] = "dead"
            s["dead_reason"] = ("operator closed the shell window"
                               if op_kill else f"turn client exited {code}")
            self._persist()
            parent = handle.rsplit(":", 1)[0] if ":" in handle else None
            _log.warning("shell_crashed", handle, handle=handle, sid=sid,
                         exit_code=code, notify=parent or "no-parent")
            crashed.append({"session_id": sid, "handle": handle,
                            "parent": parent, "exit_code": code})
        return crashed

    def _inbox_depth(self, handle: str) -> int | None:
        """Message count of `handle`'s broker inbox — the park watermark and
        the watchdog's wake signal. The broker's inbox file is append-only
        (reads never consume), so the count is monotonic: depth > watermark
        ⟺ a message landed after the watermark was cut.

        One synchronous GET /v1/inbox/{handle} (the broker resolves the
        colon→dash alias server-side, so the spawn handle routes correctly).
        None when the broker is down/unconfigured — callers must treat that
        as "could not observe", never as zero."""
        if not self.broker_url:
            return None
        try:
            r = httpx.get(f"{self.broker_url}/v1/inbox/{handle}",
                          timeout=5.0)
            if r.status_code != 200:
                return None
            body = r.json()
            return len(body) if isinstance(body, list) else None
        except Exception:  # noqa: BLE001 — broker down ≠ pool failure
            return None

    def _transcript_path(self, claude_session_id: str) -> Path:
        """Where Claude Code writes the session's transcript:
        <CLAUDE_CONFIG_DIR>/projects/<cwd-key>/<claude_session_id>.jsonl.

        CLAUDE_CONFIG_DIR mirrors build_env's pin (EDP_CLAUDE_CONFIG_DIR
        override, else the repo's .claude-pool skeleton). The cwd-key is the
        shell's cwd with every non-alphanumeric character replaced by '-'
        (Claude Code's own scheme, e.g. C:\\x\\claude → C--x-claude); the
        spawned shells' cwd is the spawner's agent-home pin."""
        from .pty_launcher import _CLAUDE_POOL_CONFIG_DIR
        cfg = Path(os.environ.get(
            "EDP_CLAUDE_CONFIG_DIR", str(_CLAUDE_POOL_CONFIG_DIR)))
        cwd = (getattr(self.spawner, "cwd", None)
               or os.environ.get("EDP_AGENT_HOME") or os.getcwd())
        key = "".join(c if c.isalnum() else "-" for c in str(cwd))
        return cfg / "projects" / key / f"{claude_session_id}.jsonl"

    def _wait_transcript_flush(
        self, sid: str, claude_session_id: str | None, *,
        timeout: float = 20.0, quiesce: float = 2.0, poll: float = 0.25,
    ) -> bool:
        """FLUSH-BEFORE-KILL (verified live finding, 2026-07-12): Claude Code
        writes the transcript asynchronously, and killing the tree before the
        final lines land truncates the very context the resume exists to
        preserve. So wait until the transcript file EXISTS and its mtime has
        been quiescent for `quiesce` seconds, polling up to `timeout`.

        FAIL-OPEN: a transcript that never appears (or never settles) is
        logged loudly and the park proceeds — a park that hangs forever
        holding the transition lock is strictly worse than a resume that
        falls back to the cold path."""
        if not claude_session_id:
            _log.warning(
                "park_flush_skipped", sid, sid=sid,
                reason="no claude_session_id on the row — nothing to await")
            return False
        path = self._transcript_path(claude_session_id)
        deadline = time.monotonic() + timeout
        last_mtime: float | None = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = None
            if mtime is not None:
                if mtime != last_mtime:
                    last_mtime = mtime
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= quiesce:
                    return True
            time.sleep(poll)
        _log.warning(
            "park_flush_timeout",
            "transcript never quiesced within the flush window — parking "
            "anyway (fail-open); the resume may reload a truncated "
            "transcript and should reground",
            sid=sid, transcript=str(path), seen=last_mtime is not None)
        return False

    def _watch_handles(self, s: dict) -> list[str]:
        """Every broker handle the parked shell CONSUMES. A planner is
        spawned on the STEP handle `<recipe>:<step>` but drives — and
        receives worker flowback on — the PLAN handle `<recipe>-<step>`;
        watermarking only the spawn handle strands a parked planner
        forever (found live, M3 fleet drill 2026-07-18). Spawn handle
        first; the derived plan handle mirrors the plan-id convention."""
        handle = s.get("handle") or ""
        handles = [handle]
        if s.get("role") == "planner" and ":" in handle:
            recipe, step = handle.rsplit(":", 1)
            handles.append(f"{recipe}-{step}")
        return handles

    def park_session(
        self, sid: str, *,
        flush_timeout: float = 20.0, flush_quiesce: float = 2.0,
    ) -> dict:
        """Park `sid`: watermark → state="parked". THE SHELL IS LEFT ALIVE.

        The lock is KEPT (spawn refuses a parked handle; resume is the only
        legal successor) and `claude_session_id` is kept — it IS the resume
        token. Idempotent-ish: a non-active row returns parked=False with
        the reason, never raises.

        OPERATOR RULING 2026-07-25 — PARK NO LONGER KILLS THE SHELL.
        This previously did flush-wait → kill tree, on the reasoning that a
        park is a zero-cost wait (0 tokens, 0 RAM) with the row as a resume
        token. That reasoning does not hold on the Claude harness:

          `CronCreate` (the heartbeat) and `Monitor` (the rx subscription
          reader) are CLAUDE CODE TOOLS THAT LIVE INSIDE A SESSION. They are
          not framework state and THE FRAMEWORK CANNOT RE-ARM THEM. Killing
          the shell destroys both, permanently, from the framework's side.

        What survives is misleading: the observe() subscription IS persisted
        server-side and `_rewire_block` hands a resumed shell its wiring back
        — but that is DATA describing what to re-arm. Acting on it needs a
        live shell that asks for it (`reconcile(reground=true)`) and re-issues
        the calls. This module's own resume comment already conceded the
        point: a resumed shell "holds dead observe() subscriptions". In the
        operator's words: the subscription survives but nobody is listening.

        An idle Claude shell costs RAM and a process, NOT tokens. The heartbeat
        and the monitor are what make a role self-pacing and reactive; trading
        them for RAM is the wrong trade. So park is now a STATE TRANSITION
        ONLY: capacity still excludes it, the lock still holds, the FSM must
        not treat it as terminal — and the shell keeps its own wiring."""
        with self._transition_lock:
            s = self.sessions.get(sid)
            if not s or s.get("state") != "active":
                state = (s or {}).get("state")
                return {"parked": False, "session_id": sid,
                        "reason": f"session is not active (state={state!r})"
                        " — nothing to park"}
            handle = s.get("handle")
            # (1) Watermark INSIDE the park op, after the shell stopped
            # consuming — any message that lands after this line (including
            # one racing the park call itself) reads as depth > watermark
            # and wakes the resume watchdog. None = broker unobservable at
            # park time; the watchdog then treats ANY observable depth as a
            # wake signal (fail toward resuming, never toward sleeping
            # forever).
            watch = self._watch_handles(s)
            watermarks = {h: self._inbox_depth(h) for h in watch}
            watermark = watermarks.get(handle)
            if any(v is None for v in watermarks.values()):
                _log.warning(
                    "park_watermark_unavailable",
                    "broker inbox unobservable at park time — the watchdog "
                    "will resume on the first observable message",
                    sid=sid, handle=handle)
            # (2) The row: parked beside active/done; resume token kept.
            # `inbox_watermark` stays as the spawn-handle mark (back-compat);
            # `watermarks` carries every consumed handle (planner: + plan).
            s["state"] = "parked"
            s["parked"] = {
                "parked_at": _utc_now_iso(),
                "inbox_watermark": watermark,
                "watermarks": watermarks,
            }
            # (3) THE SHELL IS NOT KILLED — operator ruling 2026-07-25, see
            # the docstring. There was a flush-before-kill here followed by
            # _kill_session(sid); both are gone. The transcript flush existed
            # ONLY to protect the transcript from the kill that followed it,
            # so with no kill there is nothing to flush against and the
            # flush_timeout/flush_quiesce parameters are retained purely for
            # call-signature compatibility.
            killed = False
            self._persist()
        _log.info("park", sid, sid=sid, handle=handle,
                  watermark=watermark, killed=killed,
                  note="shell left ALIVE; cron + Monitor are in-session "
                       "Claude tools the framework cannot re-arm")
        return {"parked": True, "session_id": sid, "handle": handle,
                "inbox_watermark": watermark,
                "claude_session_id": s.get("claude_session_id")}

    def park(self, handle: str, **kw) -> dict:
        """Park by HANDLE (the shell-facing surface — a shell knows its
        EDP_HANDLE, not its pool session id)."""
        sid = self.locks.get(handle)
        if sid is None:
            return {"parked": False, "handle": handle,
                    "reason": f"no lock held for {handle!r}"}
        return self.park_session(sid, **kw)

    def resume(self, handle: str) -> dict:
        """Resume the parked shell holding `handle`'s lock via fork-resume.

        Transition parked → resuming happens under the transition lock, so
        the watchdog and the MCP-side backstop firing together cannot
        double-spawn: the second caller sees resuming/active and no-ops.
        The ~30s spawn itself runs OUTSIDE the lock.

        Fail-open: a failed fork-resume falls back to a FRESH spawn on the
        same handle (the shell regrounds from the durable plan — today's
        cold path becomes the exception, not the rule)."""
        sid = self.locks.get(handle)
        if sid is None:
            return {"resumed": False, "handle": handle,
                    "reason": f"no lock held for {handle!r}"}
        with self._transition_lock:
            s = self.sessions.get(sid)
            if s is None:
                return {"resumed": False, "handle": handle,
                        "reason": f"lock holder {sid} has no session row"}
            state = s.get("state")
            if state in ("resuming", "active"):
                # the double-caller (watchdog + backstop) no-op, by design
                return {"resumed": False, "handle": handle, "no_op": True,
                        "state": state,
                        "reason": f"session is already {state} — no-op"}
            if state != "parked":
                return {"resumed": False, "handle": handle,
                        "reason": f"session is {state!r}, not parked"}
            # OPERATOR RULING 2026-07-25 — A PARKED SHELL IS NOW LEFT ALIVE
            # (see park_session). So "parked" no longer implies a dead
            # process, and fork-resuming one would put a SECOND shell on this
            # handle: two heartbeats, two monitors, two dispatchers, both
            # holding the same lock's identity. That is strictly worse than
            # the loss this ruling exists to prevent.
            #
            # A live parked shell needs no resume: it kept its own CronCreate
            # heartbeat and its own Monitor subscriptions, which is the whole
            # point of not killing it. Waking it is the broker's job, not a
            # respawn. So flip it back to active and STOP — the mail that
            # triggered this resume is already in the inbox it is watching.
            if self._session_alive(sid) is True:
                s["state"] = "active"
                self._persist()
                _log.info("resume_noop_shell_alive", handle,
                          handle=handle, sid=sid,
                          note="parked shell still alive — restored to "
                               "active without a fork; it kept its own cron "
                               "and Monitor")
                return {"resumed": False, "handle": handle, "no_op": True,
                        "state": "active", "shell_alive": True,
                        "reason": "parked shell is still alive and kept its "
                                  "own heartbeat and subscriptions — "
                                  "restored to active, no fork needed"}
            s["state"] = "resuming"
            base = s.get("claude_session_id")
        role = s.get("role") or "planner"
        # a resume stays as visible as the shell it resumes; an untagged row
        # resolves through the same operator precedence as a fresh spawn
        # (monitor by default — no invisible resumed shell either).
        mode = (s.get("mode")
                or os.environ.get("EDP_SPAWN_MODE", "monitor"))
        fork = str(uuid.uuid4())
        _log.info("resume_start", handle, handle=handle, sid=sid,
                  base=base, fork=fork)
        resumed_via = "fork-resume"
        try:
            # PORT-OPENCODE M2: an opencode shell IGNORES caller-minted ids,
            # so the row's claude_session_id (the minted uuid) is not its
            # real resume token — the spawner captured the generated one.
            # Backends without the seam return None and nothing changes.
            token = getattr(self.spawner, "session_token",
                            lambda _sid: None)(sid)
            if token:
                base = token
            if not base:
                raise RuntimeError(
                    "no parked claude_session_id — nothing to fork-resume")
            self.spawner.launch(
                sid, role, handle, mode,
                claude_session=fork, resume_session=base,
                activation=self.PARK_RESUME_ACTIVATION,
            )
            # opencode `--continue` keeps the SAME session id (the spawner
            # seam returns it); claude fork-resume mints `fork`. Store the
            # token the NEXT resume actually needs.
            new_claude_session = (getattr(self.spawner, "session_token",
                                          lambda _sid: None)(sid) or fork)
        except Exception as exc:  # noqa: BLE001 — resume-fail → cold fallback
            _log.warning("resume_fork_failed",
                         "falling back to a FRESH spawn on the same handle; "
                         "the shell regrounds from the durable plan",
                         handle=handle, sid=sid, base=base, error=repr(exc))
            fresh = str(uuid.uuid4())
            try:
                # cold path: the parked transcript is lost AND the dead
                # predecessor may have already READ its dispatch mail
                # (advancing the shared inbox cursor), so a default
                # check_inbox comes back EMPTY — observed live 2026-07-20
                # as a worker "reporting missing launch context". The
                # replay opt-in is the designed catch-up: say so.
                self.spawner.launch(
                    sid, role, handle, mode, claude_session=fresh,
                    activation=(
                        "You are a FRESH shell on a handle whose "
                        "predecessor died mid-work. Recover your full "
                        "task context FIRST: check_inbox(replay=true) "
                        "re-delivers the retained inbox including "
                        "anything your predecessor consumed. Then follow "
                        "your role protocol file IN FULL from Step 1."))
                new_claude_session = fresh
                resumed_via = "fresh-fallback"
            except Exception as exc2:  # noqa: BLE001
                with self._transition_lock:
                    s["state"] = "parked"   # still resumable later
                self._persist()
                _log.error("resume_failed", handle, handle=handle, sid=sid,
                           error=repr(exc2))
                return {"resumed": False, "handle": handle,
                        "reason": f"fork-resume AND fresh fallback failed: "
                        f"{exc2!r}; session left parked"}
        with self._transition_lock:
            s["claude_session_id"] = new_claude_session
            s["state"] = "active"
            s["proc"] = _proc_fingerprint(self.spawner.pid(sid))
            s["last_seen"] = s["resumed_at"] = _utc_now_iso()
            s.pop("parked", None)
            self._persist()
        _log.info("resume_done", handle, handle=handle, sid=sid,
                  via=resumed_via, claude_session=new_claude_session)
        return {"resumed": True, "handle": handle, "session_id": sid,
                "via": resumed_via, "claude_session_id": new_claude_session}

    # ── s26 item 1: close-on-terminal-status (the worker-shell leak) ──────
    #
    # THE BUG. A worker's close is the last line of a TEXT guide. Nothing
    # compels an assistant turn after the worker emits its report, so a worker
    # that stops to report never resumes: it deletes its cron, replies in chat,
    # and idles at a prompt holding RAM until a human closes it. A text
    # instruction cannot be the only thing between a finished action and a
    # reaped shell.
    #
    # WHY THIS SHAPE, and why it does NOT contradict `reap`'s "NOT a background
    # auto-reaper" stance directly below. That stance rejects an EAGER LOOP that
    # infers death from silence — R5's whole point is that silence != death, and
    # a heads-down shell reasoning for 40 minutes is alive. This is not that:
    #
    #   * The trigger is a TERMINAL ACTION STATUS, not elapsed silence. The
    #     shell has told the store it is finished. There is no inference.
    #   * It is PUSH-ARMED for ONE session, by that session, at the moment it
    #     reports. The pool never scans, never polls a store, never enumerates
    #     "stale" shells. Nothing is armed that did not arm itself.
    #   * Idle is a SECOND gate, not the trigger. A shell still emitting output
    #     is re-checked, never killed mid-flush.
    #   * The kill goes through `release` → `_kill_session` → `_proc_kill_allowed`,
    #     which is FAIL-CLOSED on a missing/mismatched create_time. R10 holds:
    #     we only ever signal a pid+create_time we ourselves recorded at spawn.
    #     A shell with no pool row — the neuron's foreground shell, the user's
    #     terminal — can never be armed, because arming requires a session id.
    #
    # A reaping act stays REASONED. What changed is that the reason is now a
    # fact the shell asserted about itself, rather than a human noticing.
    def arm_close_when_idle(
        self, sid: str, idle_secs: float = 120.0, reason: str = "",
        max_checks: int = 5, park: bool = False,
    ) -> dict:
        """Arm a ONE-SHOT deferred reap for `sid`. Idempotent: re-arming an
        already-armed session leaves the existing timer alone.

        Returns `{"session_id", "armed", "reason"}`. `armed=False` when the
        session is unknown or already released — the HEALTHY case, meaning the
        shell closed itself and the normal path won. Never raises."""
        s = self.sessions.get(sid)
        if not s or s["state"] != "active":
            return {"session_id": sid, "armed": False,
                    "reason": "session is not active — nothing to arm"}
        if sid in self._close_timers:
            # PARK-FLAG CORRECTNESS (2026-07-20, lost-park incident): a
            # blanket "already armed" let an earlier park=False arm WIN
            # over a later park=True — the shell believed it parked, the
            # timer released it terminally, and the row was stranded as
            # `done` with no watermark. A differing park flag is a NEW
            # intent: cancel the stale timer and re-arm with the new one.
            if bool(s.get("close_armed_park")) == park:
                return {"session_id": sid, "armed": True,
                        "reason": "already armed"}
            old = self._close_timers.pop(sid, None)
            if old is not None:
                old.cancel()
            _log.warning("close_rearm_park_changed", sid, sid=sid,
                         old_park=bool(s.get("close_armed_park")),
                         new_park=park)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop (sync test / CLI). Arming is a no-op rather than an
            # error: the shell's own pool_close_self still closes it.
            return {"session_id": sid, "armed": False,
                    "reason": "no running event loop"}
        s["close_armed_park"] = park      # forensic + the differ-guard above
        task = loop.create_task(
            self._close_when_idle(sid, idle_secs, reason, max_checks, park))
        self._close_timers[sid] = task

        def _done(t) -> None:
            # A bare `pop` here would SWALLOW any exception raised inside the
            # reap task (asyncio only reports it when the task is garbage
            # collected, as "Task exception was never retrieved"). That is how
            # a reap silently never happens while the arm reports success —
            # the leak this whole mechanism exists to close, reintroduced one
            # level down. Surface it instead.
            self._close_timers.pop(sid, None)
            if not t.cancelled() and t.exception() is not None:
                _log.error("close_when_idle_failed", sid, sid=sid,
                           error=repr(t.exception()))

        task.add_done_callback(_done)
        _log.info("close_armed", sid, sid=sid, idle_secs=idle_secs,
                  reason=reason)
        return {"session_id": sid, "armed": True, "reason": reason}

    async def _close_when_idle(
        self, sid: str, idle_secs: float, reason: str, max_checks: int,
        park: bool = False,
    ) -> None:
        """Wait for `sid`'s shell to fall idle, then release (or park) it.

        Re-checks up to `max_checks` times while the shell is still producing
        output — a worker that reports and THEN runs its close sequence
        (CronDelete → stop Monitor → pool_close_self) is busy, not leaked, and
        must be left alone to finish. Once it closes itself, `sessions[sid]`
        leaves `active` and this returns without signalling anything.

        DESIGN-v7 1.5.2 `park`: the same idle-gated trigger, but the terminal
        act is `park_session` — this is the shell-callable park path (a
        planner arms it, ends its turn, and the pool parks it once quiet).
        The park's flush-wait + kill are blocking, so they run off the loop."""
        for _ in range(max(1, max_checks)):
            await asyncio.sleep(idle_secs)
            s = self.sessions.get(sid)
            if not s or s["state"] != "active":
                # The healthy path: the shell closed itself first.
                _log.info("close_when_idle_noop", sid, sid=sid)
                return
            last = self.spawner.last_output_ts(sid)
            if last is not None and (time.time() - last) < idle_secs:
                continue   # still emitting → busy, not leaked. Re-check.
            _log.info("close_when_idle_reap", sid, sid=sid, reason=reason,
                      park=park)
            if park:
                out = await asyncio.to_thread(self.park_session, sid)
                if not out.get("parked"):
                    # A shell that BELIEVES it parked but did not is the
                    # worst stranding class (lost-park incident) — stamp
                    # the row so the failure names itself, never silent.
                    s["park_failed"] = out.get("reason", "unknown")
                    _log.warning("park_FAILED_after_arm", sid, sid=sid,
                                 reason=out.get("reason"))
            else:
                self.release(sid)
            return
        _log.info("close_when_idle_gave_up", sid, sid=sid,
                  checks=max_checks)

    def liveness(self, handle: str) -> str:
        # 2026-05-26: the pool persists `sessions` + `locks` to disk but NOT
        # the in-memory `_launches` (PTY handles). After a pool restart the
        # spawner has no record of a session even though its lock still loads
        # from disk. `_session_alive` handles both worlds: the PTY handle when
        # this pool launched it, else the persisted process fingerprint — so a
        # still-running shell reads "alive" again rather than "dead" (which
        # would trigger the FSM's crash-recovery sweep to mass-reincarnate
        # every live planner) or a permanent "unknown" (which pinned the
        # planner in wait after the 2026-05-31 blanket-kill incident).
        sid = self.locks.get(handle)
        if sid is None:
            return "unknown"
        # DESIGN-v7 1.5.2: `parked` (and its transient `resuming`) is a
        # LIVENESS ANSWER OF ITS OWN — neither alive nor dead. Reporting a
        # parked planner "dead" would trip the FSM's crash-recovery
        # reincarnation; reporting it "alive" would make the FSM wait on a
        # shell that cannot answer. Name the state instead.
        state = (self.sessions.get(sid) or {}).get("state")
        if state in ("parked", "resuming"):
            return state
        probed = self._session_alive(sid)
        if probed is None:
            return "unknown"   # genuinely no info (no fingerprint persisted)
        if probed:
            self._touch(sid)   # W11: confirmed alive → last_seen
        return "alive" if probed else "dead"

    def last_output_ts(self, handle: str) -> float | None:
        """W7 busyness signal for `handle`: epoch mtime of its session's
        PTY-drain log (delegated to the spawner). None when the handle
        holds no lock, or the spawner has no log/mtime for the session
        (monitor mode, or orphaned across a pool restart). Purely
        observational — never mutates state."""
        sid = self.locks.get(handle)
        if sid is None:
            return None
        return self.spawner.last_output_ts(sid)

    def lock_list(self) -> list[dict]:
        """GET-only lock inspection (OBJECT-MODEL.md increment 3). Each
        lock carries its holder + truthful liveness so the neuron/planner
        see which handles are REALLY held vs. phantom (dead holder, lock
        not yet reaped). Does not mutate — reaping stays the deliberate
        reap() act."""
        out = []
        for handle, sid in self.locks.items():
            out.append({
                "handle": handle,
                "session_id": sid,
                "liveness": self.liveness(handle),
            })
        return out

    # ── W12: token-free pause (process suspension) ────────────────────────
    #
    # NOTHING IN THIS SECTION STORES A `paused` BOOLEAN, and that is the single
    # most important property of the feature. `pause_state` re-measures the
    # target's thread suspend counts on every call. If a stale watchdog resumes
    # a frozen shell behind our back, the very next read says `running` — the
    # panel cannot show "paused" over a shell that is burning tokens.
    #
    # A pause writes NO RECIPE STATE either. `suspend_recipe` (W11) is a durable
    # park: it kills the shells and stamps `recipe.suspended_at`, which makes
    # `next_action` refuse dispatch and makes `resume_recipe` re-fork planners.
    # Process-pause is a temporary freeze: it kills nothing, records nothing,
    # and dies with the host. They compose only because this one stays silent.

    def _pause_target(self, handle: str) -> tuple[str, dict, int, float] | dict:
        """Resolve `handle` → the fingerprint the pool RECORDED AT SPAWN.

        R10, mechanically: a pid reaches `suspend_tree` only by coming out of
        this registry. The neuron's foreground shell and the user's terminal are
        also `claude.exe` and hold no lock, so they can never be named here. A
        row without a persisted `create_time` is REFUSED, not best-efforted —
        pids are recycled, and a recycled pid frozen by us is a process nothing
        will ever resume.
        """
        sid = self.locks.get(handle)
        if sid is None:
            return {"ok": False, "refused": f"no live shell holds {handle!r}"}
        sess = self.sessions.get(sid) or {}
        if sess.get("state") != "active":
            return {"ok": False,
                    "refused": f"session {sid} is not active"}
        fp = sess.get("proc") or {}
        pid, ct = fp.get("pid"), fp.get("create_time")
        if not pid:
            return {"ok": False,
                    "refused": f"no persisted pid for {handle!r}"}
        if ct is None:
            return {"ok": False, "refused": (
                f"no persisted create_time for {handle!r} — refusing to signal "
                "a pid that may have been reused")}
        return sid, sess, pid, ct

    def pause_state(self, handle: str) -> dict:
        """MEASURED, at read time, every time (F0). Never a stored flag.

        `frozen: None` means the instrument could not see — rendered as unknown,
        never as running. An instrument that cannot detect a state must not
        report its absence as a clean result.
        """
        target = self._pause_target(handle)
        if isinstance(target, dict):
            return {"handle": handle, "state": "unknown", "frozen": None,
                    "measured": False, "reason": target["refused"]}
        sid, _sess, pid, ct = target
        from .proctree import observe_tree_state
        obs = observe_tree_state(pid, ct)
        return {"handle": handle, "session_id": sid, "measured": True, **obs}

    def pause_shell(self, handle: str) -> dict:
        target = self._pause_target(handle)
        if isinstance(target, dict):
            _log.info("pause_refused", handle, handle=handle,
                      reason=target["refused"])
            return target
        sid, _sess, pid, ct = target
        from .proctree import suspend_tree
        res = suspend_tree(
            pid, ct,
            token_dir=_pause_token_dir(self.state_path),
            deadline_secs=_pause_deadline_secs(),
        )
        _log.info("pause", handle, handle=handle, sid=sid, pid=pid,
                  ok=res.get("ok"),
                  observed=(res.get("observed") or {}).get("state"))
        return {"handle": handle, "session_id": sid, **res}

    def resume_shell(self, handle: str) -> dict:
        target = self._pause_target(handle)
        if isinstance(target, dict):
            return target
        sid, _sess, pid, ct = target
        from .proctree import resume_tree
        res = resume_tree(
            pid, ct, token_dir=_pause_token_dir(self.state_path))
        _log.info("resume", handle, handle=handle, sid=sid, pid=pid,
                  ok=res.get("ok"),
                  observed=(res.get("observed") or {}).get("state"))
        return {"handle": handle, "session_id": sid, **res}

    def _recipe_handles(self, recipe_id: str) -> list[str]:
        """Every LOCKED handle of `recipe_id`'s live rows. Fan-out is over the
        registry, never over an image name — `Never mass-suspend` means the set
        is enumerated from rows this pool wrote, and is empty when there are
        none."""
        out = []
        for sid, s in self.sessions.items():
            if s.get("state") != "active":
                continue
            if not _row_matches_recipe(s, recipe_id):
                continue
            h = s.get("handle")
            if h and self.locks.get(h) == sid:
                out.append(h)
        return out

    def pause_recipe(self, recipe_id: str) -> dict:
        handles = self._recipe_handles(recipe_id)
        results = {h: self.pause_shell(h) for h in handles}
        return {"recipe_id": recipe_id, "handles": handles,
                "paused": sum(1 for r in results.values() if r.get("ok")),
                "results": results}

    def resume_recipe(self, recipe_id: str) -> dict:
        handles = self._recipe_handles(recipe_id)
        results = {h: self.resume_shell(h) for h in handles}
        return {"recipe_id": recipe_id, "handles": handles,
                "resumed": sum(1 for r in results.values() if r.get("ok")),
                "results": results}

    # ── W12 panel data ────────────────────────────────────────────────────
    def _last_output(self, sid: str, sess: dict) -> dict:
        """W7's busyness signal, WITH the reason it is missing when it is.

        DESIGN-v6 §W12 names `last_output_ts` as the Shells view's liveness
        column. ON THIS HOST THAT COLUMN CANNOT POPULATE: `EDP_SPAWN_MODE=
        monitor`, so the pool uses `ConsoleLaunch`, which has no `log_path` —
        only headless `PtyLaunch` writes a PTY-drain log. a1 measured `None` on
        all 18 samples of a live shell.

        So the API returns the absence AND its cause, and the panel renders
        "unavailable — <why>". It does NOT substitute a plausible proxy
        (`last_seen`, `spawned_at`, a poll timestamp). A panel that displays a
        number it did not measure is the same defect as a pause that reports a
        boolean it did not observe.
        """
        ts = self.spawner.last_output_ts(sid)
        if ts is not None:
            return {"last_output_ts": ts, "last_output_available": True,
                    "last_output_reason": ""}
        mode = sess.get("mode")
        if mode == "monitor":
            why = ("monitor mode: the visible console has no PTY drain log, so "
                   "this signal does not exist for this shell")
        elif not self.spawner.knows(sid):
            why = ("orphaned across a pool restart: the in-memory PTY handle "
                   "that owns the drain log did not survive")
        else:
            why = "no drain-log mtime yet"
        return {"last_output_ts": None, "last_output_available": False,
                "last_output_reason": why}

    def panel_shells(self) -> list[dict]:
        """One row per session, with the paused indicator MEASURED per row."""
        rows = []
        for sid, s in self.sessions.items():
            handle = s.get("handle") or ""
            row = {
                "session_id": sid,
                "role": s.get("role"),
                "handle": handle,
                "recipe_id": s.get("recipe_id"),
                "state": s.get("state"),
                "spawn_mode": s.get("mode"),
                "spawned_at": s.get("spawned_at"),
                "last_seen": s.get("last_seen"),
                "liveness": self.liveness(handle) if handle else "unknown",
                **self._last_output(sid, s),
            }
            row["pause"] = (
                self.pause_state(handle) if s.get("state") == "active"
                else {"state": "unknown", "frozen": None, "measured": False,
                      "reason": "session is not active"}
            )
            rows.append(row)
        return rows

    def reap(self, handle: str) -> dict:
        """2026-05-25: DELIBERATE, orchestrator-invoked reap of the
        worker holding `handle`'s lock — force-kill the shell + release
        the lock so re-dispatch/siblings can proceed. The intelligent
        escape for a worker the neuron has JUDGED stuck/dead (replaces
        the OS-kill hack). NOT a background auto-reaper — reaping is a
        reasoned act, not an eager loop.

        `note` carries what actually happened to the PROCESS, including a
        refusal ("orphan NOT signalled: …"): the lock is always released, but
        a caller must be able to see that the shell may still be running
        rather than read a released lock as proof of a dead process."""
        sid = self.locks.get(handle)
        if sid is None:
            return {"reaped": None, "note": f"no lock held for {handle!r}"}
        killed = self._kill_session(sid)
        s = self.sessions.get(sid)
        if s is not None:
            s["state"] = "done"
        if self.locks.get(handle) == sid:
            del self.locks[handle]
        self._persist()
        return {"reaped": sid,
                "note": f"{sid}: {killed}; released {handle!r}"}


#: The static panel app. `edp-pool/src/edp_pool/service.py` → parents[2] is the
#: edp-pool repo root, self-located exactly like main.py's `_root`.
_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"

#: The sibling claude repo, whose `.recipes/<id>/briefs/*.md` the panel's plan
#: review renders. Self-located (parents[3] == <root>), same discipline as
#: main.py: a clone reads its OWN briefs, never a stray inherited path.
_AGENT_HOME = Path(__file__).resolve().parents[3] / "claude"


def _briefs_dir(recipe_id: str) -> Path:
    home = Path(os.environ.get("EDP_AGENT_HOME") or _AGENT_HOME)
    return (home / ".recipes" / recipe_id / "briefs").resolve()


def _safe_brief_path(recipe_id: str, name: str) -> Path:
    """Confine a brief read to `<agent_home>/.recipes/<recipe_id>/briefs/`.

    The panel is loopback-only and unauthenticated, so a traversal here would
    turn a read-only review surface into an arbitrary-file reader. Resolve, then
    verify containment — never trust the name, and never string-match `..`.
    """
    base = _briefs_dir(recipe_id)
    target = (base / name).resolve()
    if not target.is_relative_to(base) or target.suffix != ".md":
        raise PanelRefused(400, f"refused brief path {name!r}")
    return target


def spawn_neuron_driver(recipe_id: str, cmd: str, heartbeat_secs: float,
                        broker_url: str | None) -> int | None:
    """Launch scripts/neuron_heartbeat.py as a DETACHED child driving one
    external neuron (timer + SSE wake -> `cmd` per turn). Returns the pid or
    None. Module-level seam so tests patch it instead of spawning uv.
    Output goes to .pool-logs/neuron-driver-<recipe>.log — visible, per the
    no-invisible-shells ruling (the driver itself is tiny; the neuron turns
    it fires run in whatever window the cmd opens)."""
    import subprocess
    claude_dir = Path(
        os.environ.get("EDP_AGENT_HOME")
        or Path(__file__).resolve().parents[3] / "claude")
    log_dir = Path(__file__).resolve().parents[2] / ".pool-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in recipe_id)
    log = open(log_dir / f"neuron-driver-{safe}.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            ["uv", "run", "--project", str(claude_dir), "python",
             str(claude_dir / "scripts" / "neuron_heartbeat.py"),
             "--recipe", recipe_id, "--cmd", cmd,
             "--heartbeat-secs", str(heartbeat_secs),
             *(["--broker-url", broker_url] if broker_url else [])],
            stdout=log, stderr=subprocess.STDOUT,
            # CREATE_NO_WINDOW is CONSOLE-DETACHMENT (2026-07-20, live
            # finding): without it the driver inherits the pool's console
            # — when the stack window shut down, orphaned drivers kept the
            # supervisor cmd frozen at "Terminate batch job (Y/N)?" even
            # after Y.
            creationflags=(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            cwd=str(claude_dir))
        return proc.pid
    except Exception as e:  # noqa: BLE001 — uv missing etc.
        _log.warning("neuron_driver_spawn_failed", str(e),
                     recipe_id=recipe_id)
        return None


def run_recipe_ctl(verb: str, recipe_id: str, timeout_s: float = 300) -> dict:
    """Run scripts/recipe_ctl.py in the claude project and return its JSON
    envelope. Module-level so tests patch it instead of spawning uv.
    Bounded: suspend steers live planners to close (can take minutes);
    anything past `timeout_s` returns an honest error, never a hang."""
    import subprocess
    claude_dir = Path(
        os.environ.get("EDP_AGENT_HOME")
        or Path(__file__).resolve().parents[3] / "claude")
    try:
        proc = subprocess.run(
            ["uv", "run", "--project", str(claude_dir), "python",
             str(claude_dir / "scripts" / "recipe_ctl.py"), verb, recipe_id],
            capture_output=True, text=True, encoding="utf-8",
            timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"recipe_ctl {verb} timed out after "
                                      f"{timeout_s:.0f}s"}
    except Exception as e:  # noqa: BLE001 — uv missing etc.: honest error
        return {"ok": False, "error": f"recipe_ctl failed to launch: {e}"}
    # the ctl prints ONE json object as its LAST stdout line (logs may
    # precede it); relay it verbatim so the panel shows the tool's words.
    for line in reversed((proc.stdout or "").strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                break
    return {"ok": False,
            "error": (proc.stderr or proc.stdout or "no output")[-800:]}


def create_app(
    spawner: Spawner | None = None, broker_url: str | None = None,
    state_path: str | Path | None = None,
):
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    svc = PoolService(spawner or FakeSpawner(), broker_url, state_path)
    app = FastAPI()
    app.state.svc = svc          # the service the routes close over, for tests
    mount(app, svc)

    def _envelope(err) -> JSONResponse:
        return JSONResponse(
            status_code=_ENVELOPE_HTTP_STATUS,
            content=err.model_dump(mode="json"),
        )

    @app.exception_handler(PanelRefused)
    async def _panel_refused(_request: Request, exc: PanelRefused):
        # LOUDLY, per A2. A guard that refuses quietly is indistinguishable
        # from a route that does not exist.
        _log.warning("panel_refused", exc.detail, status=exc.status)
        return JSONResponse(status_code=exc.status,
                            content={"refused": exc.detail})

    def _panel_guard(request: Request) -> None:
        """Both request-scoped guards, in one place, for the PANEL surface."""
        require_loopback_bind()      # A2
        require_local_origin(request)  # A3

    @app.post("/v1/spawn")
    async def spawn(request: Request):
        b = await request.json()
        _log.info("POST /v1/spawn", b.get("handle", ""),
                  role=b.get("role"), handle=b.get("handle"),
                  parent=b.get("parent_session"))
        # mode precedence: request body > pool-side spawn_defaults.json (the
        # W12 panel toggle) > EDP_SPAWN_MODE env (operator global toggle) >
        # "monitor" (user ruling 2026-07-12: every shell VISIBLE by default —
        # an invisible shell burning tokens is the failure mode; headless is
        # a deliberate opt-in, never a silent fallback). Agents never choose
        # mode — it's an operator/monitoring concern, off the PoolPort.
        from .spawn_defaults import load_spawn_defaults
        mode = b.get("mode") or load_spawn_defaults().get(
            "spawn_mode") or os.environ.get("EDP_SPAWN_MODE", "monitor")
        # 2026-05-25 concurrency fix: svc.spawn does a BLOCKING PTY launch
        # (spawn + wait_ready, up to 30s, longer if a shell is slow). Run
        # it OFF the event loop so concurrent pool calls from other shells
        # aren't frozen behind it (the "all workers stuck on the MCP call"
        # symptom — the pool serialized on its event loop during a spawn).
        res = await asyncio.to_thread(
            svc.spawn,
            b["role"], b["handle"], b.get("parent_session"), mode,
            claude_session=b.get("claude_session"),
            resume_session=b.get("resume_session"),
            # s17 FA3: optional per-action model tier from the spawn body;
            # absent → None → svc.spawn defaults to the host tier (Opus).
            model=b.get("model"),
        )
        if not isinstance(res, str):  # ToolError
            return _envelope(res)
        # register the relative-ref alias into the broker (best-effort)
        if b.get("parent_session") and svc.broker_url:
            try:
                async with httpx.AsyncClient() as c:
                    await c.post(
                        f"{svc.broker_url}/v1/alias",
                        json={
                            "owner_session": b["parent_session"],
                            "alias": f"my-{b['role']}",
                            "target": res,
                        },
                    )
            except Exception:  # broker down ≠ spawn failure; log-only
                pass
        # s16: bridge a planner's colon EDP_HANDLE (`<recipe>:<step>`) to the
        # DASH inbox it actually reads on (`<recipe>-<step>`, its
        # whoami().self_address — see _self_and_parent_addresses). Without
        # this, a broker_send to the visible colon handle dead-letters into
        # the colon-sanitized `<recipe>_<step>.jsonl` the planner never polls.
        # Workers are self-consistent (self_address == colon handle) → no
        # bridge needed. Absolute (ownerless) alias; best-effort, idempotent
        # across re-spawn (same handle → same dash target).
        handle = b.get("handle", "")
        idx = handle.rfind(":")
        if b.get("role") == "planner" and idx >= 0 and svc.broker_url:
            dash = f"{handle[:idx]}-{handle[idx + 1:]}"
            try:
                async with httpx.AsyncClient() as c:
                    await c.post(
                        f"{svc.broker_url}/v1/alias",
                        json={
                            "owner_session": "*",
                            "alias": handle,
                            "target": dash,
                        },
                    )
            except Exception:  # broker down ≠ spawn failure; log-only
                pass
        return {"session_id": res}

    @app.post("/v1/release/{session_id}")
    async def release(session_id: str, body: dict | None = None):
        # DESIGN-v7 1.5.2: optional {"park": true} turns the close into a
        # park (blocking flush-wait + kill → off the event loop). No body /
        # no flag is the unchanged legacy close.
        if body and body.get("park"):
            return await asyncio.to_thread(svc.park_session, session_id)
        svc.release(session_id)
        return {"ok": True}

    @app.post("/v1/close_when_idle/{session_id}")
    async def close_when_idle(session_id: str, body: dict | None = None):
        """s26 item 1. The shell whose action just reached a TERMINAL status
        arms its own deferred reap. One session, pushed by that session — the
        pool never scans. See PoolService.arm_close_when_idle.

        DESIGN-v7 1.5.2: `{"park": true}` makes the deferred act a PARK —
        this is how a planner parks ITSELF (arm, end the turn, and the pool
        parks the quiesced shell; a self-park cannot be synchronous because
        the shell must stop consuming before the watermark is cut)."""
        body = body or {}
        return svc.arm_close_when_idle(
            session_id,
            idle_secs=float(body.get("idle_secs", 120.0)),
            reason=str(body.get("reason", "")),
            park=bool(body.get("park", False)),
        )

    @app.post("/v1/park/{handle}")
    async def park(handle: str):
        """DESIGN-v7 1.5.2: immediate park of the shell holding `handle`'s
        lock (operator/MCP surface; a shell parking ITSELF should prefer the
        close_when_idle park trigger above so it isn't killed mid-turn)."""
        _log.info("POST /v1/park", handle, handle=handle)
        return await asyncio.to_thread(svc.park, handle)

    @app.post("/v1/resume/{handle}")
    async def resume_parked(handle: str):
        """DESIGN-v7 1.5.3: fork-resume a parked handle. The MCP-side
        backstop (`pool_resume_planner`) and the pool's own resume watchdog
        both land here-or-equivalent; the parked→resuming transition makes
        the second caller a no-op."""
        _log.info("POST /v1/resume", handle, handle=handle)
        return await asyncio.to_thread(svc.resume, handle)

    @app.get("/v1/sessions")
    async def sessions(recipe_id: str | None = None):
        # W11: OPTIONAL `recipe_id` filter so a suspended recipe's rows can
        # be found without scanning every session. Absent param ⇒ the
        # unfiltered full list, exactly as before (compatibility). Rows
        # persisted by an OLD pool have no `recipe_id` key → read with
        # `.get`, never `[...]`, so a legacy row filters out, never raises.
        rows = list(svc.sessions.values())
        if recipe_id is None:
            return rows
        return [r for r in rows if _row_matches_recipe(r, recipe_id)]

    @app.get("/v1/locks")
    async def locks():
        return svc.lock_list()

    @app.get("/v1/liveness/{handle}")
    async def liveness(handle: str):
        # W7: carry the busyness signal alongside state. `last_output_ts`
        # is the epoch mtime of the shell's PTY-drain log (None when
        # unknown) — a recently-grown log = alive-and-busy even mid a
        # silent reasoning block. `state` unchanged so existing callers
        # reading ["state"] keep working.
        return {
            "handle": handle,
            "state": svc.liveness(handle),
            "last_output_ts": svc.last_output_ts(handle),
        }

    @app.post("/v1/reap/{handle}")
    async def reap(handle: str):
        _log.info("POST /v1/reap", handle, handle=handle)
        # kill is blocking-ish (terminate a process) → off the loop too.
        return await asyncio.to_thread(svc.reap, handle)

    @app.get("/v1/doctor")
    async def doctor():
        # W14 (DESIGN-v6): the same five stack-health checks the
        # `python -m edp_pool.doctor` CLI runs, as JSON for the future W12
        # panel. run_doctor's binary check + HTTP pings are blocking, so run
        # it OFF the event loop (like svc.spawn). Pass the LIVE lock table in
        # so the stale-lock sweep reads it directly instead of self-HTTPing
        # this pool's own /v1/locks.
        from .doctor import run_doctor
        return await asyncio.to_thread(
            run_doctor, broker_url=svc.broker_url, locks=svc.lock_list())

    # ══ W12 panel surface ═════════════════════════════════════════════════
    # EVERY route below runs `_panel_guard` (A2 loopback bind + A3 Origin/Host).
    # The MCP-facing routes above deliberately do not — see the block comment
    # at the top of this module.

    @app.get("/panel")
    async def panel(request: Request):
        _panel_guard(request)
        page = _STATIC_DIR / "panel.html"
        if not page.exists():
            raise PanelRefused(404, f"panel.html not found at {page}")
        return HTMLResponse(page.read_text(encoding="utf-8"))

    @app.get("/v1/panel/shells")
    async def panel_shells(request: Request):
        _panel_guard(request)
        # Measuring the paused state probes every thread of every tracked
        # tree, so keep it off the event loop.
        return await asyncio.to_thread(svc.panel_shells)

    @app.get("/v1/limits")
    async def get_limits(request: Request):
        """Effective spawn caps + which are operator overrides (panel)."""
        _panel_guard(request)
        return svc.effective_limits()

    @app.post("/v1/limits")
    async def set_limits(request: Request):
        """Operator-set caps from the panel; null clears an override back
        to its EDP_MAX_* env / code default. Persisted across restarts."""
        _panel_guard(request)
        body = await request.json()
        return svc.set_limits(body)

    @app.get("/v1/panel/channels")
    async def panel_channels(request: Request):
        """CHANNELS view backing: the broker registry, proxied (the
        panel's JS cannot cross origins to the broker)."""
        _panel_guard(request)
        if not svc.broker_url:
            raise PanelRefused(503, "no broker_url configured")
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{svc.broker_url}/v1/channels")
        return JSONResponse(status_code=r.status_code, content=r.json())

    @app.get("/v1/panel/channels/{name}/messages")
    async def panel_channel_messages(name: str, request: Request,
                                     tail: int = 50):
        """A channel's recent messages (full bodies), newest last. Pure
        read — the operator's cursor is their eyes."""
        _panel_guard(request)
        if not svc.broker_url:
            raise PanelRefused(503, "no broker_url configured")
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{svc.broker_url}/v1/inbox/{name}")
        if r.status_code != 200:
            return JSONResponse(status_code=r.status_code,
                                content=r.json())
        msgs = r.json()
        return {"channel": name, "total": len(msgs),
                "messages": msgs[-max(1, min(tail, 200)):]}

    @app.get("/v1/shells/{handle}/pause")
    async def shell_pause_state(handle: str, request: Request):
        """The MEASURED state. There is no stored counterpart to read."""
        _panel_guard(request)
        return await asyncio.to_thread(svc.pause_state, handle)

    @app.post("/v1/shells/{handle}/pause")
    async def shell_pause(handle: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(svc.pause_shell, handle)

    @app.post("/v1/shells/{handle}/resume")
    async def shell_resume(handle: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(svc.resume_shell, handle)

    @app.post("/v1/recipes/{recipe_id}/pause")
    async def recipe_pause(recipe_id: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(svc.pause_recipe, recipe_id)

    @app.post("/v1/recipes/{recipe_id}/resume")
    async def recipe_resume(recipe_id: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(svc.resume_recipe, recipe_id)

    # ── external neuron drivers (armed by the neuron's own tool call) ─────
    @app.post("/v1/neuron-driver")
    async def neuron_driver_arm(request: Request):
        _panel_guard(request)
        b = await request.json()
        return await asyncio.to_thread(
            svc.arm_neuron_driver, str(b.get("recipe_id") or ""),
            str(b.get("cmd") or ""),
            float(b.get("heartbeat_secs") or 1800))

    @app.get("/v1/neuron-driver")
    async def neuron_driver_list(request: Request):
        _panel_guard(request)
        return list(svc.neuron_drivers.values())

    @app.delete("/v1/neuron-driver/{recipe_id}")
    async def neuron_driver_disarm(recipe_id: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(svc.disarm_neuron_driver, recipe_id)

    # ── durable recipe suspend/resume (panel-driven, v7 follow-up) ────────
    # The W11 verbs live in the edp_claude tool layer (different venv); the
    # panel reaches them through scripts/recipe_ctl.py, which drives the SAME
    # tool code a neuron would and prints the tool's own JSON envelope. The
    # subprocess seam is a module function so tests can patch it.
    @app.post("/v1/recipes/{recipe_id}/suspend")
    async def recipe_suspend(recipe_id: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(
            run_recipe_ctl, "suspend", recipe_id)

    @app.post("/v1/recipes/{recipe_id}/resume-recipe")
    async def recipe_resume_durable(recipe_id: str, request: Request):
        _panel_guard(request)
        return await asyncio.to_thread(
            run_recipe_ctl, "resume", recipe_id)

    # ── panel approvals (v7 follow-up) ────────────────────────────────────
    # The hook POSTs a blocked tool call, then long-polls /wait; the panel
    # lists /pending and POSTs /decide. Loopback + origin guarded like every
    # panel surface. Fail-open end to end: any error path leaves the shell's
    # own permission flow in charge.
    @app.post("/v1/approvals")
    async def approvals_create(request: Request):
        _panel_guard(request)
        body = await request.json()
        return svc.approval_request(body if isinstance(body, dict) else {})

    @app.get("/v1/approvals/pending")
    async def approvals_pending(request: Request):
        _panel_guard(request)
        return svc.approval_pending()

    @app.post("/v1/approvals/{aid}/decide")
    async def approvals_decide(aid: str, request: Request):
        _panel_guard(request)
        body = await request.json()
        return svc.approval_decide(
            aid, str(body.get("decision") or ""), body.get("reason") or "")

    @app.get("/v1/approvals/{aid}/wait")
    async def approvals_wait(aid: str, request: Request,
                             timeout_s: float = 55.0):
        _panel_guard(request)
        return await asyncio.to_thread(svc.approval_wait, aid, timeout_s)

    # ── spawn config (FRESH SPAWNS ONLY; the panel banner says so) ────────
    @app.get("/v1/panel/spawn_defaults")
    async def get_spawn_defaults(request: Request):
        _panel_guard(request)
        from .spawn_defaults import ALLOWED_KEYS, load_spawn_defaults
        return {"defaults": load_spawn_defaults(),
                "allowed_keys": list(ALLOWED_KEYS),
                "applies_to": "fresh spawns only"}

    @app.post("/v1/panel/spawn_defaults")
    async def set_spawn_defaults(request: Request):
        _panel_guard(request)
        from .spawn_defaults import BannedSpawnDefault, save_spawn_defaults
        body = await request.json()
        try:
            written = save_spawn_defaults(body if isinstance(body, dict) else {})
        except BannedSpawnDefault as exc:
            raise PanelRefused(400, str(exc)) from exc
        _log.info("spawn_defaults_written", "", **written)
        return {"defaults": written, "applies_to": "fresh spawns only"}

    # ── plan review: render a brief the neuron wrote ─────────────────────
    @app.get("/v1/panel/briefs")
    async def list_briefs(recipe_id: str, request: Request):
        _panel_guard(request)
        d = _briefs_dir(recipe_id)
        if not d.is_dir():
            return {"recipe_id": recipe_id, "briefs": []}
        return {"recipe_id": recipe_id,
                "briefs": sorted(p.name for p in d.glob("*.md"))}

    @app.get("/v1/panel/brief")
    async def read_brief(recipe_id: str, name: str, request: Request):
        _panel_guard(request)
        p = _safe_brief_path(recipe_id, name)
        if not p.is_file():
            raise PanelRefused(404, f"no brief {name!r} for {recipe_id!r}")
        return {"recipe_id": recipe_id, "name": name,
                "text": p.read_text(encoding="utf-8")}

    # ── thin same-origin broker proxy (avoids CORS; :9300 is a second port) ─
    @app.get("/v1/broker/messages")
    async def broker_messages(request: Request, to: str | None = None,
                              kind: str | None = None,
                              since_ts: str | None = None):
        _panel_guard(request)
        if not svc.broker_url:
            raise PanelRefused(503, "no broker_url configured on this pool")
        params = {k: v for k, v in
                  (("to", to), ("kind", kind), ("since_ts", since_ts))
                  if v is not None}
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{svc.broker_url}/v1/messages", params=params)
        return JSONResponse(status_code=r.status_code, content=r.json())

    @app.post("/v1/broker/publish")
    async def broker_publish(request: Request):
        """THE ONE CHOKEPOINT (A1). Every message the panel sends to the broker
        passes through here, and every message that passes through here is
        stamped. There is no second path: this is the only place in this module
        that POSTs to the broker's publish route, and
        `test_panel_publish_is_the_only_route_to_the_broker` pins that it stays
        the only one — a second call site is how the stamp gets bypassed.
        """
        _panel_guard(request)
        if not svc.broker_url:
            raise PanelRefused(503, "no broker_url configured on this pool")
        payload = await request.json()
        if not isinstance(payload, dict):
            raise PanelRefused(400, "request body must be a JSON object")
        if not payload.get("to") or not payload.get("kind"):
            raise PanelRefused(400, "`to` and `kind` are required")
        payload.setdefault("msg_id", str(uuid.uuid4()))
        payload.setdefault("ts", _utc_now_iso())
        remote = request.client.host if request.client else None
        payload = stamp_panel_channel(payload, remote=remote)
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(f"{svc.broker_url}/v1/publish", json=payload)
        _log.info("panel_publish", payload["to"], to=payload["to"],
                  msg_kind=payload["kind"], status=r.status_code)
        return JSONResponse(status_code=r.status_code, content=r.json())

    return app
