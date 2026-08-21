"""Recipe schema (LLD §2.2; DESIGN-v4 §2.1).

The `_clear_test_invariants` validator is the P4/P5 guard: a half-built
recipe cannot advance past the state whose required context is missing, so
a fresh LLM resuming from `recipe.json` alone is never under-informed.
"""

from datetime import datetime
from typing import Literal

from pydantic import (BaseModel, ConfigDict, Field, model_serializer,
                      model_validator)

from .instruction import RecipeState


class Branch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    question: str
    status: Literal["open", "needs_user_input", "resolved", "deferred"]
    verdict: str | None = None
    rationale: str = ""


class Outcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    verification: str
    met: bool = False
    # 2026-05-24: evidence that the outcome was actually verified (a
    # reviewer-fork verdict + user confirmation). `met=True` is only
    # legitimate WITH evidence — close_recipe 'succeeded' requires it.
    met_evidence: str | None = None
    # WP1 G-OUTCOME (2026-08-12): a USER-waived outcome. `waiver_ref` is the
    # answer_id of a recorded `user_gate_answer` event (record_user_answer
    # gate mode) — a RECORDED ARTIFACT, never a free-text quote param. Both
    # emission-gated below (omitted at their defaults) so a legacy recipe
    # round-trips byte-identically.
    waived: bool = False
    waiver_ref: str | None = None
    # QoL Phase 3 (2026-08-21, F8-class): the FORM the outcome must take.
    # Before this, artifact form lived ONLY in prose, which is how an
    # "interactive UI" ask shipped as an essay ABOUT the UI. Optional +
    # emission-gated so every legacy outcome round-trips byte-identically.
    # Vocabulary (kept open as str for forward-compat; the INPUT model
    # enums it): code | interactive_ui | document | image | 3d_asset |
    # data | service | mixed | runnable_app | pipeline.
    deliverable: str | None = None
    # Corpus audit 2026-08-21: the operator's OWN acceptance path, cold and
    # end to end — the axis every green-but-wrong close failed on. The
    # acceptor walks it before any pass. Optional + emission-gated.
    user_path: str | None = None

    @model_serializer(mode="wrap")
    def _ser_waiver_gate(self, handler):
        # WP1 emission gate: omit the waiver pair at their defaults so an
        # unwaived (legacy) outcome serializes byte-shape-identical to the
        # pre-WP1 schema (RP-A discipline).
        data = handler(self)
        if not data.get("waived"):
            data.pop("waived", None)
        if data.get("waiver_ref") is None:
            data.pop("waiver_ref", None)
        if data.get("deliverable") is None:
            data.pop("deliverable", None)
        if data.get("user_path") is None:
            data.pop("user_path", None)
        return data


class Constraint(BaseModel):
    """W1 (DESIGN-v6 §W1) executable constraint — the checkable form of a
    decision/ban, consumed by the W2/W9 guards. A recorded constraint turns
    "remembered" into "enforced": `match` (a regex or substring) is tested
    against the artifacts named in `applies_to`, and `message` is surfaced on
    a hit. Legacy-compatible: only populated on NEW typed writes; existing
    decisions/rejected-options carry `constraint=None`."""

    model_config = ConfigDict(extra="forbid")
    match: str
    match_kind: Literal["regex", "substring"]
    # e.g. ["action_result", "spec_doc", "llm_payload"] — the artifact
    # streams a guard checks. Free list[str]; those three are the W2/W9 set.
    applies_to: list[str] = Field(default_factory=list)
    message: str = ""


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    rationale: str
    by: str
    at: datetime
    # W1 typed-decision fields (DESIGN-v6 §W1). All OPTIONAL + default None so
    # a legacy decision deserializes byte-identically; emission-gated below
    # (omitted at their defaults). `title` (≤90 chars, required for NEW writes
    # at the tool layer), `kind` (the typed category), `subject` (the dedupe
    # key enabling supersede-by-subject / edit-semantics) and `constraint`
    # (the executable Constraint the W2/W9 guards consume) are already accepted
    # on the flat record_context InputModel (W4) — this schema PERSISTS them.
    # The record_context→Decision wiring + north_star active_constraints view
    # are a SEPARATE action; here the storage shape is established only.
    title: str | None = None
    kind: Literal[
        "constraint", "direction", "scope", "preference", "fact", "legacy",
    ] | None = None
    subject: str | None = None
    constraint: Constraint | None = None
    # s27 Item 3A: marks a decision must-reach-worker. ONLY load_bearing
    # decisions are stamped into Action.injected_context (keeps the auto-
    # injected grounding tight — s26's "never nomic" would be flagged true).
    # Optional; emission-gated below (omitted when False/default) so a
    # pre-restart OLD-schema reader under extra='forbid' never sees the key.
    load_bearing: bool = False
    # s26 item 13 — CROSS-STEP ALIASING FIX. A load-bearing decision is stamped
    # into worker grounding RECIPE-WIDE (pool_spawn_worker), and until now there
    # was NO WAY TO SAY "this one is for one step only". So a decision whose text
    # addresses a step-relative actor ("Reviewer a4 owns the fix", written under
    # plan …-s18) was stamped verbatim into a LATER plan's same-named action and
    # read by it as its own instruction. Action ids are only meaningful RELATIVE
    # TO A PLAN; the stamp erased that relativity.
    #
    # `scope_plan_id` restores it: when set, the decision is stamped ONLY into
    # actions of that plan. When None (the default, and every legacy decision)
    # the decision is recipe-wide exactly as before — so this is purely additive
    # and no existing grounding changes. Emission-gated below (omitted at the
    # None default) so a pre-restart OLD-schema reader under extra='forbid'
    # never sees the key and the 0e7ca8 fixture round-trips byte-identically.
    scope_plan_id: str | None = None
    # P2 tiering (2026-06-10): when the text is tiered out, `text_ref` holds
    # the sidecar path (relative to the recipe dir) and the inline `text`
    # becomes a one-line digest ON DISK ONLY — RecipeStore.load hydrates the
    # full text back before validation, so in-memory consumers never see the
    # digest. Emission-gated (omitted when None).
    text_ref: str | None = None
    # W1/a9: companion ref for a2's Decision.rationale tiering coverage —
    # same on-disk-only, load-hydrated, emission-gated discipline as text_ref.
    rationale_ref: str | None = None
    # P2 superseded-decision archive: a superseded decision stays in the
    # honest history but leaves the ACTIVE set — recipe_context's pointer
    # index and the pool_spawn_worker load-bearing stamp skip it. Both
    # fields emission-gated (omitted at defaults).
    status: Literal["active", "superseded"] = "active"
    superseded_by: str | None = None
    # v7 WS3 (2026-08-05) — CONSEQUENCES AT WRITE (§2.1): the step/action ids
    # this decision constrains. The edge index derives decision→target edges
    # from it, and scoped invalidation wakes ONLY shells whose handle
    # intersects the transitive closure — everyone else's ground (and prompt
    # cache) stays valid. [] (every legacy decision) = recipe-wide, exactly
    # the pre-v7 behavior — purely additive, like scope_plan_id above. The
    # MEANING-at-write digest is NOT a new field: `title` (≤90, required for
    # NEW writes at the tool layer) already is it — d76/d77: use the
    # mechanism that exists. Emission-gated below (omitted when empty).
    affects: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _ser_load_bearing_gate(self, handler):
        # Omit optional fields at their defaults so an untouched decision
        # serializes byte-shape-identical to the pre-change schema (the
        # RP-A emission-gate discipline: a pre-restart extra='forbid'
        # reader never sees the new keys).
        data = handler(self)
        if not data.get("load_bearing"):
            data.pop("load_bearing", None)
        if data.get("text_ref") is None:
            data.pop("text_ref", None)
        if data.get("rationale_ref") is None:
            data.pop("rationale_ref", None)
        if data.get("status") == "active":
            data.pop("status", None)
        if data.get("superseded_by") is None:
            data.pop("superseded_by", None)
        # s26 item 13 emission gate: omit at the None default so an unscoped
        # (recipe-wide) decision — i.e. every legacy one — serializes
        # byte-shape-identical to the pre-change schema.
        if data.get("scope_plan_id") is None:
            data.pop("scope_plan_id", None)
        # v7 WS3 emission gate: omit when empty so an unscoped decision
        # serializes byte-shape-identical to pre-v7.
        if not data.get("affects"):
            data.pop("affects", None)
        # W1 typed fields: omit at their None defaults so an untouched
        # (legacy) decision serializes byte-shape-identical to pre-W1.
        for _f in ("title", "kind", "subject", "constraint"):
            if data.get(_f) is None:
                data.pop(_f, None)
        return data

    # W1 (DESIGN-v6 §W1, o6 byte-identity steer): NO length cap/validator on
    # this schema. Decision construction AND tiered hydration must accept ANY
    # length — legacy recipes (0e7ca8 + the 38 dirs) carry >1200-char decision
    # texts, and P2 tiering re-inflates the full text on hydrate before
    # validation, which a construction-time cap would then reject. The >1200
    # WRITE-TIME refusal lives in the record_context TOOL path, not here.


class Assumption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    by: str
    at: datetime
    # W1/a9: companion ref for a2's Assumption.text tiering coverage —
    # on-disk-only, load-hydrated, emission-gated (omitted when None).
    text_ref: str | None = None
    # W8 (DESIGN-v6 §W8): the assumption acknowledgement gate. All fields
    # are purely ADDITIVE with safe defaults so a legacy Assumption
    # (id,text,by,at with none of these keys) deserializes unchanged and
    # is grandfathered to status="acked" by the validator below. NEVER add
    # a construction-time cap/validator that could reject a legacy text or
    # shape — the fields only add, never constrain.
    load_bearing: bool = False
    status: Literal["pending", "acked", "rejected"] = "pending"
    acked_by: str | None = None
    acked_at: str | None = None
    # Optional step/action ids this assumption bears on (advisory).
    affects: list[str] = []

    @model_validator(mode="after")
    def _grandfather_status(self):
        # d24 (o6-protecting): a NON-load-bearing assumption — which
        # includes ANY legacy shape carrying none of the W8 fields —
        # resolves to "acked". Only auto-resolve the "pending" DEFAULT so
        # an explicit status choice (e.g. a caller-set "rejected") is
        # preserved. A load_bearing assumption stays "pending" until acked.
        if not self.load_bearing and self.status == "pending":
            self.status = "acked"
        return self

    @model_serializer(mode="wrap")
    def _ser_text_ref_gate(self, handler):
        # Omit text_ref at its None default so an untiered assumption
        # serializes byte-shape-identical to the pre-tiering schema.
        data = handler(self)
        if data.get("text_ref") is None:
            data.pop("text_ref", None)
        # W8 additive fields: emission-gate at their RESTING defaults so a
        # legacy / non-load-bearing assumption serializes byte-shape-
        # identical to the pre-W8 schema (RP-A discipline: a pre-restart
        # extra='forbid' reader never sees the new keys). A non-load-
        # bearing assumption's resting status is the grandfathered "acked";
        # a load_bearing one's is "pending".
        if not data.get("load_bearing"):
            data.pop("load_bearing", None)
        resting_status = "pending" if self.load_bearing else "acked"
        if data.get("status") == resting_status:
            data.pop("status", None)
        if data.get("acked_by") is None:
            data.pop("acked_by", None)
        if data.get("acked_at") is None:
            data.pop("acked_at", None)
        if not data.get("affects"):
            data.pop("affects", None)
        return data


class RejectedOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str
    reason: str
    # W1 (DESIGN-v6 §W1): "a ban becomes checkable, not remembered." Optional +
    # default None so a legacy rejected-option deserializes byte-identically;
    # emission-gated below (omitted when None). Populated by the separate
    # record_context→RejectedOption wiring action.
    constraint: Constraint | None = None
    # W1/a9: companion ref for a2's RejectedOption.text tiering coverage —
    # on-disk-only, load-hydrated, emission-gated (omitted when None).
    text_ref: str | None = None
    # W9 part 2 item 4 (d76 — findings are PROPOSALS, never silent steering).
    # `guards.check_constraints` skips any record whose `status` is not
    # "active", so a "proposed" ban carries NO teeth: it is visible in the
    # recipe and inert until a neuron activates it in a batch
    # (`confirm_direction_constraints`). The default is "active" so a legacy
    # rejected-option — which carries no constraint and is therefore a
    # structural no-op in the guard anyway — deserializes and re-serializes
    # unchanged. The WRITE path is what makes a constraint-bearing ban
    # proposed: RecordRejectedOption sets status="proposed" whenever a
    # constraint is supplied, for EVERY caller. No role branch, so no caller
    # can activate a ban by being the right role.
    status: Literal["proposed", "active"] = "active"

    @model_serializer(mode="wrap")
    def _ser_constraint_gate(self, handler):
        # Omit `constraint` + `text_ref` at their None defaults, and `status`
        # at its "active" default, so an untouched (legacy) rejected-option
        # serializes byte-shape-identical to pre-W1 (RP-A emission-gate
        # discipline).
        data = handler(self)
        if data.get("constraint") is None:
            data.pop("constraint", None)
        if data.get("text_ref") is None:
            data.pop("text_ref", None)
        if data.get("status") == "active":
            data.pop("status", None)
        return data


class RecipeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assumptions: list[Assumption] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    rejected_options: list[RejectedOption] = Field(default_factory=list)
    open_questions: list[dict] = Field(default_factory=list)


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    kind: str  # FREE TEXT — no enum (user directive 2026-05-16)
    description: str
    status: Literal["pending", "in_progress", "done", "skipped"]
    depends_on: list[str] = Field(default_factory=list)
    execution: Literal["inline", "spawn_planner"]
    plan_ref: str | None = None
    outputs: list[str] = Field(default_factory=list)
    rationale_for_next: str = ""
    # Phase 7 (2026-05-21): crash-recovery re-dispatch counter. The
    # planner for this step died before terminal; auto-re-dispatch once,
    # surface after. Mirrors Action.attempt.
    attempt: int = 0
    # P2 tiering (2026-06-10): sidecar pointer for a tiered description —
    # on-disk shape only; RecipeStore.load hydrates the full description
    # back before validation. Emission-gated (omitted when None).
    description_ref: str | None = None
    # Context-diet Phase 2 — cross-cutting concerns DECLARED AT THE STEP.
    # The Action layer has carried `concerns` since SPECIALIZATION-LAYERED-
    # RULESETS.md, but the step layer could not, so a concern the neuron knew
    # at map time died between recipe -> step -> plan and was left to the
    # planner's loose interpretation (the reported worker-misalignment
    # class). The flow-down gate (record_plan / dispatch) refuses a plan
    # whose actions do not cover every step concern. Emission-gated (omitted
    # when empty) so legacy recipes round-trip byte-identically.
    concerns: list[str] = Field(default_factory=list)
    # Phase 2 — the step's ACCEPTANCE SKETCH: free-text expected-outcome
    # lines the neuron states up front ("the API rejects bad input with
    # 4xx"). The planner formalizes each into action acceptance and maps it
    # EXPLICITLY in Plan.sketch_covered_by (explicit mapping is testable;
    # fuzzy text-matching is a lie generator). Emission-gated when empty.
    acceptance_sketch: list[str] = Field(default_factory=list)
    # v7 WS3 (2026-08-05) — OUTCOME LINEAGE (§2.5/§2.6): the star
    # expected-outcome ids this step exists to serve. The anti-trivial gate:
    # a step serving no outcome is orphaned work the write path (declare-step
    # tool, next increment) refuses to admit; the edge index surfaces legacy
    # orphans as a query instead. [] on every legacy step = unlinked, exactly
    # the pre-v7 shape. Emission-gated (omitted when empty).
    serves: list[str] = Field(default_factory=list)
    # v7 WS3 (§2.6c) — the step ESTIMATE, authored at declaration (planner
    # PM discipline: estimate, don't vibe): {tokens?: int, hours?: float}.
    # budget_status compares planned vs actual per step. Emission-gated.
    estimate: dict | None = None
    # F35 R3b#3 (2026-08-18) — IMMUTABLE execution ORIGIN. G-STEP's
    # laundering scan keyed on the CURRENT execution, so flipping a
    # spawn_planner step to inline before marking it done exempted it
    # from both checks. Stamped once at add_step; the object CRUD layer
    # refuses patches to it. None = legacy (scan falls back to the live
    # execution). Emission-gated.
    execution_origin: str | None = None
    # QoL Phase 3 — the step's deliverable FORM (see Outcome.deliverable).
    deliverable: str | None = None

    @model_serializer(mode="wrap")
    def _ser_tiering_gate(self, handler):
        data = handler(self)
        if data.get("execution_origin") is None:
            data.pop("execution_origin", None)
        if data.get("description_ref") is None:
            data.pop("description_ref", None)
        if not data.get("concerns"):
            data.pop("concerns", None)
        if not data.get("acceptance_sketch"):
            data.pop("acceptance_sketch", None)
        # v7 WS3 emission gate: omit when empty so a legacy step serializes
        # byte-shape-identical to pre-v7.
        if not data.get("serves"):
            data.pop("serves", None)
        if not data.get("estimate"):
            data.pop("estimate", None)
        if data.get("deliverable") is None:
            data.pop("deliverable", None)
        return data


class Comprehension(BaseModel):
    model_config = ConfigDict(extra="forbid")
    branches: list[Branch] = Field(default_factory=list)
    expected_outcomes: list[Outcome] = Field(default_factory=list)
    # 2026-05-28 hard gate: comprehension is "converged" ONLY when
    # curiosity returned clear/done (set AUTOMATICALLY when such a reply
    # arrives — the neuron cannot fake it) OR the user explicitly signed
    # off to proceed without full convergence (record_comprehension_
    # signoff). A TERMINATED/crashed curiosity is NOT clear. record_outcome
    # refuses while both are False — so the neuron can't launder a
    # disrupted curiosity into "goal clear" and skip the loop (the
    # new-trends 2026-05-28 failure).
    curiosity_cleared: bool = False
    user_signoff: bool = False
    signoff_quote: str = ""   # the user's verbatim proceed-instruction
    # P6 (2026-06-10) user-discussion gate: leaving COMPREHENDING for the
    # first planner dispatch now requires user_signoff OR this explicitly
    # recorded skip (record_comprehension_signoff(skipped=true, reason=…) —
    # reason mandatory, audit-trailed). Keeps autonomy possible while
    # making "the user never saw the plan" a deliberate, recorded choice.
    # Emission-gated below.
    signoff_skipped: bool = False
    skip_reason: str = ""
    # F35 R3a#6 (2026-08-18): the map GREW after the user's signoff (a step
    # was added while the recipe was in REVIEWING). The FSM's reviewing-
    # reopen AWAIT_USERs while this is set; record_comprehension_signoff
    # clears it. Emission-gated below.
    signoff_stale: bool = False
    # P6 recheck bookkeeping: ISO ts of the last re-grounding moment (a
    # curiosity clear or a fresh signoff). The load-bearing-drift recheck
    # nag clears when the baseline is refreshed at one of those moments.
    # Emission-gated below.
    last_recheck_at: str | None = None
    # s27 Item 1 (major-change recheck): snapshot of the comprehended map
    # ({"n_steps","n_outcomes"}) captured the moment the recipe first leaves
    # COMPREHENDING. The FSM compares the LIVE recipe against it to SUGGEST a
    # fresh-shell curiosity re-consult when the map has grown materially past
    # what was comprehended (scope creep — the second recheck trigger beside
    # repeated failures). Optional; emission-gated below (omitted when None) so
    # a pre-restart OLD-schema reader under extra='forbid' never sees the key.
    baseline: dict | None = None
    # v7 (2026-07-13) — the OPEN curiosity interrogator for this recipe.
    # Stamped by consult_curiosity at spawn, cleared when its clear/done
    # reply converges (reconcile). While set and the shell is alive, a
    # SECOND spawn is refused: a neuron that forgets the open interrogator
    # (measured: a codex neuron consumed its questions, spawned a fresh one,
    # and stranded both) must FOLLOW UP with this id, not fork the
    # conversation. Emission-gated below.
    curiosity_open_id: str | None = None

    @model_serializer(mode="wrap")
    def _ser_baseline_gate(self, handler):
        # Omit optional fields at their defaults so an untouched
        # comprehension serializes byte-shape-identical to the pre-change
        # schema (RP-A emission-gate discipline); emit only once set.
        data = handler(self)
        if data.get("baseline") is None:
            data.pop("baseline", None)
        if not data.get("signoff_skipped"):
            data.pop("signoff_skipped", None)
        if not data.get("signoff_stale"):
            data.pop("signoff_stale", None)
        if not data.get("skip_reason"):
            data.pop("skip_reason", None)
        if data.get("last_recheck_at") is None:
            data.pop("last_recheck_at", None)
        if data.get("curiosity_open_id") is None:
            data.pop("curiosity_open_id", None)
        return data


class DirectionReview(BaseModel):
    """VESTIGIAL — RETAINED FOR LOAD-COMPATIBILITY ONLY. DO NOT DELETE.

    This held W9's direction-review checkpoint bookkeeping. The whole
    neuron-facing direction-review surface was REMOVED (d128/d132: the reviewer
    is the planner's subagent and is never available to the neuron), so NOTHING
    READS THESE FIELDS ANY MORE — no checkpoint, no counter stamping, no
    off_track push, no reviewer mode.

    They stay on the model because `Recipe.model_config` is `extra="forbid"` and
    recipes ALREADY ON DISK carry `direction_review` +
    `actions_done_since_direction_review` (the live framework recipe carries a
    counter of 150). Deleting the fields would make every one of those recipes
    fail to load. Purging them from disk instead would be a rewrite of the
    recipe store, which the lazy-migration / byte-identity discipline (o6)
    forbids. So: inert data, no reader, and a legacy recipe keeps loading.

    If you are here to "clean up two unused fields": that is the trap. Removing
    them breaks the load path for every existing recipe."""

    model_config = ConfigDict(extra="forbid")
    every_n: int = Field(default=5, ge=1)
    baseline: dict = Field(default_factory=dict)
    emitted: dict = Field(default_factory=dict)
    last_verdict: dict | None = None


#: The serialized shape of an untouched DirectionReview. Recipe's emission gate
#: pops the key when it matches, so a never-reviewed recipe carries no W9 keys.
_DIRECTION_REVIEW_RESTING = DirectionReview().model_dump(mode="json")


class SpecialistConsult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consult_id: str
    specialist_id: str  # matches a docs/guides/specialist-<id>.md
    query: str
    verdict: dict
    at: datetime


class OcakAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["recipe", "plan"]
    # The 4 OCAK questions the helper returned. Agent records its own
    # per-question verdicts in `findings`.
    findings: dict  # {"O": "...", "C": "...", "A": "...", "K": "..."}
    verdict: Literal["passed", "gaps_found", "overridden_by_user"]
    gaps: list[str] = Field(default_factory=list)
    notes: str = ""
    at: datetime


class Recipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipe_id: str = Field(min_length=1)
    user_goal_verbatim: str = Field(min_length=1)  # never paraphrased
    user_goal_distilled: str = ""
    domain: str = Field(min_length=1)
    state: RecipeState
    comprehension: Comprehension = Field(default_factory=Comprehension)
    # Post-HITL sweep 2026-05-20: specialists are consulted on demand by
    # the neuron, not seeded by the FSM. OCAK is a post-reasoning audit,
    # not a pre-reasoning checklist. `comprehension.branches` is kept
    # for legacy recipe back-compat; new code writes to the two fields
    # below. See docs/design/philosophy/ocak-as-helper-not-enforcer.md.
    specialist_consults: list[SpecialistConsult] = Field(default_factory=list)
    ocak_audit: OcakAudit | None = None
    # Team-architecture restoration Phase 2 (2026-05-21):
    # inbox_cursor advances each time HANDLE_MESSAGES is emitted, so
    # next_action delivers each message exactly once. Communication
    # flows via next_action — no Monitor, no subscribe, no LLM choice
    # to fetch.
    inbox_cursor: datetime | None = None
    # W5 (DESIGN-v6 §W5) — consult/steer delivery backstop. `reconcile` drains
    # kind=consult/steer messages from THIS recipe's OWN inbox (the durable
    # recipe_id recipient the neuron already observes — no separate consult
    # recipient) and stashes each as a compact pending record here
    # ({msg_id,kind,from,ts,preview}), so the digest surfaces an undrained
    # consult (recipe_context / get_recipe_digest) and a compacted shell
    # re-sees it (W2 reground). An entry clears once a subsequent
    # record_context decision references its msg_id (steer-ack); until then it
    # re-surfaces every tick. `consult_cursor` is the high-water ts already
    # drained (mirrors inbox_cursor, strict `>`), so an acked+cleared entry is
    # never re-added from the broker window. Both are additive with resting
    # defaults + emission-gated below, so a legacy recipe (0e7ca8) serializes
    # byte-shape-identical (o6 / RP-A emission-gate discipline).
    consult_pending: list[dict] = Field(default_factory=list)
    consult_cursor: datetime | None = None
    steps: list[RecipeStep] = Field(default_factory=list)
    context: RecipeContext = Field(default_factory=RecipeContext)
    final_outcome: dict | None = None
    # W11 (DESIGN-v6 §W11) suspend/resume. `suspended_at` is a tz-aware UTC
    # ISO stamp; `neuron_session_id` pins the shell to resume into. Both are
    # ORTHOGONAL to the FSM `state` — suspension is NOT a state transition, so
    # the state enum and its transition table are untouched. Additive with
    # None defaults + emission-gated below, so a never-suspended recipe (and
    # the legacy 0e7ca8 fixture) serializes byte-shape-identical to pre-W11.
    #
    # RP-A ordering caveat (assumption a5): the gate protects the at-rest
    # shape only until a value is first WRITTEN. Once a real suspend stamps
    # `suspended_at`, a still-running PRE-W11 reader under extra='forbid'
    # REFUSES to load that recipe — so no recipe may be suspended before the
    # coordinated restart.
    suspended_at: str | None = None
    neuron_session_id: str | None = None
    # VESTIGIAL, NO READER — see the DirectionReview docstring. W9's
    # direction-review surface is removed (d128/d132); reconcile no longer
    # stamps this counter and no code reads either field. They remain because
    # this model is extra="forbid" and recipes on disk still carry them, so
    # deleting the fields would refuse to load every existing recipe. Both stay
    # emission-gated below, so a recipe that never carried them still doesn't.
    actions_done_since_direction_review: int = Field(default=0, ge=0)
    direction_review: DirectionReview = Field(default_factory=DirectionReview)
    # v7 WS3 (§2.6c, 2026-08-05) — the recipe BUDGET, first-class on the
    # star: {claude_tokens?: int, delegate_usd?: float, wall_clock_hours?:
    # float} — any subset. Planned side of budget_status; delegate actuals
    # come from the bridge audit sidecars. None (every legacy recipe) = no
    # budget declared, no gate. Emission-gated below.
    budget: dict | None = None
    # WP2 (2026-08-12) — the TARGET REPO ROOT this recipe's work lands in.
    # Validated at record time (StartRecipe / the update_object recipe patch):
    # an absolute path that exists and contains a `.git` directory — so the
    # reviewer git-diff brief and the G-COMMIT close gate can trust it without
    # re-validating. None (every legacy recipe) = no workspace, no gate.
    # Emission-gated below.
    workspace: str | None = None
    # QoL Phase 3 (2026-08-21) — OPERATOR HOLD: a user process rule
    # ("train ALL specialists before dispatch", "show me the design
    # first") recorded as a MACHINE constraint, not prose. While set, the
    # step wave and planner spawns refuse, naming this text. The neuron
    # sets/clears it via update_object('recipe', patch={'dispatch_hold':
    # ...}); None (legacy) = no hold, emission-gated.
    dispatch_hold: str | None = None
    version: int = Field(ge=1, default=1)
    created_at: datetime
    updated_at: datetime

    @model_serializer(mode="wrap")
    def _ser_consult_gate(self, handler):
        # W5: omit the consult backstop fields at their resting defaults so a
        # recipe that never received a consult/steer serializes byte-shape-
        # identical to the pre-W5 schema (RP-A discipline: a pre-restart
        # extra='forbid' reader never sees the new keys).
        data = handler(self)
        if not data.get("consult_pending"):
            data.pop("consult_pending", None)
        if data.get("consult_cursor") is None:
            data.pop("consult_cursor", None)
        # W11: same discipline for the suspend/resume pair.
        if data.get("suspended_at") is None:
            data.pop("suspended_at", None)
        if data.get("neuron_session_id") is None:
            data.pop("neuron_session_id", None)
        # W9: same discipline for the direction-review checkpoint. A recipe that
        # has never accrued a done action and never been direction-reviewed emits
        # NEITHER key (o6: the 0e7ca8 fixture must round-trip byte-identical).
        # `direction_review` is compared against its resting default rather than
        # a truthiness test, because the model always dumps to a non-empty dict.
        if not data.get("actions_done_since_direction_review"):
            data.pop("actions_done_since_direction_review", None)
        if data.get("direction_review") == _DIRECTION_REVIEW_RESTING:
            data.pop("direction_review", None)
        # v7 WS3 emission gate: no declared budget → no key (byte-identical
        # legacy round-trip).
        if not data.get("budget"):
            data.pop("budget", None)
        # WP2 emission gate: no recorded workspace → no key (same discipline).
        if data.get("workspace") is None:
            data.pop("workspace", None)
        if data.get("dispatch_hold") is None:
            data.pop("dispatch_hold", None)
        return data

    @model_validator(mode="after")
    def _clear_test_invariants(self) -> "Recipe":
        # Past CREATED: must carry the verbatim goal + a domain (already
        # min_length-guarded; restated here as the explicit invariant).
        if self.state != RecipeState.CREATED:
            if not self.user_goal_verbatim or not self.domain:
                raise ValueError(
                    "recipe past CREATED requires user_goal_verbatim + domain"
                )
        # Leaving COMPREHENDING: no branch may still need user input, and at
        # least one step must exist (you cannot PLAN nothing).
        if self.state in (
            RecipeState.PLANNING,
            RecipeState.EXECUTING,
            RecipeState.REVIEWING,
            RecipeState.CLOSED,
        ):
            stuck = [
                b.id
                for b in self.comprehension.branches
                if b.status == "needs_user_input"
            ]
            if stuck:
                raise ValueError(
                    f"recipe cannot leave COMPREHENDING with branches "
                    f"needing user input: {stuck}"
                )
            if not self.steps:
                raise ValueError(
                    "recipe cannot leave COMPREHENDING with no steps"
                )
        # CLOSED requires a final_outcome.
        if self.state == RecipeState.CLOSED and self.final_outcome is None:
            raise ValueError("CLOSED recipe requires final_outcome")
        return self
