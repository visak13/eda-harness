# Loop & heartbeat — the self-paced reconcile loop (neuron + planner)

Load via `get_guide("loop-and-heartbeat")`. The cadence contract for
the two DRIVING roles — **neuron** and **planner** (workers and
curiosity do NOT drive; see "Role scope" below). The loop is a reflex,
not the goal: each wake fires `reconcile` then `next_action`, and the
recipe/plan STATE — not the cron string — carries the goal, so the cron
prompt is a fixed one-liner and never the verbatim goal (one-shot
ScheduleWakeup is retired; the durable recurring cron replaced it).

## The canonical cron prompt (exact string)

```
call reconcile then next_action and obey wait_hint: if it says wait, end your turn
```

Single source of truth: `RECONCILE_LOOP_CRON_PROMPT` in
`edp_claude/cadence.py` (`RECONCILE_LOOP_ROLES = ("neuron", "planner")`);
never reword it, never embed the goal in it.

## Thread reconcile's `changed` into next_action (load-bearing)

```
r = reconcile(handle=<h>, handle_type=<t>)      # {changed, wait_hint, wait_reason, ...}
a = next_action(handle=<h>, handle_type=<t>, reconcile_changed=r.changed)
```

`next_action` collapses an idle tick to a one-line `{no_change: true}`
payload ONLY when you pass `reconcile_changed=False` on an idle wait
with an empty inbox-diff; omit it and the short-circuit stays dormant.
Epochs are stateless: pass reconcile's fresh `changed` every tick.

## The heartbeat is the BACKSTOP — the push plane is the primary wake

Your `observe()` subscription wakes you when something happens; the cron
exists for when the push does NOT arrive, so its cadence sets how long a
lost wake stays invisible. Default **30 minutes**, deliberately: with
`rx.orphaned` armed (table below) stall detection no longer depends on
cadence; without it you are back to cadence-as-detector — arm the
subscription instead. A dropped edge needs a plane that carries edges,
not a faster poll.

## A shell has FOUR liveness states, and no instrument sees the last two

`alive` / `dead` / **frozen at a permission prompt** / **gone having
recorded nothing**. A child can block indefinitely at an approval
prompt, and every instrument reads it as healthy work:

| instrument | what it answers | its blind spot |
|---|---|---|
| pool liveness | "does the process exist?" | a parked shell reads `alive` |
| MCP tool-call log | "what MCP calls up to T?" | blind to Edit/Write/pytest; a frozen shell makes no calls |
| CPU / last_output_ts | "is it emitting?" | a parked thread is ~0% CPU, flat output |
| a direct `progress` ping | nothing — a frozen shell never reaches a turn boundary | silence proves nothing |

None answers "is it blocked right now?" — name each instrument's blind
spot before reasoning from it. The one external signal: output going
FLAT after prior activity = a prompt-wait, not a stall. Cheap
mitigation: a worker ANNOUNCES a permission-gated command before
running it ("about to run X; may block on approval").

## The FOURTH state: gone having recorded nothing

A shell that finishes and exits WITHOUT recording status is an ABSENCE,
not a state: no crash, so no alert; a clean exit, so the pool never
marks it `dead` — its row simply stops appearing, and `rx.pool` is a
LEVEL (a polled snapshot), so a level that stops arriving looks exactly
like a quiet channel. The action stays `in_progress` until somebody
runs `reconcile`, whose phantom sweep heals it. **The fix is
`rx.orphaned` (table below):** it joins plan/recipe state against pool
liveness, emitting ONLY when work is recorded as underway with nothing
behind it — silent on a healthy plan (deliberately no raw worker exits;
that would be noise and get ignored).

**Its COVERAGE BOUNDARY:** it covers a shell that was dispatched and
vanished — NOT work that never started. A batch member the head shell
exited before reaching is `pending`: UNDISPATCHED, not orphaned — the
stream stays correctly silent; the FSM's next ready-wave catches it. A
quiet orphan plane is not "every action has a shell behind it."

**Two traps:**

- **BATCH MEMBERS.** A batch runs as ONE shell under the HEAD action's
  handle; non-head members have none of their own. `rx.orphaned` checks
  a member's OWN handle first, falling back to its head only when the
  member has no live session (load-bearing: `batch_group` is immutable,
  so a re-dispatched member keeps naming a legitimately-gone head).
  Probing by hand: ping the batch HEAD — unless the member was
  re-dispatched standalone; then ask about its own handle.
- **THE NEURON'S HALF.** One level up the vanishing shell is a PLANNER
  leaving a step `in_progress` with no `plan_closed` ever coming. The
  neuron's pool leg must carry NO `states=['dead']` filter — a clean
  exit never passes through `dead`, so a dead-filtered list is empty on
  both sides and change-detection never fires; quiet the plane with
  `min_interval_ms` instead.

| what you see (same symptom, opposite actions) | what is true | do |
|---|---|---|
| wave offers a member dispatch, **batch head ALIVE** | in flight inside the head's shell | **do not spawn** — you'd race it on the same files |
| wave offers a member dispatch, **head GONE**, member not recorded | orphaned; nothing is doing it | **spawn it** — check the deliverable on disk first |

If the artifact already exists on disk, re-dispatch to VERIFY AND
RECORD, never to rebuild. Never let "a child will wake me" be a wait's
only exit — write down the condition that reverses a hold and re-check
THAT each tick; a liveness reading is true at an instant and decays.

## Obey wait_hint — pace the cron to what you're waiting on

`reconcile` / `next_action` / `status_ping` return an integer-minutes
`wait_hint` + a prose `wait_reason` from a deterministic PACING table:

| wait_reason band | wait_hint | when |
|---|---|---|
| `heads-down; leave alone` | 10 min | child in flight, pool log grew recently |
| `probe: status_ping->inspect_worker` | 2 min | child in flight, output stale |
| `acceptance imminent` | 1 min | an action parked at its verify gate |
| `nothing moves without the user` | 30 min | blocked awaiting the user |
| `wrap-up cadence` | 30 min | idle / winding down |

**Re-arm when the hint changes band**: `CronDelete` + `CronCreate` to
the new interval; idempotently re-confirm on every wait (`CronList` →
`CronCreate` if missing), `CronDelete` at close. Only the interval ever
changes; never the prompt string.

### Long structural waits: PARK (planner only, opencode only)

**HARNESS-GATED (operator ruling).** `park_hint` fires only on the
**opencode** harness, where `pool_close_self(park=true)` kills the CLI
process while the TUI window survives. **On Claude Code no `park_hint`
is ever emitted** — a claude planner stays resident and paces itself
with Monitor + cron (idle shells burn no tokens); never self-park
because a wait feels long — explicit parking remains an operator verb
(`suspend_recipe`). On opencode: on a `park_hint`, drain your inbox
once, then `pool_close_self(park=true)`; the pool resumes you when a
message lands (the neuron holds a `pool_resume_planner` backstop), and
your **first act on resume is `reconcile(reground=true)`** — Monitors
and crons died with the parked process; the rewire block re-arms them
and surfaces any `staleness_delta`. The neuron never parks; workers
close on done.

**Don't invalidate your cached prefix.** A periodically-woken shell
lives by the prompt cache: never switch model/effort or MCP servers
mid-session; `DISABLE_AUTOUPDATER=1` protects the cache too; keep
cwd/shell/platform stable.

## The Monitor is NOT consumed on fire — arm it once, don't re-run it

The driver does not exit on fire: it subscribes and blocks, streaming
one NDJSON line per event until you `TaskStop` it — re-running the
`monitor_cmd` after each event mints duplicate drivers. **Arm the
Monitor ONCE (`persistent: true`); handle each wake; re-arm only with
evidence the driver is actually gone; `TaskStop` at close.** Verify the
driver is live after arming and after any restart/compaction — a dead
subscription looks like a quiet channel; absence of wakes is not
evidence of absence of events.

## Grounding epochs & the rewire hand-back

Every `recipe_context` push and action grounding carries a stateless
`grounding_epoch` (12-hex digest of the load-bearing ground); pass your
last-seen one back as `ack_epoch` on `reconcile`/`next_action`:

| you send | server returns |
|---|---|
| `ack_epoch` MATCHES | steady-state short-circuit — ground unchanged |
| `ack_epoch` STALE | full digest + "ground changed" banner + a rewire block |
| `ack_epoch` absent | steady-state + current epoch echoed |
| `reground=true` | full digest + rewire block, unconditionally |

The **rewire block** is your wiring HANDED BACK, deterministically:
your handle's persisted `observe()` spec(s) + the exact re-issue call,
the canonical cron prompt + cadence, and any durable rules active.
EXECUTE it verbatim instead of reconstructing wiring from memory; echo
the epoch on interactive turns. After a compaction the
`SessionStart(compact)` hook directs your next loop turn to call
`next_action(reground=true)` — the code path returning the full digest
+ rewire block + the role CONTRACT CARD reload directive
(`reload_role_guides`); an O(1) directive, never a recipe-size dump.
Hard rules: a shell NEVER self-fires a slash command; `/reground` is a
USER-only affordance.

## Acceptance is a pure write; the shells run EVERY gate (d30)

`record_action_status` is a PURE status+evidence WRITE — it runs
nothing, cannot hang (constraint guards still run at the record seam).
Acceptance is DUAL-GATE: the WORKER runs every `acceptance.verify`
criterion in its own shell (plain-prose evidence) and the REVIEWER
independently re-runs it in a fresh shell; the planner requires
evidence + a reviewer pass before the step closes; the neuron only
tracks. A recorded `done` routes through `needs_review` — no framework
verify runner exists. Record discipline: evidence is PLAIN PROSE
(code-shaped tokens are hard-rejected; never retry rejected text
verbatim); `actual` OVERWRITES the evidence sidecar — put large
deliverables at a referenced scratchpad path.

## Judging a live worker — liveness & done via the object surface

Do NOT infer a worker's state from the event plane: `next_action` stamps
a dependent `in_progress` BEFORE any spawn (a phantom if none follows),
and a `done` record emits no legible broker event. On every wait tick
verify STATE via the object surface — `read_object("action")` for real
status/evidence, `query_objects("session"/"lock", scope=plan_id)` to
confirm a live worker backs an `in_progress` action. No `ready` message
+ only your own pings ⇒ suspect it never came up; "no session AND no
lock AND in_progress" = phantom (heal: status→pending + explicit
`pool_spawn_worker`). Don't reap an alive-but-silent worker — it may be
at a permission prompt or API-bound (near-0 local CPU is a Claude
worker's NORMAL pattern); reap only on `liveness=dead`, measuring by
wall-clock. A runtime-proof worker batch-copies evidence at the END (a
sparse evidence dir mid-run is not a stall); a single verify criterion
is a floor (verify the whole bundle, with real input); a recorded
finding is not an approval. The reviewer leg gets broader-regression
scope with in-session fix authority and re-proves each claim
INDEPENDENTLY: through the REAL production entrypoint, provoking each
lifecycle property and reading it back from an independent source,
re-proving a handed-down "fix this bug" premise on the real path, and
exercising the real client method — never a raw POST that bypasses the
changed code.

## Per-role observe subscriptions — THIS TABLE IS THE ONLY ONE

Hand-copied variants of this set all drifted — copy it from here;
never re-spell it.

| role | subscribe to |
|---|---|
| **neuron** | `rx.broker(me)` **(no kind filter)** + flowback `rx.recipe_events(me, kinds=['learning','discovery','blocker','spec_learning_proposed','review_finding'], exclude_from=me)` + `rx.pool(scope=me)` + **`rx.orphaned(recipe_id=me)`** |
| **planner** | `rx.broker(me)` **(no kind filter)** + `rx.worklog(plan_id)` + `rx.pool(scope=plan_id)` + **`rx.orphaned(plan_id)`** + flowback **`rx.recipe_events(recipe_id, kinds=['learning','discovery','blocker','spec_learning_proposed','review_finding'])`** |
| **worker** | `rx.broker(me, kinds=['answer','steer'])` |
| **curiosity** | `rx.broker(me, kinds=['answer','consult'])` |

**The planner's flowback leg:** `emit_recipe_event` writes to the
RECIPE's events channel; a planner without `rx.recipe_events` is deaf
to its own workers' broadcasts — they reach the neuron only, and
nothing errors: a missing subscription reads as an absence of events
(the honest claim is "I have no record", never "my worker said
nothing"). Arm it as its OWN subscription (one fate — below), bind
`recipe_id` from your lineage (not your `plan_id`), and do NOT pass
`exclude_from=me` — the NEURON's clause.

### This table is a FLOOR, not the answer

The MINIMUM every shell of that role must hold — compose more:

| your situation | add |
|---|---|
| waiting on ONE long child | race the wait against a timer deadline, so silence expires |
| driving a parallel wave, need ALL of them | a fork-join whose legs are completion-shaped |
| you suspect a silent stall | `rx.orphaned(…)` **plus a timeout** — orphan covers a vanished shell, the timeout one that is merely mute |
| escalate only after N failures | a scan to a threshold plus a filter |
| a polled source is chatty | `min_interval_ms` on **that source only** (never on a merge) |

Operators and traps: `get_guide("reactive-streams")`; worked examples:
`get_guide("reactive-streams-reference")`. **Under-wiring is a real
failure** — treating the floor as the ceiling produces stalls.

**Re-check your wiring when the situation changes shape.** `wait_reason`
is a deterministic band the loop already computes; on a tick where the
band CHANGES, spend one thought on whether your wiring still fits
(steady tick: nothing). Shifts worth re-composing for: wave-driving →
waiting on one long child; waiting → dispatching several units you need
all of; or catching yourself reasoning "it must still be working,
nothing told me otherwise" — a TRIGGER, not a conclusion: ask what
could have told you, and arm that. Review the reground hand-back's
specs rather than re-arming by reflex; re-compose by ADDING a
subscription, never by re-specing the one carrying your mail.

### DO NOT kind-filter your own directed inbox (load-bearing)

`kinds=None` applies no filter — every message addressed to you wakes
you; that is the driving-role default. **A kind-filter on your own
inbox drops messages ADDRESSED TO YOU, silently** — including `alert`,
the kind reserved for things that must interrupt, and the message
announcing the filter itself changed. Filter the CHATTY BROADCAST
planes (`rx.recipe_events`, `rx.pool`) — never your directed inbox; if
you nonetheless filter, `alert` is UNDROPPABLE and never drop
`plan_closed` / `done` / `question` / `answer` / `steer` / `consult`.
**And do not MERGE a chatty or newly-landed source into the driver
carrying your inbox — arm it as its OWN subscription.** A merge gives
every leg one fate: monitors that over-emit are auto-stopped, so a
fault in the new source takes your MAIL down with it — going deaf is
silent. **One fate per subscription** — a source you are still learning
to trust must not be able to kill one you depend on.

> Residual, unfixed: the wake set is narrowed in TWO independent places
> — your `observe` spec and the tool layer's `ROLE_WAKE_KINDS` — with
> no reconciliation between them; `rx.broker(me)` closes your half.

`min_interval_ms` on `observe()` caps ONLY the polled snapshot sources
(`rx.pool`/`rx.plan`/`rx.external`), per-source and before your
`rx.merge`; the critical planes (`rx.worklog`, `rx.broker`) are never
limited. Never put a wait-for-quiet operator in front of an event you
must not miss, and never rate-limit a merged stream.

## Role scope — who uses this loop

* **neuron + planner** → the canonical reconcile-loop prompt above:
  `reconcile` → `next_action(reconcile_changed=…)` → obey `wait_hint`.
* **worker + curiosity** → they do NOT call reconcile/next_action; they
  keep their existing `check_inbox`-based Step-0 cron prompts VERBATIM.
