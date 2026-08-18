"""Instruction + state enums (LLD §2.1)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RecipeState(StrEnum):
    CREATED = "created"
    COMPREHENDING = "comprehending"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    CLOSED = "closed"


class PlanState(StrEnum):
    DRAFTED = "drafted"
    DISPATCHING = "dispatching"
    ACCEPTANCE_REVIEW = "acceptance_review"
    TERMINAL = "terminal"


class InstructionKind(StrEnum):
    # LIVE: plan_fsm emits this in ACCEPTANCE_REVIEW whenever the domain declares
    # no success criteria — the escape hatch is "ask the model", not "hard-code a
    # rule". DO NOT REMOVE IT: deleting it breaks the path that resolves a plan's
    # terminal status. (It is NOT an MCP tool verb and must never be added to
    # roles.py — build_mcp fails CLOSED on drift and would take the server down
    # for every shell.)
    INVOKE_SKILL = "invoke_skill"
    ASK_USER = "ask_user"
    # v5 P1 — OCAK forced by the FSM (one branch/outcome/step at a time):
    ANSWER_BRANCH = "answer_branch"
    DECLARE_OUTCOME = "declare_outcome"
    DECLARE_STEP = "declare_step"
    # (RECORD_STEP — declared but emitted by NO state machine, audited s29/a1 +
    # s29/a3b — was DELETED in the 2026-08-12 dead-surface sweep along with the
    # deregistered RecordStep tool class. Unlike INVOKE_SKILL above, nothing
    # ever constructed an Instruction of that kind.)
    SPAWN_PLANNER = "spawn_planner"
    # F31 (2026-08-18, owner ruling): the FINAL ACCEPTANCE PASS is explicit
    # in the FSM — emitted when every outcome is met but no 'pass'
    # acceptance_verdict is recorded yet. The neuron obeys it with
    # dispatch_acceptance(recipe_id=…), which spawns the advisor-seat
    # ACCEPTOR in its own shell; DONE follows a recorded 'pass'.
    DISPATCH_ACCEPTANCE = "dispatch_acceptance"
    RUN_INLINE = "run_inline"
    DISPATCH_ACTION = "dispatch_action"
    RECORD_RESULT = "record_result"
    REPLAN = "replan"
    ASK_NEURON = "ask_neuron"
    WAIT = "wait"
    DONE = "done"
    # post-HITL sweep 2026-05-20 — helper-not-enforcer comprehension flow:
    REASON = "reason"  # free reasoning phase (replaces forced 7-branch loop)
    CONSULT_SPECIALIST = "consult_specialist"  # agent named a specific gap
    RUN_AUDIT = "run_audit"  # before declaring outcome / before record_plan
    AWAIT_USER = "await_user"  # agent or audit surfaced ambiguity
    # team-architecture restoration Phase 2 (2026-05-21) —
    # bi-directional comm substrate; messages flow via next_action:
    HANDLE_MESSAGES = "handle_messages"
    # Phase 7 (2026-05-21) — crash recovery: a child died before
    # terminal and auto-re-dispatch was already spent; surface to the
    # parent (neuron → user; planner → neuron).
    CHILD_CRASHED = "child_crashed"
    # (DIRECTION_REVIEW_DUE was W9's neuron-facing direction-review checkpoint.
    # REMOVED — d128/d132: the reviewer is the PLANNER's subagent and is never
    # available to the neuron, so an instruction ordering the neuron to branch
    # one asserted a capability it does not hold. The neuron's direction
    # integrity is comprehension_recheck -> curiosity -> signoff.)
    #
    # DESIGN-v6 W10b (2026-07-10) — the stuck->consult escalation ladder.
    # Emitted to the PLANNER when an action shows a stuck signal (re-dispatch
    # churn, repeated acceptance failures, or a worker parked on a question
    # past its patience window). Carries an AUTO-COMPOSED question and the
    # consult tier (opus). ADVISORY: the FSM
    # advises and never convenes anything itself (d76). Latched to fire once
    # per stuck-signal crossing so it can never hold a dispatch.
    ESCALATE_CONSULT = "escalate_consult"
    # DESIGN-v7 1.5.3 (2026-07-12) — the resume BACKSTOP advisory. Emitted to
    # the NEURON by `reconcile` (recipe handle) when a plan's planner is
    # PARKED (Plan.parked set / pool liveness "parked") and either its inbox
    # holds messages newer than the park or the park has aged past the
    # threshold with non-terminal actions outstanding. The pool's resume
    # watchdog is the PRIMARY wake (seconds); this instruction exists for
    # when the watchdog is down. ADVISORY, d76: it tells the neuron to call
    # pool_resume_planner(handle) and enforces nothing; LATCHED (once per
    # signal state, mirroring the W10b escalation-ladder latch) so it can
    # never spam the tick.
    RESUME_PLANNER = "resume_planner"
    # DESIGN-v7 P4.2 (2026-07-12) — the reviewer's-own-fix re-check. Emitted
    # to the PLANNER when an action's review_verdict carries
    # fixed_inline=true: author + dispatch ONE cheap task_class="verify"
    # worker that re-runs the action's recorded acceptance commands verbatim
    # and transcribes raw output (guide: verify-only.md — judges nothing,
    # fixes nothing), closing the d74 gap without reviewer-reviews-reviewer
    # regress. ADVISORY (d76) and LATCHED per verdict stamp
    # (Plan.verify_leg_emitted) so it costs one tick, never holds a dispatch.
    DISPATCH_VERIFY_LEG = "dispatch_verify_leg"


class Instruction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: InstructionKind
    args: dict = Field(default_factory=dict)
    rationale: str = Field(min_length=1)  # always populated — never a bare step
    # v5 P2/P3 — pushed every call so a compacted session is re-grounded.
    # {recap, prior, anti_patterns}. The LLM never fetches this; the tool
    # injects it.
    context: dict = Field(default_factory=dict)
    updates_suggested: list[dict] = Field(default_factory=list)
