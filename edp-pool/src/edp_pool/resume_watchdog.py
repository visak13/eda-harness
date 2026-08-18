"""Pool-side resume watchdog for DESIGN-v7 parked shells (plan 1.5.3).

A PARKED shell is a dead process with a live obligation: the moment a broker
message lands for its handle, someone must fork-resume it — but the shell has
no SSE consumer (it is not running) and the broker has no rule engine. The
pool is the one durable, always-on process that can both OBSERVE the inbox
and SPAWN the successor, so the watchdog lives here.

Shape: a daemon THREAD inside the pool process, polling every ~5s. This is
deliberately NOT the out-of-tree WMI construction `pause_watchdog.py` uses,
and the difference is principled, not lazy:

  * pause_watchdog exists to survive the POOL ITSELF dying mid-freeze — a
    frozen process nothing will ever resume is a leak, so the net must
    outlive the netter. A parked row has no such failure mode: it is
    PERSISTED pool state. If the pool dies, the restarted pool reloads the
    parked rows and this watchdog resumes watching them — nothing is lost
    but latency.
  * Pool-poll over broker-SSE: a poll loop is robust to broker restarts
    (the next tick simply succeeds) where a subscription must detect the
    broken stream and rebuild it. Pool over neuron-heartbeat: seconds of
    wake latency instead of up to 30 minutes.

FIRING DISCIPLINE (mirrors the pause watchdog's asymmetry ruling): resuming
a shell that didn't need it costs one ~30s spawn and a reground — always
recoverable. NEVER resuming a shell whose inbox has traffic strands a plan
forever. When the two errors are asymmetric, bias toward the recoverable
one. Hence:

  * depth unobservable (broker down)      → log, retry next tick. Nothing
    is inferred from silence.
  * stored watermark None (broker was down AT PARK TIME) → any observable
    depth > 0 fires. Over-eager by up to one whole inbox history, but the
    alternative — adopting the first observed depth as a baseline — can
    swallow the exact message that landed between park and first probe.
  * depth > watermark                     → fire `service.resume(handle)`.

Double-fire safety is NOT this module's job: `service.resume` takes
parked → resuming under the service's transition lock, so this watchdog and
the MCP-side backstop tool racing each other resolve to one spawn + one
no-op there, by construction.
"""

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from edp_contracts import get_logger

_log = get_logger("edp-pool")


def _agent_home() -> Path | None:
    raw = os.environ.get("EDP_AGENT_HOME", "").strip()
    return Path(raw) if raw else None


def _rx_file_sources(handles: set[str]) -> list[Path]:
    """The FILE-plane sources of every persisted rx subscription armed by
    a shell bound to one of `handles` (2026-07-19, operator ruling: "the
    agent should be able to set up the reactive stream using rxpy like
    the claude edp harness did"). The AGENT arms with observe() — the
    same protocol act as a Claude shell — which persists
    `.reactive/<sub>.spec` (its RxPY expression) + `.bindings.json`
    ({"me": handle}). A live Claude shell runs the returned monitor_cmd;
    a PARKED opencode shell cannot, so THIS watchdog is the Subscription:
    it translates the spec's file-plane sources (rx.recipe_events →
    recipe events.jsonl, rx.worklog → plan worklog.jsonl) into watched
    paths whose GROWTH resumes the shell. The broker plane needs no
    translation — it is the inbox-depth watch below."""
    home = _agent_home()
    if home is None:
        return []
    out: list[Path] = []
    rx_dir = home / ".reactive"
    if not rx_dir.is_dir():
        return []
    for bindings in rx_dir.glob("*.bindings.json"):
        try:
            me = json.loads(bindings.read_text(encoding="utf-8")).get("me")
        except (OSError, ValueError):
            continue
        if me not in handles:
            continue
        spec_file = bindings.with_name(
            bindings.name.replace(".bindings.json", ".spec"))
        try:
            spec = spec_file.read_text(encoding="utf-8")
        except OSError:
            continue
        m_ev = re.search(r"rx\.recipe_events\s*\(([^)]*)\)", spec)
        if m_ev:
            # a handle's recipe id is its longest prefix that exists as a
            # recipe dir (handles append :step / -step:action to it).
            rid = me.split(":", 1)[0]
            while rid and not (home / ".recipes" / rid).is_dir():
                rid = rid.rsplit("-", 1)[0] if "-" in rid else ""
            if rid:
                out.append((home / ".recipes" / rid / "events.jsonl",
                            _spec_kinds(m_ev.group(1))))
        m_wl = re.search(r"rx\.worklog\s*\(([^)]*)\)", spec)
        if m_wl:
            plan_id = me.split(":", 1)[0]
            out.append((home / ".plans" / plan_id / "worklog.jsonl",
                        _spec_kinds(m_wl.group(1))))
    return out


def _spec_kinds(args: str) -> frozenset[str] | None:
    """The kinds=[...] filter of one rx source call, or None = unfiltered.
    The subscription's filter is LOAD-BEARING: events.jsonl also records
    every mundane recipe_saved, and firing on raw growth woke shells for
    nothing (observed live: a console popup per store save)."""
    m = re.search(r"kinds\s*=\s*\[([^\]]*)\]", args)
    if not m:
        return None
    kinds = frozenset(re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)))
    return kinds or None


def _interval_secs() -> float:
    """Poll cadence. ~5s keeps wake latency in seconds while costing one
    cheap GET per parked handle per tick (parked handles are few by design
    — parking exists precisely because live shells are expensive)."""
    try:
        return float(os.environ.get("EDP_RESUME_WATCHDOG_SECS", "5"))
    except ValueError:
        return 5.0


def _turn_timeout_secs() -> float:
    """Hard bound on ONE turn's wall clock (2026-07-20, operator finding:
    3 hours of silence — the provider was erroring and opencode retries
    forever with no output). A turn past this bound is killed; the kill's
    nonzero exit feeds sweep_crashed, so the parent gets a `crashed`
    event instead of infinite invisible waiting. 0 disables. Default 40
    min — SME training turns legitimately run ~20-30."""
    try:
        return float(os.environ.get("EDP_TURN_TIMEOUT_SECS", "2400"))
    except ValueError:
        return 2400.0


def _heartbeat_secs() -> float:
    """The parked-shell HEARTBEAT band (1:1 parity, 2026-07-19): a Claude
    shell self-arms a 30-min CronCreate reconcile tick; a parked opencode
    shell cannot, so the pool supplies the identical backstop — a parked
    row older than this band is resumed even with ZERO inbox traffic, runs
    its reconcile (staleness delta, escalation ladder, advisories), and
    re-parks if there is nothing to do (each re-park resets the clock).
    Same 1800s default as the Claude cron band. 0 disables."""
    try:
        return float(os.environ.get("EDP_PARKED_HEARTBEAT_SECS", "1800"))
    except ValueError:
        return 1800.0


class ResumeWatchdog:
    """Daemon thread: every tick, resume any parked handle whose broker
    inbox grew past its park watermark. Constructed and started by
    `PoolService.startup()`, stopped by `shutdown()`."""

    def __init__(self, svc, interval: float | None = None):
        self.svc = svc
        self.interval = _interval_secs() if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # rx FILE-plane baselines: (sid, path) -> size when first observed
        # parked. Growth past the baseline = a new event/worklog line for a
        # subscription the shell itself armed -> resume. Over-eager by at
        # most one tick's window (asymmetry ruling: recoverable beats
        # stranded). Cleared when the row leaves parked.
        self._file_baselines: dict[tuple[str, str], int] = {}

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return  # idempotent — one watchdog per service, ever
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="edp-pool.resume-watchdog", daemon=True)
        self._thread.start()
        _log.info("resume_watchdog_started", "",
                  interval_secs=self.interval)

    def stop(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=self.interval + 1.0)
        self._thread = None

    def _run(self) -> None:
        # `wait(interval)` doubles as the sleep AND the stop signal, so a
        # shutdown never blocks behind a full tick's sleep.
        while not self._stop.wait(self.interval):
            try:
                self.tick()
            except Exception as exc:  # noqa: BLE001 — the loop must survive
                # A watchdog that dies on one bad tick is a watchdog that
                # silently stops watching — the failure mode this whole
                # module exists to prevent. Log and keep ticking.
                _log.error("resume_watchdog_tick_failed", repr(exc))

    # ── CHANNELS (topology 2026-07-21) ─────────────────────────────────
    # The registry (broker /v1/channels) is authoritative membership.
    # Two planes ride it, both no-ops while the registry is empty:
    #   * MEMBER WAKE — a channel message addressed to a parked member
    #     (body.for == its handle, or "@all") resumes it: live steering
    #     of workers lands at their next tool boundary instead of
    #     waiting out the park.
    #   * MENTION DISPATCH — a message whose `for:` names a NON-live
    #     plan:action (worker) or recipe:step (planner) handle IS the
    #     spawn signal. The hard cap refuses VISIBLY: a `blocker`
    #     message posts back into the channel, never a silent queue.
    def _channels(self) -> list[dict]:
        broker = getattr(self.svc, "broker_url", None)
        if not broker:
            return []
        try:
            import httpx
            r = httpx.get(f"{broker}/v1/channels", timeout=5.0)
            return r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001 — broker down: quiet, retry next tick
            return []

    def _channel_msgs(self, channel: str) -> list[dict]:
        broker = getattr(self.svc, "broker_url", None)
        try:
            import httpx
            r = httpx.get(f"{broker}/v1/inbox/{channel}", timeout=5.0)
            return r.json() if r.status_code == 200 else []
        except Exception:  # noqa: BLE001
            return []

    def _post_channel(self, channel: str, kind: str, body: dict) -> None:
        broker = getattr(self.svc, "broker_url", None)
        if not broker:
            return
        import uuid
        try:
            import httpx
            httpx.post(f"{broker}/v1/publish",
                       json={"msg_id": str(uuid.uuid4()),
                             "ts": datetime.now(timezone.utc).isoformat(),
                             "from": "pool", "to": channel,
                             "kind": kind, "body": body},
                       timeout=5.0)
        except Exception:  # noqa: BLE001
            pass

    def _live_handles(self) -> set[str]:
        return {s.get("handle") for s in self.svc.sessions.values()
                if s.get("state") in ("active", "parked", "resuming")}

    def channels_tick(self) -> None:
        """Member wakes + mention dispatch over the registry. Baselines
        start at first sight (never history storms)."""
        channels = self._channels()
        if not channels:
            return
        if not hasattr(self, "_chan_seen"):
            self._chan_seen: dict[str, int] = {}
        live = self._live_handles()
        parked = {s.get("handle"): sid
                  for sid, s in self.svc.sessions.items()
                  if s.get("state") == "parked"}
        for ch in channels:
            name = ch["channel"]
            members = set(ch.get("members", []))
            msgs = self._channel_msgs(name)
            base = self._chan_seen.setdefault(name, len(msgs))
            fresh, self._chan_seen[name] = msgs[base:], len(msgs)
            for msg in fresh:
                target = (msg.get("body") or {}).get("for")
                if not target:
                    continue
                if target == "@all":
                    for h, sid in parked.items():
                        if h in members:
                            self.svc.resume(h)
                    continue
                if target in parked:
                    _log.info("channel_member_wake", target,
                              handle=target, channel=name)
                    self.svc.resume(target)
                # OPERATOR RULING (2026-07-21): "only an agent can spawn
                # an agent using tools." A mention of a NON-live handle
                # spawns NOTHING here — dumb logic never initiates a
                # token-spending process. Mentions ADDRESS and WAKE;
                # dispatch is a pool_spawn_* tool call made by a drive
                # agent (PM/Team Lead), full stop. The addressed message
                # waits in the channel and delivers the moment an agent
                # dispatches that handle.

    def _publish_crashed(self, crash: dict) -> None:
        """Announce one detected crash as CORE kind `crashed` in the
        parent handle's inbox. Best-effort: broker down leaves the dead
        row standing — the parent's heartbeat band finds it via liveness
        on its next reconcile."""
        parent = crash.get("parent")
        broker = getattr(self.svc, "broker_url", None)
        if not parent or not broker:
            return
        import uuid
        try:
            import httpx
            httpx.post(
                f"{broker}/v1/publish",
                json={"msg_id": str(uuid.uuid4()),
                      "ts": datetime.now(timezone.utc).isoformat(),
                      "from": crash["handle"], "to": parent,
                      "kind": "crashed",
                      "body": {"handle": crash["handle"],
                               "session_id": crash["session_id"],
                               "exit_code": crash["exit_code"]}},
                timeout=5.0)
        except Exception as exc:  # noqa: BLE001
            _log.warning("crash_publish_failed", crash["handle"],
                         handle=crash["handle"], err=repr(exc))

    def tick(self) -> list[str]:
        """One pass over the parked rows. Returns the handles it resumed
        (unit tests drive this directly — no thread, no sleeping)."""
        resumed: list[str] = []
        # crash flowback first: the service DETECTS-AND-MARKS dead turn
        # clients; THIS watchdog announces each as the CORE `crashed`
        # kind into the parent's inbox — which the very same tick's inbox
        # watch below can then deliver as a wake.
        try:
            # turn-timeout: kill any turn client stuck past the bound so
            # the crash sweep below converts it into a `crashed` event.
            bound = _turn_timeout_secs()
            if bound > 0:
                for _tsid, _ts in list(self.svc.sessions.items()):
                    if _ts.get("state") != "active":
                        continue
                    runtime = getattr(self.svc.spawner, "turn_runtime",
                                      lambda _s: None)(_tsid)
                    if runtime is not None and runtime > bound:
                        _log.warning(
                            "turn_timeout_kill", _ts.get("handle") or _tsid,
                            handle=_ts.get("handle"), sid=_tsid,
                            runtime_secs=int(runtime), bound_secs=int(bound))
                        self.svc.spawner.kill(_tsid)
            for c in self.svc.sweep_crashed():
                self._publish_crashed(c)
        except Exception as exc:  # noqa: BLE001 — never kill the tick
            _log.error("sweep_crashed_failed", repr(exc))
        try:
            self.channels_tick()
        except Exception as exc:  # noqa: BLE001 — never kill the tick
            _log.error("channels_tick_failed", repr(exc))
        # snapshot: service methods mutate `sessions` concurrently
        for _sid, s in list(self.svc.sessions.items()):
            if s.get("state") != "parked":
                for key in [k for k in self._file_baselines
                            if k[0] == _sid]:
                    self._file_baselines.pop(key, None)
                continue
            handle = s.get("handle")
            if not handle:
                continue
            # Watch EVERY handle the shell consumes (a planner's worker
            # flowback lands on its PLAN handle, not its spawn handle —
            # the M3 stranding bug). Watermarks are per-handle; rows parked
            # before `watermarks` existed fall back to the legacy
            # spawn-handle mark for the spawn handle and None (= fire on
            # any traffic) for derived ones.
            parked = s.get("parked") or {}
            marks = parked.get("watermarks") or {
                handle: parked.get("inbox_watermark")}
            for h in self.svc._watch_handles(s):
                depth = self.svc._inbox_depth(h)
                if depth is None:
                    # broker down/unreachable: nothing observed ⇒ nothing
                    # inferred. Retry next tick — robustness to broker
                    # downtime is why this polls instead of subscribing.
                    _log.debug("resume_watchdog_broker_unreachable", h,
                               handle=h)
                    continue
                watermark = marks.get(h)
                if watermark is None:
                    # park couldn't observe the broker; fire on ANY traffic
                    # (see module docstring — over-eager beats stranded).
                    if depth > 0:
                        _log.info("resume_watchdog_fire_no_watermark",
                                  handle, handle=handle, watched=h,
                                  depth=depth)
                        self.svc.resume(handle)
                        resumed.append(handle)
                        break
                    continue
                if depth > watermark:
                    _log.info("resume_watchdog_fire", handle, handle=handle,
                              watched=h, depth=depth, watermark=watermark)
                    self.svc.resume(handle)
                    resumed.append(handle)
                    break
            if handle in resumed:
                continue
            # rx FILE plane — the shell's OWN observe() subscriptions
            # (rx.recipe_events / rx.worklog sources), executed here
            # because a parked shell has no Monitor to run them. The
            # spec's kinds filter is honored: appended lines are read and
            # only a MATCHING kind fires; non-matching growth is consumed
            # silently (baseline advances) so it can never re-trigger.
            for path, kinds in _rx_file_sources(
                    set(self.svc._watch_handles(s))):
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                key = (_sid, str(path))
                # F36 R4#15: seed the baseline from the PARK-TIME capture
                # when the park recorded one — first-tick adoption hid any
                # event that landed in the park→first-tick gap forever.
                if key not in self._file_baselines:
                    _park_bases = ((s.get("parked") or {})
                                   .get("file_baselines") or {})
                    _seed = _park_bases.get(str(path))
                    self._file_baselines[key] = (
                        int(_seed) if _seed is not None else size)
                base = self._file_baselines[key]
                if size <= base:
                    continue
                fire = kinds is None
                if not fire:
                    try:
                        with path.open("rb") as f:
                            f.seek(base)
                            delta = f.read(size - base).decode(
                                "utf-8", "replace")
                        for line in delta.splitlines():
                            try:
                                if json.loads(line).get("kind") in kinds:
                                    fire = True
                                    break
                            except ValueError:
                                continue
                    except OSError:
                        continue
                self._file_baselines[key] = size
                if fire:
                    _log.info("resume_watchdog_rx_file_fire", handle,
                              handle=handle, watched=str(path),
                              size=size, baseline=base)
                    self.svc.resume(handle)
                    resumed.append(handle)
                    break
            if handle in resumed:
                continue
            # No traffic — the cron-parity heartbeat backstop: resume any
            # row parked longer than the band so it runs one reconcile
            # turn, exactly what a Claude shell's 30-min cron fires.
            beat = _heartbeat_secs()
            parked_at = parked.get("parked_at")
            if beat > 0 and parked_at:
                try:
                    age = (datetime.now(timezone.utc)
                           - datetime.fromisoformat(parked_at)
                           ).total_seconds()
                except ValueError:
                    age = None
                if age is not None and age > beat:
                    _log.info("resume_watchdog_heartbeat", handle,
                              handle=handle, parked_secs=int(age),
                              band_secs=int(beat))
                    self.svc.resume(handle)
                    resumed.append(handle)
        return resumed
