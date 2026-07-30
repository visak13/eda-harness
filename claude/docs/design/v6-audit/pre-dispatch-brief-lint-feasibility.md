# Pre-dispatch verb-scope lint — feasibility

**VERDICT 1 (PRIMARY, guide corpus): BUILD.** A call-site lint of role guides against
`ROLE_TOOLSETS` measures **80% precision (8 true positives / 10 hits)** over the whole
46-file guide corpus and finds **six new latent enforce-mode breaks beyond the two already
known** — including `broker_send` on the planner's plan-close path, i.e. the exact d59 verb,
sitting in a permanent guide rather than a throwaway brief.

**VERDICT 2 (SECONDARY, brief prose): DO NOT BUILD.** The same matcher class over the real
brief corpus (161 briefs) measures between **0.5% and 50% precision depending on strictness,
with recall so low it misses most of what it claims to guard**. A naive substring scan — the
form already shipped in `_reject_dispatch_prose` — flags **91 of 161 briefs (56.5%)** and
produces, as far as I can adjudicate, **zero true positives**. Ship the guide sweep; do not
ship a linter over prose.

These are two verdicts, not one, and they should not be averaged. The guide corpus is bounded,
curated and written in a house style that marks call sites. Brief prose is free text authored
under time pressure, and it discusses verbs far more often than it invokes them.

---

## Scope note

This document was rescoped mid-action by a planner steer (msg `3dcbe020`, relaying a neuron
ruling): the guide sweep became primary, the brief-prose lint secondary. The brief-prose
measurement was already complete when the steer arrived and is reported unchanged below.

**One correction to the steer, per its own "ground beats brief" standing instruction.** The
steer says `get_recipe_digest` and `status_ping` are "two instances of ONE bug". In live code
only one is open: `get_recipe_digest` **is** in `_PLANNER` today (`roles.py:89`, the d17
derived-floor bump), so it is closed, not open. `status_ping` is real and open. Everything
below is measured against live code, not against the brief.

---

## What I VERIFIED vs what I INFERRED

**VERIFIED** (ran it, read it, or reproduced it):

- The corpus sizes, matcher outputs and every hit count in this document. Corpora were pulled
  through the object surface (`query_objects` on `step` / `action`, driven in-process through
  the same `build_registry(ctx)` the MCP server registers) — never by reading `.recipes/` or
  `.plans/` files.
- Every `ROLE_TOOLSETS` membership claim, read from `src/edp_claude/tools/roles.py`.
- The live `role_scope_violation` for `status_ping`. I read it myself from the s25 plan
  worklog rather than take the planner's report:
  `{"ts": "2026-07-09T20:46:20.687438+00:00", "kind": "role_scope_violation",
  "agent_role": "planner", "tool": "status_ping", "mode": "warn"}`
- That an action object carries **no executing role**, and that role is chosen at spawn.
- That `_ROLE_ACTIVATOR.get(role, f"/{role}")` (`pty_launcher.py:313`) falls back to `/{role}`,
  so `consult` resolves to `/consult` despite having no explicit entry. **There is no
  consult-role mismatch** — I checked this specifically because the missing table entry looked
  like one.

**INFERRED** (reasoned, not observed):

- That the lint **would** have caught d59. The offending brief lived on
  `recipe-scratch-disposable-w11-suspend-resume-li-5ccc6e`, which was reaped and deleted after
  a10. **Its text is not in the corpus and I could not run any matcher against it.** I infer a
  catch only because d59 records that the brief named `broker_send`. This is the single
  weakest link in the case for the brief lint, and it is worth stating plainly: *the one
  incident that motivated the brief lint is the one incident I cannot measure.*
- That granting a verb "grants no new reach" — argued per finding below, not proven.
- Counterfactual catch-counts for guides are inferences about a hypothetical past CI run.

---

# PART 1 — The guide sweep (PRIMARY)

## Corpus and method

| | |
|---|---|
| Corpus | 46 files: `.claude/commands/*.md` (11) + `docs/guides/*.md` (35) |
| Role-scoped subset | 6 activators + `planner-*` + `neuron-*` + `specialist-training.md` |
| Vocabulary | 86 registered tool names (`ALL_TOOL_CLASSES` ∪ `{record_context}`) |
| Role mapping | `pty_launcher.py:289-303` `_ROLE_ACTIVATOR`, 1:1 for activators |

Guide → role attribution is honest only for the activators (the pool literally sends
`/worker`, `/agentic-plan`, … to a shell stamped with that `EDP_ROLE`) and for the
`planner-*` / `neuron-*` phase guides. **Guides carry no role metadata** — `GetGuide._run`
(`_tools.py:5805`) loads any guide for any caller — so the remaining 13 guides are
un-attributable and are handled separately in "Coverage limits" below.

## Matcher comparison, measured

| Matcher | Files flagged | Verb-hits | Adjudication |
|---|---|---|---|
| (a) naive substring, lowercased | 16 | 56 | unusable — negations and prose dominate |
| (e) **call-site**: `` `verb(` `` inside a backtick/fence span | **6** | **10** | **8 TP, 1 FP, 1 borderline** |

Matcher (e) requires the verb in **callee position** — the identifier immediately followed by
`(` — and only inside a backticked or fenced span. That one constraint is what separates
"the guide tells you to call this" from "the guide mentions this".

### A matcher bug worth recording

My first call-site implementation scoped backticks with `` `[^`\n]+` `` (no newline inside the
span). It reported 7 hits and **missed two of the most important true positives** —
`status_ping` and `broker_send` in `planner-phase-drive.md` — purely because markdown had
line-wrapped inside the backticks:

```
**Cheap child checks:** on heartbeat ticks `status_ping('<plan_id>:
<action_id>')` (liveness + last worklog line, no dump)
```

Allowing newlines inside the span (`` `[^`]+` ``) plus whitespace-collapsing recovered both.
**Any implementation of this lint must normalise whitespace inside code spans before
matching.** A lint that silently misses the verb that motivated it is worse than no lint.

## FINDINGS — 8 true positives, 6 of them new

Two were already known and are not re-litigated. The other six are new.

| # | Role | Verb | Guide (file:line) | Status |
|---|---|---|---|---|
| 1 | planner | `get_recipe_digest` | — | **CLOSED** — already granted, `roles.py:89` |
| 2 | planner | `status_ping` | `planner-phase-drive.md:174` | known; reproduced live |
| 3 | planner | **`broker_send`** | `planner-phase-drive.md` (plan-close + ask_neuron) | **NEW** |
| 4 | planner | **`neuron_search`** | `planner-phase-drive.md`, `planner-phase-author.md:112` | **NEW** |
| 5 | reviewer | **`get_specialist_doc`** | `.claude/commands/reviewer.md:62` | **NEW** |
| 6 | reviewer | **`propose_spec_learning`** | `.claude/commands/reviewer.md:141` | **NEW** |
| 7 | specialist | **`neuron_set_base_session`** | `.claude/commands/specialist.md:137` | **NEW** |
| 8 | specialist | **`neuron_set_status`** | `.claude/commands/specialist.md:294,303` | **NEW** |
| 9 | neuron | `remember` | `neuron-phase-d.md` | **NEW** (conditional) |

### 3. `broker_send` — planner. The d59 verb, in a permanent guide.

`planner-phase-drive.md` instructs the planner twice, once on the **plan-close path**:

> `` 2. `broker_send(to="<recipe_id>", kind="plan_closed", body={"plan_id": "<plan_id>"})`. ``

and once as the `ask_neuron` mechanism. `broker_send` is absent from `_PLANNER`
(`roles.py:68-111`). Under enforce, **every planner would fail at close**.

This is the finding that most justifies the sweep. d59 was diagnosed as a one-off brief
authored carelessly against a scratch recipe. It is not. The same verb is prescribed by the
planner's own standing guide, on its exit path, and has been for as long as that guide has
existed. Nothing caught it because nothing looks.

**The derived-floor argument does NOT apply here — do not grant `broker_send`.** `roles.py:73-89`
permits a grant when the verb "grants NO new reach". `broker_send` fails that test: it takes an
arbitrary `to=` address, whereas the planner's `reply` / `notify_above` / `ask_above` /
`emit_recipe_event` are all lineage-scoped. Granting it would hand every planner unrestricted
addressing. **Correct remedy: fix the guide.** `ask_neuron` → `ask_above(audience='neuron')`;
the `plan_closed` broadcast → `record_step_result`, which `_PLANNER` already carries. I did not
verify that `record_step_result` fully replaces the `plan_closed` message semantics; a4 must
check before editing.

### 4. `neuron_search` — planner.

`planner-phase-author.md:112`: "take the set of distinct `specialization` values and
`neuron_search` each." `planner-phase-drive.md`: `` `neuron_search(query=<args.specialization>)` ``.
Absent from `_PLANNER`.

This one **is** a derived floor, and a hard one: `PoolSpawnWorker._run` (`_tools.py:4017`)
*refuses* to spawn when a declared `specialization` has not been resolved to a `spec_id`. The
planner therefore cannot dispatch any specialist action without a resolution verb, and holds
none. Under enforce, **the entire specialist dispatch path is dead**. Grant `neuron_search`
(read-only search over the neuron DB). a4 should confirm the refusal by reading that seam.

### 5–6. `get_specialist_doc`, `propose_spec_learning` — reviewer.

`reviewer.md:61-62` — "**Load the COMPILED doc and check CONFORMANCE to it** (mandatory, not
optional): `get_specialist_doc(spec_id=<your spec_id>)`". `_REVIEWER` carries
`get_specialist_docs` (plural) but **not** the singular. The reviewer's rubric load — its
entire job — is prescribed against a verb it does not have.

Worse, `reviewer.md:49-51` *asserts its own scope wrongly*:

> Your on-role floor is READ-ONLY: `read_object`, `get_specialist_doc`/`get_specialist_docs`,
> plus `reply`/`notify_above`/`emit_recipe_event`/`propose_spec_learning`.

Neither `get_specialist_doc` nor `propose_spec_learning` is in `_REVIEWER`. A guide that
documents a role's toolset incorrectly is a second failure mode the sweep catches for free.

Remedies differ: `get_specialist_doc` → **fix the guide** to call the plural (a pass-through
superset; zero reach change, one-line edit). `propose_spec_learning` → **grant it**; reviewer
flowback of durable stack craft is a designed feature (`reviewer.md:141` and the spec-learning
flow), and the verb is advisory-only — it proposes, the neuron disposes.

### 7–8. `neuron_set_base_session`, `neuron_set_status` — specialist.

`specialist.md:137` prescribes `neuron_set_base_session(...)` under a bold
"**This call is what makes you USABLE — do not skip it.**", and `:294`/`:303` prescribe
`neuron_set_status(...)` for the HITL approval gate. Neither is in `_SPECIALIST`. Under
enforce a specialist **cannot complete its own training**.

Note the guide contradicts itself: `specialist.md:57-58` lists both verbs as things the
*neuron* holds. a4 must reconcile the two passages, not just the toolset.

### 9. `remember` — neuron (conditional).

`neuron-phase-d.md` prescribes `` `remember(fact=..., domain=...)` ``. `remember` is in
`_CONSOLIDATED_OUT` (`roles.py:43-48`) and therefore absent from `_NEURON`. **Conditional**:
this only bites a neuron shell stamped `EDP_ROLE=neuron` (pool-spawned). The user's foreground
neuron has no `EDP_ROLE`, so `toolset_for_role` returns `None` and it keeps the full registry.

**Do not grant it back** — that would reverse W4/d14 deliberately. Fix the guide to
`record_context(kind=fact)`, which the same guides already say supersedes it.

### The one clear false positive, quoted verbatim

`planner-phase-author.md:200-201`, flagged as planner/`assemble_ruleset`:

> - **A `concerns=[X]` tag needs a `spec-X` ruleset layer** or the worker's
>   `assemble_ruleset(concerns=[X])` errors; the `concerns` field is IMMUTABLE post-authoring.

The call site is real but the caller is the **worker**, not the planner reading the guide. My
matcher attributes call sites to the guide's role, so it misfires whenever a guide describes
another role's call. That is the FP mode to expect, and it is rare (1 in 10).

**But the misfire uncovered a genuine defect anyway.** `assemble_ruleset` is in
`SPECIALIST_ONLY` (`roles.py:25-31`) — so it is absent from `_WORKER` *and* `_REVIEWER`.
`neuron.md` likewise says "so it exists before any worker/reviewer calls `assemble_ruleset`".
Under enforce, **no worker can assemble the ruleset for a `concerns=[...]` action.** Whether
to grant it or to route concerns through `get_specialist_docs` is a design decision.
`reviewer.md:53-56` already concedes the question is open ("Reviewer scope enforcement stays
deferred pending the read-side ruleset-composition question"). **Surface to the neuron; a4
should not auto-decide this one.**

### The borderline hit

`specialist-training.md`, specialist/`update_object`: "`add_spec_entry` and
`update_object(type="spec")` only APPEND". Descriptive of API semantics rather than an
instruction — but `CRUD_OBJECT_SCOPE["specialist"]` is `frozenset()` (read-only,
`roles.py:213`), so the specialist cannot call `update_object` on anything. Real mismatch,
low severity. Surface, don't rush.

## Coverage limits — state them or the sweep lies

1. **Three stamped roles have no `ROLE_TOOLSETS` entry and are therefore un-lintable.**
   `pty_launcher.py:289-303` stamps `curiosity`, `goal_keeper`, `pattern_observer`;
   `toolset_for_role` returns `None` for all three, so `build_mcp` registers the **full
   registry** (fail-open). Their guides name 10, 4 and 8 verbs respectively and **cannot be
   checked against anything**. This independently corroborates a1's "three-role fail-open
   over-grant" from the guide side. A sweep that silently skips them would report green over a
   hole.

2. **13 universal guides have no role.** Loadable by any role via `get_guide`. The only sound
   check is against the intersection of every shell role's toolset — which is **11 verbs**.
   Measured, every universal guide names verbs outside it: `architecture-vocabulary.md` names
   23 verbs, 14 outside; `loop-and-heartbeat.md` 14/9; `environment-discovery.md` 18/9. An
   intersection check here would be pure noise. The honest options are (i) exclude them and say
   so, or (ii) require universal guides to attribute each call site to a role
   (`environment-discovery.md` already does this — it is a per-role table). **Recommend (i)
   for now**, with the count of excluded files logged, never silently.

3. `ocak.md` names a retired role.

## The B5 mutation-proved test (spec for a4 — do not implement here)

One test guards the whole class. This is the point of the sweep.

**File:** `tests/test_role_guide_scope.py`

**Data (tables-as-data, mirroring `roles.py` style):**
- `GUIDE_ROLE: dict[str, str]` — the 6 activators, from `_ROLE_ACTIVATOR`, plus the
  `planner-*` / `neuron-*` / `specialist-training.md` prefix rules.
- `WAIVERS: dict[tuple[str, str], str]` — `(guide_path, verb) -> reason`. Every waiver names
  its reason. Seed it with exactly the two non-instructions above
  (`planner-phase-author.md`/`assemble_ruleset`, `specialist-training.md`/`update_object`).
- `UNLINTABLE_ROLES: frozenset` — `curiosity`, `goal_keeper`, `pattern_observer`.

**Matcher:** code-span extraction with `` `[^`]+` `` **and** fenced blocks, whitespace-collapsed,
then `(?<![a-z0-9_])<verb>\s*\(`.

**Assertions:**
1. For each role-scoped guide: `callsites(text) - ROLE_TOOLSETS[role] - waived == set()`.
   Failure message names guide, verb, role and the offending line.
2. Every `WAIVERS` key refers to a guide that exists and a verb still in the registry —
   so a waiver cannot silently outlive the thing it waives.
3. `UNLINTABLE_ROLES` is exactly `set(_ROLE_ACTIVATOR) - set(ROLE_TOOLSETS)`. When a4 or a
   later action closes the fail-open gap, this assertion fails and forces the guide into scope.
   *Coverage is asserted, not assumed.*

**Mutation proof (each must be watched RED, then reverted GREEN):**
- **M1 — the grant is load-bearing.** Remove `record_action_status` from `_WORKER`. `worker.md`
  Step 4 call-sites it. Expect RED naming `worker` / `record_action_status`. Proves assertion 1
  reacts to a *toolset* regression.
- **M2 — the matcher is load-bearing.** Insert `` `broker_send(to="x")` `` into `worker.md`.
  Expect RED naming `worker` / `broker_send`. Proves assertion 1 reacts to a *guide* regression.
- **M2b — line-wrap regression.** Reformat M2's insertion so the backtick span wraps a newline.
  **It must still go RED.** This is the exact bug that hid `status_ping`; without M2b the test
  would pass while blind to it.
- **M3 — the waiver list is load-bearing.** Add a waiver for a verb that is *not* call-sited.
  Expect RED from assertion 2. Proves waivers cannot become a silent amnesty.
- **M4 — coverage is load-bearing.** Add a fake role to `ROLE_TOOLSETS`. Expect RED from
  assertion 3.

**The test lands RED.** Findings 2–9 are live. a4 must make it green by *fixing roles.py or the
guides*, waiving only with a written reason — not by loosening the assertion. Note that a green
suite here would itself be the sixth instance of green-suite-guarding-nothing; M1–M4 exist
precisely so that cannot happen quietly.

---

# PART 2 — The brief-prose lint (SECONDARY)

## Corpus

Pulled via `query_objects('step', …)` and `query_objects('action', plan_id=…)` across all 25
plans. **161 briefs = 25 step descriptions + 136 action descriptions.** Executing role taken as
`planner` for `execution="spawn_planner"` steps and `worker` for actions (see the structural
blocker below — that second assumption is not sound).

## Measured precision

| Matcher | Briefs flagged | Verb-hits | True positives |
|---|---|---|---|
| (a) naive substring | **91 / 161 (56.5%)** | 201 | **0 found** |
| (a′) + word boundaries | 91 / 161 | 195 | 0 found |
| (b) backticked identifiers | 5 / 161 | 7 | 1 |
| (e) call-site in code span | **2 / 161** | 2 | **1** |
| (e′) call-site, no backtick required | 40 / 161 | 48 | ~1 |

**Naive substring precision ≈ 0.5% at best (≤1/201), and I could not confirm a single true
positive among its 201 hits.** The top three FP drivers are `next_action` (27 hits),
`reconcile` (22) and `get_recipe_digest` (19).

### The hazard, confirmed exactly as the brief predicted

All **8** `broker_send` hits in the corpus are discussion, negation or quotation. Not one
instructs anybody to call it. Verbatim:

> **a1's brief:** "the a10 live validation (d59) caught a planner briefed to call
> `broker_send`, a verb the planner surface does not carry"

> **a2's brief (this one):** "The neuron itself wrote a step brief instructing a planner to call
> broker_send - a verb absent from the planner's ROLE_TOOLSETS"

> **s25/a5's brief:** "which both name broker_send while instructing nobody to call it. VERDICT.
> Record it with record_branch_verdict."

A lint over this corpus would refuse the very briefs that exist to *diagnose* the problem —
including the brief commissioning the lint.

### Three further FP classes, quoted verbatim

**Seam names.** My own brief names `add_step`, `add_action` and `create_plan` — as code seams to
read, not verbs to call:

> "The seams where a brief is authored and where a shell is spawned: add_step / add_action /
> create_plan and the pool_spawn_* routes"

**Behavioural description.** `s24/a1`: "next_action is NOT IO-free." `s24/a2` describes the
suspend/resume divergence by naming both verbs. `s23/a5`: "Implement the NEW neuron-only
`suspend_recipe(recipe_id, reason="")` tool" — a call-site *in signature position*, which even
matcher (e) cannot distinguish from an invocation.

**Ordinary English.** In `neuron.md`, `remember` matched as a plain verb:

> "Call it every loop; it costs no reasoning to remember, and it re-grounds you"

## The one true positive in 161 briefs

`action:s23/a7_scratch_crash_resume_e2e`, executed by a **worker**:

> "3. Call `resume_recipe(<scratch_id>)` and observe:"

`resume_recipe` is absent from `_WORKER` (22 verbs). The action ran green under warn mode.
Under enforce that worker would have had **no such tool**. A real, live, d17-class break — and
the only one in the corpus.

**And it is precisely the case that proves recall is the fatal problem.** That same brief also
instructs the worker to "Create a scratch recipe with at least one step, one plan, and a mix of
action statuses", then to spawn and reap a real worker. Doing that requires `start_recipe`,
`add_step`, `create_plan`, `add_action`, `next_action`, `pool_spawn_worker` and `pool_reap` —
**seven** verbs absent from `_WORKER`, **none of which the brief names**. The lint would catch
1 of 8 out-of-scope verbs the action actually needed.

This is the structural defect of the whole idea: **a brief instructs by describing work, not by
naming verbs.** Verb names appear when an author is being helpful, which is uncorrelated with
whether the verb is in scope.

## A structural blocker no matcher can fix

**An action carries no executing role.** `_SpawnWorkerIn` (`_tools.py:4002-4009`) is
`{plan_id, action_id, force}`. Reviewers arrive via `BranchReviewer` (`_tools.py:7040-7054`).
`Action`'s fields (`describe_objects('action')`) carry no role. **At `add_action` time the lint
cannot know whether a worker or a reviewer will execute the brief, so it cannot choose a
`ROLE_TOOLSETS` to check against.**

Measured consequence: my matcher scored every action as `worker` and therefore flagged
`s25/a5` — a *reviewer* action — for naming `record_branch_verdict`, which is squarely in
`_REVIEWER`. A false positive created entirely by role misattribution, on the action whose job
is to review this document.

Moving the lint to dispatch time (`PoolSpawnWorker._run`, `_tools.py:4017`) fixes the role but
**loses the whole point**: the brief is already written, the planner has moved on, and a hard
refusal there strands a plan mid-dispatch rather than correcting an author.

## Insertion points, by file:line

**Author time**
- `AddAction._run` — `_tools.py:1735`; existing guards at `:1780` (`_reject_producer_verify`)
  and `:1786` (`_reject_dispatch_prose`). The natural hook. Role unknown here (blocker above).
- `AddStep._run` — `_tools.py:2060`. **No guard of any kind today.** Executing role *is*
  knowable: `_AddStepIn.execution` (`:2048`) is `Literal["inline", "spawn_planner"]`, so
  `spawn_planner` ⇒ planner. This is the only brief seam where the role is sound — and it is
  the seam d59 came through.
- `CreatePlan._run` — `_tools.py:1661`. Carries no brief text. **Not an insertion point.**

**Dispatch time**
- `PoolSpawnWorker._run` — `_tools.py:4017` (role known: worker)
- `PoolSpawnPlanner._run` — `_tools.py:3984` (role known: planner)
- `BranchReviewer._run` — `_tools.py:7054` (role known: reviewer)

**Guide time (where the sweep belongs)**
- `ROLE_TOOLSETS` — `roles.py:171`
- `build_mcp` drift guard — `mcp_server.py:147-158`. **The precedent.** It already refuses to
  build a server when `roles.py` names a tool absent from the registry — fail-closed, no
  name special-cased. The guide sweep is the same invariant one level up: *the guides may not
  name a verb absent from the role's set.* It belongs in the test suite, not at runtime.

## The precedent nobody should ignore: `_reject_dispatch_prose`

`_tools.py:3078` already ships a naive substring lint over `add_action` descriptions:

```python
low = description.lower()
hit = next((t for t in _DISPATCH_PROSE_TOKENS if t in low), None)
```

It **hard-refuses** (`_precondition`) on `get_specialization`, `branch_specialist`,
`pool_spawn_worker`. It has a 3-token vocabulary and no negation handling, so today an action
brief saying *"do not call `pool_spawn_worker`"* is rejected outright. Widening this from 3
tokens to 86 is exactly option (a), and my measurement says it would flag 56.5% of real briefs.

## The four options, costed

| | Option | Cost | Precision (measured) | Failure mode |
|---|---|---|---|---|
| **(a)** | naive substring / regex over prose | ~30 LoC; extends `_reject_dispatch_prose` | **≈0.5%** (≤1 TP / 201 hits) | Fires on negation, quotation, seam names, English words. As a hard refuse, blocks the diagnostic briefs. **Reject.** |
| **(b)** | backticked / fenced identifiers only | ~60 LoC (span extraction) | 1 TP / 7 hits ≈ **14%** | Briefs rarely backtick. Signature position (`suspend_recipe(recipe_id, reason="")`) is indistinguishable from a call. Line-wrap blindness. **Reject.** |
| **(c)** | author-declared `verbs_used: list[str]`, checked mechanically | Schema change on `_AddActionIn`/`_AddStepIn` + migration + every author updated | ~100% by construction | **Recall depends on the author noticing** — and the whole failure is that the author *didn't*. d59's neuron would have declared `verbs_used=[]` in perfect good faith. Adds burden, guards nothing. **Reject.** |
| **(d)** | don't build; make the warn-mode `role_scope_violation` loud | ~0–20 LoC | n/a | Detection stays post-hoc. But it is *real* detection: it fires on the actual call, with the actual role, zero FPs. **Adopt for briefs.** |
| **(e)** | **call-site lint over GUIDES, as a test** | ~80 LoC + waiver table | **80%** (8 TP / 10) | Misattributes another role's call site (1/10). Cannot cover the 3 fail-open roles or the 13 universal guides. **Adopt for guides.** |

Option (d) is not "do nothing". Today the violation lands in a plan worklog and nothing reads
it. Concretely: have the reviewer's acceptance pass read
`read_worklog(plan_id, kinds=['role_scope_violation'])` and refuse `done` on a non-empty result.
That is a handful of lines, has no false positives *by construction* (it observes real calls by
real roles), and would have caught d59 at the point it mattered — before the plan closed. It is
strictly better than any prose matcher, and it composes with the guide sweep rather than
competing with it.

## Smallest honest version that would have caught d59

The brief lint is not it. **The guide sweep is** — `broker_send` sits in
`planner-phase-drive.md` on the plan-close path (finding 3), so the sweep catches the verb that
d59 caught by luck, in a *permanent* artifact, before any shell spawns.

If a brief-side check is still wanted, the only defensible one is at `AddStep._run`
(`_tools.py:2060`), the single seam where the executing role is knowable from data
(`execution="spawn_planner"` ⇒ planner) — and it should **warn, never refuse**, because the
measured FP rate on step briefs is 56.5%. I do not recommend building it. A warning nobody
reads is how `role_scope_violation` got here in the first place.

---

## Recommendation

1. **BUILD the guide sweep** as `tests/test_role_guide_scope.py`, mutation-proved per M1–M4.
   It lands RED on findings 2–9.
2. **DO NOT BUILD the brief-prose lint.** Adopt option (d) instead: fail an action's acceptance
   on a non-empty `role_scope_violation` worklog.
3. **Fix guides, don't grant verbs, where the derived-floor "no new reach" test fails.** Grant
   `status_ping` + `neuron_search` (planner) and `propose_spec_learning` (reviewer);
   grant `neuron_set_base_session` + `neuron_set_status` (specialist). **Do not grant
   `broker_send` or `remember`** — fix `planner-phase-drive.md` and `neuron-phase-d.md`.
4. **Surface, do not auto-decide:** `assemble_ruleset` for worker/reviewer (the `concerns` path
   is dead under enforce), and `update_object` for specialist.
5. **Enforce is not safe today.** Independent of a1's audit, findings 2–8 alone would break the
   planner's close path, the planner's specialist dispatch, the reviewer's rubric load, and the
   specialist's training completion.

*Produced by action a2 (research + judgement only). No production code was changed. The
measurement scripts were throwaway and are deleted.*
