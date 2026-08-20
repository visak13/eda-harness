"""The motor nerve — a *governed* actionable sink for the reactive plane.

Today `driver.run()` only WAKES a watching shell (sensory nerve). This module
adds the bridge that lets a stream emission drive a FRAMEWORK ACTION — but as a
narrow, sanctioned, audited, advisory-by-default valve, NOT open mutation. The
"rx observes, CRUD mutates" invariant is preserved in spirit: rx still only
observes, and the only writes an emission can cause are a fixed allowlist of
idempotent / advisory tool calls, each idempotency-keyed, rate-capped, audited,
and (for anything beyond the default-ON advisory pair) explicitly opted-in.

Grounded in the APPROVED Phase-0 safety spec
(`eda-ml/docs/event_plane/PHASE0-EFFECTSPEC-SAFETY-SPEC.md`) with the user's
three settled knobs:
  * the recipe-context write is REMOVED from the default-ON set → requires
    opt-in. (That write is `record_context(kind=…)`; it was `record_decision`
    until W6.4 retired that verb.)
  * default token bucket = {capacity:5, refill_per_min:5} per rule.
  * Tier-2 mutating actions stay FULLY DARK (validate-only, cannot execute)
    until Phase 3.

CRITICAL INVARIANT (do not weaken): an `EffectSpec` is DECLARATIVE DATA, never
code. It is validated against a schema + a hard-coded allowlist and dispatched
BY NAME. It is never `eval`-ed. Nothing in this module touches `compile_spec`'s
`_SAFE_BUILTINS` sandbox — that guard is for the observe() lambda and stays
exactly as it was. The arg language is deliberately tiny: a literal
(`{"const": X}`) or a pure dotted-path read of the event (`{"from_event":
"a.b.c"}`). No expressions, no `getattr`, no interpolation.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

# ── error taxonomy (consumable, never a silent no-op) ──────────────────────
class EffectError(ValueError):
    """Base for all EffectSpec rejections."""


class EffectAllowlistError(EffectError):
    """The action is not in the closed allowlist (rejected at COMPILE time)."""


class EffectMutatingNotOptedIn(EffectError):
    """A non-default-ON action used without the explicit per-rule opt-in
    (`mutating: true`) — rejected at COMPILE time. You cannot mutate (or use a
    non-default advisory action) by omission."""


class EffectArgUnresolved(EffectError):
    """A `from_event` path was absent in the emitted event (raised at FIRE
    time → audited as `arg_unresolved`, effect NOT fired — never a silent
    default)."""


# ── the closed, hard-coded action allowlist ────────────────────────────────
# classification:
#   "default_on"  — advisory, executes with NO opt-in (broker_send observation,
#                   notify_above).
#   "opt_in"      — advisory but REQUIRES `mutating:true` opt-in to execute
#                   (record_context, per the user's Q1 knob). Reversible /
#                   append-only, so it MAY execute in Phase 2 once opted-in.
#   "tier2"       — mutating, REQUIRES `mutating:true` to even validate AND is
#                   FULLY DARK in Phase 2 (validate-only, cannot execute until
#                   Phase 3).
# `args` documents the real tool's input contract (from tools/_tools.py);
# `required` is the subset the EffectSpec must wire.
@dataclass(frozen=True)
class _Allowed:
    cls: str
    args: frozenset[str]
    required: frozenset[str]


_ALLOWLIST: dict[str, _Allowed] = {
    # ── Tier 1 — advisory, default-ON ──────────────────────────────────────
    "broker_send": _Allowed(
        "default_on",
        frozenset({"to", "kind", "body", "from_"}),
        frozenset({"to", "kind"})),
    "notify_above": _Allowed(
        "default_on",
        frozenset({"kind", "body"}),
        frozenset({"kind"})),
    # ── Tier 1 — advisory, opt-in (Q1 knob) ────────────────────────────────
    # W6.4 retired `record_decision` from every ROLE surface; the effect plane
    # does not role-scope, so this allowlist was the last live write-path to it.
    # It now names the successor. The arg set is `record_context`'s real one
    # (_RecordContextIn): `kind` selects the route and is REQUIRED — an effect
    # must say what it is recording, never inherit a default.
    "record_context": _Allowed(
        "opt_in",
        frozenset({"kind", "recipe_id", "text", "rationale", "reason", "by",
                   "load_bearing"}),
        frozenset({"kind", "recipe_id", "text"})),
    # ── Tier 2 — mutating, opt-in + FULLY DARK in Phase 2 ──────────────────
    "reconcile": _Allowed(
        "tier2",
        frozenset({"handle", "handle_type"}),
        frozenset({"handle"})),
    "next_action": _Allowed(
        "tier2",
        frozenset({"handle", "handle_type", "hint"}),
        frozenset({"handle"})),
    "pool_reap": _Allowed(
        "tier2",
        frozenset({"handle"}),
        frozenset({"handle"})),
    "record_outcome": _Allowed(
        "tier2",
        frozenset({"recipe_id", "description", "verification"}),
        frozenset({"recipe_id", "description"})),
}

# The default-ON executable set (no opt-in) — exactly the user's Q1 result.
DEFAULT_ON_ACTIONS = frozenset(
    name for name, a in _ALLOWLIST.items() if a.cls == "default_on")
# Everything else needs `mutating:true` opt-in (opt-in advisory + tier-2).
OPT_IN_ACTIONS = frozenset(
    name for name, a in _ALLOWLIST.items() if a.cls in ("opt_in", "tier2"))
TIER2_ACTIONS = frozenset(
    name for name, a in _ALLOWLIST.items() if a.cls == "tier2")

DEFAULT_RATE = {"capacity": 5, "refill_per_min": 5}


# ── the declarative EffectSpec ─────────────────────────────────────────────
@dataclass(frozen=True)
class EffectSpec:
    """A validated, declarative binding of an emission → ONE allowlisted action.

    Build via `EffectSpec.compile(raw_dict)` so the allowlist + opt-in gate run
    at COMPILE time (analogous to how `compile_spec` rejects a non-Observable).
    The only fields are the approved schema:
    action / args / rule_id / mutating / dry_run / rate / enabled.
    """

    action: str
    rule_id: str
    args: dict[str, dict] = field(default_factory=dict)
    mutating: bool = False
    dry_run: bool = False
    rate: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_RATE))
    enabled: bool = True

    # the from_event paths this spec reads (for the idempotency subset + audit)
    @property
    def from_event_paths(self) -> list[str]:
        return sorted(
            src["from_event"] for src in self.args.values()
            if isinstance(src, dict) and "from_event" in src)

    @property
    def tier(self) -> str:
        return _ALLOWLIST[self.action].cls

    @staticmethod
    def compile(raw: dict[str, Any]) -> "EffectSpec":
        """Validate a raw EffectSpec dict and return a frozen EffectSpec.
        Raises (consumable) at COMPILE time on an unknown action or a missing
        opt-in. This is the ONLY constructor consumers should use."""
        if not isinstance(raw, dict):
            raise EffectError(f"EffectSpec must be a dict, got {type(raw).__name__}")
        action = raw.get("action")
        rule_id = raw.get("rule_id")
        if not isinstance(action, str) or not action:
            raise EffectError("EffectSpec.action is required (str)")
        if not isinstance(rule_id, str) or not rule_id:
            raise EffectError("EffectSpec.rule_id is required (str)")

        # (2) CLOSED allowlist — unknown action rejected at compile.
        allowed = _ALLOWLIST.get(action)
        if allowed is None:
            raise EffectAllowlistError(
                f"action {action!r} is not in the effect allowlist "
                f"({sorted(_ALLOWLIST)})")

        args = raw.get("args", {}) or {}
        if not isinstance(args, dict):
            raise EffectError("EffectSpec.args must be a dict[str, ArgSource]")
        # each arg source must be exactly one of {const} | {from_event}
        for k, src in args.items():
            if (not isinstance(src, dict)
                    or set(src) not in ({"const"}, {"from_event"})):
                raise EffectError(
                    f"arg {k!r} must be {{'const': X}} or "
                    f"{{'from_event': 'dotted.path'}}, got {src!r}")
            if "from_event" in src and not isinstance(src["from_event"], str):
                raise EffectError(f"arg {k!r} from_event must be a dotted string")
        # required tool args must be wired
        missing = allowed.required - set(args)
        if missing:
            raise EffectError(
                f"action {action!r} requires args {sorted(allowed.required)}; "
                f"missing {sorted(missing)}")
        # no unknown tool args (closed contract)
        extra = set(args) - allowed.args
        if extra:
            raise EffectError(
                f"action {action!r} got unknown args {sorted(extra)}; "
                f"allowed {sorted(allowed.args)}")

        mutating = bool(raw.get("mutating", False))
        # (6) advisory-by-default: anything outside the default-ON pair needs
        # the explicit per-rule opt-in. You cannot mutate (or use a non-default
        # advisory action) by omission.
        if action in OPT_IN_ACTIONS and not mutating:
            raise EffectMutatingNotOptedIn(
                f"action {action!r} requires explicit opt-in "
                f"(mutating: true); default-ON actions are "
                f"{sorted(DEFAULT_ON_ACTIONS)}")

        rate = raw.get("rate") or dict(DEFAULT_RATE)
        if not (isinstance(rate, dict)
                and isinstance(rate.get("capacity"), int)
                and isinstance(rate.get("refill_per_min"), int)):
            raise EffectError(
                "EffectSpec.rate must be {capacity:int, refill_per_min:int}")

        return EffectSpec(
            action=action, rule_id=rule_id, args=dict(args), mutating=mutating,
            dry_run=bool(raw.get("dry_run", False)),
            rate={"capacity": rate["capacity"],
                  "refill_per_min": rate["refill_per_min"]},
            enabled=bool(raw.get("enabled", True)))


# ── token bucket (per rule_id) ─────────────────────────────────────────────
class _TokenBucket:
    """Classic token bucket. `now()` is injectable so tests are deterministic
    (a frozen clock = no refill within the test window)."""

    def __init__(self, capacity: int, refill_per_min: int,
                 now: Callable[[], float]):
        self.capacity = float(capacity)
        self.refill_per_sec = refill_per_min / 60.0
        self._now = now
        self.tokens = float(capacity)
        self.updated = now()

    def take(self) -> bool:
        t = self._now()
        elapsed = max(0.0, t - self.updated)
        self.tokens = min(self.capacity,
                          self.tokens + elapsed * self.refill_per_sec)
        self.updated = t
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


# ── argument resolution (the ENTIRE data language) ─────────────────────────
_MISSING = object()


def _walk(event: Any, dotted: str) -> Any:
    """Pure dict/get walk of a dotted path. NO getattr / NO index into code
    objects / NO eval. Missing → `_MISSING`."""
    cur = event
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def resolve_args(spec: EffectSpec, event: Any) -> dict[str, Any]:
    """Resolve each ArgSource against the emitted event. Raises
    EffectArgUnresolved on a missing `from_event` path (never a silent
    default)."""
    out: dict[str, Any] = {}
    for key, src in spec.args.items():
        if "const" in src:
            out[key] = src["const"]
        else:
            val = _walk(event, src["from_event"])
            if val is _MISSING:
                raise EffectArgUnresolved(
                    f"arg {key!r}: from_event path {src['from_event']!r} "
                    f"absent in event")
            out[key] = val
    return out


def _canonical(obj: Any) -> str:
    # same canonicalisation the driver's _poll_changes uses (driver.py:145).
    return json.dumps(obj, sort_keys=True, default=str)


def idempotency_key(spec: EffectSpec, event: Any) -> str:
    """sha256(rule_id :: canonical_json(resolved from_event subset)). Only the
    from_event paths the spec actually reads form the subset, so two emissions
    that resolve to the same governed inputs collapse to one key."""
    subset = {p: _walk(event, p) for p in spec.from_event_paths}
    subset = {k: (None if v is _MISSING else v) for k, v in subset.items()}
    raw = f"{spec.rule_id}::{_canonical(subset)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def provenance_stamp(spec: EffectSpec, owner: str) -> dict[str, Any]:
    """The _prov stamp written onto an effect's emitted artifact, so a
    subscriber can filter out its OWN output (echo-loop defence, §7)."""
    return {"rule_id": spec.rule_id, "owner": owner,
            "effect": True, "plane": "motor"}


# audit outcomes (the closed vocabulary written to the audit sink)
OUTCOME_EXECUTED = "executed"
OUTCOME_DRY_RUN = "dry_run"
OUTCOME_DEDUPED = "deduped"
OUTCOME_RATE_LIMITED = "rate_limited"
OUTCOME_PRECONDITION_FAILED = "precondition_failed"
OUTCOME_ARG_UNRESOLVED = "arg_unresolved"
OUTCOME_PROVENANCE_DROPPED = "provenance_dropped"
OUTCOME_TIER2_DARK = "blocked_tier2_dark"
OUTCOME_DISABLED = "disabled"
OUTCOME_FAILED = "failed"


@dataclass
class EffectDecision:
    rule_id: str
    action: str
    idem_key: str
    resolved_args: dict[str, Any]
    outcome: str
    dry_run: bool
    detail: str = ""

    def as_audit_line(self) -> dict[str, Any]:
        return {
            "event": "effect_fired",
            "rule_id": self.rule_id,
            "action": self.action,
            "idem_key": self.idem_key,
            "resolved_args": self.resolved_args,
            "outcome": self.outcome,
            "dry_run": self.dry_run,
            "detail": self.detail,
        }


# ── echo detection (shared by the motor AND sensory nerves) ────────────────
# _prov_echo: provenance-stamp matching — effect-plane writes carry `_prov`
# and are recognized exactly. is_self_echo: authorship matching for the
# sensory path (WP3 2026-08-12) — a shell must not be WOKEN by events it
# authored itself (the planner tails its own worklog, which its own tool
# calls append; 265k self-inflicted polls/wakes in the df971d log corpus).

# handles appear in two spellings: EDP_HANDLE uses colons, broker inboxes
# use dashes (and plan ids themselves contain dashes, so the mapping is only
# well-defined colon→dash). Compare in normalized (all-dash) space.
def _norm_handle(handle: str) -> str:
    return (handle or "").strip().replace(":", "-")


# worklog bookkeeping kinds that are BY CONSTRUCTION self-caused on the
# reader's own log (written on the check_inbox delivery path) — never signal.
_SELF_BOOKKEEPING_KINDS = frozenset({"message_received"})

_AUTHOR_FIELDS = ("from", "from_", "by", "actor", "agent", "handle", "owner")


def _prov_echo(event: Any, rule_id: str, owner: str) -> bool:
    prov = event.get("_prov") if isinstance(event, dict) else None
    if not isinstance(prov, dict):
        # provenance may also live under a `body` wrapper (broker shape)
        body = event.get("body") if isinstance(event, dict) else None
        prov = body.get("_prov") if isinstance(body, dict) else None
    if not isinstance(prov, dict):
        return False
    return (prov.get("rule_id") == rule_id
            or prov.get("owner") == owner)


def is_self_echo(event: Any, owner: str) -> bool:
    """True iff `event` was authored by `owner` (either handle spelling), or
    is reader-side bookkeeping. Used by the sensory nerve to drop self-wakes
    before they reach the shell; the motor nerve's provenance filter
    (`_prov_echo`) remains separate and stricter."""
    if not owner or not isinstance(event, dict):
        return False
    me = _norm_handle(owner)
    if event.get("kind") in _SELF_BOOKKEEPING_KINDS:
        return True
    for scope in (event, event.get("body") if isinstance(event.get("body"), dict) else {}):
        for field in _AUTHOR_FIELDS:
            v = scope.get(field)
            if isinstance(v, str) and _norm_handle(v) == me:
                return True
    return False


# ── the dispatcher (one per registered rule) ───────────────────────────────
ToolExecutor = Callable[[str, dict[str, Any]], Any]
AuditSink = Callable[[dict[str, Any]], None]
LivenessProbe = Callable[[str], str]  # handle -> liveness ("dead"/"alive"/...)


class EffectDispatcher:
    """Owns one rule's safety state (seen-set + token bucket) and turns each
    emission into exactly ONE audited decision.

    Order of checks (each terminal step writes ONE audit line):
      0. enabled kill-switch
      1. provenance / echo filter (drop our own output)
      2. resolve args (arg_unresolved → no call)
      3. idempotency (deduped → no call)
      4. rate cap (rate_limited → no call)
      5. precondition (pool_reap dead-only → precondition_failed → no call)
      6. dry_run (audit only → no call)
      7. phase/tier dark gate (tier-2 in Phase 2 → no call)
      8. execute (executed | failed)

    `executor` is injected (tests pass a recording stub; the driver wires the
    real advisory broker/notify executor). `audit_sink` receives one terminal
    line per decision. `phase` (default 2) keeps Tier-2 dark; Phase 3 flips it.
    """

    def __init__(self, spec: EffectSpec, owner: str, *,
                 executor: ToolExecutor,
                 audit_sink: AuditSink,
                 liveness_probe: LivenessProbe | None = None,
                 phase: int = 2,
                 seen_cap: int = 4096,
                 now: Callable[[], float] | None = None,
                 on_intent: AuditSink | None = None,
                 seen_seed: Iterable[str] = ()):
        self.spec = spec
        self.owner = owner
        self._exec = executor
        self._audit = audit_sink
        self._liveness = liveness_probe
        self.phase = phase
        self._now = now or time.monotonic
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._seen_cap = seen_cap
        # F42#4 — cross-restart dedup: a replacement driver replays a
        # lookback window (default 120s) with what used to be an EMPTY
        # process-local set, so a durable effect executed just before the
        # crash fired AGAIN on replay. The driver seeds this from the
        # rule's own audit trail (the keys it already decided on).
        for k in seen_seed:
            if k:
                self._seen_add(str(k))
        self._bucket = _TokenBucket(
            spec.rate["capacity"], spec.rate["refill_per_min"], self._now)
        # crash-mid-execute visibility: intent goes to the live stream (NOT the
        # settled audit artifact, so audit line-count == decision-count).
        self._on_intent = on_intent

    # ── helpers ────────────────────────────────────────────────────────────
    def _record(self, decision: EffectDecision) -> EffectDecision:
        self._audit(decision.as_audit_line())
        return decision

    def _seen_add(self, key: str) -> None:
        self._seen[key] = None
        while len(self._seen) > self._seen_cap:
            self._seen.popitem(last=False)

    def _is_echo(self, event: Any) -> bool:
        return _prov_echo(event, self.spec.rule_id, self.owner)

    # ── the single entry point ──────────────────────────────────────────────
    def handle(self, event: Any) -> EffectDecision:
        spec = self.spec

        # 0. kill switch
        if not spec.enabled:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, "", {}, OUTCOME_DISABLED,
                spec.dry_run, "rule disabled"))

        # 1. provenance / echo filter — drop our own output before any work.
        if self._is_echo(event):
            return self._record(EffectDecision(
                spec.rule_id, spec.action, "", {}, OUTCOME_PROVENANCE_DROPPED,
                spec.dry_run, "event carries this rule's own provenance"))

        # 2. resolve args
        try:
            resolved = resolve_args(spec, event)
        except EffectArgUnresolved as exc:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, "", {}, OUTCOME_ARG_UNRESOLVED,
                spec.dry_run, str(exc)))

        idem = idempotency_key(spec, event)

        # 3. idempotency
        if idem in self._seen:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved, OUTCOME_DEDUPED,
                spec.dry_run, "duplicate idempotency key"))

        # 4. rate cap (consume a token only for a NEW, real candidate fire)
        if not self._bucket.take():
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved, OUTCOME_RATE_LIMITED,
                spec.dry_run, "token bucket empty"))

        # mark seen now: a candidate that passed dedup+rate must not be
        # re-evaluated on replay even if a later gate aborts it.
        self._seen_add(idem)

        # 5. preconditions
        precond = self._check_precondition(resolved)
        if precond is not None:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved,
                OUTCOME_PRECONDITION_FAILED, spec.dry_run, precond))

        # 6. dry-run: resolve + audit, DO NOT call the tool.
        if spec.dry_run:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved, OUTCOME_DRY_RUN,
                True, "dry_run: tool not called"))

        # 7. tier-2 dark gate (Phase 2): validate-only, cannot execute.
        if spec.action in TIER2_ACTIONS and self.phase < 3:
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved, OUTCOME_TIER2_DARK,
                spec.dry_run,
                f"tier-2 mutating action dark until Phase 3 (phase={self.phase})"))

        # 8. execute — stamp provenance, fire, audit one terminal line.
        resolved = self._stamp(resolved)
        if self._on_intent is not None:                 # crash-visibility
            self._on_intent({"event": "effect_intent", "rule_id": spec.rule_id,
                             "action": spec.action, "idem_key": idem})
        try:
            self._exec(spec.action, resolved)
        except Exception as exc:  # noqa: BLE001 — surface, never swallow
            return self._record(EffectDecision(
                spec.rule_id, spec.action, idem, resolved, OUTCOME_FAILED,
                spec.dry_run, f"executor raised: {exc}"))
        return self._record(EffectDecision(
            spec.rule_id, spec.action, idem, resolved, OUTCOME_EXECUTED,
            spec.dry_run, "tool called"))

    # ── precondition guards ──────────────────────────────────────────────────
    def _check_precondition(self, resolved: dict[str, Any]) -> str | None:
        """Return a failure reason string, or None if preconditions hold."""
        action = self.spec.action
        # advisory broker_send must stay an advisory `observation` on the wire.
        if action == "broker_send" and resolved.get("kind") != "observation":
            return ("broker_send effect is advisory-only: kind must be "
                    f"'observation', got {resolved.get('kind')!r}")
        # pool_reap is scoped dead-only: re-check liveness at fire time. Never
        # reap an alive worker (mirrors the human PoolReap rule).
        if action == "pool_reap":
            handle = resolved.get("handle")
            live = (self._liveness(handle) if self._liveness else "unknown")
            if live != "dead":
                return (f"pool_reap precondition: handle {handle!r} liveness="
                        f"{live!r}, not 'dead' — refusing to reap")
        return None

    def _stamp(self, resolved: dict[str, Any]) -> dict[str, Any]:
        """Stamp the effect's outgoing artifact with provenance (echo-loop
        defence). Only artifacts that carry a `body`/note get the stamp."""
        prov = provenance_stamp(self.spec, self.owner)
        out = dict(resolved)
        if isinstance(out.get("body"), dict):
            out["body"] = {**out["body"], "_prov": prov, "advisory_only": True}
        return out


def subscribe_effect(observable, spec: EffectSpec, owner: str, *,
                     executor: ToolExecutor, audit_sink: AuditSink,
                     liveness_probe: LivenessProbe | None = None,
                     phase: int = 2,
                     now: Callable[[], float] | None = None,
                     on_intent: AuditSink | None = None,
                     on_error: Callable[[Exception], None] | None = None):
    """Bind a governed EffectSpec to a composed pipeline. Each emission flows
    through the dispatcher's safety gauntlet. Returns (subscription, dispatcher)
    so a caller can dispose the subscription and inspect the rule's state.

    A DOMAIN failure on the stream (`on_error`) is the stream's concern, not the
    effect's — it never fires the effect; reserve it for transport drops."""
    disp = EffectDispatcher(
        spec, owner, executor=executor, audit_sink=audit_sink,
        liveness_probe=liveness_probe, phase=phase, now=now,
        on_intent=on_intent)
    sub = observable.subscribe(
        on_next=disp.handle,
        on_error=(on_error or (lambda e: None)))
    return sub, disp
