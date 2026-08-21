# QoL baseline — Phase-0 drill friction log (2026-08-21)

A mock recipe ("browser habit tracker, design-first, Sol critiques the
look") was driven END TO END through the real tool layer (stub broker/pool,
scratch home), role-playing every seat by its card verbatim: neuron →
curiosity (2 rounds + fidelity) → planner → worker → reviewer (FAIL →
rework → PASS) → step close → acceptor → close_recipe. Every friction below
was OBSERVED, not inferred. This is the checklist the overhaul phases must
clear; the post-change re-drill re-runs the same recipe and checks each box.

Legend: [P1]…[P5] = the overhaul phase that owns the fix ·
[+] = a positive to PRESERVE.

## Identity & orientation

- [ ] F1 [P2] `whoami` on the main seat: all-null identity + rx jargon;
      nothing says "you are the neuron; your parent is the user".
- [ ] F2 [P1] `start_recipe` (and most writes) return bare ids/`ok:true`
      with no next-move pointer; a cold seat must know the card by heart.
- [ ] F3 [P2] Worker's `injected_context` carries ONLY the grounding brief:
      no goal, no decisions, no bans, no position ("step N of M"), nothing
      about prev/next. The builder has the least visibility in the fleet.
- [ ] F4 [P2] Planner digest clips its own step description mid-sentence;
      `recent_events` is 8× `recipe_saved` with empty summaries (noise).
- [ ] F5 [P3] `workspace` is captured NOWHERE: `start_recipe` has no param,
      the acceptor consult ships `workspace: null` while its card orders
      "go to the workspace and look"; G-COMMIT silently no-ops.

## Intent fidelity

- [ ] F6 [P2] `read_object(recipe, detail="digest")` serves ONLY
      `user_goal_distilled`; curiosity's card-mandated diff vs
      `user_goal_verbatim` is unexecutable — and distilled is silently a
      copy, so the gap is invisible.
- [ ] F7 [P3] Grounding brief: stored whole, injected first-6000-chars; the
      3 LOAD-BEARING corrections in the tail never arrive; recovery costs a
      full broker round-trip. (Truncation marker is loud — keep that.)
- [ ] F8 [P3] `record_action_status(done)` accepted evidence that ADMITS the
      signed-off design-first order was skipped — `manual_review` acceptance
      runs no check; self-accept-on-green reproduced live.
- [ ] F9 [P4] Sol never entered the loop: no route fires, no card demands a
      visual critique; only the (mock) brief text carried it.
- [ ] F10 [P5] Curiosity fidelity protocol is honor-system: a `done` reply
      to a stale msg_id passes with no fidelity round ever delivered.
- [ ] F11 [P3] OCAK audit: `recap` shows `audit=none` forever; nothing gates
      on it; `run_ocak_audit` exists unused.

## Tool ergonomics (the "hit or miss" class)

- [ ] F12 [P1] Param vocabulary drifts per verb for the SAME concept:
      `consult_curiosity(handle=)` vs siblings' `recipe_id=`; signoff's
      `user_quote=` vs guessed `quote=`; `create_plan(step_id=)` vs the
      schema field `recipe_step_id`; `record_grounding_brief(content=)` vs
      `record_context(text=)`.
- [ ] F13 [P1] Serial-refusal discovery: `add_step` = 3 calls (enum guess →
      G-EST → ok); `create_plan` = 4 calls (param name → justify shape →
      ok). Schemas must state ALL requirements upfront (enums + required
      sets + nested shapes).
- [ ] F14 [P1] `record_step_result` refusal names `result (dict)` but not
      the dict's shape.
- [ ] F15 [P1] `record_branch_verdict` demands `recipe_id` + `branch_id`
      from a reviewer whose env lineage already determines both.
- [ ] F16 [P1] Writes don't echo created ids (`record_outcome` → `ok:true`)
      → forced read-backs to wire lineage.
- [ ] F17 [P1] `create_plan.review_policy.justify` is keyed by action_id
      BEFORE any action exists — an ordering the planner cannot satisfy
      honestly.
- [ ] F18 [P1] `consult_curiosity` body duplicates `context` as
      `caller_framing` verbatim.
- [ ] F19 [P1] Every payload is raw JSON (operator ruling: structured text).
- [ ] F20 [P5] Inconsistent seat gating: `record_context(north_star_update)`
      refused a handle-carrying role-less seat while `record_outcome` /
      `add_step` accepted the identical seat.

## FSM & pacing

- [ ] F21 [P5] REPRODUCED from live: `next_action(all_ready=true)` on a
      ready recipe returns `dispatch_wave count=0` with ZERO explanation;
      plain `next_action` then instructs `spawn_planner s1`. Two pacer
      surfaces, different answers, no cross-reference.
- [ ] F22 [P5] G-STEP: both actions done, plan still `state='drafted'` —
      the FSM does not follow reality; the planner must manually pump
      `next_action` to make the record admit finished work ("laggy",
      mechanized).
- [ ] F23 [P4] Challenge-threshold contradiction: planner card says 3+
      actions require a challenge; the spawn advisory threatens step-close
      refusal at 2. (Phase 4 retargets the challenge at generated code
      anyway.)

## Positives to preserve

- [+] P-A `ask_above` auto-enriches questions (goal / doing /
      acceptance_diff / blocks_on_this) by construction.
- [+] P-B The `pool_spawn_worker` review-leg refusal is the best error in
      the drill: names the exact fix, the reason, and the escape hatch —
      the refusal SHAPE to standardize everywhere.
- [+] P-C G-VERDICT reopened a done action over a recorded reviewer FAIL —
      no fail-laundering, clear reopen note.
- [+] P-D The acceptance consult carries `user_goal_verbatim` whole, and
      `get_recipe_digest`'s north_star part does too.
- [+] P-E The grounding-brief truncation warning at record time is loud and
      prescriptive (even though the cap itself is F7).

Drill artifacts: scenes + driver in the session scratchpad (`drill/`),
stores under `drill/home/`, the shipped page under `drill/workspace/`.
