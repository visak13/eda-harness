"""Deterministic plan FSM (LLD §4; DESIGN-v4 §2.2 table)."""

from ..domains import success_criteria_for
from ..schemas import Instruction, InstructionKind, Plan, PlanState
from .envelope import compose_question_envelope

K = InstructionKind

SKILL_ACCEPTANCE = "acceptance-review"

# ── DESIGN-v6 W10b: stuck → consult escalation ladder ──────────────────────
# Both thresholds are 2, and they mean DIFFERENT things because the counters do.
# `attempt` counts CRASH re-dispatch (reconcile bumps it when a worker died or
# went phantom, and nowhere else); `verify_failures` counts failed ACCEPTANCE
# cycles (see the schema note on Action.verify_failures for why one cycle
# reported through both d30 seams counts once). An action can be stuck either
# way, so either signal alone is enough to escalate.
STUCK_ATTEMPT_THRESHOLD = 2
STUCK_VERIFY_FAILURES_THRESHOLD = 2

# ── WP2 G-REWORK: the HARD re-dispatch cap ─────────────────────────────────
# At 2 the escalation ladder above ADVISES (a consult question, latched, the
# plan proceeds). At 4 the FSM stops re-dispatching the action entirely: a
# fifth mint of the same shell for the same failing work is grind, not
# progress. A frozen action is excluded from the ready frontier (single
# dispatch, wave, and batch absorption — all via the shared predicates), and
# the WAIT rationale names it FROZEN pending ask_above. Pure data judgment —
# no IO; unfreezing is a human/parent decision (reset the counters via the
# tool surface after ask_above), never the FSM's.
STUCK_HARD_CAP = 4


def _frozen(a) -> bool:
    """WP2 G-REWORK — is action `a` past the hard re-dispatch cap? PURE."""
    return (getattr(a, "attempt", 0) >= STUCK_HARD_CAP
            or getattr(a, "verify_failures", 0) >= STUCK_HARD_CAP)

# (The W10b consult-tier lookup — CONSULT_ROLE + `_consult_model`, which read
# roles.MODEL_TIERS — was deleted in the 2026-08-12 dead-surface retirement
# along with the tier table itself and the consult shell role. The escalation
# instruction below no longer names a model: the advisory carries the question,
# and how a raised question is answered is the parent's call.)


def _ready_actions(p: Plan, live_action_ids: frozenset[str] = frozenset()):
    """The SINGLE source of truth for readiness: every action that is
    pending with ALL of its depends_on already done/skipped, in plan order.
    Both the single-action dispatch (_first_ready_action) and the
    all-ready-wave surface (plan_ready_wave) are built on this ONE predicate
    so a second, divergent readiness rule can never drift in.

    `live_action_ids` (s27/C7) — action_ids the CALLER has confirmed already
    have a LIVE shell. They are excluded from readiness, so the FSM never
    instructs a dispatch for work a live worker is already doing.

    Why liveness and not the status string (d78): the FSM's status oracle
    ALREADY excludes `in_progress` (this predicate gates on `pending`). The
    state that shipped the s26 double-dispatch is `pending` + LIVE session —
    reachable because a spawn performed OUTSIDE the FSM's dispatch instruction
    (an explicit `pool_spawn_worker`, as crash recovery prompts) leaves the
    status at `pending` while a real shell runs. `pending` is therefore not a
    truthful proxy for "nothing is running this"; only the pool is.

    The FSM stays PURE (principle 6): it does no IO and holds no pool client.
    Liveness enters as an INPUT the tool layer computed, never as a probe from
    inside here. An empty set (the default) means "caller asserts nothing is
    known to be live", which is the pre-s27 behaviour every existing caller
    relied on."""
    done = {a.action_id for a in p.actions if a.status in ("done", "skipped")}
    # WP2 G-REWORK: a frozen action (past STUCK_HARD_CAP) leaves the ready
    # frontier — both dispatch surfaces inherit the exclusion from this one
    # predicate, exactly like the liveness rule above.
    return [a for a in p.actions
            if a.status == "pending" and set(a.depends_on) <= done
            and a.action_id not in live_action_ids
            # F35 R3a#4: a member whose BATCH HEAD shell is live is owned
            # work — the head executes it (or legally re-executes after a
            # reopen); dispatching a rival onto the member handle would
            # double-run it.
            and (getattr(a, "batch_owner", None) not in live_action_ids
                 or not getattr(a, "batch_owner", None))
            and not _frozen(a)]


def _first_ready_action(p: Plan, live_action_ids: frozenset[str] = frozenset()):
    return next(iter(_ready_actions(p, live_action_ids)), None)


def _begin_verify_cycle(a) -> None:
    """DESIGN-v6 W10b — a dispatch OPENS a fresh acceptance cycle for `a`.

    This is the idempotence key for `Action.verify_failures`, and it is here
    rather than keyed on `attempt` for a reason worth stating: `attempt` counts
    CRASH re-dispatch only (reconcile bumps it when a worker died or went
    phantom). It does NOT advance on a verify failure, so keying on
    (action_id, attempt) would silently swallow the SECOND genuine failed cycle —
    the exact cycle the escalation ladder exists to catch. Stamping in_progress
    is the one event that means "this action is being executed afresh", so that
    is the boundary. Both dispatch paths (single + ready-wave) call this."""
    a.verify_failure_counted = False


def _batch_members(p: Plan, head,
                   live_action_ids: frozenset[str] = frozenset()) -> list:
    """DESIGN-v7 1.4 Stage A — the DISPATCH UNIT for a ready `head` action.

    An unbatched head (no `batch_group`, the pre-v7 default) dispatches alone:
    the unit is `[head]`, byte-identical to the old behaviour. A batched head
    pulls in every OTHER pending action sharing its `batch_group` whose deps
    are satisfied, in declared (plan) order — and "satisfied" here means each
    dep is either already done/skipped OR an EARLIER member of this same unit.
    That second clause is the whole point: the dominant batch shape is a small
    SERIAL chain (a2 depends_on a1, a3 on a2 …), whose later members are NOT
    in the ready frontier — their deps close only as the ONE worker shell
    executes the members in order. Requiring the in-unit dep to be declared
    EARLIER keeps the executed order equal to the declared order by
    construction (a member depending on a LATER sibling is simply left out,
    still pending, and dispatches once its dep really closes).

    `live_action_ids` is threaded exactly as `_ready_actions` threads it
    (s27/C7): a member the caller confirmed has a LIVE shell — e.g. from an
    earlier solo dispatch of that action — is never absorbed into the unit.

    PURE (no IO — principle 6). The CALLER stamps the returned members
    in_progress; this only selects them."""
    if not head.batch_group:
        return [head]
    done = {a.action_id for a in p.actions if a.status in ("done", "skipped")}
    members = [head]
    in_unit = {head.action_id}
    for a in p.actions:
        if a.action_id == head.action_id:
            continue
        if (a.batch_group != head.batch_group or a.status != "pending"
                or a.action_id in live_action_ids or _frozen(a)):
            # WP2 G-REWORK: a frozen member is never absorbed into a unit —
            # the batch would re-execute exactly the work the cap froze.
            continue
        if set(a.depends_on) <= done | in_unit:
            members.append(a)
            in_unit.add(a.action_id)
    return members


def _dispatch_instruction(a, members: list | None = None) -> Instruction:
    """Build the DISPATCH_ACTION Instruction for one ready action. Shared
    by the single-action pacer and the wave surface so both emit the
    IDENTICAL descriptor shape (phase 7 / MULTI-SPEC).

    DESIGN-v7 1.4: when `a` heads a BATCH (`a.batch_group` set), the head
    instruction additionally carries `batch_action_ids` — the full dispatch
    unit in declared order, head first — so the planner spawns ONE shell
    (`pool_spawn_worker(..., action_ids=<batch_action_ids>)`) that executes
    every member. An unbatched action emits the pre-v7 descriptor shape
    unchanged (no new key — consumers that predate batching never see it)."""
    args = {
        "action_id": a.action_id,
        # phase 7 / MULTI-SPEC (2026-06-03): the descriptors this
        # action needs resolved. `specializations` is the canonical
        # list (N may be >1 for a cross-stack action); the singular
        # `specialization` is surfaced as the first element for any
        # legacy consumer of this instruction.
        "specializations": a.effective_specializations(),
        "specialization": next(
            iter(a.effective_specializations()), None),
    }
    if a.batch_group:
        args["batch_group"] = a.batch_group
        args["batch_action_ids"] = [m.action_id for m in (members or [a])]
    return Instruction(
        kind=K.DISPATCH_ACTION,
        args=args,
        rationale=a.description,
    )


def plan_ready_wave(p: Plan,
                    live_action_ids: frozenset[str] = frozenset(),
                    ) -> list[Instruction]:
    """DESIGN-v6 all-ready-wave surface: return a DISPATCH_ACTION for EVERY
    action currently ready (pending + all depends_on satisfied), stamping
    each one `in_progress` so a SINGLE plan save persists the whole wave
    atomically (the tool layer does the one save). Lets a planner fire the
    entire ready frontier in one turn instead of one action per tick.

    Invariants (all inherited from the shared `_ready_actions` predicate,
    NOT a second rule):
    - never returns an action with unmet deps (predicate gates on it);
    - never returns an already-in_progress/done action, so the W2
      duplicate-dispatch guard and depends_on gating stay authoritative;
    - never returns an action the caller listed in `live_action_ids` (a live
      shell is already doing it) — see `_ready_actions` for why liveness, not
      the status string, is the oracle;
    - stamping the frontier in_progress cannot make any OTHER pending
      action newly ready (a dep is only satisfied by done/skipped, never
      in_progress), so the returned list IS exactly the current frontier.

    DESIGN-v7 1.4: a BATCH GROUP is ONE wave slot. When a frontier action
    heads a batch, the whole dispatch unit (`_batch_members`) is stamped
    in_progress in this same atomic wave, but the wave returns ONE
    instruction for it — the head, carrying `batch_action_ids` — because the
    unit costs the pool ONE shell. Two frontier actions sharing a group
    collapse into one slot (the first-declared one heads it); a batch member
    absorbed into a unit is never re-surfaced as its own slot.

    Pure + deterministic (no IO, no LLM — principle 6). Only fires while the
    plan is DISPATCHING; a DRAFTED plan with actions is advanced to
    DISPATCHING first, mirroring plan_next_action. Any other state → []."""
    if p.state == PlanState.DRAFTED and p.actions:
        p.state = PlanState.DISPATCHING
    if p.state != PlanState.DISPATCHING:
        return []
    # Materialise the frontier BEFORE mutating any status (the list
    # comprehension is fully evaluated here), then stamp — so the readiness
    # set is computed against the pre-wave state exactly once.
    ready = _ready_actions(p, live_action_ids)
    instrs = []
    dispatched: set[str] = set()
    for a in ready:
        if a.action_id in dispatched:
            continue   # absorbed into an earlier slot's batch unit
        members = _batch_members(p, a, live_action_ids)
        for mem in members:
            mem.status = "in_progress"  # tool-forced stamp, mirrors single dispatch
            _begin_verify_cycle(mem)    # W10b: the dispatch IS the cycle boundary
            # F44#6 — mirror the single-dispatch stamp (F35 R3a#4): every
            # member records the owning head so liveness recovery can probe
            # the head shell even after the head action itself is terminal.
            if len(members) > 1:
                mem.batch_owner = a.action_id
            dispatched.add(mem.action_id)
        instrs.append(_dispatch_instruction(a, members))
    return instrs


def bump_verify_failure(a) -> bool:
    """Count ONE failed acceptance cycle for action `a`. Returns True when this
    call actually incremented the counter, False when the cycle was already
    counted. IDEMPOTENT PER CYCLE — that is the whole point of it existing.

    Under d30 a single failed acceptance cycle is REPORTED at two independent
    seams: the WORKER runs the gate in its own shell and records
    `status="failed"`, and the REVIEWER independently re-runs it in a fresh shell
    and records a failing action verdict. Both seams call this. Whichever reports
    first counts the cycle; the other is a no-op. Without that, the dual gate —
    which is the HEALTHY path, not a stuck one — would bump twice per cycle and
    the escalation ladder would fire at half its stated threshold, convening an
    Opus consult every time a worker failed once and a reviewer agreed.

    The latch is cleared at the DISPATCH boundary (`_begin_verify_cycle`), so the
    next execution of this action can be counted again. PURE (no IO)."""
    if a.verify_failure_counted:
        return False
    a.verify_failures += 1
    a.verify_failure_counted = True
    return True


def stuck_signals(a, parked: bool = False) -> list[str]:
    """The stuck signals action `a` currently shows, in the design's order.
    Empty when it is not stuck. PURE — no IO, no clock (principle 6)."""
    out: list[str] = []
    if getattr(a, "attempt", 0) >= STUCK_ATTEMPT_THRESHOLD:
        out.append(f"re-dispatch churn: attempt={a.attempt} "
                   f"(>= {STUCK_ATTEMPT_THRESHOLD}); a worker died or went "
                   "phantom on this action more than once")
    vf = getattr(a, "verify_failures", 0)
    if vf >= STUCK_VERIFY_FAILURES_THRESHOLD:
        out.append(f"failed acceptance cycles: verify_failures={vf} "
                   f"(>= {STUCK_VERIFY_FAILURES_THRESHOLD}); the acceptance "
                   "gate has been run and has failed on distinct cycles")
    if parked:
        out.append("a worker is parked on an unanswered question past twice "
                   "its wait_hint")
    return out


def stuck_actions(p: Plan, parked_action_ids: frozenset[str] = frozenset()):
    """Every (action, signals) pair currently showing a stuck signal, in plan
    order. `parked_action_ids` is a caller-computed INPUT — the FSM holds no
    clock and reads no broker, exactly as `live_action_ids` is threaded in
    (s27/C7). PURE."""
    out = []
    for a in p.actions:
        if a.status in ("done", "skipped"):
            continue
        sig = stuck_signals(a, a.action_id in parked_action_ids)
        if sig:
            out.append((a, sig))
    return out


def compose_consult_question(p: Plan, a, signals: list[str],
                             worklog_tail: list[str] | None = None) -> str:
    """Compose the consult question for a stuck action IN CODE, from the
    action's acceptance diff + the tail of the plan's worklog.

    AUTO-COMPOSED AND ACTION-SPECIFIC BY CONSTRUCTION: it names this plan, this
    action, this action's own description, its own acceptance diff, and the
    signals that actually fired. There is no template branch that can produce a
    generic question, and none that can produce an empty one — the envelope's
    `acceptance_diff` always emits the EXPECTED/ACTUAL lines even when both are
    unrecorded.

    DESIGN-v7 2.1: now a THIN CALLER of `envelope.compose_question_envelope`
    (which generalizes the same ingredients to every upward question). The
    consult TEXT is unchanged — the envelope supplies the goal / doing /
    acceptance-diff fields and this function renders them into the pinned
    stuck-consult prose.

    PURE: `worklog_tail` is passed in (already-read lines), never read here."""
    env = compose_question_envelope(plan=p, action=a)
    tail = [t for t in (worklog_tail or []) if t.strip()]
    parts = [
        f"A stuck action needs a second opinion: plan {p.plan_id!r}, action "
        f"{a.action_id!r} (status {a.status!r}).",
        "",
        f"GOAL OF THE PLAN: {env.get('goal', p.goal)}",
        "",
        f"WHAT THE ACTION WAS ASKED TO DO: {env.get('doing', a.description)}",
        "",
        "ACCEPTANCE DIFF:",
        env["acceptance_diff"],
        "",
        "WHY THE FSM THINKS IT IS STUCK:",
        *(f"  - {s}" for s in signals),
    ]
    if tail:
        parts += ["", "RECENT WORKLOG (tail):", *(f"  {t}" for t in tail)]
    parts += [
        "",
        "Diagnose why this action is not converging and recommend a concrete "
        "next move: fix the deliverable, fix the acceptance criteria, split "
        "the action, or abandon it. Say which, and why.",
    ]
    return "\n".join(parts)


def _escalation_key(a, parked: bool) -> list:
    """The latch key: the exact signal state at emission. Re-emits only when a
    signal ADVANCES (another crash, another failed cycle, or a newly-parked
    worker) — never on an unchanged tick."""
    return [getattr(a, "attempt", 0), getattr(a, "verify_failures", 0),
            bool(parked)]


def plan_escalation_instruction(
        p: Plan,
        parked_action_ids: frozenset[str] = frozenset(),
        worklog_tails: dict[str, list[str]] | None = None,
) -> Instruction | None:
    """Emit ESCALATE_CONSULT at most ONCE per stuck-signal crossing, or None.

    LATCHED, and this is now the only latched advisory left (W9's direction-review
    checkpoint, the other one, was removed in d128/d132):
    an un-latched instruction returned ahead of the dispatch would re-emit every
    tick and never hand back DISPATCH_ACTION, turning an advisory checkpoint into
    a mechanism that BLOCKS the build. d76 forbids the FSM from being one. Latched,
    the escalation costs exactly one tick and the plan proceeds; if nothing changes,
    the next tick dispatches or waits as it otherwise would.

    ADVISORY, NOT AN ACTION. The instruction TELLS the planner to raise the
    auto-composed question via ask_above. This function convenes nothing,
    spawns nothing, and does no IO — it returns a description of a call the
    planner may ignore.

    Mutates only the latch (`p.escalation_emitted`), which is a bookkeeping
    mutation of the same class as the `p.state` advance its caller already makes.
    The caller persists it.

    PURE besides that: `parked_action_ids` and `worklog_tails` are caller-computed
    inputs (the FSM holds no clock and reads no worklog)."""
    stuck = stuck_actions(p, parked_action_ids)
    if not stuck:
        return None
    emitted = p.escalation_emitted or {}
    for a, signals in stuck:
        key = _escalation_key(a, a.action_id in parked_action_ids)
        if emitted.get(a.action_id) == key:
            continue    # already escalated at this exact signal state
        question = compose_consult_question(
            p, a, signals, (worklog_tails or {}).get(a.action_id))
        emitted = dict(emitted)
        emitted[a.action_id] = key
        p.escalation_emitted = emitted
        return Instruction(
            kind=K.ESCALATE_CONSULT,
            args={
                "action_id": a.action_id,
                "recipe_id": p.recipe_id,
                "question": question,
                "signals": signals,
            },
            rationale=(
                f"ESCALATE — action {a.action_id!r} is stuck "
                f"({len(signals)} signal(s)). The auto-composed question is in "
                "args.question; raise it with ask_above (decision-class "
                "questions go to the neuron, mechanics to your parent). This "
                "is ADVICE: it is emitted once per signal crossing, it holds "
                "no dispatch, and the FSM escalates nothing itself. Record "
                "what you do with the answer via record_context. "
                "NOTE: the spawned-consult verb this instruction used to name "
                "was retired by operator ruling on 2026-07-25 (see "
                "tools/roles.py `_OPERATOR_RETIRED`)."
            ),
        )
    return None


def plan_verify_leg_instruction(p: Plan) -> Instruction | None:
    """v7 P4.2 — emit DISPATCH_VERIFY_LEG at most once per fixed_inline
    verdict, or None. The reviewer fixed something in-session and STATED it
    as data (`record_branch_verdict(fixed_inline=true)`); its own fix is the
    one artifact in the batch nothing independently re-ran (d74). The remedy
    is one cheap verify-only worker re-running the recorded acceptance
    commands verbatim — transcription, not judgment, so the regress stops
    there.

    LATCHED on `p.verify_leg_emitted` keyed by the verdict's `at` stamp — a
    NEWER verdict on the same action re-arms; an unchanged tick never
    re-emits (the exact escalation-ladder discipline above: an unlatched
    advisory would hold the dispatch, and d76 forbids that). Mutates only
    the latch; the caller persists. ADVISORY: this dispatches nothing."""
    emitted = p.verify_leg_emitted or {}
    for a in p.actions:
        rv = a.review_verdict or {}
        if not rv.get("fixed_inline"):
            continue
        key = rv.get("at") or "unstamped"
        if emitted.get(a.action_id) == key:
            continue
        emitted = dict(emitted)
        emitted[a.action_id] = key
        p.verify_leg_emitted = emitted
        return Instruction(
            kind=K.DISPATCH_VERIFY_LEG,
            args={
                "action_id": a.action_id,
                "acceptance_kind": a.acceptance.kind,
                "expected": a.acceptance.expected,
            },
            rationale=(
                f"DISPATCH VERIFY LEG — the reviewer fixed {a.action_id!r} "
                "in-session (fixed_inline=true), and its own fix has had no "
                "independent re-run (d74). Author ONE small "
                "task_class='verify' action whose description lists "
                f"{a.action_id!r}'s acceptance.verify commands VERBATIM and "
                "instructs get_guide('verify-only'), then dispatch it as a "
                "normal worker (pool_spawn_worker(task_class='verify', "
                "allow_candidate_tier=true)). It re-runs the commands and "
                "transcribes raw output — it judges nothing and fixes "
                "nothing, so no further review of the review is needed. "
                "This is ADVICE (d76): emitted once per verdict, holds no "
                "dispatch."
            ),
        )
    return None


def plan_pacing_state(p: Plan, *, output_stale: bool = False,
                      awaiting_user: bool = False) -> str:
    """DESIGN-v6 W7 item 1 — classify a plan's current PACING state from
    inputs already in the record. Pure + deterministic (no clock, no IO):
    the caller derives `output_stale` (from the last worklog ts vs now) and
    `awaiting_user`, then looks up the (minutes, reason) via
    state_machines.pacing_hint(). Precedence: awaiting_user > verify_pending >
    child_in_progress (recent|stale) > idle_or_done."""
    if awaiting_user:
        return "awaiting_user"
    statuses = [a.status for a in p.actions]
    if any(s == "verify" for s in statuses):
        return "verify_pending"
    if any(s == "in_progress" for s in statuses):
        return ("child_in_progress_stale_output" if output_stale
                else "child_in_progress_recent_output")
    return "idle_or_done"


def handle_pacing_state(liveness: str, action_status: str | None,
                        output_stale: bool = False) -> str:
    """DESIGN-v6 W7 item 1 — pacing for a single child HANDLE (the status_ping
    surface), from its pool liveness + the action's status + output staleness.
    A dead/unknown child is idle from the pacer's view (reap/reconcile own
    recovery, not the pacing hint). Pure + deterministic."""
    if action_status == "verify":
        return "verify_pending"
    if liveness == "alive":
        return ("child_in_progress_stale_output" if output_stale
                else "child_in_progress_recent_output")
    return "idle_or_done"


def plan_next_action(p: Plan,
                     live_action_ids: frozenset[str] = frozenset(),
                     parked_action_ids: frozenset[str] = frozenset(),
                     worklog_tails: dict[str, list[str]] | None = None,
                     ) -> Instruction:
    """`live_action_ids` (s27/C7, d78): action_ids the CALLER confirmed have a
    LIVE shell. Such an action is never dispatched; it falls through to the
    WAIT this function already computes. The FSM is an ADVISOR (d76) — it may
    be ignored, but it may not state something false about the world, and
    "dispatch this" about work a live worker is already doing is false.

    `parked_action_ids` + `worklog_tails` (W10b): caller-computed inputs for the
    escalation ladder, threaded exactly as `live_action_ids` is. Both default to
    empty, so every pre-W10b caller gets byte-identical behaviour on a plan whose
    actions carry the default counters."""
    # Team-architecture-restoration Phase 1 (2026-05-21):
    # The plan-level self-audit gate is REMOVED for the same reason as
    # the recipe-level one — self-audit by the same shell that built
    # the plan is theatre. Phase 5 restores `/critic` (separate shell)
    # which IS the right place for plan-level OCAK audit per the
    # original framework-ocak.md.
    if p.state == PlanState.DRAFTED:
        if not p.actions:
            return Instruction(
                kind=K.REPLAN, args={},
                rationale="draft has no actions; author them",
            )
        p.state = PlanState.DISPATCHING
        return plan_next_action(p, live_action_ids, parked_action_ids,
                                worklog_tails)

    if p.state == PlanState.DISPATCHING:
        # W10b escalation ladder, ahead of the dispatch selection: an action
        # that has already churned or failed acceptance twice should get a
        # second opinion BEFORE it is blindly re-dispatched a third time. This
        # is latched (once per signal crossing) and ADVISORY — the very next
        # tick falls through to the dispatch below, so it can never wedge the
        # plan. On a plan with default counters and no parked worker it is
        # `None` and this branch is a no-op.
        esc = plan_escalation_instruction(p, parked_action_ids, worklog_tails)
        if esc is not None:
            return esc
        # v7 P4.2, same latched-advisory discipline: a fixed_inline verdict
        # advises ONE verify-only leg before the next dispatch is selected.
        vleg = plan_verify_leg_instruction(p)
        if vleg is not None:
            return vleg
        nxt = _first_ready_action(p, live_action_ids)
        if nxt is not None:
            # Mirror recipe_fsm.py: stamp in_progress AT dispatch so the
            # next next_action no longer re-selects this action — it
            # falls through to the WAIT branch below (which next_action
            # enriches with the heartbeat). Tool-forced, not inferred
            # (DESIGN-v5). The tool persists this mutation.
            #
            # DESIGN-v7 1.4: the dispatch unit is `_batch_members(p, nxt)` —
            # for an unbatched action that is exactly [nxt] (pre-v7
            # behaviour, byte-identical); for a batch head it is the whole
            # group chain, ALL stamped here so the single persistence seam in
            # the tool saves the unit atomically. The head instruction
            # carries `batch_action_ids`.
            members = _batch_members(p, nxt, live_action_ids)
            for mem in members:
                mem.status = "in_progress"
                _begin_verify_cycle(mem)  # W10b: dispatch IS the cycle boundary
                # F35 R3a#4: every member records WHOSE shell owns it (the
                # head's) so suppression can see through the head handle.
                if len(members) > 1:
                    mem.batch_owner = nxt.action_id
            return _dispatch_instruction(nxt, members)
        # F35 R3a#2 (2026-08-18): a FAILED action with a pending dependent
        # was a stable deadlock — failed is never re-selected, the
        # dependent never becomes ready, and the plan WAITed forever on
        # "actions in flight". At the point where nothing is dispatchable,
        # reopen the failed blockers to pending with a counted cycle: the
        # frontier re-dispatches rework, and G-REWORK's hard cap turns a
        # grind into a FROZEN + ask_above escalation instead of silence.
        # A failed action with NO pending dependent keeps the old honest
        # semantics (the plan terminates partial).
        _failed_ids = {a.action_id for a in p.actions
                       if a.status == "failed"}
        blocking_failed = sorted({
            d for a in p.actions if a.status == "pending"
            for d in a.depends_on if d in _failed_ids
        })
        if blocking_failed:
            for a in p.actions:
                if a.action_id in blocking_failed:
                    a.status = "pending"
                    bump_verify_failure(a)
            return Instruction(
                kind=K.WAIT, args={"reopened_action_ids": blocking_failed},
                rationale=(
                    f"G-DEPS: reopened failed {blocking_failed} to pending "
                    "— each blocks a pending dependent, and a failed "
                    "prerequisite never re-dispatches on its own. Rework "
                    "dispatches on the next tick; a repeat grind freezes "
                    "at the G-REWORK cap into an ask_above. To abandon "
                    "the line instead, skip the dependents (G-SKIP rules "
                    "apply) or close the plan honestly partial."
                ),
            )
        # `verify` is non-terminal (2026-05-28): an action parked in
        # verify is NOT done — the plan must keep waiting on it (the gate
        # hasn't confirmed), not advance to acceptance-review as if it
        # completed. This is what makes the verify state honest at the
        # FSM level (fixes O4: a verify action ≠ a done one).
        non_terminal = [
            a for a in p.actions
            if a.status in ("pending", "in_progress", "verify", "needs_review")
        ]
        if non_terminal:
            verifying = [a.action_id for a in non_terminal
                         if a.status == "verify"]
            rationale = "actions in flight; awaiting results"
            if verifying:
                rationale = (
                    f"actions in flight; {len(verifying)} parked in "
                    f"`verify` (gate not yet confirmed): {verifying}"
                )
            # s27/C7: name the actions suppressed for liveness, so a planner
            # reading the WAIT can see WHY an otherwise-ready action was not
            # dispatched (it has a live shell) rather than inferring a stall.
            suppressed = [a.action_id for a in non_terminal
                          if a.action_id in live_action_ids]
            if suppressed:
                rationale += (
                    f"; {len(suppressed)} not dispatched because a LIVE "
                    f"worker already holds them: {suppressed}"
                )
            # WP2 G-REWORK: name the frozen actions so the WAIT reads as
            # "held by policy", never as an unexplained stall. A frozen
            # action will NOT be re-dispatched by the FSM; unfreezing is an
            # ask_above decision.
            frozen = [a.action_id for a in p.actions
                      if a.status == "pending" and _frozen(a)]
            if frozen:
                rationale += (
                    f"; {len(frozen)} FROZEN pending ask_above "
                    f"(G-REWORK: attempt/verify_failures >= "
                    f"{STUCK_HARD_CAP}): {frozen} — the FSM will not "
                    "re-dispatch them; raise ask_above for a human/parent "
                    "decision (rework differently, split, or abandon)"
                )
            return Instruction(
                kind=K.WAIT, args={}, rationale=rationale,
            )
        # R1 F#1 (2026-08-18): a recorded FAIL verdict blocks success. An
        # action whose CURRENT review_verdict says passed=False is not
        # resolved by its own `done` status — the reviewer closes its leg
        # `done` after stamping fail (reviewer card), so all-terminal is
        # reachable over a known defect. At the success boundary the FSM
        # reopens those actions to `pending`: the normal frontier re-
        # dispatches them, a rework verdict overwrites the stamp, and
        # G-REWORK's hard cap (verify_failures was already bumped at
        # record time) freezes a grind into an ask_above. The verdict
        # TOOL still never flips status (d30) — this is the FSM's own
        # legal transition, like stamping in_progress at dispatch.
        # F35 R3b#9 note: `skipped` counts too — the domain success rules
        # treat done/skipped alike, so a fail-verdicted skipped action was
        # the remaining hole in the R1 fix. (A user-authorized G-SKIP records its
        # own worklog override; re-skipping after the reopen goes through
        # that same user gate again, so the user's word still outranks the
        # reviewer's — but never silently.)
        failed_verdicts = [
            a for a in p.actions
            if a.status in ("done", "skipped")
            and (a.review_verdict or {}).get("passed") is False
        ]
        if failed_verdicts:
            for a in failed_verdicts:
                a.status = "pending"
                # Count the cycle even when no worker/reviewer seam did —
                # rework that never clears the stamp must walk into the
                # G-REWORK hard cap (frozen → ask_above), not loop forever.
                bump_verify_failure(a)
            ids = [a.action_id for a in failed_verdicts]
            return Instruction(
                kind=K.WAIT, args={"reopened_action_ids": ids},
                rationale=(
                    f"G-VERDICT: reopened {ids} to pending — each carries "
                    "a reviewer verdict with passed=false, and a plan "
                    "cannot close succeeded over a recorded FAIL. Rework "
                    "will be re-dispatched on the next tick; a passing "
                    "re-review overwrites the stamp. If the verdict is "
                    "wrong or the rework path is unclear, raise ask_above."
                ),
            )
        p.state = PlanState.ACCEPTANCE_REVIEW
        return plan_next_action(p, live_action_ids, parked_action_ids,
                                worklog_tails)

    if p.state == PlanState.ACCEPTANCE_REVIEW:
        ts = success_criteria_for(p.domain)(p)
        if ts is None:
            return Instruction(
                kind=K.INVOKE_SKILL, args={"skill": SKILL_ACCEPTANCE},
                rationale="resolve acceptance before terminal status",
            )
        p.terminal_status = ts
        p.state = PlanState.TERMINAL
        return plan_next_action(p)

    return Instruction(
        kind=K.DONE,
        args={"terminal_status": p.terminal_status},
        rationale=f"plan terminal: {p.terminal_status}",
    )
