# Loop & heartbeat — the self-paced reconcile loop (neuron + planner)

Load via `get_guide("loop-and-heartbeat")`. This is the cadence contract for
the two roles that DRIVE a recipe/plan by their own heartbeat — the **neuron**
and the **planner**. Workers and curiosity do NOT drive; they keep their
`check_inbox` heartbeat and can skip this page (see "Role scope" below).

The loop is a **reflex, not the goal**. Each wake fires a short, role-scoped
reflex — `reconcile` then `next_action` — and the recipe/plan STATE (not the
cron string) carries the goal. This is why the cron prompt is a fixed one-liner
and never the verbatim goal (the retired ScheduleWakeup-long-prompt pattern).

## The canonical cron prompt (exact string)

Arm your heartbeat cron with **exactly** this prompt — neuron and planner only:

```
call reconcile then next_action and obey wait_hint: if it says wait, end your turn
```

This is the single source of truth (`RECONCILE_LOOP_CRON_PROMPT` in
`edp_claude/cadence.py`; `RECONCILE_LOOP_ROLES = ("neuron", "planner")`). Do not
reword it and do not embed the goal in it.

## Thread reconcile's `changed` into next_action (load-bearing)

"Call reconcile **then** next_action" is not two independent calls — the loop
**passes reconcile's result into next_action**:

```
r = reconcile(handle=<h>, handle_type=<t>)      # returns {changed, detail, wait_hint, wait_reason, ...}
a = next_action(handle=<h>, handle_type=<t>, reconcile_changed=r.changed)
```

`next_action` collapses an idle tick to a one-line `{no_change: true, wait_hint,
wait_reason}` payload **only** when the loop opts in by passing
`reconcile_changed=False` (i.e. reconcile just reported the record already
matches reality) AND the tick is an idle WAIT with an empty inbox-diff. This is
the W7 idle-token-drop: on a heads-down hour it turns each expensive
instruction+context push into a one-liner.

**If you omit `reconcile_changed`, the short-circuit stays DORMANT** — a bare
`next_action()` (reconcile_changed left `None`) always returns the full
instruction, so its `wait_hint` still rides in the args, but the per-tick token
saving never fires. Threading the value is what activates it in production.
Epochs are stateless (d13): `reconcile_changed` is a per-call signal, never a
stored `last_acked_epoch` — pass reconcile's fresh `changed` every tick.

## The heartbeat is the BACKSTOP — the push plane is the primary wake

Your `observe()` subscription is what wakes you *when something happens*. The
cron exists for when that push **doesn't arrive** — a dropped event, a dead
driver, a missed transition. So its cadence sets **how long a lost wake stays
invisible**, and that is the number to choose deliberately:

**REVISED 2026-07-25 — the default is now 30 MINUTES, and that is deliberate.**
The old advice below told a planner dispatching a serial chain to poll at ~60s.
That was written when cadence was, in practice, the stall detector — and using
it that way is a category error that costs a poll a minute forever and still
leaves a window. **With `rx.orphaned` armed (see the per-role table), detection
no longer depends on cadence at all**, so the backstop widens and the
observation budget goes to the shells doing work.

- **Whatever you are waiting on**: the push plane is the primary wake and
  `rx.orphaned` covers the silent-exit case. Follow `wait_hint`.
- **If you have NOT armed `rx.orphaned`** (an older shell, or a plane you could
  not re-arm): you are back to cadence-as-detector, and then a tight interval is
  the only thing standing between you and an invisible stall. Arm the
  subscription instead — it is strictly better and far cheaper.

The historical warning still holds for the case it was written about: a planner
running an 11-minute heartbeat lost a worker's `done` on the push plane and did
not notice for four minutes. The lesson is **not** "poll harder" — it is that a
dropped edge needs a plane that carries edges, which is what was missing.

## A shell has FOUR liveness states, and no instrument sees the last two

`alive` / `dead` / **frozen at a permission prompt** / **gone having recorded
nothing.** The fourth is covered in its own section below (it is not a liveness
reading at all — it is an ABSENCE, and it needs a different instrument). On a manual-permission
host a child running a Bash/PowerShell command can block INDEFINITELY at an
approval prompt, and every instrument reads it as healthy work:

| instrument | what it actually answers | its blind spot |
|---|---|---|
| pool liveness | "does the process exist?" | says `alive` — the process is fine, it is just parked |
| MCP tool-call log | "what MCP calls happened up to T?" | blind to Edit/Write/pytest (they run through the harness), and a frozen shell makes no calls at all |
| CPU / last_output_ts | "is it emitting?" | a parked thread is ~0% CPU and flat output |
| a direct `progress` ping | nothing — **a frozen shell never reaches a turn boundary to read its inbox** | cannot be answered, so silence proves nothing |

None of them answers *"is it blocked right now?"* So a planner cannot
distinguish a converging worker from a frozen one, and will either over-wait or
reap live work. **Do not "refute" a suspected block by citing an instrument that
cannot see it** — name each instrument's blind spot before you reason from it.

The one external signal that does exist: **output goes FLAT after prior
activity. On a manual-permission host, flat-output-after-activity is the
signature of a prompt-wait, not a stall.**

Mitigation, and it is the cheap one: **a worker about to run a permission-gated
command ANNOUNCES it first** — one line ("about to run X; may block on
approval"). A later freeze is then expected and legible instead of a mystery
that costs the planner an hour of guessing and nearly costs the worker a reap.

## The FOURTH state: gone having recorded nothing (2026-07-25)

A shell that finishes its work and then exits **without recording status** is
the one failure none of the instruments above can see, because **it is not a
state — it is an absence.** There is no crash, so no `child_crashed` and no
alert. The exit is *clean*, so the pool never marks it `dead`; the row simply
stops appearing. And `rx.pool` is a **LEVEL** — a polled snapshot — so **a level
that stops arriving is indistinguishable from a quiet channel.** The one event
you most need is the one event the plane cannot carry.

What it costs: the action stays `in_progress`, a status **no code ever writes
and no code ever clears** except a worker that is already gone. The plan looks
busy. Nothing is running. It stays that way until somebody happens to call
`reconcile` — whose phantom sweep heals it correctly and always did. **The
healing logic was never the defect; nothing told anyone to run it.**

This is what made the heartbeat interval the de-facto stall detector, and that
was a category error. `reconcile`'s job is drift-control and state progression.
Using cadence to detect an absence means paying a poll a minute forever and
STILL leaving a window.

**The fix is `rx.orphaned` — subscribe to it (see the table above).** It JOINS
plan/recipe state against pool liveness and emits only when work is recorded as
underway with nothing behind it. It deliberately does NOT emit raw worker exits:
that would fire on every normal close, become noise, and get ignored — which is
precisely how this blindness survived. A wake there always means something is
wrong. A healthy plan emits nothing at all.

**Its COVERAGE BOUNDARY, because somebody will otherwise lean on it for the one
case it cannot see.** It joins work RECORDED AS UNDERWAY against pool liveness.
So it covers a shell that was dispatched and then vanished — and it does NOT
cover work that never STARTED. A batch member the head shell exited before
reaching is `pending`, not `in_progress`: it is UNDISPATCHED, not orphaned, and
this stream will stay correctly silent about it forever. That case is caught by
the FSM offering the action on your next ready-wave, and by you reading actual
state on a wait tick — not here. Do not read a quiet orphan plane as "every
action has a shell behind it."

**Two traps this closes, and you must know both:**

- **BATCH MEMBERS.** A batch runs as ONE shell registered under the **head**
  action's handle; non-head members have no handle. Probing `<plan_id>:<member>`
  asks about a handle that never existed, gets nothing, and reads a healthy
  member as dead. `rx.orphaned` checks a member's OWN handle first and falls back
  to its head only when the member has no live session of its own. When you probe
  by hand, **ping the batch HEAD** — unless the member was re-dispatched
  standalone, in which case it now has its own handle and that is the one to ask
  about. (The own-handle-first order is not a nicety: `batch_group` is IMMUTABLE
  after authoring, so a member re-dispatched on its own keeps pointing at a head
  that is legitimately gone. Resolving to the head alone declared a healthy
  worker orphaned on every poll, forever, with no move available to the planner
  that fixed it.)
- **THE NEURON'S HALF.** One level up the vanishing shell is a PLANNER, and it
  leaves a step `in_progress` while the neuron waits on a `plan_closed` that
  will never be sent. The neuron's pool leg used to carry `states=['dead']` —
  **that filter is exactly the blindness**, because a clean exit never passes
  through `dead`. It has been removed from the table above; quiet that plane
  with `min_interval_ms` instead (safe here: the pool is a level).

**Two situations, identical symptom, opposite correct actions** — this is the
discrimination that costs you if you get it wrong:

| what you see | what is true | do |
|---|---|---|
| wave offers a member dispatch, **batch head ALIVE** | it is in flight inside the head's shell | **do not spawn** — you would race it on the same files |
| wave offers a member dispatch, **head GONE**, member not recorded | orphaned; nothing is doing it | **spawn it** — and check the deliverable on disk first |

**Check the disk before you decide.** If the artifact already exists, the shell
got far enough to produce it and the question is no longer "is it still
building?" but "why was it never recorded?" — which has exactly one answer.
Re-dispatch to VERIFY AND RECORD, never to rebuild; rebuilding destroys
finished work.

**And never let "a child will wake me" be a wait's only exit.** Write down the
condition that reverses a hold and re-evaluate *that* on the next tick, rather
than inheriting the decision. A liveness reading is true at an instant and
decays silently; it is not a standing fact.

## Obey wait_hint — pace the cron to what you're waiting on

`reconcile`, `next_action`, and `status_ping` each return an integer-minutes
`wait_hint` plus a prose `wait_reason`, computed from a deterministic PACING
table (no LLM). Use them to set your cron interval instead of blindly firing
every minute:

| wait_reason band | wait_hint | when |
|---|---|---|
| `heads-down; leave alone` | 10 min | child in flight, pool log grew recently |
| `probe: status_ping->inspect_worker` | 2 min | child in flight but output went stale |
| `acceptance imminent` | 1 min | an action is parked at its verify gate |
| `nothing moves without the user` | 30 min | blocked awaiting the user |
| `wrap-up cadence` | 30 min | idle / winding down |

### Long structural waits: don't heartbeat — PARK (planner only, DESIGN-v7 1.5.2)

> **HARNESS-GATED (2026-07-21, operator ruling).** Everything in this section
> fires only on the **opencode** harness, where `pool_close_self(park=true)`
> kills the CLI process but the **TUI window survives** and the resume forks
> straight back into it. **On Claude Code no `park_hint` is ever emitted** —
> there the shell *is* the process, so a park closes it outright and the
> resume is a NEW shell replaying the transcript onto a "You were parked and
> resumed" line that costs a turn to act on. A claude planner **stays
> resident** and paces itself with its Monitor + heartbeat cron, exactly as
> the neuron does. This costs nothing: an idle Claude shell burns no tokens
> while waiting, and the context re-send that park/fork-resume pays on wake
> is the same one it was trying to avoid. If you are on claude, read the rest
> of this section as background — the hint will not arrive, and you must not
> self-park because a wait feels long. Explicit parking still exists for the
> operator's own verbs (`suspend_recipe`); what was withdrawn is the standing
> advice to park on every long wait.

When a planner's `wait` args carry a code-computed **`park_hint`** (pacing
state `child_in_progress_*` or `awaiting_user`, expected wait ≥
`EDP_PARK_THRESHOLD_SECS`, default 600s), the right move is not a slower
cron — it is no shell at all: **drain your inbox once more, then
`pool_close_self(park=true)`** and end the turn. The pool parks the quiesced
shell (0 tokens, 0 process; handle lock + resume token kept; `Plan.parked`
stamped as the durable recovery copy) and **resumes you automatically when a
message lands** on your inbox — the pool's resume watchdog polls parked
inboxes every few seconds, and the neuron holds a `pool_resume_planner`
backstop for when the watchdog is down. You return as a FORK of your parked
session with your reasoning context preserved. **Your first act on resume is
`reconcile(reground=true)`** — your Monitors and crons died with the parked
process, and the reground's rewire block is what re-arms them; it also
surfaces any `staleness_delta` (sibling work that landed while you slept —
revalidate before dispatching, per agentic-plan.md). Parking is a planner
move only: the neuron drives the whole recipe and stays resident; workers
never park (they are disposable and close on done).

**Re-arm when the hint changes band.** Set the cron interval to roughly the
`wait_hint`; when the next tick returns a hint in a different band (a heads-down
10-min wait becomes a 1-min "acceptance imminent"), `CronDelete` + `CronCreate`
to the new interval. Don't gate on "already armed this session" — idempotently
re-confirm the cron on every wait (`CronList` → `CronCreate` if missing), and
`CronDelete` at close. The prompt string stays the canonical one above; only the
interval changes.

## Don't invalidate your cached prefix (DESIGN-v6 §W6/2b)

A periodically-woken shell re-reads its whole context on every wake, so it lives
or dies by the prompt cache. Claude Code caches automatically; on a Claude
subscription the TTL is **1 hour** by default (API-key/Bedrock/Foundry default to
5 min and opt in via `ENABLE_PROMPT_CACHING_1H=1`). With a 1-hour TTL every wake
band above rides a WARM cache instead of a cold full-price re-read — which is why
`wait_hint` bands are free to be workload-driven and no longer have to squeeze
under 5 minutes.

Each of these forces a full recompute of the cached prefix. They are cheap to
avoid and expensive to trip:

- **Never switch model or effort mid-session.** Both are set at SPAWN and never
  changed in-flight (the pool does this; `effortLevel` is a settings key, not a
  per-turn knob).
- **Never connect or disconnect an MCP server mid-session.**
- **`DISABLE_AUTOUPDATER=1` is ALSO a cache protection**, not only a breakage
  guard: a Claude Code upgrade invalidates every prefix on resume.
- **Keep cwd / shell / platform stable across wakes** (the pool already does).
- **Compaction is bounded:** `/compact` rebuilds the CONVERSATION cache but
  REUSES the system-prompt cache — so a compaction is not a full cold start.

## The Monitor is NOT consumed on fire — arm it once, don't re-run it

**This rule used to say the opposite, and the opposite was false.** It said the
driver is consumed when an event fires, so you should "re-run your `monitor_cmd`
before doing anything else". A planner obeyed it literally and ended up with
FOUR live drivers on one subscription, every event arriving 4×.

The driver does **not** exit on fire. It subscribes and blocks; its sources
(broker SSE, file tails, pollers) never complete, so it keeps streaming — one
NDJSON line, one notification, per event, until you `TaskStop` it. Note what the
retired rule did: the SAME guide already warns that a second `observe()` mints a
duplicate driver, so **its re-arm rule manufactured the exact duplicate its other
rule forbids.**

> **Arm the Monitor ONCE (`persistent: true`). Handle each wake. Do NOT re-run
> the `monitor_cmd`.** Re-arm only with evidence the driver is actually gone
> (e.g. the Monitor task has exited) — and `TaskStop` it at close.

And because a dead or starving subscription is indistinguishable from a quiet
channel: **verify the driver is live after arming and after any
restart/compaction.** Absence of wakes is not evidence of absence of events —
nothing today tells a shell it has gone deaf.

## Grounding epochs & the rewire hand-back (W2)

Every `recipe_context` push and every `read_object("action")` grounding carries
a **`grounding_epoch`** — a STATELESS 12-hex digest of the recipe's load-bearing
ground (active load-bearing decisions + active constraints/bans + pending unacked
load-bearing assumptions). It is recomputed from the recipe on every call; there
is NO stored `last_acked_epoch` (d13). Pass your last-seen epoch back as
`ack_epoch` on `reconcile`/`next_action` (both accept `ack_epoch` and `reground`):

| you send | server returns |
|---|---|
| `ack_epoch` MATCHES current | steady-state pointer / short-circuit — ground unchanged |
| `ack_epoch` STALE | full `get_recipe_digest` + "ground changed" banner **+ a rewire block** |
| `ack_epoch` absent | steady-state + current epoch echoed (a lean cron tick, NOT compaction) |
| `reground=true` | full digest + rewire block, unconditionally |

The **rewire block** is your wiring HANDED BACK (deterministic, no LLM): your
handle's ACTUAL persisted `observe()` spec(s) + the exact call to re-issue (run
its `monitor_cmd` under Monitor), the canonical cron prompt CONSTANT + current
cadence (never the goal), and any durable `register_rule` already active. On a
reground/stale tick, EXECUTE the rewire block verbatim instead of reconstructing
your wiring from memory. On interactive turns, echo the epoch from your last
context push (e.g. `epoch=<hex>`) so a stale-vs-current mismatch is visible.

## Automatic re-ground after a compaction (W13)

You never have to remember to re-ground after the harness compacts your context.
A **`SessionStart(compact)` hook** (`.claude/hooks/reground-on-compact.py`) fires
on `source == 'compact'` (a no-op for startup/resume/clear) and injects a short,
bounded banner that directs your very next reconcile-loop turn to call
**`next_action(reground=true)`** — the same code-assembled, no-LLM path that
returns the full W1 digest + W2 monitor-rewire block from the single source of
truth (`_reground_payload`). The hook injects only that O(1) directive, never a
recipe-size dump. The **step-count-gap backstop** (`recipe_fsm.py`) stays as the
SECONDARY net for ground drift that is not a compaction. Two hard rules (d36):
the agent NEVER self-fires a slash command — the re-ground rides the loop's own
`next_action(reground=true)`, not a `/`-command — and a manual **`/reground`** is
a USER-only affordance (a human may type it to force a re-ground; a shell must
not).

## Acceptance is a pure write; the shells run EVERY gate (d30)

`record_action_status` is a PURE status+evidence WRITE: it stores the claim +
evidence and returns instantly. It runs NOTHING — no acceptance command AND no
file/glob check — spawns no subprocess, enqueues no detached verify, and cannot
hang. The a1 constraint guards still run at the record seam (a banned-pattern
completion is refused citing the decision id); worker evidence is INERT DATA.

Acceptance is DUAL-GATE (d30): every `acceptance.verify` criterion — command
AND file/glob alike — is run by the WORKER in its own shell as part of the work
(reported as plain-prose evidence) AND independently re-run by the REVIEWER in a
fresh shell (that re-run IS the objective gate, via the worker→reviewer chain);
the framework runs neither. The planner requires evidence + a reviewer pass
before the step closes; the neuron only TRACKS. A recorded `done` no longer
parks at a framework `verify` state — that state is unreachable-on-record under
d30, replaced by `needs_review` + the worker→reviewer chain. No detached pool
verify-runner, no `verify_result`, no in-process pure-check gate, no
`EDP_DETACHED_VERIFY` — all retired.

**Worker record discipline (folded from foreground lore, W15/a6).** (1)
`record_action_status` evidence must be PLAIN PROSE — zero code-shaped tokens
(no backticks, filenames+extensions, line numbers, dotted/snake_case
identifiers, CLI/route names) or the permission layer hard-rejects the record;
describe the gate outcome in words and never retry rejected text verbatim.
(2) `record_action_status` `actual` OVERWRITES the evidence sidecar
(`evidence/<ACTION>-actual.md`) — a large deliverable (design doc, full report)
goes to a scratchpad path referenced from the summary, never into `actual`.

## Judging a live worker — liveness & done via the object surface (W15/a6)

Do NOT infer a worker's state from the reactive event plane: `next_action`
STAMPS a dependent `in_progress` before any spawn (a phantom if none follows),
and `record_action_status(done)` is a pure write with no legible broker event.
On every wait tick verify STATE via the object surface — `read_object("action")`
for real status/evidence, `query_objects("session"/"lock", scope=plan_id)` to
confirm a live worker actually backs an `in_progress` action. A genuine worker
sends a `ready` message and writes real worklog; no `ready` + only your own
pings ⇒ suspect it never came up, and "no session AND no lock AND in_progress"
= phantom (heal with status→pending + explicit `pool_spawn_worker`).

- **Don't reap an alive-but-silent worker on silence alone.** It may be
  awaiting a user-permission grant, or it is API-bound (a Claude worker's
  compute is server-side, so near-0 LOCAL CPU + no local worklog write is the
  NORMAL working pattern). Reap only on `liveness=dead`; measure elapsed by
  WALL-CLOCK (real timestamps), not cron-cycle count; surface a suspected
  permission-wait instead of reaping a valid in-progress run.
- **A runtime-proof worker batch-copies its evidence at the END** — a sparse
  evidence dir mid-run is expected, not a stall; judge liveness from the pool +
  dev-server log, not artifact count.
- **A single `acceptance.verify` criterion is a floor, not the proof.** Before
  surfacing a runtime-proof/demo for USER blessing, manually verify the whole
  BUNDLE (every promised screenshot on disk, no leftover PLACEHOLDER, each
  requirement honestly marked pass) and require real/trusted input, not a
  programmatic `element.click()`.
- **A recorded finding is not an approval.** A decision that accepts your
  MEASUREMENT is a different speech act from a yes to an apply/gate question —
  wait for the explicit answer to that question.
- **Give the independent reviewer leg broader-regression scope.** Per-action
  verify criteria (which the WORKER runs in-shell and the REVIEWER re-runs, d30)
  cover only the workstream's own files; a doc/guide-sync that trips a
  project-wide guard (size cap, thin-dispatcher, coherence) slips through —
  scope the reviewer to guard/size/coherence tests outside the per-action set,
  with in-session fix authority.

## Reviewer re-prove discipline — don't let builders self-bless (W15/a6)

A dedicated reviewer/verify leg re-proves each claim INDEPENDENTLY:

- **Through the REAL production entrypoint**, not the builder's standalone
  harness; prove execution discipline (sequential vs concurrent) by re-driving
  the SAME planner-derived DAG under each mode and reading event ORDER off the
  plane, not wall-clock.
- **Actively PROVOKE each lifecycle property** and read it back from an
  independent source — evidence that only echoes the build's own demo log is
  not proof.
- **Re-prove a handed-down "fix this bug" premise** on the real path before
  applying the fix; report hardening-vs-functional-repair honestly.
- **Name the concrete real role in a spawn/verify brief** — a generic noun like
  "probe" gets read literally as `role=probe` — and exercise the real CLIENT
  method, not a raw service POST that can bypass the changed code.

## Per-role observe subscriptions — THIS TABLE IS THE ONLY ONE

Composed here once, on purpose: this set used to be hand-copied into four places
and **all four drifted** — the neuron's list appeared with 6 kinds in one guide,
5 in another, and 4 in the code, and no two agreed. Copy it from here; never
re-spell it.

| role | subscribe to |
|---|---|
| **neuron** | `rx.broker(me)` **(no kind filter)** + flowback `rx.recipe_events(me, kinds=['learning','discovery','blocker','spec_learning_proposed','review_finding'], exclude_from=me)` + `rx.pool(scope=me)` + **`rx.orphaned(recipe_id=me)`** |
| **planner** | `rx.broker(me)` **(no kind filter)** + `rx.worklog(plan_id)` + `rx.pool(scope=plan_id)` + **`rx.orphaned(plan_id)`** + flowback **`rx.recipe_events(recipe_id, kinds=['learning','discovery','blocker','spec_learning_proposed','review_finding'])`** — see below, this row was WRONG until 2026-07-25 |
| **worker** | `rx.broker(me, kinds=['answer','steer'])` |
| **curiosity** | `rx.broker(me, kinds=['answer','consult'])` |

### The planner's flowback leg — added 2026-07-25 after it bit twice in one night

**A PLANNER DID NOT HOLD `rx.recipe_events` AND WENT DEAF TO ITS OWN WORKERS.**
`emit_recipe_event` writes to the RECIPE's events channel. The neuron subscribes
to it; a planner did not. So a worker's broadcast reached the neuron and **never
reached the planner that briefed it** — not a dropped event, not a race: the
plane was never wired to the planner at all.

Found live on the Fit recipe (s13). TWO findings from its own workers went that
way in one evening — a Web Crypto/IndexedDB constraint and a stale-manifest
report — and in both cases the NEURON had to relay them back DOWN to the
planner. That relaying is precisely what the flowback channel exists to remove.

**Why it is worse than an ordinary missed subscription.** The planner composes
the next action's brief. It is the shell that most needs a worker's discovery,
and it was the last to know. Worse, it cannot notice: nothing arrives, nothing
errors, and there is no signal that a plane is missing. The planner in question
searched its plan worklog for text that was never going to be there, then
asserted to the neuron that its worker *had said nothing* — when the honest
claim available to it was "I have no record of that". **A missing subscription
does not read as missing information; it reads as an absence of events.** Same
family as the rest of this guide's hard-won rules: the failure is an absence
that looks exactly like a pass.

**Arm it as its OWN subscription**, not merged into the driver carrying your
inbox — see ONE FATE PER SUBSCRIPTION in `get_guide("reactive-streams")`.
Bind `recipe_id` from your lineage, not your `plan_id`.

Do NOT pass `exclude_from=me` (that is the NEURON's clause, which stops the
neuron waking on its own emissions); a planner is not the emitter here, and
copying the neuron's row verbatim would filter out nothing while looking
correct.

### This table is a FLOOR, not the answer

It is the MINIMUM every shell of that role must hold — not the complete wiring
for your situation. **Compose more when your situation calls for it.** The layer
carries far more than these three sources, and the reason recipes use so little
of it is that this table is copyable and the rest needs a second guide fetch a
context-pressed shell never makes. So the upgrade path is here:

| your situation | add |
|---|---|
| waiting on ONE long child | race the wait against a timer deadline, so silence expires instead of lasting forever |
| driving a parallel wave and you need ALL of them | a fork-join whose legs are **completion-shaped**, or it never fires |
| you suspect a silent stall | `rx.orphaned(…)` **plus a timeout** — the orphan source covers a vanished shell, the timeout covers one that is merely mute |
| you want N failures before escalating | a scan to a threshold plus a filter, rather than reacting to the first |
| a polled source is chatty | `min_interval_ms` on **that source only** (never on a merge) |

Composition operators and their traps: `get_guide("reactive-streams")`; worked
examples: `get_guide("reactive-streams-reference")`.

**Under-wiring is a real failure, not the safe default.** Most warnings in these
guides are about over-subscribing, which makes the minimal set feel safest — but
on 2026-07-25 three separate stalls were all UNDER-subscription: a pool leg
filtered so a clean exit was invisible, an orphan source nobody had armed, and a
timeout nobody used on a shell that went quiet mid-batch. Caution about what you
arm is earned; treating the floor as the ceiling is not.

### Re-check your wiring when the situation changes shape (during the heartbeat)

You arm at step zero, when you know least about how the run will go. The reflex
loop is where you re-orient, so it is also where you notice the wiring no longer
fits — **but the loop is deliberately cheap and this must not make it expensive.**
So use the signal the loop ALREADY computes: `wait_reason` is a deterministic
band (`heads-down` / `probe` / `acceptance imminent` / `nothing moves without the
user` / `wrap-up`). **On a tick where the band CHANGES, spend one thought on
whether your wiring still fits; on a tick where it does not, do nothing.** A
steady tick stays a one-line no-change payload, exactly as now.

Three shifts worth re-composing for, and what to add is in the table above: you
moved from driving a wave to waiting on one long child; you moved from waiting to
dispatching several units you need all of; or **you caught yourself reasoning "it
must still be working, nothing told me otherwise"** — that sentence is not a
conclusion, it is a trigger. Ask what *could* have told you, and arm that.

The reground hand-back returns your persisted specs to re-arm: **review whether
they are still right rather than re-arming them by reflex.**

**Re-compose by ADDING a subscription, not by re-specing the one carrying your
mail** — see the one-fate rule below.

### DO NOT kind-filter your own directed inbox (load-bearing)

`kinds=None` applies **no filter** — every message addressed to you wakes you.
That is the default for the two long-lived driving roles, and it is a correction
paid for in lost hours:

**A kind-filter on your own inbox drops messages ADDRESSED TO YOU, silently, and
nothing tells you.** The neuron's filter omitted `alert` — *the kind reserved for
things that must interrupt* — so it swallowed an alert that the enforce-flip gate
was unsound, an alert that the objective gate could not record its verdict, an
alert that `record_context` silently drops a `constraint`, and, perfectly, **the
message announcing that the filter itself had changed.** The channel that carries
bad news must not be filterable by the thing the bad news is about. Total inbound
volume was ~40 messages in 12 hours: the filter never saved anything worth what it
cost. The USER caught this, not the shell.

Filter the CHATTY BROADCAST planes (`rx.recipe_events`, `rx.pool`) — never your
directed inbox. If you nonetheless filter, `alert` is UNDROPPABLE, and never drop
`plan_closed` / `done` / `question` / `answer` / `steer` / `consult`
(`consult`/`steer` are the user's inbound channel, W5).

**And do not MERGE a chatty or newly-landed source into the driver that carries
your inbox — arm it as its OWN subscription.** A merge gives every leg one fate:
monitors that emit too many events are stopped automatically, so a fault in the
new thing takes your MAIL down with it, and going deaf is silent. This is not
hypothetical. A planner merged the orphan leg with its broker inbox; a detector
bug then emitted an identical false verdict every two seconds, and the only way
to stay reachable was to tear the whole subscription down and re-arm without it.
Had the auto-throttle won that race first, the shell would have lost every steer
and answer addressed to it with no indication that anything had changed. Same
lesson as the kind-filter above, arriving from the opposite direction: there a
filter made a needed signal invisible; here an unfiltered one threatened to
drown the channel it shared. **One fate per subscription is the point — a source
you are still learning to trust must not be able to kill one you depend on.**

> **Residual, unfixed and worth knowing:** the wake set is narrowed in TWO
> independent places — your own `observe` spec, and `ROLE_WAKE_KINDS` in the tool
> layer (`reactive/runtime.py`) — with no reconciliation between them and no
> warning when a directed message arrives outside either. A shell can stop hearing
> its own mail and never find out. `rx.broker(me)` closes your half of it.
Chatty planes can be quieted with the per-spec `min_interval_ms` rate-limit knob
on `observe()` (default 0 = every emission wakes you). It caps ONLY the polled
snapshot sources (`rx.pool`/`rx.plan`/`rx.external`), per-source and before your
`rx.merge`; your critical planes (`rx.worklog`, `rx.broker`) are never limited,
at any setting. It used to be a debounce on the MERGED stream, which silently
DISCARDED a worker's `done` whenever a poller was merged in — never put a
wait-for-quiet operator in front of an event you must not miss, and never
rate-limit a merged stream. Full account: `get_guide("reactive-streams")`.

## Role scope — who uses this loop

* **neuron + planner** → the canonical reconcile-loop prompt above; they drive
  via `reconcile` → `next_action(reconcile_changed=…)` and obey `wait_hint`.
* **worker + curiosity** → they do NOT call reconcile/next_action; they keep
  their existing `check_inbox`-based Step-0 cron prompts VERBATIM. The canonical
  reconcile-loop prompt is neuron+planner ONLY.
