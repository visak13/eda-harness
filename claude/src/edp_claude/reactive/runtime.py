"""RxRuntime — the `rx` handle exposed to an `observe()` lambda.

Two halves, deliberately separable so composition is testable without
I/O:

* **sources** (`broker`/`worklog`/`plan`/`recipe`/`pool`/`external`) are
  delegated to a `source_provider` callable. Production wires the real
  threaded I/O (see `driver.py`); tests inject `reactivex.of(...)` or a
  Subject so the operator composition can be asserted deterministically.
  `topic` is pure sugar over `broker` (recipient `topic:<name>`) — no new
  transport; it composes from the existing broker source.
* **combinators + operators** delegate straight to RxPY — we do NOT
  reinvent them (resolved decision: use RxPY). `merge`/`fork_join`/
  `race`(=amb)/`combine_latest` are combinators; `filter`/`map`/`take`/
  `take_until`/`debounce_ms`/`sample_ms`/`buffer_ms`/
  `distinct_until_changed`/`scan`/`retry`/`timeout_ms`/`catch`/
  `switch_map`/`with_latest_from` are pipe-operators.

`timer`/`interval` are pure (no I/O) so they bypass the provider.
"""

from collections.abc import Callable
from typing import Any

import reactivex as rx
from reactivex import Observable
from reactivex import operators as ops

SourceProvider = Callable[..., Observable]


# ── W7 part 4 (DESIGN-v6 §W7.4): per-role observe() wake kind-sets ───────────
# The CANONICAL, code-grounded single source of truth for which broker/flowback
# kinds each role's `observe()` subscription restricts to. Rx-noise suppression
# = wake ONLY on the kinds that role must act on, but PRESERVING every role's
# existing guide-mandated set. The role .md guides author these exact sets in
# their `rx.broker(me, kinds=[...])` specs (neuron.md, agentic-plan.md,
# worker.md); the guide-sync action renders the prose from this table. Keeping
# it here (next to the kind-filter that consumes `kinds=`) lets a test PIN the
# invariant so the "a prior draft dropped plan_closed/done/question" regression
# can never recur silently.
#
# NOTE (scope): DESIGN-v7 P5.1 widened these sets (+steer_ack/+alert on
# neuron+planner, +grounding on planner) so the consume-ack and echo-back
# defenses wake their judges instead of waiting for the heartbeat. `progress`
# stays out of every set (d53 stands — it is aggregated into the
# progress_rollup instead).
ROLE_WAKE_KINDS: dict[str, dict[str, list[str]]] = {
    "neuron": {
        # rx.broker(me, kinds=[...])
        # `progress` is deliberately ABSENT (d53 tier-1, backlog item 8). It is
        # absorb-and-drop liveness noise: a child pinging "still working" is not
        # a move the neuron must act on. While it sat here it did double damage
        # — it woke a full LLM turn on push, AND (because the W7 idle
        # short-circuit's inbox check consults this very table) it defeated the
        # idle collapse during EXECUTING. Nothing is lost: the ping still lands
        # in the inbox and is read on the next real wake.
        # v7 P5.1: + steer_ack (the 3.2 consume-ack — the neuron must see its
        # steer restated promptly to judge the restatement) and + alert (a
        # child's environment-degraded signal must not wait for the heartbeat).
        "broker": ["question", "answer", "steer", "plan_closed",
                   "steer_ack", "alert"],
        # rx.recipe_events(me, kinds=[...]) — the FLOWBACK broadcast channel
        "recipe_events": ["learning", "discovery", "blocker",
                          "spec_learning_proposed", "review_finding"],
        # rx.pool(scope=me, states=[...]) — a scoped pool wake = one of MY
        # shells crashed
        "pool_states": ["dead"],
    },
    "planner": {
        # rx.broker(me, kinds=[...]) — worker results + questions + steers;
        # planner ALSO merges rx.worklog(plan_id) + rx.pool(scope=plan_id)
        # (no kind filter — worklog/pool are already control-plane sources).
        # v7 P5.1: + grounding (the 3.1 echo — the planner judges a worker's
        # restatement against the directive at dispatch time), + steer_ack,
        # + alert (same rationale as the neuron's).
        "broker": ["done", "question", "answer", "steer",
                   "grounding", "steer_ack", "alert"],
    },
    "worker": {
        # rx.broker(me, kinds=[...]) — a worker only ever needs a reply/steer
        # from its parent planner.
        "broker": ["answer", "steer"],
    },
}

# The load-bearing PRIMARY wakes that must NEVER be dropped from a role's
# broker kind-set — the exact regression a prior W7 draft introduced. A test
# asserts each is a subset of ROLE_WAKE_KINDS[role]["broker"].
ROLE_PRIMARY_WAKES: dict[str, list[str]] = {
    "neuron": ["question", "plan_closed"],
    "planner": ["done", "question"],
    "worker": ["answer", "steer"],
}

# The author a handle-less NEURON shell stamps on its own flowback emissions.
# `_emit_recipe_event` writes `from = <self_address> or "neuron"`, and a neuron
# has no EDP_HANDLE, so it falls back to this sentinel — even though the
# neuron's canonical address IS its recipe_id. `recipe_events(exclude_from=…)`
# must treat the two as the SAME author or item-12 self-waking survives the
# filter. Keep in step with `_emit_recipe_event`.
NEURON_SELF_AUTHOR = "neuron"


def wake_kinds(role: str, source: str = "broker") -> set[str] | None:
    """The kinds `role` wakes on for one event `source`, or None when the role
    (or source) has no declared set.

    None means "unknown role — do not filter": every consumer treats it as
    kind-blind, so an unmapped role can never lose a wake. This is the single
    accessor for ROLE_WAKE_KINDS, so the rx subscription and the W7 idle
    short-circuit's inbox check are guaranteed to consult the same table
    (backlog item 8: they used to disagree, and the disagreement was the bug).
    """
    kinds = ROLE_WAKE_KINDS.get(role, {}).get(source)
    return set(kinds) if kinds else None


class SpecError(ValueError):
    """The observe() lambda failed to compile to an Observable."""


def _seconds(ms: float) -> float:
    return ms / 1000.0


# ── W7 part 4 (delivery half): which planes the rate-limit knob may touch ────
# `min_interval_ms` quiets a CHATTY plane. A chatty plane is always a POLLED
# SNAPSHOT source: `pool`/`plan`/`external` re-read the whole state each tick
# (driver `_poll_changes`, 2s) and their emissions are LEVELS — the newest
# snapshot supersedes every older one, so dropping an intermediate one loses
# nothing the next one doesn't carry.
#
# The critical planes are EDGES, not levels: a worklog `action_status_changed`
# / a broker `answer` happens ONCE and is gone. They are low-frequency by
# nature, so they are never what the knob was reached for — and they are the
# events a shell exists to hear. THEY ARE NEVER RATE-LIMITED, on any path, at
# any knob setting.
#
# This split is the whole fix. A single knob on the MERGED stream cannot make
# it: any operator there (debounce OR throttle/sample) picks its survivor from
# a stream where a 2s poller emits continuously, so the poller wins the window
# and the once-only edge is DISCARDED, not delayed.
RATE_LIMITABLE_SOURCES: frozenset[str] = frozenset(
    {"pool", "plan", "external", "orphaned"})
CRITICAL_SOURCES: frozenset[str] = frozenset(
    {"broker", "topic", "worklog", "recipe", "recipe_events"})


class RxRuntime:
    """The `rx` handle an observe() spec composes against.

    `rate_limit_ms` (the observe() `min_interval_ms` knob) is applied HERE, at
    SOURCE CONSTRUCTION — i.e. BEFORE any `rx.merge` the spec performs — and
    ONLY to the RATE_LIMITABLE_SOURCES. That placement is load-bearing, not a
    style choice: it is what makes a critical event UNSTARVABLE whatever the
    knob is set to."""

    def __init__(self, source_provider: SourceProvider,
                 rate_limit_ms: float = 0.0):
        self._provider = source_provider
        self._rate_limit_ms = rate_limit_ms if rate_limit_ms > 0 else 0.0

    # ── the rate-limit knob (per-source, chatty planes only) ───────────────
    def _rate_limited(self, src: Observable) -> Observable:
        """Cap this chatty source's wake rate at one emission per window,
        keeping the LATEST snapshot (`ops.sample`) — a bounded wake rate that
        cannot wait-for-a-quiet-that-never-comes. `0` (the default) returns the
        source UNCHANGED, so the knob-off pipeline is byte-for-byte today's."""
        if not self._rate_limit_ms:
            return src
        return src.pipe(ops.sample(_seconds(self._rate_limit_ms)))

    # ── sources (delegated to the provider; kind-filter applied here) ──────
    def broker(self, recipient: str, kinds: list[str] | None = None,
               since: str | None = None, replay: bool = False) -> Observable:
        # replay=False (default) → follow-only: the source seeds since_ts=now
        # so only NEW messages wake (no first-subscribe inbox replay storm).
        # replay=True (or an explicit since=) opts into history — symmetric
        # with rx.worklog(replay=…). The kind-filter stays client-side.
        src = self._provider(
            "broker", recipient=recipient, since=since, replay=replay)
        if kinds:
            kset = set(kinds)
            src = src.pipe(ops.filter(lambda m: kind_of(m) in kset))
        return src

    def topic(self, name: str, kinds: list[str] | None = None,
              since: str | None = None, replay: bool = False) -> Observable:
        # Phase 1-B domain ingestion: a THIN convenience over the EXISTING
        # broker recipient-addressing — NO new transport. A "topic" is just
        # the broker recipient `topic:<name>`, so a domain/UI emitter
        # publishes with broker_send(to="topic:<name>", kind=..., body=...)
        # and a pipeline taps it with rx.topic(name). kinds/since pass
        # straight through to broker (same kind-filter + reconnect-since
        # semantics; change-detection unaffected — broker is already a
        # control-plane source). replay= passes through (follow-only default;
        # opt into a topic's history with replay=True).
        return self.broker(recipient=f"topic:{name}", kinds=kinds,
                           since=since, replay=replay)

    def worklog(self, plan_id: str | None = None,
                recipe_id: str | None = None,
                replay: bool = False) -> Observable:
        return self._provider("worklog", plan_id=plan_id,
                              recipe_id=recipe_id, replay=replay)

    def recipe_events(self, recipe_id: str, kinds: list[str] | None = None,
                      replay: bool = False,
                      exclude_from: str | list[str] | None = None,
                      ) -> Observable:
        # P4 FLOWBACK (2026-06-10): the recipe-scoped BROADCAST channel.
        # Pure sugar over the existing worklog tail of the recipe's
        # events.jsonl (same pattern as rx.topic over broker) — NO new
        # transport. Emissions are the structured events any shell in the
        # recipe's lineage publishes via emit_recipe_event (kind=learning/
        # discovery/progress/blocker/status_ping/spec_learning_proposed/
        # review_finding, channel="flowback"), plus the P3 advisory_override
        # audit records — so a neuron subscribing here receives worker and
        # reviewer learnings LIVE without the planner relaying. Narrow with
        # kinds=[...]; follow-only by default (replay=True for history).
        #
        # exclude_from (backlog item 12): the channel's subscriber is also one
        # of its WRITERS, so without a SENDER filter every event a shell emits
        # echoes straight back and wakes its own author. Pass your own address
        # to suppress that echo. Only self-authored events are dropped — the
        # SAME kind from any other sender still wakes, which is the whole point
        # of the channel.
        src = self._provider("worklog", plan_id=None, recipe_id=recipe_id,
                             replay=replay)
        src = src.pipe(ops.filter(
            lambda e: isinstance(e, dict)
            and (e.get("channel") == "flowback"
                 or e.get("kind") == "advisory_override")))
        if kinds:
            kset = set(kinds)
            src = src.pipe(ops.filter(lambda e: e.get("kind") in kset))
        authors = _excluded_authors(exclude_from, recipe_id)
        if authors:
            src = src.pipe(ops.filter(lambda e: author_of(e) not in authors))
        return src

    def plan(self, plan_id: str) -> Observable:
        return self._rate_limited(self._provider("plan", plan_id=plan_id))

    def recipe(self, recipe_id: str, replay: bool = False) -> Observable:
        return self._provider("recipe", recipe_id=recipe_id, replay=replay)

    def orphaned(self, plan_id: str | None = None,
                 recipe_id: str | None = None,
                 grace_secs: float | None = None) -> Observable:
        # 2026-07-25. The ORPHANED-ACTION edge: actions recorded as dispatched
        # with no live worker behind them (batch members resolved to their head
        # first, since only the head has a handle). This exists because a
        # worker that exits WITHOUT recording status emits nothing anywhere —
        # no crash, no event, it just stops appearing in the pool level — and a
        # level that stops arriving looks exactly like a quiet channel. See
        # `driver.RealSources._src_orphaned` for the full account.
        #
        # Pass `recipe_id=` instead for the NEURON's half of the same defect:
        # steps left `in_progress` with no live planner behind them, which is
        # what a planner exiting without recording looks like from above.
        #
        # Emits only when the orphan SET changes, and an empty set is the
        # steady state, so a healthy plan/recipe never wakes you.
        return self._rate_limited(
            self._provider("orphaned", plan_id=plan_id, recipe_id=recipe_id,
                           grace_secs=grace_secs))

    def pool(self, handle: str | None = None,
             scope: str | None = None,
             states: list[str] | None = None) -> Observable:
        # Item 6: `states=['dead']` makes a scoped pool wake a crash signal
        # only (not every spawn/clean-close). Optional + back-compat (None =
        # all liveness rows, now order-canonical to kill reorder churn).
        return self._rate_limited(
            self._provider("pool", handle=handle, scope=scope, states=states))

    def external(self, url: str, **kw: Any) -> Observable:
        return self._rate_limited(self._provider("external", url=url, **kw))

    # ── pure sources ───────────────────────────────────────────────────────
    def timer(self, ms: float) -> Observable:
        return rx.timer(_seconds(ms))

    def interval(self, ms: float) -> Observable:
        return rx.interval(_seconds(ms))

    def of(self, *values: Any) -> Observable:
        return rx.of(*values)

    # ── combinators (return an Observable) ─────────────────────────────────
    def merge(self, *sources: Observable) -> Observable:
        return rx.merge(*sources)

    def concat(self, *sources: Observable) -> Observable:
        return rx.concat(*sources)

    def fork_join(self, *sources: Observable) -> Observable:
        # waits for ALL to COMPLETE — each leg must be completion-shaped
        # (take(1)/take_until) or this never fires (REACTIVE-STREAMS §3a).
        return rx.fork_join(*sources)

    def combine_latest(self, *sources: Observable) -> Observable:
        return rx.combine_latest(*sources)

    def race(self, *sources: Observable) -> Observable:
        # RxPY spells "first to emit wins" as amb().
        return rx.amb(*sources)

    def zip(self, *sources: Observable) -> Observable:
        return rx.zip(*sources)

    # ── pipe-operators (return an operator usable in .pipe(...)) ───────────
    def filter(self, predicate: Callable[[Any], bool]):
        return ops.filter(predicate)

    def map(self, mapper: Callable[[Any], Any]):
        return ops.map(mapper)

    def take(self, n: int):
        return ops.take(n)

    def take_until(self, other: Observable):
        return ops.take_until(other)

    def debounce_ms(self, ms: float):
        # WAIT-FOR-QUIET, not rate-limiting. It emits only once the stream has
        # been SILENT for the whole window and keeps only the LAST item of the
        # burst — so on a stream with a poller in it the quiet never comes and
        # whatever the poller emitted wins. Never put it in front of an event
        # you must not miss. (The `min_interval_ms` knob used to compile to
        # this, on the MERGED stream; that is the starvation s29 fixed.)
        return ops.debounce(_seconds(ms))

    def sample_ms(self, ms: float):
        return ops.sample(_seconds(ms))

    def buffer_ms(self, ms: float):
        return ops.buffer_with_time(_seconds(ms))

    def distinct_until_changed(self, key: Callable[[Any], Any] | None = None):
        return ops.distinct_until_changed(key)

    def scan(self, accumulator: Callable[[Any, Any], Any], seed: Any = None):
        return ops.scan(accumulator, seed)

    def retry(self, count: int | None = None):
        return ops.retry(count) if count is not None else ops.retry()

    def timeout_ms(self, ms: float):
        return ops.timeout(_seconds(ms))

    def catch(self, handler: Callable[[Exception, Observable], Observable]):
        return ops.catch(handler)

    def with_latest_from(self, *others: Observable):
        return ops.with_latest_from(*others)

    def switch_map(self, mapper: Callable[[Any], Observable]):
        def _op(source: Observable) -> Observable:
            return source.pipe(ops.map(mapper), ops.switch_latest())
        return _op


def kind_of(msg: Any) -> Any:
    """Message kind, whether the event is a dict (broker JSON) or an
    object with a `.kind`."""
    if isinstance(msg, dict):
        return msg.get("kind")
    return getattr(msg, "kind", None)


def author_of(event: Any) -> Any:
    """Who emitted this event, as an ADDRESS string (or None).

    Two record shapes reach `recipe_events`, and they spell the author
    differently:

    * flowback events (`_emit_recipe_event`) carry ``from``: a bare address
      string, or the NEURON_SELF_AUTHOR sentinel.
    * `advisory_override` audit records (and the store trails) carry ``by``:
      a DICT ``{"role", "handle"}`` from `attribution.actor()` — never a
      string. We read its `handle`.

    Caveat, deliberately not papered over: `actor()` derives from EDP_HANDLE,
    which a NEURON shell does not set, so a neuron's own `by.handle` is the
    literal ``"unknown"`` and cannot be matched against its address. That is
    exactly why `_emit_recipe_event` stamps the `from` sentinel and why the
    self-wake filter keys on `from`. A neuron's own advisory_override is
    therefore NOT suppressed today — see the a3 evidence note."""
    if isinstance(event, dict):
        author = event.get("from")
        if author:
            return author
        by = event.get("by")
        return by.get("handle") if isinstance(by, dict) else by
    return getattr(event, "from_", None) or getattr(event, "sender", None)


def _excluded_authors(exclude_from: str | list[str] | None,
                      recipe_id: str) -> set[str]:
    """The author addresses whose events are suppressed for this subscriber.

    A neuron passes its own address, which for a neuron IS the recipe_id — but
    it stamps its emissions with the NEURON_SELF_AUTHOR sentinel (it has no
    EDP_HANDLE to resolve). Both spellings therefore name the same author and
    both must be excluded together, or the self-wake this filter exists to stop
    walks straight through it."""
    if not exclude_from:
        return set()
    authors = ({exclude_from} if isinstance(exclude_from, str)
               else set(exclude_from))
    if recipe_id in authors:
        authors.add(NEURON_SELF_AUTHOR)
    return authors


# Builtins the observe() lambda may use. Deliberately small — the lambda
# composes streams, it does not run arbitrary programs. No import, no
# open, no eval/exec, no getattr.
_SAFE_BUILTINS: dict[str, Any] = {
    "len": len, "range": range, "min": min, "max": max, "sum": sum,
    "abs": abs, "round": round, "sorted": sorted, "any": any, "all": all,
    "list": list, "dict": dict, "set": set, "tuple": tuple, "str": str,
    "int": int, "float": float, "bool": bool, "enumerate": enumerate,
    "zip": zip, "map": map, "filter": filter, "True": True, "False": False,
    "None": None,
}


def compile_spec(spec: str, runtime: RxRuntime,
                 bindings: dict[str, Any] | None = None) -> Observable:
    """Compile an observe() lambda string to an Observable. The spec is a
    single expression over `rx` (the runtime) plus any `bindings` the
    agent supplied (e.g. `me`, `plan_id`, `buoys`). Raises SpecError on a
    non-Observable result or any evaluation error — the observe() tool
    turns that into a consumable error (never a silent no-op)."""
    # rx + bindings go in GLOBALS (not locals) so nested lambdas in the
    # spec — e.g. `lambda s: rx.of(...)` — can resolve them via closure
    # (a function's free vars look up __globals__, never eval locals).
    g: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS, "rx": runtime}
    g.update(bindings or {})
    try:
        result = eval(spec, g)  # noqa: S307 — restricted builtins; spec is
        # the agent's own composition, not third-party input.
    except Exception as exc:  # noqa: BLE001 — surface ANY compile failure
        raise SpecError(f"observe spec failed to evaluate: {exc}") from exc
    if not isinstance(result, Observable):
        raise SpecError(
            "observe spec must evaluate to an Observable (rx.merge/"
            "rx.broker/...); got "
            f"{type(result).__name__}")
    return result
