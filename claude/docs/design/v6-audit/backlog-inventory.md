# DESIGN-v6 — Framework backlog inventory

Assembled by the neuron on 2026-07-09 from **all 54** `review_finding` +
`discovery` events on recipe `…eaa75d`'s flowback channel. Nothing here is
from memory; every row traces to an event, a decision, or a code read.

Purpose: make the backlog **countable** so it can be bounded. The recipe is
self-hosting — it hardens the stack it runs on — so it *generates* findings as
it goes. Without a cut line that is an infinite loop.

**Cost unit.** A code fix cannot be made without a planner: steps are
`inline` or `spawn_planner`, actions live under a plan, a plan needs a planner,
and R1 forbids the neuron from editing code. So the cheapest unit of change is
**one planner + one plan**. Observed cost: s24 = planner + 4 shells;
s25 = planner + 5 shells. **A step per bug is the expensive shape.** Batching
bugs under one planner is the only real lever.

---

## A. CLOSED (verified, this session)

| # | Item | Where closed | Evidence |
|---|------|--------------|----------|
| A1 | `dehydrate` rewrote already-reffed sidecars even when content unchanged; `next_action` not IO-free | s24 / B1 | guarded `[0,0,0,0,0]` vs unguarded `[371,0,0,0,0]`; 11/11 mutations RED under independent re-derivation |
| A2 | suspend/resume silently dropped a recorded live planner; resume note was unconditional | s24 / B2 | WARN + `planners_orphaned` counter + note now conditional on counts |
| A3 | `get_recipe_digest` missing from `_PLANNER` | d17 (W11/a6) | derived-floor 31→32 |
| A4 | `status_ping`, `neuron_search` missing from `_PLANNER` | s25 / a4 | derived-floor 32→34; live `role_scope_violation` reproduced in two shells |
| A5 | `broker_send` prescribed to planners by `planner-phase-drive.md` | s25 / a4 | **guide fixed**, not granted — `broker_send` takes arbitrary `to=`, fails d62's no-new-reach test |
| A6 | `assemble_ruleset` misfiled in `SPECIALIST_ONLY`, unreachable by worker/reviewer | s25 / a4 (neuron ruling) | pure lookup, `idempotent=True`, writes nothing; o7 preserved in substance |
| A7 | warn-mode `role_scope_violation` logging structurally blind for most scoped roles | s25 / a4 | bare-handle blind spot fixed |
| A8 | `test_phoenix_down_is_warning_not_error` environmentally fragile | s25 / B4 (a3) | mocked; asserts the behaviour it names |

## B. ACCEPTED GAPS (deliberate; loud, counted, never silent)

| # | Item | Why accepted |
|---|------|--------------|
| B1 | A planner live at suspend whose step left `in_progress` is not re-forked on resume | Safe union needs `resume_recipe` to mutate FSM state, which it deliberately does not. Only reachable window is a planner finalising an already-closed, already-reviewed plan. Now WARNs + counts. Ruling d61. |
| B2 | `EDP_ROLE_SCOPE` stays `warn` | Verdict **NOT READY**. Flipping today breaks the planner's close path and specialist dispatch. Blockers enumerated in `enforce-readiness-verdict.md`. |

## C. OPEN — CORRECTNESS / SAFETY (recommend fixing)

| # | Item | Severity | Notes |
|---|------|----------|-------|
| C1 | **Worker can end its turn before `pool_close_self`** — shell idles forever holding RAM | HIGH (user-reported) | Text guide's last line is the only thing closing the shell. Fires on any worker whose last act is a substantive report. Fix must be structural (reap on *terminal action status*, or make `record_action_status(terminal)` release the session), not prose. |
| C2 | Pool restart **permanently orphans** its pre-restart shells | MEDIUM | `spawner.kill()` no-ops when the Spawner doesn't `knows()` the session. d2 mandates one restart *per phase* → every phase boundary strands its shells. Fix = fall back to `kill_process_tree(persisted_pid)` **gated on a `create_time` fingerprint match**. Killing a recycled pid is the R10 catastrophe. |
| C3 | 9 registry rows read `state='active'` over dead processes | LOW | `active_workers()` reconciles on demand only; a stale row can hold a concurrency slot. **Fixed in s26/a1 for the worker path.** |
| C3-r | **RESIDUAL, ACCEPTED (post-freeze, d72):** `reconcile_sessions()` fires only when a **worker** spawn counts capacity, so a dead **planner** row can read `state='active'` until the next worker spawn | LOW | Found by s26/a1 *inside* its own fix, and correctly **fenced rather than built** — the first residual to land under d72's freeze. Not fixed in this recipe. Impact is bounded: a stale planner row misleads a liveness *read*, and the neuron's R5 death test (OS pid + `create_time` fingerprint) does not trust the registry alone. Recorded, accepted, left alone. |
| C4 | **`injected_context` aliases across steps** — a step-scoped decision addressed to "Reviewer a4" in s18 was stamped verbatim into s24's a4 brief | MEDIUM | A worker can receive another step's instructions as its own. Real correctness bug. |
| C5 | **Six unregistered tool names prescribed by live guides**; `pattern-observer.md` actively *calls* `pattern_observer_analyze(...)` | MEDIUM | `build_mcp` fails **closed** on drift — transcribing these into `roles.py` takes the MCP server down at startup for every shell. Invisible to the class-guard test by construction. **Needs a neuron/user ruling: unbuilt tool, or dead guide text?** Same question for `invoke_skill`. |
| C6 | Broker **kind-vocabulary mismatch**: `discovery` and `grounding` are valid recipe-event kinds but unregistered `BrokerKind`s | **UNCONFIRMED** | Inherited from a 2026-07-05 discovery event and repeated by the neuron as fact in s26's brief **without verification**. s26's planner tested it: `notify_above(kind='grounding')` returned `ok` with a `msg_id` — it did **not** reject. Rewritten as prove-or-refute, against *delivery* evidence: **an `ok` is not proof of delivery; it may dead-letter.** `notify_above(kind='discovery')` *was* observed to reject. Determine which kinds actually fail and on which plane. |
| C7 | **`next_action` instructs a double-dispatch.** It returned `dispatch_action` for an action already `in_progress` with a live worker | **MEDIUM** (was LOW) | Reproduced live on s26. The duplicate-dispatch guard refuses only `done`/`needs_review`, **not `in_progress`**. The planner drive guide tells planners to obey the instruction — so an obedient planner double-spawns. s26's planner avoided it only by checking the object surface and declining. The guard and the guide disagree. |
| C10 | `crash_recovery{action:'auto_re_dispatch'}` is logged **without a spawn actually occurring** | MEDIUM | Observed live on s26/a1: the FSM logged the intent; no new session was created by it (the planner's own explicit re-dispatch did that). **A log line asserting an action the code did not take** — the same disease as B2's unconditional resume note and the six green-suite instances, on the telemetry plane. Found by s26's planner. |
| C8 | **Reviewer briefs prescribe `record_branch_verdict`**, which cannot record an action-level verdict | MEDIUM | `RecordBranchVerdict._run` (`_tools.py:1863-1885`) iterates `comprehension.branches` and refuses when none matches; this recipe's is empty, and there is no `branch` object type at all (13 types, none of them `branch`). Found by s25/a5 *when its own brief told it to call the verb*. The d17 disease, one level up: it now infects the briefs the neuron writes. Reviewer's real channel is `record_action_status(status, evidence)`. |
| C9 | The class-guard test **cannot see unregistered tools**, and `UNSCANNED_GUIDES` is an escape hatch | MEDIUM | `_gaps()` draws candidates only from *registered* tools, so a guide naming a nonexistent verb is invisible **by construction** — a green class-guard test is not evidence that guides name only real tools (s25/a5). `UNSCANNED_GUIDES` lets a future author hide a gap by declaring a guide unattributed with a >30-char reason. Both **bound what the gate proves**. C5 is the live instance. |

## C-HIGH. CANDIDATE — the "no-false-done" gate may be prose

**Status: OBSERVATION, awaiting s26/a5's independent verification. Not a proven
defect. Do not act on it.** Filed by s26's planner, which refused to write it up
as confirmed.

- **Observed:** a1 recorded a terminal status; its action reads `status='done'`.
  `query_objects('action', where={'status':'needs_review'})` over the plan returns **0**.
- **Three guides claim otherwise**, in the words that define the whole mechanism:
  `architecture-vocabulary`, `planner-phase-author`, and `planner-phase-drive` each say
  *"a recorded done is a CLAIM that moves the action to needs_review, never a
  framework-blessed done."*
- **Neuron's code read (a claim, to be tested — not a verdict):** `_tools.py:3322-3326`
  states the gate is **planner-enforced**, not FSM-enforced; `record_action_status` is a
  pure status+evidence write (d29/d30, a user directive that *superseded* the older
  model); `plan_fsm.py:147` treats `needs_review` as non-terminal, so the gate is real
  **when something sets it** — and nothing in the record path does.
- **If confirmed, the defect is the GUIDES**, not the code: prose promising a gate the
  code never implemented. The d17 class one level up — *a reassurance that nothing
  checks, inside the description of the checking mechanism.* Seventh instance.
- **Nothing is at risk on any plan in this recipe.** Every step authored an explicit
  reviewer leg and closed only on an independent reviewer PASS. The planner said so
  itself, which is what makes the finding trustworthy rather than alarmist.
- **Second-order, NOT a bug and NOT to be "fixed":** nothing in *code* compels a plan to
  carry a reviewer leg. That is a **property of the acceptance model the user chose in
  d29/d30** — acceptance lives in the worker's own verify plus the reviewer's independent
  re-run in a fresh shell, not in the framework. Surfaced to the user. If they want it
  enforced (e.g. plan-terminal refuses when no action carries a reviewer binding), that is
  **Phase 4 / W9**, already budgeted.
- **Disposition under d72:** guide correction costs zero new shells (a2 owns the guide
  corpus this wave and needs no `_tools.py` access); the planner places it in a2 or defers
  it to Phase 5's doc bucket. No new step, no new planner. The model-property finding is
  recorded and accepted.

## D. OPEN — SELF-PACING / COST (the "spiralling" cluster)

| # | Item | Notes |
|---|------|-------|
| D1 | **The doorbell (d53)** — the idle loop needs no LLM | *Agreed with the user, never scheduled.* Tier-1: `_inbox_has_new` is kind-blind while the wake-set is kind-filtered, so `progress` pings defeat the idle short-circuit. Tier-2: a standalone non-LLM cadence ticker. |
| D2 | W7 proactive-escalation counts **recipe-level** wait cycles → cries "no progress" over a plan advancing briskly underneath | Fired twice today; both times a liveness check showed the planner healthy. Trains the neuron to interrupt the user, or to ignore the escalation channel entirely. |
| D3 | The neuron **wakes on its own emissions** — it is a writer on the channel it subscribes to; the wake predicate doesn't filter on sender | Cheap fix, same cluster as D1. |
| D4 | `wait_hint` (10s) is computed independently of the neuron's actual heartbeat (30 min), so "3 cycles" means ~90 min, not 30 s | Makes D2 worse: W7's own self-pacing widens the tick and thereby *shortens* the effective patience. |
| D5 | **Expense visibility** (user request, 2026-07-09) | Already a planned workstream: **W10b `cost_report`, Phase 4.** Nothing needs inventing. |

## E. OPEN — DISCIPLINE / DOC (cheap, no code risk)

| # | Item |
|---|------|
| E1 | `DESIGN-v6.md` W3 line-194 (`0e7ca8` is a recipe id, not a spec), W5 §2 self-contradiction, W11's two stale sentences |
| E2 | `role-toolsets-derived.md` has a `## CURIOSITY` section with no `ROLE_TOOLSETS` entry |
| E3 | d17 sync: the canonical per-role `observe` kind-sets live in **four** places |
| E4 | Windows footgun: `pathlib.Path.write_text()` applies `os.linesep` translation, silently converting line endings |
| E5 | Neuron guide rule: **a code-grounded read is not stable while a worker is mid-edit in that file.** The neuron made this error twice in one day — citing a4's in-flight `roles.py` edit as pre-existing precedent, and verifying "workers close correctly" *after* the user had manually closed the lingering shell. Tell: if a comment in the cited region names the current step, it is not prior art. |
| E6 | Mutation-check discipline is now a standing rule (d60 B5, d64): a cleaned corpus cannot prove the test that guards it; re-introduce the offending form, confirm RED, revert. |

---

## The cut line

**Six green-suite-guarding-nothing instances** have been found in this recipe.
The disease is not any single bug; it is *shipping a reassurance that nothing
checks*. Every fix below carries a mutation-proved test or it does not land.

- **s26 (one planner, workers in parallel):** C1–C6, C8, C9, **D1-tier-1**, D2, D3, D4 + E5, E6 as guide edits.
  Rationale: all correctness/safety, plus the self-pacing cluster that is
  *currently costing tokens on every heartbeat*. **D1-tier-1** = make
  `_inbox_has_new` kind-aware so `progress` pings stop defeating the idle
  short-circuit; it is user-approved (d53), pure code, and pays for itself.
- **Phase 4 (already budgeted):** D5 → W10b `cost_report` (pull forward into
  s26 if cheap — it is a read-side report, no new machinery).
  **D1-tier-2** (the standalone non-LLM cadence ticker) is a natural W10b
  companion and stays here: it is a new process, not a bug fix.
- **Phase 5 (already budgeted, shares the W6.4/W6.5 planner):** E1–E4.
- **Not fixed, recorded:** B1, B2.
- **Found AFTER this inventory** (C7 re-rated, C10 new, C6 downgraded to unconfirmed):
  dispositioned under d70's **no-new-planner rule** — they do NOT get a step of
  their own and are NOT injected into s26 mid-flight. C7 and C10 ride Phase 4's
  W9 (oversight) planner, which already owns the "does the machinery tell the
  truth about itself" surface. C6 is already inside s26 as a prove-or-refute.
  This is the rule working as intended on its first real test: the backlog
  grew, and the spend did not.

**Is s26 the last batch?** For A–E as scoped above, yes — with one honest
caveat: this recipe surfaces framework defects *because* it runs on the
framework. New findings will keep arriving. The commitment that can be made is
not "no more findings"; it is **no more unplanned steps**: anything found after
this inventory is recorded and dispositioned, and lands in Phase 4/5's already-
budgeted planners or is explicitly accepted — never a new planner of its own.
