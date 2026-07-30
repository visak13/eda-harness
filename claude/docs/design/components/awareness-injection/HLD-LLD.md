# HLD+LLD — awareness-injection (component, change to built #2)

**Stage:** S1+S2 combined (well-reasoned in DESIGN-v5; proportionate).
**Authority:** DESIGN-v5 P1–P4. §5.5 impact = this doc (before code).

## Problem (from the debug log + v5)
The tools take/dispatch/gatekeep; they don't force awareness or inject
context. OCAK is a skippable skill. Errors are raw pydantic →
schema-guessing retry storms (the original system's named failure, live).

## Changes

### P4 — only meaning crosses the boundary (kills the friction)
- **Instruction-shaped errors (generic, in `_ClaudeTool`).** On
  `ValidationError`, emit a `do-X` message: `needs: <field> (<type>)…;
  bad enum: <field>=<got> allowed=<set>; drop extra: <names>; resend.`
  Never raw pydantic. One precise retry, not a guessing storm.
- **Intent-level tools (tool fills scaffolding):**
  - `start_recipe(goal, domain) -> {recipe_id}` — tool sets recipe_id
    (slug), `state=created`, timestamps, empty comprehension/steps.
    LLM never hand-authors Recipe scaffolding.
  - `record_branch_verdict(recipe_id, branch_id, verdict,
    needs_user=False, question_for_user=None)` — answer ONE OCAK branch.
  - `record_outcome(recipe_id, description, verification)` — one
    expected_outcome.
  - `add_step(recipe_id, description, execution)` — one step
    (`execution` ∈ inline|spawn_planner; tool makes step_id, status).
  Existing `record_recipe/record_step/...` stay for power use.

### P1 — OCAK forced by the FSM, not hoped as a skill
`recipe_fsm` comprehending rewritten:
- On `created → comprehending`, the **tool deterministically seeds the
  fixed 7 branches** (feasibility, role_clarity, actors, concerns,
  new_tech, estimation, goal_setter), status `open`, canonical
  questions. The LLM does not author the branch set.
- `next_action` returns `answer_branch` for the FIRST `open` branch
  (one at a time — the LLM cannot skip ahead). LLM replies via
  `record_branch_verdict`. A verdict must be substantive (≥40 chars,
  not in a trivial-stoplist {"ok","n/a","none","yes","no"}) or the FSM
  keeps the branch open and re-asks with "answer substantively".
  `needs_user=True` → `next_action` returns `ask_user`; resolved when
  the user answers (existing `record_user_answer`).
- All branches resolved → `next_action` returns `declare_outcome`
  until ≥1 outcome (`record_outcome`), then `declare_step` until ≥1
  step (`add_step`). Only then → `planning`. (The existing
  `_clear_test_invariants` still guards the schema; the FSM now *drives*
  the path so it can't be shortcut.)
- `ocak.md` skill is **retired** to a 6-line pointer ("comprehension is
  driven by next_action; answer each branch substantively"). The
  cluster stays dead (DESIGN-v5 §3).

### P2/P3 — next_action injects, memory pushed not chosen
- `Instruction` gains `context: dict` = `{recap, prior, anti_patterns}`:
  - `recap`: 1–2 lines — state, branches resolved/total, what's pending
    (re-grounds a compacted session every call).
  - `prior`: decisions + assumptions already on disk.
  - `anti_patterns`: `_anti_patterns(recipe)` hook — returns `[]` now
    with `# TODO(memory-inject)`; the *mechanism* (tool pushes, LLM
    never fetches) lands now. No LLM-choosable recall for on-track
    context.

## Tool count
16 → 20 (`start_recipe`, `record_branch_verdict`, `record_outcome`,
`add_step`). Registry/count assertions updated.

## Blast radius
edp-claude only: `tools/_tools.py` (+4 tools, generic error fmt),
`fsm/recipe_fsm.py` (comprehending rewrite + branch seeding),
`schemas/instruction.py` (`context` field), `neuron.md` (new instruction
kinds, `start_recipe` on create), `ocak.md` (retire to pointer). FSM
tests rewritten for the forced path; +intent-tool tests; +error-shape
test. Schemas/contracts/broker/pool untouched. Integration additive-safe.

## Out of scope (flagged)
- `edp-fsm` masked-LLM (DESIGN-v5 §5 #2) — next component.
- Real anti-pattern memory — `# TODO(memory-inject)`; mechanism only.
- Substantive-verdict heuristic is deliberately crude (length +
  stoplist); a masked-LLM judge is the later refinement.

## Verdict
Kills the friction AND the disease in one component; OCAK becomes
unskippable; context is pushed. Proceed to code.
