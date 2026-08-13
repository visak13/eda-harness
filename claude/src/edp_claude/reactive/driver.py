"""Reactive driver — compiles an observe() spec to an RxPY pipeline and
emits NDJSON, one line per emission, that a Claude Code `Monitor` watches.

Run as a standalone process (one per `observe()` call / Subscription):

    python -m edp_claude.reactive.driver --spec-file <path> [--bindings-file <path>]

Each emission prints `{"event": <payload>}`; a stream error prints
`{"error": "..."}`; completion prints `{"completed": true}`. The sink
only WAKES the watching shell + delivers the payload — it performs no
mutation (that stays in the object/CRUD surface).
"""

import json
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import reactivex as rx
from reactivex import Observable
from reactivex import operators as ops
from reactivex.disposable import Disposable

from .effects import EffectDispatcher, EffectSpec, is_self_echo
from .runtime import RxRuntime, compile_spec


# ── NDJSON sink + run loop ────────────────────────────────────────────────
def run(observable: Observable, out: TextIO | None = None,
        dispatcher: "EffectDispatcher | None" = None,
        owner: str = "") -> None:
    """Subscribe to `observable`, emit NDJSON to `out` (stdout), block
    until the stream completes or errors. For an infinite stream this
    blocks until the process is killed (Monitor stops it = unsubscribe).

    Sensory nerve (default, `dispatcher=None`): every emission is printed as
    `{"event": ...}` and the watching Monitor wakes the shell — NO mutation.

    Motor nerve (`dispatcher` set): every emission ALSO flows through the
    governed EffectDispatcher (allowlist + idempotency + rate + audit +
    advisory-by-default). The dispatcher's per-decision audit line is emitted
    on the SAME NDJSON stream so the watching shell sees every effect decision.
    The 'rx observes, CRUD mutates' invariant holds: rx still only observes;
    the only writes are the dispatcher's narrow, sanctioned, audited valve."""
    out = out or sys.stdout
    done = threading.Event()

    def _emit(obj: dict) -> None:
        out.write(json.dumps(obj, default=str) + "\n")
        out.flush()

    def on_next(value: Any) -> None:
        # WP3 sensory echo filter (2026-08-12): never wake a shell for an
        # event it authored itself (own-worklog tail, own outbound mirror).
        # Silent drop — a self-echo is non-signal by definition.
        if owner and is_self_echo(value, owner):
            return
        _emit({"event": value})
        if dispatcher is not None:
            # the motor nerve: one governed, audited decision per emission.
            decision = dispatcher.handle(value)
            _emit({"effect_audit": decision.as_audit_line()})

    def on_error(err: Exception) -> None:
        _emit({"error": str(err)})
        done.set()

    def on_completed() -> None:
        _emit({"completed": True})
        done.set()

    sub = observable.subscribe(
        on_next=on_next, on_error=on_error, on_completed=on_completed)
    try:
        done.wait()
    finally:
        sub.dispose()


# ── real advisory executor + file audit sink (the production motor wiring) ──
def _record_context(repo_root: Path, args: dict[str, Any]) -> Any:
    """Execute the allowlisted `record_context` effect through the REAL tool —
    the same verb a shell calls, so an effect-written decision is stored by the
    same code path as a hand-written one (no second writer to drift).

    The tool body is async and the rx sink is a plain thread with no running
    loop, so it runs on its own loop. The decision / assumption /
    rejected_option routes touch the recipe store only — never the broker or
    the pool — so the stub-backed context is the whole dependency, and there is
    no client to leak."""
    import asyncio

    from ..server import make_context
    from ..tools._tools import RecordContext

    return asyncio.run(RecordContext(make_context(repo_root)).run(dict(args)))


def make_broker_executor(broker_url: str, parent: str | None = None,
                         repo_root: Path | None = None):
    """The real Tier-1 ADVISORY executor: `broker_send` (observation) and
    `notify_above` (to the parent inbox) over the broker's POST /v1/publish,
    plus `record_context` — the opt-in advisory action, which appends to recipe
    context through the real verb (append-only, reversible; it is the ONE write
    the allowlist permits, and only for a rule that opted in with
    `mutating:true`).

    Tier-2 mutating actions never reach an executor in Phase 2 (the dispatcher
    dark-gates them), so this executor deliberately knows nothing else — an
    unexpected action raises (never a silent mutation)."""
    import uuid
    from datetime import datetime, timezone

    import httpx

    def _publish(to: str, kind: str, body: dict) -> Any:
        # A complete BrokerMessage envelope: the broker REQUIRES msg_id + a
        # tz-aware UTC ts and validates them (a partial dict is rejected 409).
        # `from` is the wire alias for the model's `from_` field.
        msg = {
            "msg_id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc).isoformat(),
            "from": "motor-nerve",
            "to": to,
            "kind": kind,
            "body": body,
        }
        with httpx.Client(timeout=10) as c:
            r = c.post(f"{broker_url.rstrip('/')}/v1/publish", json=msg)
            r.raise_for_status()
            return r.json()

    def executor(action: str, args: dict[str, Any]) -> Any:
        if action == "broker_send":
            return _publish(args["to"], args.get("kind", "observation"),
                            args.get("body", {}))
        if action == "notify_above":
            dest = parent or args.get("to")
            if not dest:
                raise ValueError("notify_above needs a parent inbox")
            return _publish(dest, args.get("kind", "observation"),
                            args.get("body", {}))
        if action == "record_context":
            return _record_context(repo_root or Path("."), args)
        raise ValueError(
            f"motor-nerve advisory executor refuses action {action!r} "
            "(Phase 2 = Tier-1 advisory only)")

    return executor


def make_file_audit_sink(path: Path):
    """Append-only JSONL audit sink (the same append-only mechanism the rest of
    the system reads). One line per effect decision."""
    path.parent.mkdir(parents=True, exist_ok=True)

    def sink(line: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")

    return sink


# ── real threaded I/O sources (production source_provider) ────────────────
@dataclass
class RealConfig:
    broker_url: str = "http://127.0.0.1:9300"
    pool_url: str = "http://127.0.0.1:9301"
    repo_root: Path = Path(".")
    poll_ms: int = 2000


def _threaded(producer: Callable[[Any, threading.Event], None]) -> Observable:
    """Wrap a blocking producer loop in an Observable. `producer(observer,
    stop)` runs on a daemon thread and must poll `stop` so disposal
    (Monitor teardown) actually stops the I/O."""
    def on_subscribe(observer, scheduler=None):  # noqa: ANN001
        stop = threading.Event()

        def loop():
            try:
                producer(observer, stop)
                if not stop.is_set():
                    observer.on_completed()
            except Exception as exc:  # noqa: BLE001 — domain transport error
                if not stop.is_set():
                    observer.on_error(exc)

        t = threading.Thread(target=loop, daemon=True)
        t.start()
        return Disposable(lambda: stop.set())

    return rx.create(on_subscribe)


# sentinels for the change-detecting poller
_UNSET = object()
_SKIP = object()


def _tail_jsonl(path: Path, observer, stop: threading.Event,
                poll_ms: int, replay: bool = False) -> None:
    """Follow appends (tail -F). `replay=False` (default) seeks to EOF
    first → only NEW entries wake the subscriber; the historical entries
    (e.g. the plan-authoring `plan_saved` lines) are NOT replayed as
    wakes — that was pure noise on every fresh subscription (the s6
    planner's 'historical plan_saved replays'). Catch-up after a gap is
    via read_worklog / the heartbeat, not a wake storm. `replay=True`
    opts back into full history (the reconnect-replay use)."""
    pos: int | None = None
    while not stop.is_set():
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                if pos is None:
                    if replay:
                        pos = 0
                    else:
                        f.seek(0, 2)        # EOF — follow-only
                        pos = f.tell()
                f.seek(pos)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            observer.on_next(json.loads(line))
                        except json.JSONDecodeError:
                            pass
                pos = f.tell()
        stop.wait(poll_ms / 1000.0)


def _poll_changes(fetch: Callable[[], Any], observer,
                  stop: threading.Event, poll_ms: int) -> None:
    """Poll `fetch()` each tick but emit ONLY when the value changed.
    State-snapshot sources (pool/plan) are data-plane: an unchanged
    snapshot is pure noise (the rx.pool() flood that buried the s6
    planner in identical multi-recipe dumps). Change-detection turns them
    into control-plane signals — a pool emit is a real liveness change
    (a crash!), a plan emit is a real action-status transition. `fetch`
    returns `_SKIP` to mean 'nothing to read this tick' (e.g. plan file
    not written yet); any exception is treated as `_SKIP`."""
    last = _UNSET
    while not stop.is_set():
        try:
            val = fetch()
        except Exception:  # noqa: BLE001 — a transient read is just a skip
            val = _SKIP
        if val is not _SKIP:
            key = json.dumps(val, sort_keys=True, default=str)
            if key != last:
                # Item 6: suppress the startup empty-snapshot wake — the first
                # tick ([]/{}) differs from _UNSET and would emit one spurious
                # wake per fresh subscription; record it without emitting.
                first_empty = last is _UNSET and not val
                last = key
                if not first_empty:
                    observer.on_next(val)
        stop.wait(poll_ms / 1000.0)


def _parse_ts(value: Any) -> "datetime | None":
    """Parse an ISO-8601 broker `ts` to an aware datetime (None if it can't
    be parsed). Naive timestamps are assumed UTC so a comparison with the
    connect-time cutoff is always tz-aware — matching how the broker stores
    `BrokerMessage.ts` (a tz-aware UTC datetime)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _follow_only(messages: Observable, cutoff: "datetime | None") -> Observable:
    """Follow-only boundary for a broker message stream — the wire-side twin
    of `_tail_jsonl(replay=False)`'s seek-to-EOF. Drops every message whose
    `ts` is at-or-before `cutoff` (the connect-time instant), so only NEW
    messages (`ts > cutoff`) wake the subscriber. Strict `>` and datetime
    comparison mirror the broker's own `read(..., since)` (`m.ts > since`),
    so this client-side guard is byte-for-byte equivalent to the broker
    filtering and holds regardless of transport (also makes follow-only
    unit-testable with an injected observable). `cutoff=None` → no filter
    (the explicit replay / full-history path). A message whose `ts` can't be
    parsed is KEPT (never silently dropped — the broker already applied the
    same `since` boundary upstream)."""
    if cutoff is None:
        return messages

    def _after_cutoff(msg: Any) -> bool:
        ts = _parse_ts(msg.get("ts") if isinstance(msg, dict) else None)
        return ts is None or ts > cutoff

    return messages.pipe(ops.filter(_after_cutoff))


class RealSources:
    """The production `source_provider` — real broker SSE / file tails /
    pool polling. Constructed by the CLI; not used in unit tests (they
    inject deterministic observables instead)."""

    def __init__(self, cfg: RealConfig):
        self.cfg = cfg

    def __call__(self, name: str, **kw: Any) -> Observable:
        fn = getattr(self, f"_src_{name}", None)
        if fn is None:
            raise ValueError(f"unknown reactive source {name!r}")
        return fn(**kw)

    def _src_broker(self, recipient: str, since: str | None = None,
                    replay: bool = False) -> Observable:
        # FOLLOW-ONLY DEFAULT (FA2-F1) — the wire twin of
        # `_tail_jsonl(replay=False)`'s seek-to-EOF. The broker retains every
        # message ever sent to a recipient; a fresh subscribe with no `since`
        # used to replay the WHOLE inbox as wakes (the ~10x first-subscribe
        # storm: tens of historical `answer`/`steer`/`done` lines re-fired on
        # every resumed neuron / newly spawned shell). Now, when `replay` is
        # off and no explicit `since` is given, the cursor is seeded to
        # connect-time so the first request carries `since_ts=now` and only
        # NEW messages (`ts > now`) wake — catch-up after a gap is the
        # heartbeat's job (reconcile / check_inbox), per the doctrine.
        #
        # Opt back into history via `replay=True` (full inbox, the
        # reconnect-replay use) or `since=<ts>` (catch up from a known point).
        # ZERO broker change: `since_ts` already filters server-side
        # (`store.read`: `m.ts > since`); `_follow_only` re-applies the
        # identical boundary client-side so the semantics are transport-
        # independent and unit-testable.
        import httpx

        if replay:
            effective_since = since          # None → full history; ts → from ts
        elif since is not None:
            effective_since = since          # explicit catch-up point
        else:
            effective_since = datetime.now(timezone.utc).isoformat()  # now
        cutoff = None if replay else _parse_ts(effective_since)

        def producer(observer, stop):
            last = effective_since
            while not stop.is_set():
                params = {"recipient": recipient, "max_seconds": 600}
                if last:
                    params["since_ts"] = last
                try:
                    with httpx.Client(timeout=None) as c, c.stream(
                        "GET", f"{self.cfg.broker_url}/v1/events", params=params
                    ) as resp:
                        for line in resp.iter_lines():
                            if stop.is_set():
                                return
                            if line.startswith("data:"):
                                msg = json.loads(line[len("data:"):].strip())
                                last = msg.get("ts", last)
                                observer.on_next(msg)
                except Exception:  # noqa: BLE001 — reconnect on drop
                    stop.wait(1.0)  # backoff before reconnect (with `last`)

        return _follow_only(_threaded(producer), cutoff)

    def _src_worklog(self, plan_id: str | None = None,
                     recipe_id: str | None = None,
                     replay: bool = False) -> Observable:
        if plan_id:
            path = self.cfg.repo_root / ".plans" / plan_id / "worklog.jsonl"
        elif recipe_id:
            path = self.cfg.repo_root / ".recipes" / recipe_id / "events.jsonl"
        else:
            raise ValueError("worklog source needs plan_id or recipe_id")
        return _threaded(
            lambda obs, stop: _tail_jsonl(
                path, obs, stop, self.cfg.poll_ms, replay=replay))

    def _src_recipe(self, recipe_id: str,
                    replay: bool = False) -> Observable:
        return self._src_worklog(recipe_id=recipe_id, replay=replay)

    def _src_plan(self, plan_id: str) -> Observable:
        # data-plane: re-reads the whole plan each tick → emit ONLY when an
        # action status actually changes (not the same dict every poll).
        path = self.cfg.repo_root / ".plans" / f"{plan_id}.json"

        def fetch():
            if not path.exists():
                return _SKIP
            data = json.loads(path.read_text(encoding="utf-8"))
            return {a["action_id"]: a["status"]
                    for a in data.get("actions", [])}

        return _threaded(
            lambda obs, stop: _poll_changes(
                fetch, obs, stop, self.cfg.poll_ms))

    def _src_pool(self, handle: str | None = None,
                  scope: str | None = None,
                  states: list[str] | None = None) -> Observable:
        # data-plane: GET /v1/locks returns EVERY recipe's locks each tick.
        # `scope`/`handle` is a HANDLE PREFIX (a plan_id or recipe_id) to
        # filter to the subscriber's own shells; change-detection then
        # emits only on a real liveness change → a pool wake = a crash
        # signal, not idle noise.
        import httpx

        prefix = scope or handle

        def fetch():
            r = httpx.get(f"{self.cfg.pool_url}/v1/locks", timeout=10)
            rows = r.json() if r.status_code // 100 == 2 else []
            if prefix:
                rows = [lk for lk in rows
                        if str(lk.get("handle", "")).startswith(prefix)]
            # Item 6: optional state filter (a scoped pool wake should be a
            # CRASH signal — states=['dead'] — not every spawn/clean-close) +
            # canonical order so a remove-then-readd reorder of the lock list
            # does not spuriously wake change-detection.
            if states:
                sset = set(states)
                rows = [lk for lk in rows if lk.get("liveness") in sset]
            # canonical {handle, liveness} projection: drop the volatile
            # session_id (a reap-then-respawn of the same handle gets a new id
            # and would otherwise churn the snapshot) + sort (order-independent
            # so a remove-then-readd reorder does not spuriously wake). A pool
            # event is now a real handle->liveness change, nothing else.
            rows = sorted(
                ({"handle": lk.get("handle"),
                  "liveness": lk.get("liveness")} for lk in rows),
                key=lambda lk: (str(lk["handle"]), str(lk["liveness"])))
            return rows

        return _threaded(
            lambda obs, stop: _poll_changes(
                fetch, obs, stop, self.cfg.poll_ms))

    def _src_orphaned(self, plan_id: str | None = None,
                      recipe_id: str | None = None,
                      grace_secs: float | None = None) -> Observable:
        """Actions left DISPATCHED with no live worker behind them.

        THE GAP THIS CLOSES (2026-07-25). A worker that finishes its file and
        then exits WITHOUT recording status emits nothing on any existing
        plane: there is no crash, so no `child_crashed`; the session simply
        stops appearing in the pool snapshot. `rx.pool` is a LEVEL (a polled
        list) and a level that stops arriving is indistinguishable from a quiet
        channel — so the one event a planner most needs was the one event
        structurally incapable of reaching it. The stall stayed invisible until
        somebody happened to call `reconcile`, which made the heartbeat
        interval the de-facto stall detector. It was never the right
        instrument, and paying a poll a minute to narrow that window is how the
        observation budget got burned.

        This source turns that ABSENCE into an EDGE by JOINING two things
        neither plane knows about the other: the plan's action statuses and the
        pool's liveness. It deliberately does NOT emit a raw worker-exit — that
        would fire on every normal close, become noise, and get ignored, which
        is exactly how the original blindness survived. A wake here always
        means: work is recorded as underway and nothing is doing it.

        BATCH RESOLUTION is the load-bearing part. A batch unit runs as ONE
        shell registered under the HEAD action's handle; non-head members have
        no handle of their own, so probing `<plan_id>:<member>` asks about a
        handle that never existed, finds nothing, and reads as dead. Members
        are therefore resolved to their head before liveness is consulted —
        the same rule a planner has to apply by hand today.

        The GRACE window is what keeps this honest: `next_action` stamps
        `in_progress` before the spawn completes, so an action legitimately
        sits dispatched-without-a-lock for a moment. Anything younger than the
        grace is not reported.
        """
        import os
        import time

        import httpx

        if grace_secs is None:
            try:
                grace_secs = float(
                    os.environ.get("EDP_ORPHAN_GRACE_SECS", "90"))
            except ValueError:
                grace_secs = 90.0

        if not plan_id and not recipe_id:
            raise ValueError("orphaned source needs plan_id or recipe_id")

        plan_path = self.cfg.repo_root / ".plans" / f"{plan_id}.json"
        recipe_path = (self.cfg.repo_root / ".recipes"
                       / str(recipe_id) / "recipe.json")
        # action_id (or step_id) -> monotonic ts it was FIRST seen unbacked.
        first_unbacked: dict[str, float] = {}

        def _alive_handles() -> set[str]:
            r = httpx.get(f"{self.cfg.pool_url}/v1/locks", timeout=10)
            rows = r.json() if r.status_code // 100 == 2 else []
            return {str(lk.get("handle")) for lk in rows
                    if lk.get("liveness") == "alive"}

        def _aged(unit_id: str, backing: str | set[str], now: float,
                  seen: set[str], alive: set[str]) -> int | None:
            """None if backed or still inside the grace window; else the age.
            `backing` may be a SET of candidate handle forms — live-drill fix
            (2026-08-07): a planner's pool LOCK registers under the COLON
            spawn handle while its broker inbox is the DASH form; probing
            only one form false-fired "orphaned" every poll for a planner
            that was alive all along (the monitor-event flood)."""
            candidates = backing if isinstance(backing, set) else {backing}
            if candidates & alive:
                first_unbacked.pop(unit_id, None)
                return None
            seen.add(unit_id)
            since = first_unbacked.setdefault(unit_id, now)
            age = now - since
            if age < grace_secs:
                return None
            # MINUTE-quantized so the emitted payload is stable between
            # polls — a raw seconds age made every poll look "changed" and
            # defeated downstream dedup (part of the 2026-08-07 flood).
            return int(age // 60) * 60

        def fetch_recipe():
            """The NEURON's half of the same defect. One level up, the shell
            that can vanish without recording is a PLANNER, and the record it
            leaves behind is a step stuck `in_progress` with no planner alive.
            The neuron's prescribed subscription watches its own inbox and dead
            pool locks — neither of which fires when a planner exits cleanly
            having recorded nothing, so the neuron waits on a `plan_closed`
            that will never be sent. Same absence, same invisibility, one
            level up."""
            if not recipe_path.exists():
                return _SKIP
            data = json.loads(recipe_path.read_text(encoding="utf-8"))
            steps = [s for s in data.get("steps", []) if isinstance(s, dict)]
            open_steps = [s for s in steps if s.get("status") == "in_progress"
                          and s.get("execution") == "spawn_planner"]
            if not open_steps:
                first_unbacked.clear()
                return []
            alive = _alive_handles()
            now = time.monotonic()
            orphans, seen = [], set()
            for s in open_steps:
                sid = str(s.get("step_id"))
                # Live-drill fix (2026-08-07): the pool LOCK registers the
                # COLON spawn handle `<recipe>:<step>`; the broker inbox is
                # the DASH form. Accept either — probing only the dash form
                # false-fired every 2s for a demonstrably alive planner.
                backings = {f"{recipe_id}:{sid}", f"{recipe_id}-{sid}"}
                age = _aged(sid, backings, now, seen, alive)
                if age is None:
                    continue
                orphans.append({
                    "step_id": sid,
                    "status": s.get("status"),
                    "backing_handle": sorted(backings),
                    "unbacked_secs": age,
                    "reason": "step dispatched with no live planner",
                })
            for gone in set(first_unbacked) - seen:
                first_unbacked.pop(gone, None)
            return sorted(orphans, key=lambda o: o["step_id"])

        def _group_members(actions: list[dict]) -> dict[str, list[str]]:
            """batch_group -> every member action_id in declared order.

            2026-08-13 (live s1 observation): the previous head resolution
            was STATIC — first-in-declared-order. A batch re-dispatched
            under a LATER member after its original head exited (head a1
            dies mid-batch, planner re-spawns under a2) left the remaining
            members probing the dead a1 forever: a 60s false-orphan flood
            with no planner move that stops it. The truthful rule: ONE
            shell runs a batch under SOME member's handle, so a member is
            backed iff ANY member of its group holds a live session."""
            members: dict[str, list[str]] = {}
            for a in actions:
                aid = a.get("action_id")
                grp = a.get("batch_group")
                if aid and grp:
                    members.setdefault(grp, []).append(str(aid))
            return members

        def fetch_plan():
            if not plan_path.exists():
                return _SKIP
            data = json.loads(plan_path.read_text(encoding="utf-8"))
            actions = [a for a in data.get("actions", [])
                       if isinstance(a, dict)]
            members = _group_members(actions)

            # Only a DISPATCHED action needs a worker behind it. Terminal
            # statuses need nothing, and `pending` has not been handed out yet.
            dispatched = [a for a in actions
                          if a.get("status") == "in_progress"]
            if not dispatched:
                first_unbacked.clear()
                return []

            alive = _alive_handles()
            now = time.monotonic()
            orphans, seen = [], set()
            for a in dispatched:
                aid = str(a.get("action_id"))
                grp = a.get("batch_group")
                # An action's OWN handle always counts; a batched action is
                # ALSO backed by any group member's live shell — one shell
                # runs the batch under SOME member's handle, and which member
                # that is changes when the batch is re-dispatched after a
                # partial exit (see _group_members). Probing a static head
                # false-fired every poll for a healthy batch.
                candidates = {f"{plan_id}:{aid}"}
                if grp:
                    candidates |= {f"{plan_id}:{m}"
                                   for m in members.get(grp, [])}
                age = _aged(aid, candidates, now, seen, alive)
                if age is None:
                    continue
                orphans.append({
                    "action_id": aid,
                    "status": a.get("status"),
                    "backing_handle": sorted(candidates),
                    "batch_group": grp,
                    "unbacked_secs": age,
                    "reason": ("batch member with no live shell in its group"
                               if grp
                               else "dispatched with no live worker"),
                })
            for gone in set(first_unbacked) - seen:
                first_unbacked.pop(gone, None)
            return sorted(orphans, key=lambda o: o["action_id"])

        fetch = fetch_recipe if recipe_id else fetch_plan
        return _threaded(
            lambda obs, stop: _poll_changes(
                fetch, obs, stop, self.cfg.poll_ms))

    def _src_external(self, url: str, mode: str = "get",
                      **kw: Any) -> Observable:
        import httpx

        def producer(observer, stop):
            last = _UNSET
            while not stop.is_set():
                try:
                    r = httpx.get(url, timeout=30)
                    val = (r.json() if "json" in r.headers.get(
                        "content-type", "") else r.text)
                except Exception as exc:  # noqa: BLE001 — failure-as-value
                    val = {"external_error": str(exc), "url": url}
                # dedup so a polled changefeed returning identical content
                # doesn't re-wake (data-plane reduction); `once` always
                # emits its single sample.
                key = json.dumps(val, sort_keys=True, default=str)
                if mode == "once":
                    observer.on_next(val)
                    return
                if key != last:
                    last = key
                    observer.on_next(val)
                stop.wait(self.cfg.poll_ms / 1000.0)

        return _threaded(producer)


# ── per-handle subscription lookup (W2 leg 2 — the rewire hand-back source) ──
def serve_handle_specs(handle: str,
                       agent_home: "str | Path | None" = None) -> list[dict]:
    """Every persisted observe subscription registered to `handle`, each as
    `{sid, spec, bindings, effect}`, resolved from the `.reactive` root under
    EDP_AGENT_HOME. The read-only per-handle spec lookup the W2 rewire
    hand-back reads and this driver's `--lookup-handle` CLI serves — so a
    compacted shell (or a fresh driver process) can rediscover its own wiring
    from disk with no session memory. Deterministic, stdlib, no I/O beyond the
    local `.reactive` files."""
    from .handle_index import specs_for_handle

    import os as _os
    home = Path(agent_home or _os.environ.get("EDP_AGENT_HOME", "."))
    return specs_for_handle(home / ".reactive", handle)


# ── CLI ───────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(prog="edp-reactive-driver")
    ap.add_argument("--spec-file")
    ap.add_argument("--bindings-file")
    # W2 leg 2: serve the per-handle subscription lookup (print JSON + exit)
    # instead of running a stream. This is the rewire hand-back's disk source
    # exposed on the driver a fresh shell already knows how to invoke.
    ap.add_argument("--lookup-handle",
                    help="print the JSON list of observe subscriptions "
                         "registered to this handle and exit")
    # Phase 2-A motor nerve: an OPTIONAL governed EffectSpec (declarative JSON).
    # Absent → pure sensory nerve (wake only), exactly as before.
    ap.add_argument("--effect-file",
                    help="declarative EffectSpec JSON → governed actionable sink")
    ap.add_argument("--owner", default="",
                    help="this rule's owner inbox (provenance / echo filter)")
    # W7 part 4: the per-spec rate-limit knob. 0 (default) = off = today's
    # every-emission wake. >0 caps the wake rate of the CHATTY POLLED sources
    # (RATE_LIMITABLE_SOURCES: pool/plan/external) at one emission per window,
    # BEFORE any merge. Critical sources (broker/worklog/recipe_events) are
    # never limited, so no knob setting can starve a once-only event.
    ap.add_argument("--min-interval-ms", type=float, default=0.0,
                    help="rate-limit the chatty POLLED sources (pool/plan/"
                         "external) to one wake per this window (ms), applied "
                         "per-source before the merge; critical sources are "
                         "never limited; 0 = off")
    args = ap.parse_args(argv)

    # W2 leg 2: per-handle spec lookup — serve the hand-back source, then exit.
    if args.lookup_handle:
        specs = serve_handle_specs(args.lookup_handle)
        print(json.dumps(  # noqa: T201 — CLI output IS this subcommand's result
            {"handle": args.lookup_handle, "subscriptions": specs},
            default=str))
        return 0
    if not args.spec_file:
        ap.error("--spec-file is required unless --lookup-handle is given")

    spec = Path(args.spec_file).read_text(encoding="utf-8")
    bindings: dict[str, Any] = {}
    if args.bindings_file:
        bindings = json.loads(
            Path(args.bindings_file).read_text(encoding="utf-8"))

    cfg = RealConfig(
        broker_url=os.environ.get("EDP_BROKER_URL", RealConfig.broker_url),
        pool_url=os.environ.get("EDP_POOL_URL", RealConfig.pool_url),
        repo_root=Path(os.environ.get("EDP_AGENT_HOME", ".")),
    )
    # W7 part 4: the knob is handed to the RUNTIME, not applied to the compiled
    # pipeline — so it lands on each chatty source as the spec constructs it,
    # BEFORE the spec's own rx.merge. Applying it after compile_spec would put
    # one operator on the MERGED stream, where a 2s poller wins every window and
    # discards the critical event it was merged with (the s29 starvation).
    runtime = RxRuntime(RealSources(cfg), rate_limit_ms=args.min_interval_ms)
    observable = compile_spec(spec, runtime, bindings)

    dispatcher: EffectDispatcher | None = None
    if args.effect_file:
        raw = json.loads(Path(args.effect_file).read_text(encoding="utf-8"))
        effect_spec = EffectSpec.compile(raw)   # allowlist + opt-in at compile
        audit_path = (cfg.repo_root / ".reactive" / "effect_audit"
                      / f"{effect_spec.rule_id}.jsonl")
        dispatcher = EffectDispatcher(
            effect_spec, owner=args.owner,
            executor=make_broker_executor(cfg.broker_url, parent=args.owner,
                                          repo_root=cfg.repo_root),
            audit_sink=make_file_audit_sink(audit_path),
            liveness_probe=_make_liveness_probe(cfg),
            phase=2)  # Tier-2 stays dark until Phase 3

    run(observable, dispatcher=dispatcher, owner=args.owner)
    return 0


def _make_liveness_probe(cfg: "RealConfig"):
    """Probe a handle's liveness from the pool (for pool_reap's dead-only
    precondition). Unreachable pool → 'unknown' (refuses to reap)."""
    import httpx

    def probe(handle: str) -> str:
        try:
            r = httpx.get(f"{cfg.pool_url}/v1/locks", timeout=10)
            rows = r.json() if r.status_code // 100 == 2 else []
        except Exception:  # noqa: BLE001 — unknown liveness refuses the reap
            return "unknown"
        for lk in rows:
            if lk.get("handle") == handle:
                return str(lk.get("liveness", "unknown"))
        return "unknown"

    return probe


if __name__ == "__main__":
    raise SystemExit(main())
