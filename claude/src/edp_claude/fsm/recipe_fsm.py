"""Deterministic recipe FSM (LLD §4; DESIGN-v4 §2.1 table, verbatim).

`recipe_next_action` may advance `recipe.state` for pure bookkeeping
transitions (e.g. COMPREHENDING->PLANNING once branches resolve). The
caller (next_action tool) persists when state changed — documented
deviation from "next_action is read-only" (REFACTOR will note it).
"""

import hashlib
import json

from ..schemas import (
    Instruction,
    InstructionKind,
    Recipe,
    RecipeState,
)

K = InstructionKind

SKILL_CRITIC = "critic-review"  # TODO(critic-audit) — later component

# Post-HITL sweep 2026-05-20 (docs/design/philosophy/ocak-as-helper-not
# -enforcer.md): OCAK_BRANCHES (the forced 7-branch checklist) is gone.
# Comprehension now flows: free reasoning → optional specialist consult
# → mandatory OCAK audit → declare outcome → declare step. The agent
# does the thinking; the helpers scaffold; the FSM tracks state. The
# specialist guides live at docs/guides/specialist-<id>.md. The 4 OCAK
# audit questions live in docs/guides/framework-ocak.md.


def comprehension_baseline_counts(r: Recipe) -> dict:
    """P6: the snapshot the recheck triggers compare the live recipe
    against — steps/outcomes (s27 scope-creep) + ACTIVE load-bearing
    decisions and superseded count (load-bearing drift)."""
    active = [d for d in r.context.decisions
              if getattr(d, "status", "active") == "active"]
    return {
        "n_steps": len(r.steps),
        "n_outcomes": len(r.comprehension.expected_outcomes),
        "n_load_bearing": sum(
            1 for d in active if getattr(d, "load_bearing", False)),
        "n_superseded": len(r.context.decisions) - len(active),
    }


def refresh_comprehension_baseline(r: Recipe, at: str) -> None:
    """P6: re-ground the recheck baseline at a re-grounding moment — a
    fresh curiosity clear, or a user signoff after a comprehension-brief /
    delta discussion. Clears the pending recheck nag. Baseline counts are
    refreshed only once a baseline exists (it is set as the recipe first
    leaves COMPREHENDING); last_recheck_at always advances."""
    if r.comprehension.baseline is not None:
        r.comprehension.baseline = comprehension_baseline_counts(r)
    r.comprehension.last_recheck_at = at


# W9's NEURON-FACING DIRECTION-REVIEW SURFACE IS REMOVED (d128 user correction,
# d129 Part A item 1, d132). It used to live here: `direction_review_status` (the
# checkpoint read), a latched DIRECTION_REVIEW_DUE instruction telling the neuron
# to branch a direction reviewer, `mark_direction_reviewed` (the anchor), and an
# off_track nag riding the recipe_context push.
#
# THE REVIEWER IS THE PLANNER'S SUBAGENT AND IS NEVER AVAILABLE TO THE NEURON, so
# a checkpoint that ORDERS the neuron to spawn one was machinery asserting a
# capability the neuron does not hold. The neuron's direction integrity is
# `_comprehension_recheck` (below) -> a CURIOSITY consult when bias-risk is high,
# the decision is large, or the recipe is fresh -> the recorded SIGNOFF; a
# mutually-agreed decision may be signed off without a consult. The recipe is the
# neuron's MEMORY LAYER, not a dictator.
#
# The PLANNER's reviewer leg (a role="reviewer" dispatch) is untouched.
# (`branch_reviewer` itself is deleted — owner ruling 2026-08-04.)


def _ready_steps(r: Recipe, live_step_ids: frozenset[str] = frozenset()):
    """The SINGLE source of truth for step readiness: every step that is
    pending with ALL of its depends_on already done/skipped, in declared
    order — the recipe analogue of plan_fsm._ready_actions, extracted
    (DESIGN-v7 1.5.1) so the single-step dispatch and the step-frontier wave
    share ONE predicate and a second, divergent readiness rule can never
    drift in.

    `live_step_ids` — step_ids the CALLER has confirmed are already OWNED by
    a live planner shell (pool liveness 'alive', and — 1.5.2 — 'parked' or
    'resuming': a parked planner is 0 process but still the step's owner;
    its resume token holds the handle lock, so instructing a dispatch for
    its step would be false). Threaded as an INPUT exactly as plan_fsm
    threads live_action_ids (s27/C7, d78): the FSM stays PURE (principle 6)
    — no pool client in here, ever. Empty (the default) = the caller asserts
    nothing is known to be live, the pre-1.5.1 behaviour every existing
    caller relied on."""
    done_ids = {s.step_id for s in r.steps if s.status in ("done", "skipped")}
    return [s for s in r.steps
            if s.status == "pending" and set(s.depends_on) <= done_ids
            and s.step_id not in live_step_ids]


def _first_ready_step(r: Recipe):
    return next(iter(_ready_steps(r)), None)


def recipe_ready_step_wave(r: Recipe,
                           live_step_ids: frozenset[str] = frozenset(),
                           ) -> list[Instruction]:
    """DESIGN-v7 1.5.1 — the recipe STEP-FRONTIER wave, mirroring
    plan_fsm.plan_ready_wave: return one SPAWN_PLANNER Instruction for EVERY
    spawn_planner step currently ready (pending + all depends_on satisfied +
    not already owned by a live/parked planner), stamping each in_progress so
    the tool layer persists the whole wave in ONE atomic recipes.save.

    THIS IS THE PARALLELISM. The serial root cause the plan names:
    `_first_ready_step` selects exactly ONE step, the PLANNING branch
    dispatches it and flips to EXECUTING, and the EXECUTING branch WAITs
    unconditionally — so independent steps ran one planner at a time. The
    wave fires from BOTH `PLANNING` and `EXECUTING`: a step that becomes
    newly ready WHILE others run (its dep closed mid-flight) must dispatch
    without waiting for the whole recipe to drain back to PLANNING.

    Invariants (all inherited from the shared `_ready_steps` predicate):
    - never returns a step with unmet deps, never an in_progress/done step,
      never a step in `live_step_ids` (a live OR PARKED planner owns it);
    - stamping the frontier in_progress cannot make another pending step
      newly ready (a dep is satisfied only by done/skipped), so the returned
      list IS exactly the current frontier;
    - `execution="inline"` steps are NOT wave slots: a wave slot is a
      planner spawn (one pool shell), and an inline step runs in the
      CALLER's own context — it is left pending for the single-step path
      (recipe_next_action emits RUN_INLINE for it once the recipe hands
      back to PLANNING). Deliberate: emitting SPAWN_PLANNER for an inline
      step would instruct a spawn the step's own contract forbids.

    Mirrors plan_ready_wave's state handling: REVIEWING with a ready step
    REOPENS to PLANNING (the v2.1 phased-map rule), a dispatch from PLANNING
    advances to EXECUTING. COMPREHENDING/CREATED never wave — the
    comprehension + signoff gates are not bypassable by a batch surface.
    Pure + deterministic (no IO, no LLM — principle 6); the CALLER persists
    the mutations (one atomic save) and performs every spawn."""
    if (r.state == RecipeState.REVIEWING
            and _ready_steps(r, live_step_ids)):
        r.state = RecipeState.PLANNING
    if r.state not in (RecipeState.PLANNING, RecipeState.EXECUTING):
        return []
    # Materialise the frontier BEFORE mutating any status, then stamp — the
    # readiness set is computed against the pre-wave state exactly once.
    ready = [s for s in _ready_steps(r, live_step_ids)
             if s.execution == "spawn_planner"]
    instrs: list[Instruction] = []
    for s in ready:
        s.status = "in_progress"   # tool-forced stamp, mirrors single dispatch
        instrs.append(Instruction(
            kind=K.SPAWN_PLANNER, args={"step_id": s.step_id},
            rationale=s.description,
        ))
    if instrs and r.state == RecipeState.PLANNING:
        r.state = RecipeState.EXECUTING
    return instrs


def recipe_pacing_state(r: Recipe, *, output_stale: bool = False,
                        awaiting_user: bool = False) -> str:
    """DESIGN-v6 W7 item 1 — recipe analogue of plan_pacing_state. A recipe in
    EXECUTING has a planner (a child) in flight; REVIEWING / CLOSED is wrap-up;
    a comprehension-brief AWAIT_USER is awaiting_user (the caller derives it
    from the returned instruction kind). Pure + deterministic. Steps carry no
    `verify` status today, but the check is kept for symmetry with the plan
    classifier so it stays correct if that changes."""
    if awaiting_user:
        return "awaiting_user"
    steps = [s.status for s in r.steps]
    if any(s == "verify" for s in steps):
        return "verify_pending"
    if r.state == RecipeState.EXECUTING or any(s == "in_progress" for s in steps):
        return ("child_in_progress_stale_output" if output_stale
                else "child_in_progress_recent_output")
    return "idle_or_done"


def recipe_next_action(r: Recipe) -> Instruction:
    if r.state == RecipeState.CREATED:
        r.state = RecipeState.COMPREHENDING
        return recipe_next_action(r)

    if r.state == RecipeState.COMPREHENDING:
        # Team-architecture-restoration Phase 1 (2026-05-21):
        # The self-audit gate is REMOVED. OCAK as the agent auditing
        # itself was theatre ("we investigated ourselves and found no
        # wrongdoing"). The real audit lives in `/critic` — a SEPARATE
        # shell — which is restored in Phase 5. Until then, comprehension
        # flows REASON → outcome → declare_step. Discipline lives in the
        # brief (forbid self-eval; spawn critic for novelty/correctness/
        # security claims), not in a placeholder FSM gate.
        if not r.comprehension.expected_outcomes:
            return Instruction(
                kind=K.REASON, args={},
                rationale=(
                    "Reason freely about this goal. Generate options, "
                    "name the real goal vs the stated goal, gather "
                    "priors. Consult specialists on demand via "
                    "consult_specialist when you recognise a gap "
                    "(feasibility / role-clarity / actor-identifier / "
                    "actor-clarity / concern-validator / "
                    "new-tech-detector / estimation / goal-setter). "
                    "When ready, declare ≥1 expected outcome via "
                    "record_outcome."
                ),
            )
        if not r.steps:
            return Instruction(
                kind=K.DECLARE_STEP, args={},
                rationale=(
                    "Outcomes declared. Declare ≥1 actionable step via "
                    "add_step (execution=spawn_planner for real work, "
                    "inline only for a trivial one-liner). Do NOT "
                    "self-audit the recipe — challenge work routes "
                    "through adversarial_challenge (recorded challenges) "
                    "or an interim dispatch_acceptance(interim=true) "
                    "pass; surface novelty/correctness/security claims "
                    "to the user via AskUserQuestion rather than "
                    "self-attesting."
                ),
            )
        # P6 USER-DISCUSSION GATE (2026-06-10): outcomes + steps exist and
        # curiosity has converged — but the USER has not seen the
        # comprehended plan yet. The old flow dispatched the first planner
        # here, and flaws were discovered post-dispatch. Leaving
        # COMPREHENDING now requires the user's signoff on a comprehension
        # BRIEF, or an explicitly recorded skip (deliberate + audited),
        # before any planner spawns.
        if not (r.comprehension.user_signoff
                or r.comprehension.signoff_skipped):
            return Instruction(
                kind=K.AWAIT_USER, args={},
                rationale=(
                    "COMPREHENSION BRIEF GATE — the map is drafted but the "
                    "user has not seen it. Present a comprehension brief "
                    "CONVERSATIONALLY before dispatching anything: the "
                    "distilled goal, each expected outcome with its "
                    "verification bar, the step map, the load-bearing "
                    "decisions + rejected options, and the open risks. Use "
                    "the harness plan-mode flow when available "
                    "(EnterPlanMode → discuss → ExitPlanMode), otherwise a "
                    "structured brief + AskUserQuestion. Then record the "
                    "user's verbatim approval via record_comprehension_"
                    "signoff(user_quote=…). ONLY if the user is genuinely "
                    "unavailable and the work must proceed autonomously, "
                    "record_comprehension_signoff(skipped=true, reason=…) — "
                    "a deliberate, audited bypass, not a default."
                ),
            )
        # s27 Item 1: snapshot the comprehended map ONCE, as the recipe first
        # leaves COMPREHENDING with outcomes + steps in hand. _comprehension_
        # recheck later compares the live recipe against this to detect scope
        # creep + load-bearing drift. Set-once: never overwrite here (it is
        # refreshed only at re-grounding moments — refresh_comprehension_
        # baseline).
        if r.comprehension.baseline is None:
            r.comprehension.baseline = comprehension_baseline_counts(r)
        r.state = RecipeState.PLANNING
        return recipe_next_action(r)

    if r.state == RecipeState.PLANNING:
        nxt = _first_ready_step(r)
        if nxt is None:
            r.state = RecipeState.REVIEWING
            return recipe_next_action(r)
        # Dispatching a step moves the recipe to EXECUTING and marks the
        # step in_progress (DESIGN-v4 §7 rows 8/10). The tool persists.
        nxt.status = "in_progress"
        r.state = RecipeState.EXECUTING
        if nxt.execution == "inline":
            return Instruction(
                kind=K.RUN_INLINE, args={"step_id": nxt.step_id},
                rationale=nxt.description,
            )
        return Instruction(
            kind=K.SPAWN_PLANNER, args={"step_id": nxt.step_id},
            rationale=nxt.description,
        )

    if r.state == RecipeState.EXECUTING:
        # A spawn_planner step is out. The next_action tool checks broker
        # for plan_closed / liveness BEFORE calling the FSM and advances the
        # step; if it didn't, we wait. (FsmPort consulted by the tool only
        # when ambiguous — stubbed FSM_UNDECIDABLE until #5.)
        return Instruction(
            kind=K.WAIT, args={}, rationale="planner in progress"
        )

    if r.state == RecipeState.REVIEWING:
        # v2.1 (2026-05-22): a newly-added pending step REOPENS the
        # recipe — the map may be built in phases when clarity is low
        # (the neuron deferred s2 until s1's output was known), but it
        # must stay coherent. Without this, steps added after the first
        # batch completed stranded in `reviewing` and the back half ran
        # OUTSIDE the FSM (the Java-REST deferred-last-step trap). The
        # map is the single source of truth; the neuron never routes
        # around it.
        if _first_ready_step(r) is not None:
            # F35 R3a#6 (2026-08-18): the reopen must not outrun the USER.
            # Signoff is checked only in COMPREHENDING, so a step added
            # here used to dispatch immediately — expanding scope one step
            # at a time without the user ever seeing it (add_step in
            # `reviewing` stamps signoff_stale for exactly this check;
            # record_comprehension_signoff clears it).
            if getattr(r.comprehension, "signoff_stale", False):
                return Instruction(
                    kind=K.AWAIT_USER, args={},
                    rationale=(
                        "The map GREW after the user's signoff (a step was "
                        "added post-review). Surface the scope delta — the "
                        "new step(s), what they cost, why now — and record "
                        "record_comprehension_signoff before this "
                        "dispatches. The user approved a smaller recipe "
                        "than the one about to run."
                    ),
                )
            r.state = RecipeState.PLANNING
            return recipe_next_action(r)
        # F4.c guard: `succeeded` is reachable ONLY with declared + met
        # outcomes. No work driven / no outcomes / unverified → honest
        # PARTIAL. The spine never lies "done/succeeded" having proved
        # nothing (the exact prior-system failure this rewrite kills).
        outcomes = r.comprehension.expected_outcomes
        drove_work = any(s.status == "done" for s in r.steps)
        if not drove_work:
            return Instruction(
                kind=K.DONE, args={"partial": True},
                rationale="PARTIAL — spine drove no work; deliverable "
                "NOT produced/verified by the spine (F4.c guard)",
            )
        if not outcomes:
            return Instruction(
                kind=K.DONE, args={"partial": True},
                rationale="PARTIAL — work driven but no expected_outcomes "
                "declared; unverified (OCAK must declare outcomes)",
            )
        if all(o.met for o in outcomes):
            # F31 (2026-08-18): the FINAL ACCEPTANCE PASS is FSM-explicit.
            # The FSM is pure over the Recipe and cannot read the events
            # trail, so it ALWAYS emits DISPATCH_ACCEPTANCE here; the tool
            # layer (NextAction) downgrades it to DONE when a 'pass'
            # acceptance_verdict is already recorded (or the gate is off).
            return Instruction(
                kind=K.DISPATCH_ACCEPTANCE, args={},
                rationale=(
                    "all expected_outcomes met — run the FINAL ACCEPTANCE "
                    "PASS before close: dispatch_acceptance(recipe_id=…) "
                    "spawns the advisor-seat ACCEPTOR in its own shell; it "
                    "verifies the delivery against the VERBATIM goal + any "
                    "artifact the goal names, fixes what it safely can, "
                    "and records acceptance_verdict. DONE follows a "
                    "recorded 'pass'."),
            )
        # TODO(outcome-verify): nothing marks outcome.met yet, so a real
        # run honestly lands here — deliverable IS produced by the
        # planner/worker; verification is a flagged component.
        return Instruction(
            kind=K.DONE, args={"partial": True},
            rationale="PARTIAL — work driven; outcomes not yet verified "
            "(outcome-verification is a flagged TODO, not a failure)",
        )

    return Instruction(
        kind=K.DONE, args={"partial": True},
        rationale="recipe closed (unexpected state — partial, not a "
        "false success)",
    )


def _anti_patterns(r: Recipe) -> list[str]:
    # TODO(memory-inject): pull goal-class anti-patterns from the memory
    # component and return them so next_action PUSHES them at the LLM
    # (never an LLM-choosable recall). Mechanism is wired now; the store
    # is the next component. Returns [] until then.
    return []


def _phase_for(r: Recipe) -> str:
    """Team-architecture Phase 3 (2026-05-21): map recipe state to
    one of the 5 neuron phases. The neuron's dispatcher (neuron.md)
    reads `context.phase` and loads
    `docs/guides/neuron-phase-<phase>.md` via get_guide.

    Phases (from the old design + adapted to the new substrate):
      a  init          — created; resolve/start the recipe
      b  comprehension — reason freely; consult specialists; outcomes
      c  spawn         — declare step; pool_spawn_planner
      d  observe       — wait + handle_messages from planner
      e  evaluate      — close_recipe with final_outcome
    """
    s = r.state
    if s == RecipeState.CREATED:
        return "a"
    if s == RecipeState.COMPREHENDING:
        return "b" if not r.comprehension.expected_outcomes else "c"
    if s == RecipeState.PLANNING:
        return "c"
    if s == RecipeState.EXECUTING:
        return "d"
    if s == RecipeState.REVIEWING:
        return "e"
    return "e"  # CLOSED — agent shouldn't be called, but fall to E if so


def _comprehension_recheck(r) -> str | None:
    """s27 Item 1 Part B — comprehension is ONE-SHOT (curiosity_cleared latches
    once and never re-gates), but a long recipe drifts and by then the OWNING
    shell's read of the goal is biased. So the FSM SUGGESTS (never forces) a
    re-consult of curiosity in a FRESH, unbiased shell at MEANINGFUL points —
    NOT every step. Curiosity's implementation is unchanged (it always runs in
    its own shell — that is the whole point: a view without this shell's
    accumulated bias). Two triggers: REPEATED FAILURES (the strongest signal a
    re-grounding is due) and MAJOR SCOPE CHANGE vs the comprehension baseline
    (the map grew materially past what was grounded). Returns a one-line
    suggestion or None."""
    if not r.comprehension.curiosity_cleared:
        return None  # initial comprehension isn't even done yet
    if any(getattr(s, "attempt", 0) >= 2 for s in r.steps):
        return (
            "REPEATED FAILURES (a step re-dispatched >=2x) — the plan isn't "
            "converging and THIS shell's read of the goal may be biased. "
            "Re-consult curiosity in a FRESH shell (consult_curiosity) to "
            "regain unbiased clarity before pressing on. Comprehension is "
            "not one-and-done."
        )
    # Second trigger: MAJOR SCOPE CHANGE since the map was comprehended. The
    # baseline (set as the recipe left COMPREHENDING) is the comprehended size;
    # if the live recipe has grown materially past it — +2 steps, or any new
    # outcome mid-flight (the s5/s6 scope-creep pattern) — the original
    # grounding may no longer fit. Suggest (never force) a fresh-shell consult.
    base = r.comprehension.baseline
    if base:
        grew_steps = len(r.steps) - int(base.get("n_steps", 0)) >= 2
        grew_outcomes = (
            len(r.comprehension.expected_outcomes)
            > int(base.get("n_outcomes", 0))
        )
        if grew_steps or grew_outcomes:
            return (
                "MAJOR SCOPE CHANGE since comprehension (the recipe grew "
                f"from {base.get('n_steps')} steps / {base.get('n_outcomes')} "
                f"outcomes to {len(r.steps)} steps / "
                f"{len(r.comprehension.expected_outcomes)} outcomes) — the map "
                "no longer matches what was originally grounded. Re-consult "
                "curiosity in a FRESH, unbiased shell (consult_curiosity) to "
                "re-ground the expanded scope, then present the delta to the "
                "user (plan-mode discussion / AskUserQuestion) BEFORE the "
                "next dispatch. Comprehension is not one-and-done. This "
                "reminder clears when curiosity next returns clear or a "
                "fresh signoff is recorded."
            )
        # P6 third trigger — LOAD-BEARING DECISION DRIFT: a new load-bearing
        # decision (or a supersede) recorded after the last re-grounding is
        # exactly the d4-class strategy pivot that used to bypass curiosity
        # and the user entirely. Persistent nag: re-emitted every tick until
        # a re-grounding moment refreshes the baseline.
        now = comprehension_baseline_counts(r)
        lb_grew = now["n_load_bearing"] > int(base.get("n_load_bearing", 0))
        sup_grew = now["n_superseded"] > int(base.get("n_superseded", 0))
        if lb_grew or sup_grew:
            return (
                "LOAD-BEARING DECISION DRIFT since the last re-grounding "
                f"(active load-bearing decisions {base.get('n_load_bearing', 0)}"
                f"→{now['n_load_bearing']}, superseded "
                f"{base.get('n_superseded', 0)}→{now['n_superseded']}) — a "
                "major direction change was recorded without an unbiased "
                "check. Re-consult curiosity in a FRESH shell "
                "(consult_curiosity) about the NEW/SUPERSEDED decisions, "
                "then present the delta to the user (plan-mode discussion / "
                "AskUserQuestion) BEFORE dispatching the next planner. This "
                "reminder repeats every tick until curiosity returns clear "
                "or a fresh user signoff is recorded (either refreshes the "
                "baseline)."
            )
    return None


def _decision_title(text: str, limit: int = 90) -> str:
    """s17 RP-B — derive a stable one-line TITLE for the decisions-pointer
    index from a decision's text. Deterministic (no clock/rng): the first
    physical line, trimmed at the first natural clause boundary, capped at
    `limit`. Decisions conventionally open with an ALL-CAPS label
    ("SCOPE LOCKED (...)", "LATENCY DIRECTION (user, ...)"), so the leading
    fragment is a good human-recognisable handle for self-detection."""
    first = ""
    stripped = text.strip()
    if stripped:
        first = stripped.splitlines()[0].strip()
    for sep in (". ", " — ", " -- ", ": ", " - "):
        i = first.find(sep)
        if 0 < i <= limit:
            return first[:i].strip()
    return (first[:limit].rstrip() + "…") if len(first) > limit else first


def pending_load_bearing_assumptions(r: Recipe) -> list[dict]:
    """W8 — the recipe's UNACKED load-bearing assumptions as
    [{id, title, body}]. An assumption rests at status=="pending" exactly
    when it is load-bearing and not yet acked (a non-load-bearing assumption
    grandfathers to "acked" at construction — d24 — so only a load-bearing
    one can sit here). The a3 dispatch guard and the digest / recipe_context
    surfacing both read THIS one helper, so a reload/compaction re-lists them
    identically: the list is DERIVED from persisted recipe state on every
    call, never cached, so nothing epoch-shaped is built here (epochs stay
    stateless per d13 — W8 only RECORDS; W2 consumes later).

    `title` reuses the deterministic one-line deriver (no clock/rng); `body`
    is the assumption's full text.
    """
    return [
        {"id": a.id, "title": _decision_title(a.text), "body": a.text}
        for a in r.context.assumptions
        if getattr(a, "status", "acked") == "pending"
    ]


def grounding_epoch(r: Recipe) -> str:
    """W2 (DESIGN-v6 §W2) — the STATELESS grounding fingerprint.

    A 12-hex-char sha256 digest over the recipe's LOAD-BEARING GROUND:

    * the ACTIVE load-bearing decisions (id + full text),
    * the active constraints/bans (`derive_active_constraints`, which spans
      both `Decision.constraint` and `RejectedOption.constraint` — the same
      auto-derived view north_star / the digest surface, so the epoch can
      never disagree with the shipped constraints), and
    * the pending-unacked load-bearing assumption ids (the SAME
      `pending_load_bearing_assumptions` helper the a3 dispatch guard and the
      digest read, so a reload/compaction re-lists them identically).

    Recomputed from persisted recipe state on EVERY call — NEVER stored (d13:
    there is no `last_acked_epoch`; fresh-per-spawn MCP has no per-handle store
    to compare against, and the only per-handle state `_WAIT_CYCLES` resets on
    restart). The recipe IS the state: two shells loading the same recipe
    compute the SAME epoch, so a match/stale comparison needs no server-side
    ack store. When the ground shifts (a new load-bearing decision, a changed
    ban/constraint, a new pending assumption) the digest changes and a stale
    `ack_epoch` triggers a re-ground.

    Order-stable: each component is sorted by a deterministic key so a mere
    reorder of decisions/constraints does NOT churn the epoch (only a real
    content change does). No clock/rng (principle 6 / d13)."""
    from ..store.north_star import derive_active_constraints

    decisions = sorted(
        (
            (d.id, d.text)
            for d in r.context.decisions
            if getattr(d, "status", "active") == "active"
            and getattr(d, "load_bearing", False)
        ),
        key=lambda t: t[0],
    )
    constraints = sorted(
        (
            (c.source, c.source_id, c.match_kind, c.match,
             list(c.applies_to), c.message)
            for c in derive_active_constraints(r)
        ),
        key=lambda t: (t[0], t[1], t[3]),
    )
    pending = sorted(a["id"] for a in pending_load_bearing_assumptions(r))
    material = json.dumps(
        {"decisions": decisions, "constraints": constraints,
         "pending": pending},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def consult_pending_view(r: Recipe) -> dict:
    """W5 (DESIGN-v6 §W5) — the digest/push view of the recipe's UNDRAINED
    consult/steer inbox. `reconcile` stashes each kind=consult/steer message
    onto `r.consult_pending`; this projects it for recipe_context (push plane)
    and get_recipe_digest (re-ground plane) as ONE shared source of truth.

    A LIST output (one row per pending consult/steer), so it is bounded
    window+cursor by construction (coding-standard #18): `count`/`kinds`
    report the TRUE totals, `items` is the O(1) window, a non-null `cursor`
    means more entries exist past the window."""
    from ..tools._bounds import windowed
    pend = list(getattr(r, "consult_pending", []) or [])
    kinds: dict[str, int] = {}
    for e in pend:
        k = str(e.get("kind", "?"))
        kinds[k] = kinds.get(k, 0) + 1
    win = windowed(pend)
    return {
        "count": len(pend),
        "kinds": kinds,
        "items": win["items"],
        "cursor": win["cursor"],
        "note": (
            "UNDRAINED consult/steer on this recipe's own inbox. Answer/act on "
            "it, then record a decision (record_context kind=decision) whose "
            "text references the msg_id to CLEAR it — an unacked steer "
            "re-surfaces every reconcile tick until a decision references it."
        ),
    }


def recipe_context(r: Recipe) -> dict:
    """v5 P2/P3 — pushed on every next_action so a compacted/fresh
    session is re-grounded without the LLM choosing to look anything up.

    s17 RP-B (2026-06-07) — FSM-FOCUS + DECISIONS POINTER, never the dump.
    The pre-RP-B push re-embedded the WHOLE `context.decisions` text (~39.5K
    chars / 98.5% of the push) on EVERY tick — pure context pollution once the
    agent already holds them (BASELINE-TOKEN-FOOTPRINT.md, S17-FINDINGS-V2).
    Now the steady-state push carries only the FSM focus (recap/phase) plus an
    `active_decisions` POINTER: the active-decision COUNT, a one-line id+title
    INDEX (cheap), and an explicit on-demand LOAD instruction. The full text is
    NEVER re-shipped here; a compacted/restarted shell detects the gap from the
    index+count it cannot account for and fetches once via
    read_object('recipe').context.decisions (byte-identical to the old inline
    dump). This is the SAME decisions-by-id model RP-A uses for storage dedup.
    """
    audit_status = "none"
    if r.ocak_audit is not None:
        audit_status = r.ocak_audit.verdict
    consults = [c.specialist_id for c in r.specialist_consults]
    phase = _phase_for(r)
    # P2 superseded-decision archive: the pointer index carries ACTIVE
    # decisions only — a superseded decision stays in the honest history
    # (full read) but stops being re-surfaced every tick.
    active = [d for d in r.context.decisions
              if getattr(d, "status", "active") == "active"]
    n_dec = len(active)
    n_superseded = len(r.context.decisions) - n_dec
    # s17 a2 — BOUND the per-tick push BY CONSTRUCTION. The id+title index, the
    # load-bearing id list, and the assumptions/rejected recaps are each capped
    # to a fixed WINDOW with a cursor (via the shared _bounds.windowed helper;
    # imported lazily to avoid a tools<->fsm import cycle). count/superseded
    # still report the TRUE totals, and anything past the window is one
    # read_object('recipe') away — so this payload is O(1) in decision/
    # assumption count, never O(n) full-text.
    from ..tools._bounds import windowed
    _dec_index = windowed(
        [{"id": d.id, "title": _decision_title(d.text)} for d in active])
    _lb_ids = windowed(
        [d.id for d in active if getattr(d, "load_bearing", False)])
    _asm = windowed([a.text for a in r.context.assumptions])
    _rej = windowed([x.text for x in r.context.rejected_options])
    ctx = {
        "recap": (
            f"recipe={r.recipe_id} state={r.state} phase={phase} "
            f"outcomes={len(r.comprehension.expected_outcomes)} "
            f"steps={len(r.steps)} "
            f"(done={sum(1 for s in r.steps if s.status == 'done')}) "
            f"specialists_consulted={consults} "
            f"audit={audit_status} "
            # RP-B: carry the active-decision count IN the recap so the pointer
            # is un-missable even to a terse reader (self-detection trigger).
            f"decisions={n_dec}(see active_decisions: id+title index, "
            f"load full text on demand)"
        ),
        "phase": phase,
        "prior": {
            # RP-B: decisions are NO LONGER dumped here (see active_decisions).
            # s17 a2: assumptions/rejected are ALSO bounded now — a fixed WINDOW
            # of texts plus an explicit *_count — so a pathological recipe can't
            # reintroduce an O(n) full-text dump here. They are ≈empty on real
            # recipes; the window just makes that guarantee structural, and the
            # *_count keeps the cap honest (never a silent truncation).
            "assumptions": _asm["items"],
            "assumptions_count": _asm["count"],
            "rejected": _rej["items"],
            "rejected_count": _rej["count"],
        },
        # W8: the unacked load-bearing assumptions, batched + compaction-safe
        # (re-derived every tick so a compacted/restarted shell re-sees them).
        "pending_assumptions": pending_load_bearing_assumptions(r),
        # RP-B DECISIONS POINTER — the steady-state form of the decisions.
        "active_decisions": {
            "count": n_dec,
            "superseded": n_superseded,
            # the load-bearing ids, capped to WINDOW (full set one read away).
            "load_bearing_ids": _lb_ids["items"],
            # s17 a2: the id+title INDEX is a fixed WINDOW (<= WINDOW) with a
            # cursor — the count-first pointer, O(1) in decision count.
            "index": _dec_index["items"],
            "window": len(_dec_index["items"]),
            "cursor": _dec_index["cursor"],
            "load": (
                "These are the recipe's settled decisions, shown as an "
                "id+title INDEX only — the full text is NOT re-dumped each "
                "tick, and the index itself is a bounded window (see `cursor`: "
                "a non-null value means more active decisions exist past the "
                "window). If you already hold these decisions in your context "
                "(steady state), do nothing. If you do NOT recognise them "
                "(e.g. you were just compacted or restarted, or the count "
                "above is unfamiliar), re-ground the CHEAP way: "
                "get_recipe_digest for the map, then search_context("
                f"recipe_id='{r.recipe_id}', query=<your current topic>) for "
                "the decisions that bear on what you are doing now. Do NOT "
                "read_object the full recipe to re-learn decisions — on a "
                "large recipe that one call hydrates every decision body "
                "(oversize reads now degrade to the digest). Fetch a "
                "specific id's full text only when the digest row is not "
                "enough. Do not expect decisions re-shipped on the next tick."
            ),
        },
        "anti_patterns": _anti_patterns(r),
        # W2: the STATELESS grounding fingerprint, carried on EVERY push so the
        # recipient can echo it back as next_action/reconcile(ack_epoch=…). The
        # server recomputes + compares (no ack store; d13). A lean cron tick
        # that never carried an epoch reads as ABSENT (steady state), NOT
        # compaction — compaction is the harness's W13 job, not self-inference.
        "grounding_epoch": grounding_epoch(r),
    }
    recheck = _comprehension_recheck(r)
    if recheck:
        ctx["comprehension_recheck"] = recheck
    # W5: surface an undrained consult/steer on the push plane (only when one
    # pends, to keep the steady-state tick lean — same conditional-add pattern
    # as comprehension_recheck above).
    cp = consult_pending_view(r)
    if cp["count"]:
        ctx["consult_pending"] = cp
    # W11 (DESIGN-v6 §W11): a PARKED recipe says so on its very first tick, so a
    # fresh/resumed shell learns it from the push instead of discovering it when
    # a dispatch is refused. A FLAG + the timestamp ONLY — never the manifest:
    # RP-B made this push deliberately lean, and the manifest is a file a resume
    # reads once, not per-tick context. Conditional-add (as above): absence means
    # not suspended, which is the steady state.
    if r.suspended_at:
        ctx["suspension"] = {
            "suspended": True,
            "suspended_at": r.suspended_at,
            "note": ("this recipe is PARKED — dispatch is refused until "
                     "resume_recipe(recipe_id) clears it."),
        }
    return ctx
