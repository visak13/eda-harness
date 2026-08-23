# Neuron command redesign — findings + recommendations (2026-08-22)

Status: RECOMMENDATIONS ONLY, no code/command edits yet. Checkpoint commit `a15bf0e`.
Owner's vision (verbatim summary): neuron = router; owns the execution plan (recipe);
never writes code; keeps the framework up; loop = whoami → arm_wiring → open/resume
recipe → reconcile (changed?) → next_action; @Pool for lifecycle/capacity/liveness;
@Recipe driven by an FSM that can be wrong, CRUD is the truth.

## 1. What the evidence says (sources: commands, tools/roles.py, _tools.py, recipe_fsm.py,
reactive/*, transcripts idiot_neuron_role.txt + no_change.txt, docs/pain-points.jsonl)

- `.claude/commands/neuron.md` = 18.4k chars (~4.6k tokens budget). Composition:
  roles/neuron.md 11.1k + why-and-where 2.2k + decision-rights 1.6k + vocabulary-core 2.7k
  + terse-core 0.8k. terse-core duplicates `.claude/output-styles/edp-terse.md`.
- Neuron has **61 MCP verbs** (planner 41, worker 27, curiosity 12). roles.py itself flags
  `record_action_status`, `pool_spawn_worker`, `record_recipe`, `run_ocak_audit` as
  held-only-because-of-stale-prose. Overlaps: `fold_decisions`/`supersede_decision`,
  `broker_send`/`ask_above`/`notify_above`, `record_context`/`recall`/`search_context`.
- **No pool read verb.** There is no `pool_status`/`pool_get`; pool state reaches the
  neuron only via `rx.pool` wakes and `status_ping`/`pool_reap`. The owner's "@Pool GET"
  does not exist today.
- `whoami()` returns "neuron" for every role (memory: identity block unpopulated).
- Event plane is real and good: `arm_wiring` composes
  `rx.merge(rx.broker(me), rx.pool(scope=me), rx.recipe_events(me, kinds=[learning,
  discovery, blocker, spec_learning_proposed, review_finding]))`; Monitor wakes deliver the
  event JSON. Cron heartbeat (`*/30`) is a backstop but in transcripts it **double-fires
  with Monitor** and triggered a false "is s2 stuck" investigation (5 wasted round-trips).
- `reconcile` returns `changed` + `alert` + advisories (resume-planner, unacked steers,
  fold nag, G6 budget, reground). `next_action` is pure; returns `kind` + `context`
  (phase a–e, recap, wait_hint, review_due, comprehension_recheck…). The FSM already
  handles "scope grew → re-signoff" (`signoff_stale → AWAIT_USER`) and
  "all outcomes met → DISPATCH_ACCEPTANCE".
- **OCAK is retired in code** (recipe_fsm removed the self-audit gate; `run_ocak_audit`
  is a stub; `philosophy/ocak-as-helper-not-enforcer.md`). Comprehension today =
  `consult_curiosity` (Fable advisor) → plan_sketch → fidelity round → user signoff.
- Adversarial review today runs INSIDE each planner (`adversarial_challenge` alongside the
  build, waiver allowed). There is no final adversarial step at recipe level.
- G-COMMIT retired; acceptor runs `git status` itself. Yet neuron.md still tells the
  neuron to run `git status` via Bash in its own shell at close — contradicts "no craft
  verbs" and duplicates the acceptor.
- Observed failure modes (transcripts): neuron over-executes vs literal ask
  (resume→mutate before reading goal; "document pain" → fixed code), under-surfaces
  mid-step progress ("speak only at gates" starved the user for 40 min), asked the user
  aesthetic/band questions (Sol owns look), fought tools for ~40 calls (step-id allocator,
  curiosity reply not surfaced by `next_action.handle_messages`, Sol exit-1 glossed as
  quota cap). Most wasted calls were tool-response gaps, not prose gaps.

## 2. Challenges to the owner's vision

1. **OCAK audit**: don't resurrect the 7-box checklist. The slot it fills ("comprehension
   check before commit / after big additions") is already `consult_curiosity` + the FSM
   `AWAIT_USER` re-signoff. Recommend: call that the comprehension gate, delete
   `run_ocak_audit` + `framework-ocak` guide, or re-point the name to the curiosity round.
2. **"Adversarial round as the last step, planner just calls Sol and fixes inline"**:
   a planner shell costs a full lifecycle (~10k tokens fixed) to make one bridge call. Two
   options: (a) keep it a step but spawn it with a dedicated strategy
   (`adversarial-review`, no workers, planner fixes inline, every non-obvious Sol finding
   → `ask_above` → neuron → user); (b) make it a seat like the acceptor (Sol-bridge review
   shell). (a) needs no new role; recommend (a), enforced by the FSM: refuse
   `DISPATCH_ACCEPTANCE` until an adversarial step is done or a recorded waiver exists.
   Keep per-step `adversarial_challenge` optional (planner's call), not mandatory.
3. **reconcile() → TRUE/FALSE**: right idea but the contract must be richer than a bool:
   the Monitor wake ALREADY carries the event; reconcile should return
   `{changed, events:[…], alert?, advisories[]}` and absorb the inbox drain (today a
   curiosity reply sat unseen). `next_action` only when `changed` or on the heartbeat.
4. **`arm_wiring(<IDENTITY>)`**: neuron's inbox alias IS the recipe id, so the argument
   is recipe_id today. Fine — but `arm_wiring()` with no args should infer it from
   `whoami()` once whoami is fixed. Also: don't arm before you hold a recipe id.
5. **@Pool GET**: must be built (`pool_status(recipe_id)` → capacity, shells, liveness,
   last_output_ts). Until then the command can't honestly say "use @Pool".
6. **"Neuron doesn't write code"** is already enforced by the toolset — but the command
   still instructs `git status` via Bash at close and the transcripts show code fixes.
   Remove the Bash close ritual; acceptor owns the tree check.
7. **Speak only at gates** is too strict for long steps (pain-point, high). Replace with:
   gates + a cadence-based progress surface (e.g. on `review_due` / every N minutes of
   a step, one line + any renderable artifact).

## 3. What belongs in the command (target ≤ 4k chars, ~1k tokens)

```
# /neuron — router of ONE recipe
Identity: router, not brain. You own the execution plan (the @Recipe); every other role
is a means. You do not write code, run builds, or judge craft — your toolset has no craft
verbs. You keep the framework up: if a wake says a child is dead/stuck, recover it.
Objects named @X → describe_objects("X") once, then CRUD. CRUD is truth; the FSM
(next_action) is a pacer that can be wrong — verify with read_object before obeying
anything surprising.

Boot (every activation, incl. post-compaction):
1. whoami()                       → identity + handle
2. resolve_recipe / resume_recipe / start_recipe(goal VERBATIM)  → recipe_id
3. arm_wiring(recipe_id)          → run monitor_cmd under Monitor ONCE; CronCreate the
                                    returned cron verbatim (backstop only)
Loop (Monitor wake or cron):
   reconcile(recipe_id) → if changed: next_action(recipe_id) → obey (kind + context).
   Not changed → end turn, zero prose. Never leave an MCP call in flight at turn end.

Decision owners: USER scope/money/destructive/sign-off/pacing · NEURON routing inside
approved scope · SOL look/feel (never ask the user aesthetic questions). Classify user
text: GOAL (law) / STEER (redirect, no widening) / SHARED CONTEXT (not a task).

Gates where you speak to the user: comprehension sign-off (show the advisor's
plan_sketch verbatim + step map), scope growth re-signoff, budget overrun, questions
relayed verbatim from children, close. Plus one progress line per `review_due`.
Between gates: route, don't narrate.

Comprehension: consult_curiosity(goal) → plan_sketch → record outcomes+steps from it →
fidelity round with the same curiosity → user sign-off → first dispatch. Big in-flight
additions re-run this; small ones are CRUD on an existing step.

Close: next_action says DISPATCH_ACCEPTANCE → dispatch_acceptance(); DONE only after a
recorded `pass`; close_recipe() returns your disarm list — execute it.

Framework pain → /pain. Output: pyramid or nothing.
```

Everything else currently in neuron.md moves to:
- **tool responses** (the big win): `arm_wiring` note carries "Monitor once / cron is
  backstop / never kind-filter broker(me)"; `next_action` context carries
  `phase_guide: neuron-phase-x` ON CHANGE ONLY (or inlines the guide delta) so the
  command needn't list phases; `start_recipe` note carries goal-verbatim + workspace
  rules; `close_recipe` returns the disarm checklist; write-gate refusals already
  explain `serves`, `dispatch_hold`, estimate (G-EST), fold threshold, G6 — the Laws
  text that re-explains those is bloat.
- **guides on demand** (`neuron-phase-a..e`, `loop-and-heartbeat`, `reactive-streams`,
  `architecture-vocabulary`): keep, but `next_action` must tell the neuron WHEN to load.
- **delete/merge**: `why-and-where` (keep 5 lines: verbatim goal is law; machinery can be
  wrong; delivered≠done), `vocabulary-core` (object graph → describe_objects),
  `terse-core` (already an output-style), `neuron-card` (duplicate of command).

## 4. Tool-side work the command depends on (to do BEFORE rewriting the text)
1. `pool_status()` read verb for neuron (capacity, shells by role/state, liveness,
   last_output_ts).
2. `whoami()` populate identity (role, handle, recipe_id, inbox alias).
3. `reconcile` returns events + drains inbox; `next_action.handle_messages` parity.
4. `next_action.context.phase_guide` emitted on phase change only.
5. `close_recipe` returns disarm list (CronDelete ids, Monitor task ids).
6. FSM: adversarial step (or waiver) required before DISPATCH_ACCEPTANCE.
7. Cron heartbeat: lengthen (60 min) and make its prompt "reconcile; if changed
   next_action; else silent" — it already is; the double-fire is the Monitor + cron
   both waking on the same event; consider cron only when Monitor liveness sidecar is
   stale (arm_wiring already tracks `.spec.hb`).
8. Trim neuron verb set toward ≤45 (drop record_action_status, pool_spawn_worker,
   record_recipe, run_ocak_audit, merge fold/supersede, broker_send).
9. Fix known tool lies (memory): notify_above(summary=) drops body; add_action wrong kwarg
   accepted; grounding brief truncation at 6000; step-id allocator collisions.

## 5. Order of work (proposed)
A. Tool fixes 1–5 (small, testable) → B. rewrite roles/neuron.md + manifest (drop
terse-core, shrink shared) → C. recompile via bootdocs → D. live test: one recipe with a
one-step goal + adversarial step + acceptance → E. then planner/worker/reviewer commands
the same way.

---
## 6. Whiteboard round 2 (owner feedback 2026-08-22)

Owner rulings: OCAK stays (guide `docs/guides/framework-ocak.md` is good: post-reasoning
4-question audit, not the retired 7-box checklist) · @Pool must be exposed · adversarial
review = last step of the overall plan · reconcile returns a DELTA only (careful vs what
Monitor already delivers) · neuron drops the git/Bash close ritual · progress visibility
is mandatory (owner has zero oversight of spawned shells today) · whoami: spawned shells
know their role, no role ⇒ neuron · command must be structured and readable, no
`@X → describe_objects` shorthand · ORDER: fix the exact commands first (this session is
a whiteboard), then objects/events/tools together; no code from intuition.

### 6.1 Proposed /neuron command (draft v1 — exact text)

See the block in the conversation; canonical copy kept here once ratified.
