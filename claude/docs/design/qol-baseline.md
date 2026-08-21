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
- [x] F2 [P1] `start_recipe` (and most writes) return bare ids/`ok:true`
      with no next-move pointer; a cold seat must know the card by heart.
- [x] F3 [P2] Worker's `injected_context` carries ONLY the grounding brief:
      no goal, no decisions, no bans, no position ("step N of M"), nothing
      about prev/next. The builder has the least visibility in the fleet.
- [x] F4 [P2] Planner digest clips its own step description mid-sentence;
      `recent_events` is 8× `recipe_saved` with empty summaries (noise).
- [x] F5 [P3] `workspace` is captured NOWHERE: `start_recipe` has no param,
      the acceptor consult ships `workspace: null` while its card orders
      "go to the workspace and look"; G-COMMIT silently no-ops.

## Intent fidelity

- [x] F6 [P2] `read_object(recipe, detail="digest")` serves ONLY
      `user_goal_distilled`; curiosity's card-mandated diff vs
      `user_goal_verbatim` is unexecutable — and distilled is silently a
      copy, so the gap is invisible.
- [x] F7 [P3] Grounding brief: stored whole, injected first-6000-chars; the
      3 LOAD-BEARING corrections in the tail never arrive; recovery costs a
      full broker round-trip. (Truncation marker is loud — keep that.)
- [x] F8 [P3] `record_action_status(done)` accepted evidence that ADMITS the
      signed-off design-first order was skipped — `manual_review` acceptance
      runs no check; self-accept-on-green reproduced live.
- [x] F9 [P4] Sol never entered the loop: no route fires, no card demands a
      visual critique; only the (mock) brief text carried it.
- [ ] F10 [P5] Curiosity fidelity protocol is honor-system: a `done` reply
      to a stale msg_id passes with no fidelity round ever delivered.
- [ ] F11 [P3] OCAK audit: `recap` shows `audit=none` forever; nothing gates
      on it; `run_ocak_audit` exists unused.

## Tool ergonomics (the "hit or miss" class)

- [x] F12 [P1] Param vocabulary drifts per verb for the SAME concept:
      `consult_curiosity(handle=)` vs siblings' `recipe_id=`; signoff's
      `user_quote=` vs guessed `quote=`; `create_plan(step_id=)` vs the
      schema field `recipe_step_id`; `record_grounding_brief(content=)` vs
      `record_context(text=)`.
- [x] F13 [P1] Serial-refusal discovery: `add_step` = 3 calls (enum guess →
      G-EST → ok); `create_plan` = 4 calls (param name → justify shape →
      ok). Schemas must state ALL requirements upfront (enums + required
      sets + nested shapes).
- [x] F14 [P1] `record_step_result` refusal names `result (dict)` but not
      the dict's shape.
- [x] F15 [P1] `record_branch_verdict` demands `recipe_id` + `branch_id`
      from a reviewer whose env lineage already determines both.
- [x] F16 [P1] Writes don't echo created ids (`record_outcome` → `ok:true`)
      → forced read-backs to wire lineage.
- [x] F17 [P1] `create_plan.review_policy.justify` is keyed by action_id
      BEFORE any action exists — an ordering the planner cannot satisfy
      honestly.
- [x] F18 [P1] `consult_curiosity` body duplicates `context` as
      `caller_framing` verbatim.
- [x] F19 [P1] Every payload is raw JSON (operator ruling: structured text).
- [ ] F20 [P5] Inconsistent seat gating: `record_context(north_star_update)`
      refused a handle-carrying role-less seat while `record_outcome` /
      `add_step` accepted the identical seat.

## FSM & pacing

- [x] F21 [P5] REPRODUCED from live: `next_action(all_ready=true)` on a
      ready recipe returns `dispatch_wave count=0` with ZERO explanation;
      plain `next_action` then instructs `spawn_planner s1`. Two pacer
      surfaces, different answers, no cross-reference.
- [ ] F22 [P5] G-STEP: both actions done, plan still `state='drafted'` —
      the FSM does not follow reality; the planner must manually pump
      `next_action` to make the record admit finished work ("laggy",
      mechanized).
- [x] F23 [P4] Challenge-threshold contradiction: planner card says 3+
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

## Phase 1+2 wave-1 disposition (2026-08-21)

Fixed this wave: F3 (position block on every action read), F4 (digest
noise + `why` on open steps), F6 (digest carries verbatim goal), F12
(param aliases via `_ClaudeTool.param_aliases`), F13 (execution enum at
the schema; refusals now carry field descriptions), F14 (`result` shape
documented in-field), F15 (action-path verdict derives ids), F16
(record_outcome echoes its id), F17 (justify-forward-ids documented),
F18 (caller_framing dedup), F19 (structured-text MCP boundary,
`tools/render_text.py`), F21 (empty waves explain themselves + name the
next call). Also: hop-11 (proposed bans filtered from briefs, labeled in
brief), silent-kwarg drops now refuse (`extra="forbid"` on authoring
models; create_object translates nested acceptance), orientation module
`shared/why-and-where.md` compiled into every card (budgets raised),
spawned-shell settings parity (`eda.bat` env, `.claude-pool` outputStyle
+ model 4-6→4-8 + edp-terse style file).

Deviations from the approved plan, with reasons:
- shadow.py/shadow_spawner.py NOT deleted — they are a LIVE default-on
  feature (every spawn is shadow-wrapped; EDP_SHADOW=0 disables). The
  "dead code" note in the old backlog was stale.
- worker/reviewer NOT granted get_recipe_digest — a standing derived-
  floor ruling excludes it, and the position block + recipe brief now
  serve the same need through reads they already have.

Still open: F1/F2 (richer next-move pointers), F5 (workspace field —
Phase 3), F7 (brief cap delivery — Phase 3), F8 (deliverable-form gate —
Phase 3), F9 (advisor fabric — Phase 4), F10/F20 (protocol/gating
consistency — Phase 5), F11 (OCAK — Phase 3), F22 (FSM follows reality —
Phase 5), F23 (challenge retarget — Phase 4).

## Final disposition — post-change re-drill (2026-08-21, R1–R4)

The SAME mock recipe was re-driven end-to-end through the real tool
layer with the updated guides: **28/28 checks PASS** (verbatim goal into
the curiosity consult; batch `record_outcome`/`add_action`; teaching
refusals naming legal ids; operator hold blocking wave+spawn and
clearing; `text=`/`recipe_step_id=` aliases; position block on the
action read; structured-text boundary; small-recipe exemption from
G-CHALLENGE and from the low-level-strategy advisory; empty waves
explaining themselves; plan → terminal → step close; acceptor consult
carrying goal + deliverable + user_path). Tool-output audit: 106
rendered results across all 93 registered tools, zero JSON dumps.

Fixed since the wave-1 disposition: F2 (writes carry next-move notes),
F5 (recipe `workspace`, validated, nudged, in the acceptor consult),
F7 (brief delivered WHOLE — 20k ceiling, 6000 lean-advisory), F8
(deliverable form + `user_path` + producer-verify stand-down + the
acceptor's walk law), F9 (Sol fabric: routes, write-capable asset
delegate, images threading, visual-authority card doctrine), F23
(challenge retargeted: big recipes only, `EDP_CHALLENGE_GATE_MIN_STEPS`).

Deferred, with reasons:
- F1 (whoami identity block) — separate harness defect, tracked
  independently; the position block + orientation module now carry the
  "you are here" load.
- F10 (fidelity honor-system) — the `awaiting_user_iteration` protocol
  narrows it culturally (done only on a sign-off round); a mechanical
  stale-msg_id guard was judged not cheap and stays open.
- F20 (seat-gating asymmetry) — DELIBERATE: goal-patching
  (north_star_update) stays neuron-only per the F37 hardening;
  authoring verbs stay open. Asymmetry documented, not a bug.
- F11 (OCAK unused) — untouched this campaign; candidate for the next.
- F22 (FSM follows reality) — the pump is still manual; empty waves now
  explain themselves and name the next call, which removes the mystery
  but not the ceremony. Candidate for the next campaign.
