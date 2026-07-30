# Specialist compiled docs — compile the spec, load it clean (2026-06-02)

**Status:** agreed (user sign-off 2026-06-02). Implementation staged below.
**Builds on:** `SPECIALIZATION-LAYERED-RULESETS.md` (the JSON spec + adherence
+ `assemble_ruleset`). **Changes:** how a specialist's knowledge reaches the
worker — replaces the session-fork + link-chasing with a compiled doc.

## Problem

Today a specialist worker pays twice for its expertise:

1. **The fork replays the whole training chat.** the execution fork
   (`claude --resume <base> --fork-session`) loads the *entire* training
   conversation (all the web reading, the user back-and-forth) into the
   worker before it does any work.
2. **The JSON is links, not instructions.** `assemble_ruleset` hands the
   worker entries whose load-bearing items are URLs — so it re-reads docs
   or leans on the forked chat to *derive* what each link means.

The SME already digested all of that during training, but the system keeps
only links and re-inherits the cost every single time. It is token-heavy
and makes the worker *derive meaning* instead of *following instructions*.

## Decision — compile once, load clean

At the end of (re)training the SME **compiles** its assembled ruleset into a
**self-contained, skill-styled instruction doc** (`.md`). The worker loads
*that* into a **clean context** — no fork, no chat replay, no link-chasing.

```
TODAY (derive-at-use)                  PROPOSED (compile-once, load-clean)
 TRAIN → spec.json (LINKS)              TRAIN → spec.json (UNCHANGED — the source)
       → whole chat as base_session           → assemble_ruleset(spec) → universal⊗stack
 WORK  → fork base (full chat)  HEAVY        → COMPILE one self-contained .md  (distill)
       → assemble_ruleset (links)             → you REVIEW the .md → stable
       → derive meaning                  WORK → get_specialist_doc(spec_id) into CLEAN ctx
 REVIEW→ same fork + re-derive                → instructions drive the work
                                        REVIEW→ loads the same doc (its enforced rules)
```

## Per-stack, not per-project (the scoping rule)

A specialization is a **stack craft**, reusable across every project on that
stack — NOT a project artifact. The compiled doc carries **zero project
specifics**; the project context reaches the worker separately.

```
 SPECIALIZATION (per STACK, reusable)     PROJECT CONTEXT (per launch)
 = how this org writes prod React+TS      = what to build (recipe/plan/action)
 = the compiled .md (house style + rules) = data shapes, routes, this feature
 = project-INDEPENDENT                     = lives in the recipe/plan, NOT the doc
                  │                                        │
                  └─────── the worker combines ────────────┘
        get_specialist_doc(spec_id) = craft  +  its action = the project task
```

So the doc is handled in two places: **when the specialization loads**
(`get_specialist_doc` → the stack craft) and **at launch** (the worker reads
its `action`/recipe → the project task). Project-level taste was never the
specialization's job — the recipe and plan own that.

## The doc — decisions/taste, not craft (keeping it relevant)

Claude already writes good code; what produces "AI slop" is **inconsistency
and arbitrary choices**. The doc's only job is to **collapse the decision
space to this stack's choices**, so every worker writes code that looks like
one consistent senior engineer. The **keep/cut test for every line**:

> *Would removing this line let Claude produce something still good, but
> inconsistent with our house style?*
> **Yes → keep** (resolves a real fork). **No, Claude does it right anyway
> → cut** (it's slop *in the doc*; it dilutes signal and makes 100 rules).

This is what preserves speed + creativity: a **tight set of decisions**
(~15–30 high-signal lines), then Claude codes freely within them. The train
shell's discipline is **distill, not dump** — it just read N docs; the
temptation is to transcribe. *Every line must change what a competent coder
would otherwise do here; if it restates a best-practice Claude already
follows, delete it. Ship the shortest doc that fully removes the guesswork.*

### Structure (one doc; `adherence` disambiguates coder vs reviewer)

```markdown
# Specialist: <stack>   [compiled v<N> · <date>]

## Scope            one line — what this covers, what it doesn't.

## House style (this stack)     ← the heart: the opinionated craft choices
- Server state: TanStack Query v5 object API; the cache is the source of truth.  [required]
- Client state: Zustand. Not Redux, not Context-for-everything.                  [required]
- API enums/status modeled as discriminated unions.                              [required]

## Build approach     the 3–5 step work-order.

## Rules
- [required]  … a reviewer BLOCKS done on these.
- [expected]  … reviewer fixes if clear; a justified, recorded exception is ok.
- [preferred] … coder default; reviewer only notes a deviation.

## Never (anti-patterns)        useEffect-as-fetch · `any` to silence TS · …

## Done means …       the bar a deliverable must clear.
```

The coder reads it as "build within these"; the reviewer reads the **same
doc** as "act on `required`, fix-if-clear on `expected`, ignore `preferred`."
One artifact, zero ambiguity — the adherence tag tells each role its job. The
doc is **self-contained**: the SME `assemble_ruleset`s universal⊗stack and
distills *both* into it, so a specialist worker needs nothing else.

## Launch model — fresh worker, `spec_id`-driven; fork = re-training only

Base worker and specialist worker launch **identically** (`pool_spawn_worker`,
fresh clean context). The only difference is **data**: the action's `spec_id`.

```
 pool_spawn_worker (fresh) ── BOTH ──
      ├─ action.spec_id == null → grounding = universal (coding-standards.md)
      └─ action.spec_id == set  → get_specialist_doc(spec_id) = the stack doc
 the execution fork (branch_specialist) is RETIRED — removed 2026-06-03.
 The only remaining fork is re-training (update_specialist).
```

The planner resolves a `specialization` → its stable neuron → stamps
`action.spec_id` (via `update_object('action', patch={'spec_id':…})`), then
`pool_spawn_worker`; the worker reads `spec_id` and loads the doc. **Guard
B inverts**: a specialist action must have a `spec_id` *and a compiled doc
to load* (else there is no grounding), and `pool_spawn_worker` enforces it.

### MULTI-SPEC: an action carries N specs (2026-06-03, recipe …-s14)

The single-spec model above is the **N = 1 special case** of an additive
extension: an action may now carry **N** specs, so one worker can hold
cross-stack craft (e.g. a full-stack endpoint = Java backend + React
frontend) instead of being forced to pick one stack or go generic.

```
 pool_spawn_worker (fresh) ── BOTH ──
      ├─ effective_spec_ids == []   → grounding = universal (coding-standards.md)
      ├─ effective_spec_ids == [x]  → get_specialist_docs([x])  = that one doc, VERBATIM
      └─ effective_spec_ids == [x,y]→ get_specialist_docs([x,y]) = ORDERED CONCATENATION
                                       of both docs, each under a per-stack header
```

- **Canonical fields** (amendment A1): `action.spec_ids: list[str]` and
  `action.specializations: list[str]` are the single source of truth. There
  is **no parallel scalar** — the legacy `spec_id`/`specialization` are folded
  into the one-element list at LOAD time, and re-emitted in the legacy on-disk
  SHAPE while a list has ≤1 entry (so a pre-restart MCP/pool holding the OLD
  `extra='forbid'` schema can still re-read any plan; the plural keys appear on
  disk only once N ≥ 2). `effective_spec_ids()` dedups, order-preserving.
- **Planner smart-selection**: the planner resolves+stamps **every** relevant
  stack — `update_object('action', patch={'spec_ids': ['<a>','<b>']})` —
  *minimal and relevant* (one spec per stack the action genuinely
  writes/audits; over-stamping dilutes grounding). No hard cap on N (amendment
  A2 — discipline governs; at most a soft advisory).
- **Guard B generalizes**: it validates that **each** stamped spec has a
  compiled doc; a single missing doc fails **closed** and the error **names**
  the missing spec(s). N = 1 reduces to the two refusals shipped 2026-06-02.
- **Worker composes** via `get_specialist_docs(spec_ids)`: N = 1 is a
  bit-for-bit pass-through (single-spec path unchanged); N ≥ 2 is a plain
  ORDERED CONCATENATION, each doc under `# ===== Specialist stack: <id> =====`.
  **No universal-layer dedup** (amendment A3): the universal foundation
  repeating across stacks is accepted — noisier, never wrong; `compiled.md`
  authoring is unchanged. The worker honors EVERY stack's `[required]` rules.
- **`assemble_ruleset` is untouched**: it is a compile-time, per-spec
  operation; multi-spec is a per-action compose-time step over already-compiled
  docs — different layers, no collision.

## Re-training / first compile (how the neuron drives it)

Re-training **is** training again, resuming the trained base — and it is also
how today's link-heavy JSON specs become clean docs. The neuron drives it
through `update_specialist`, extended to emit the doc:

```
neuron → update_specialist(neuron_id, "compile your spec into a clean stack doc")
            → pool resumes the BASE (--resume <base> --fork-session, monitor)
       SME (trained ctx) → edits the JSON → COMPILES the .md → re-snapshot → pending_review
            → YOU review the .md → neuron_set_status(stable)
```

To clean up the existing trained neurons, the neuron walks each `stable`
domain neuron and fires `update_specialist(..., "compile")`; you review each
doc. (Archived neurons have no `base_session_id` and need fresh training.)

## Compiled doc location

`.specs/<spec_id>/compiled.md` — next to the spec's JSON + snapshots, written
by `write_specialist_doc` and read by `get_specialist_doc`. Diffable on disk;
you open it to review before approving `stable`.

## Staged implementation

1. **Storage + tools** — `SpecStore.write_doc/read_doc` at
   `.specs/<spec_id>/compiled.md`; `write_specialist_doc(spec_id, content)`
   (SME writes it — baked in, no path-guessing) + `get_specialist_doc(spec_id)`
   (worker reads it — baked into the worker prompt so it can't hallucinate
   the load). No behaviour change yet.
2. **Compile step** — `specialist.md`: after authoring the JSON,
   `assemble_ruleset` then COMPILE a self-contained per-stack doc via
   `write_specialist_doc` (distill-not-dump). The doc is the review artifact
   gating `stable`.
3. **Worker loads the doc** — `worker.md` Step 2: `spec_id` set →
   `get_specialist_doc(spec_id)` is the grounding (replaces `assemble_ruleset`
   for the worker); generic worker (no spec_id) → `coding-standards.md`.
4. **Dispatch + Guard B inversion** — specialist actions dispatch via
   `pool_spawn_worker` (fresh) with `spec_id` stamped + a compiled doc
   required; the execution fork is retired; update the drive/author guides;
   invert Guard B.
5. **Retire the execution fork (2026-06-03)** — `branch_specialist` +
   `flow_back_learnings` REMOVED (and the dead `spawn_branch` pool method);
   `branch_reviewer` already spawns fresh. The only fork left anywhere is
   re-training (`update_specialist`). The "specialist gets smarter" loop is
   now: review feedback → re-train → recompiled doc (not promote-a-fork).

## Acceptance checklist

Status as of 2026-06-02 — Stages 1–4 landed (343 tests green, ruff clean).

- [x] `write_specialist_doc` / `get_specialist_doc` round-trip at
      `.specs/<spec_id>/compiled.md`; get on a missing doc returns null.
      (`test_specialist_compiled_doc`)
- [x] `specialist.md` compiles the doc (assemble→distill→write) BEFORE
      `pending_review`; the doc is self-contained (universal⊗stack distilled),
      with the distill-not-dump keep/cut rule. (`test_specialist_compiles_*`)
- [x] `worker.md` loads the compiled doc by `spec_id` as its grounding —
      no fork, no `assemble_ruleset`, no link-chasing on the worker path; a
      missing doc is a BLOCKED state. (`test_worker_loads_compiled_doc_*`)
- [x] A specialist action dispatches fresh (`pool_spawn_worker`) with
      `spec_id` stamped (drive guide); the execution fork is removed.
- [x] Guard B inverted: a specialist action with no `spec_id` (unresolved)
      or no compiled doc is refused with a clear message.
      (`test_pool_spawn_worker_requires_*`)
- [x] The **reviewer** enforces the SAME compiled doc by `[adherence]`
      (one artifact, both roles), not the JSON. (`test_reviewer_enforces_*`)
- [x] The MCP/eda-designs "fetch don't generate" guidance was removed from
      the specialist + worker briefs.

- [x] **Reviewer launches fresh, not forked.** `branch_reviewer` now
      spawns a FRESH reviewer (`spawn_reviewer` → `--session-id` only, no
      `--resume`) and gates on the compiled doc (not `base_session_id`);
      `reviewer.md` enforces the compiled doc. Review is now as cheap as a
      worker — no trained-chat replay. (`test_branch_reviewer_spawns_fresh*`,
      `test_branch_reviewer_requires_compiled_doc`)
- [x] **`update_specialist` emits the doc** — by construction: the compile
      step (`specialist.md` Step 3.5) is in the main authoring flow, not
      gated to first-train, so the resume-based update path runs it too.

## You still need to do (operator action, not code)

- **Compile the existing trained specs.** `spec-react-typescript-…`,
  `spec-spring-boot-…`, `spec-python-ml-…` have JSON but **no compiled doc
  yet** — a worker dispatched for them will (correctly) hit Guard B / the
  reviewer gate ("no compiled doc"). Have the neuron run
  `update_specialist(neuron_id, "compile your spec into a clean stack
  doc")` per stable specialist; review each `.specs/<spec_id>/compiled.md`;
  mark `stable`.
