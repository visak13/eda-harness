# Reactive streams — governed effects + durable rules

Companion to `get_guide("reactive-streams")`. Fetch this **before** you pass
`effect=` to `observe()` or register a durable rule. It covers the actionable
sink (the "motor nerve"), the governed-effect safety model, and the durable rule
registry. The governing design is `eda-ml/docs/event_plane/EVENT-PLANE-UPGRADE-
DESIGN.md` (§4A/§4C) and the approved `PHASE0-EFFECTSPEC-SAFETY-SPEC.md`.

## The big picture: rx observes, the valve mutates (narrowly)

A sensory subscription only wakes you. An **actionable** subscription *also*
fires ONE framework action per emission — but through a deliberately narrow,
sanctioned valve, NOT open mutation. The invariant "rx observes, CRUD mutates"
is preserved in spirit: the only writes an emission can cause are a fixed
allowlist of idempotent/advisory tool calls, each idempotency-keyed, rate-capped,
audited, and (for anything beyond the default-ON advisory pair) explicitly
opted-in. The observe-lambda `compile_spec` restricted-builtins sandbox is
**untouched** — the EffectSpec is declarative data validated against a schema,
never `eval`-able code.

## Tool signatures (as wired in `tools/_tools.py`)

### `observe(spec, bindings={}, subscription_id=None, effect=None, owner="")`
→ `{subscription_id, bound_to, monitor_cmd, has_effect}`

- `effect` (optional): a governed **EffectSpec dict** (schema below). Absent →
  pure sensory subscription (wake-only), exactly as before. Present → each
  emission ALSO dispatches one allowlisted, idempotency-keyed, rate-capped,
  audited, advisory-by-default action via the SAME governed sink the driver runs
  at `phase=2` (Tier-2 stays DARK).
- `owner`: provenance inbox (the echo-loop filter). Defaults to `bindings["me"]`.
- The effect is validated **here** (allowlist + opt-in + arg contract) so a bad
  effect fails fast with a consumable error, never a driver that dies on launch.
  `rule_id` defaults to the `subscription_id`.
- For a reflex that must SURVIVE a restart, register it as a rule instead — an
  `observe()` effect lives only in the spawning session.

### `register_rule(name, spec, owner, bindings={}, effect=None, enabled=True, replace=False)`
→ `{name, owner, enabled, has_effect, created_ts, updated_ts, note}`

- Persists a DURABLE rule = (observe `spec` + optional governed `effect` +
  `owner`) to disk (one JSON file per rule under `.reactive/registry/`), so it
  survives a shell / broker / pool restart. A running `RuleSupervisor`
  re-subscribes every ENABLED rule on startup by spawning the existing driver.
- The `spec` is validated by composition (no I/O) and the `effect` by the SAME
  allowlist + opt-in gate the driver applies — an invalid rule never reaches
  disk. The effect's `rule_id` is forced to the rule `name` (audit identity).
- Unique `name` required; `replace=True` overwrites. A bad spec/effect/duplicate
  name returns a consumable error. Delegates to
  `edp_claude.reactive.registry.RuleRegistry` (the source of truth).

### `list_rules(enabled_only=False)`
→ `{count, rules:[<full record>…]}`

- Enumerate durable rules on disk so a no-context shell can REDISCOVER standing
  reflexes after a restart. Each record carries name, owner, enabled, the
  observe `spec` + bindings, and the governed `effect` — exactly what's needed to
  understand or re-author a rule. `enabled_only=True` lists just the rules the
  supervisor is actively keeping subscribed. Read-only.

## The EffectSpec schema (declarative data, not code)

| field | type | required | meaning |
|---|---|---|---|
| `action` | `str` (enum — see allowlist) | yes | the allowlisted tool name; rejected at compile time if unknown |
| `args` | `dict[str, ArgSource]` | yes | how each tool arg is produced. An `ArgSource` is EITHER `{"const": <json>}` (literal) OR `{"from_event": "<dotted.path>"}` (a pure dict-walk projection of the emitted event). **No expressions, no lambdas, no interpolation.** A missing `from_event` path is audited `arg_unresolved` and the effect does NOT fire |
| `rule_id` | `str` | yes (auto-set) | stable owner id; the idempotency key + audit/provenance owner. `observe` defaults it to `subscription_id`; `register_rule` forces it to the rule `name` |
| `mutating` | `bool` | no, default `false` | the explicit opt-in REQUIRED before an opt-in/Tier-2 action will even validate |
| `dry_run` | `bool` | no, default `false` | resolve + audit but DO NOT call the tool (validation mode) |
| `rate` | `{capacity:int, refill_per_min:int}` | no, default `{5,5}` | per-rule token bucket |
| `enabled` | `bool` | no, default `true` | kill switch |

Example — advisory broker fan-out (the 6th-sense watcher's shape):
```json
{
  "action": "broker_send",
  "args": {
    "to":   {"const": "sixth-sense-advisories"},
    "kind": {"const": "observation"},
    "body": {"from_event": "body"}
  }
}
```

## The governed-effect safety model

The closed, hard-coded allowlist (`effects.py` `_ALLOWLIST`) maps each permitted
action to a class. Anything not a key is rejected at compile time.

| class | actions | gate |
|---|---|---|
| **default-ON advisory** | `broker_send` (advisory `observation` kind only) · `notify_above` | execute with NO opt-in |
| **opt-in advisory** (Q1 knob) | `record_context(kind=…)` | reversible, but requires `mutating:true` to execute (it writes recipe context). `kind` is a required arg — an effect says what it records, it never inherits a default. (Was `record_decision` until W6.4 retired that verb; the effect plane does not role-scope, so this allowlist was its last live write-path.) |
| **Tier-2 mutating** (DARK) | `reconcile` · `next_action` · `pool_reap` (scoped, dead-only) · `record_outcome` | requires `mutating:true` even to validate AND cannot execute until Phase 3 (driver `phase=2`) |

The seven guarantees the dispatcher enforces on every emission:

1. **Closed allowlist** — unknown `action` rejected at compile (`EffectAllowlistError`).
2. **Advisory-by-default** — the default-ON set is `broker_send` observation +
   `notify_above` ONLY. `record_context` and all Tier-2 actions need
   `mutating:true`; a spec naming them without it is rejected at compile
   (`EffectMutatingNotOptedIn`). You cannot mutate (or even use a non-default
   advisory action) by omission.
3. **`broker_send` is advisory-only** — its `kind` must be `observation`; the
   body is stamped `advisory_only:true` + provenance.
4. **Idempotency** — `idem_key = sha256(rule_id :: canonical_json(resolved
   from_event subset))`; a bounded seen-set dedups duplicates (audited
   `deduped`), so a replay/reconnect doesn't double-fire.
5. **Rate cap** — a per-`rule_id` token bucket (default `{capacity:5,
   refill_per_min:5}`); over budget → `rate_limited`, so a stream storm can't
   become an action storm.
6. **Audit** — exactly ONE audit worklog line per decision
   (`executed` / `dry_run` / `deduped` / `rate_limited` / `precondition_failed` /
   `arg_unresolved` / `blocked_tier2_dark`). No effect is silent.
7. **Provenance / echo filter** — every emitted artifact is stamped with
   `{rule_id, owner, effect:true}` so a rule can `rx.filter` out its own output
   and not re-trigger itself.

**Ship a new effect `dry_run:true` first.** Read the audit trail to confirm it
would fire on exactly the right events with exactly the right resolved args, then
flip to `dry_run:false`. `pool_reap` additionally requires its source to be an
`rx.pool(scope=…, states=['dead'])` stream and re-checks `liveness=dead` at fire
time (`precondition_failed` + abort otherwise) — never reaps an alive worker.

## Durable rule lifecycle + the RuleSupervisor

```
register_rule(...)  → one JSON file per rule on disk (the source of truth)
RuleSupervisor.start() (a persistent service)
  → reads every ENABLED rule from disk (no session memory)
  → spawns the existing reactive driver per rule (REUSING the phase=2 governed
    sink — Tier-2 DARK), one tracked subprocess each
  → on a restart, a fresh supervisor re-reads the registry → rules survive
  → strict tracked-PID teardown on exit AND failure (graceful → hard; never a
    name/image-wide kill)
list_rules() → a fresh shell rediscovers the standing reflexes
```

The supervisor is what makes a registered rule a *standing* reflex; without it
running, registered rules are inert. Enable/disable spawn/tear-down a single
child live.

## Mutating reflexes (Tier-2): the two preconditions that keep them DARK

Tier-2 ships built, validated, and **dark**. Before any live enable:

1. **Idempotency across restart (HARD BLOCKER).** The dedup seen-set is
   in-process only, so the guarantee is exactly-once *within* a driver but
   at-least-once *across* a restart — the broker replays still-in-window events
   to a reconnecting driver, which re-fires with an empty seen-set (proven:
   3 wire advisories for a 2-trigger run across a restart). Benign for an
   advisory observation; **dangerous** for a mutating reflex — a replayed
   `next_action` re-dispatches, a replayed `pool_reap` wrongly reaps. The
   supervisor's current mitigation is to **advance the rule's broker `since`
   cursor to now on each (re)subscribe** (`registry._advance_bindings`), so a
   fresh driver only sees events from this subscription forward. The FULL fix —
   a persisted per-rule seen-set — is explicitly DEFERRED and gates any Tier-2
   live-enable.
2. **Heartbeat coexistence.** The neuron/planner heartbeat already runs
   `reconcile`+`next_action` as the FSM backstop. A mutating rule driving the
   same FSM ops must not race or duplicate it — the deterministic transition has
   exactly one writer (the FSM). This is the FSM-boundary rule (main guide)
   applied to effects, and another reason Tier-2 stays dark until deliberately,
   explicitly enabled.
