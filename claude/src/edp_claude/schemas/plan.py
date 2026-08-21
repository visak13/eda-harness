"""Plan schema (LLD §2.3; DESIGN-v4 §2.2)."""

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)

from .instruction import PlanState


class Acceptance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str  # "tests_pass" | "integration_test_pass" | "manual_review" | ...
    expected: str = ""
    actual: str | None = None
    # P2 tiering (2026-06-10): sidecar pointer for a tiered evidence blob
    # (`evidence/<action_id>-actual.md` relative to the plan dir) — on-disk
    # shape only; PlanStore.load hydrates the full text back before
    # validation. Emission-gated below (omitted when None).
    actual_ref: str | None = None
    # outcome-verify (2026-05-21): optional DETERMINISTIC check the tool
    # runs at record_action_status(done) time. If present and it fails,
    # the `done` is HARD-REJECTED — a worker cannot claim done for a
    # deliverable that doesn't exist (the calendar-HITL false-done).
    # Shapes:
    #   {"check": "file_exists", "path": "<abs path preferred>"}
    #   {"check": "file_min_bytes", "path": "...", "min": 30000}
    #   {"check": "glob_matches", "pattern": "...", "min_count": 1}
    # Non-deterministic acceptance (tests_pass / metric / manual_review)
    # leaves this null and relies on evidence + /critic review.
    verify: dict | None = None
    # WP1 G-RUNS (2026-08-12): the EXECUTION EVIDENCE ledger for a gate
    # action's `done`. Entries are {command: str, exit_code: int,
    # output_tail?: str, at: str} — an actual run, not evidence prose.
    # record_action_status APPENDS here; emission-gated below (omitted when
    # empty) so a legacy acceptance round-trips byte-identically.
    runs: list[dict] = Field(default_factory=list)
    # WP2 G-COMMIT (2026-08-12): the git commit hash the worker/reviewer
    # states the deliverable landed as (record_action_status `commit` /
    # record_branch_verdict `commit`). DATA, never derived by the tool; the
    # CloseRecipe G-COMMIT gate independently checks the workspace tree.
    # Emission-gated below (omitted when None) — legacy byte-identity.
    commit: str | None = None

    @model_serializer(mode="wrap")
    def _ser_tiering_gate(self, handler):
        # P2 emission gate: omit actual_ref when None so an untiered
        # acceptance serializes byte-shape-identical to the pre-P2 schema.
        data = handler(self)
        if data.get("actual_ref") is None:
            data.pop("actual_ref", None)
        # WP1 emission gate: omit `runs` when empty (legacy byte-identity).
        if not data.get("runs"):
            data.pop("runs", None)
        # WP2 emission gate: omit `commit` when None (legacy byte-identity).
        if data.get("commit") is None:
            data.pop("commit", None)
        return data


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_id: str
    description: str
    # P2 tiering (W1/a9): sidecar pointer for a tiered `description` — on-disk
    # shape only; PlanStore.load hydrates the full description back before
    # validation. Companion to a2's Action.description tiering coverage.
    # Emission-gated in _ser_legacy_shape (omitted when None) so an untiered
    # action serializes byte-shape-identical to the pre-tiering schema.
    description_ref: str | None = None
    # 2026-05-28: `verify` sits between in_progress and done. The worker
    # claiming done routes the action to `verify` (work claimed, gate
    # pending); only a passing acceptance gate flips verify→done. A
    # broken/failing gate leaves it visibly parked in `verify` — not a
    # deadlock, not a lying `failed`. See docs/design/OBJECT-MODEL.md.
    status: Literal[
        "pending", "in_progress", "verify", "done", "failed",
        "skipped", "needs_review"
    ]
    depends_on: list[str] = Field(default_factory=list)
    executor_mode: Literal["inline", "subagent"]
    acceptance: Acceptance
    result_ref: str | None = None
    attempt: int = 0
    # ── DESIGN-v6 W10b: the failed-ACCEPTANCE-CYCLE counter ─────────────────
    # `attempt` counts RE-DISPATCH and nothing else: it is bumped in exactly one
    # place (reconcile's crash-recovery branch, _tools.py:1581) and only when a
    # worker DIED or went phantom. An action whose acceptance keeps FAILING while
    # its worker reports cleanly never moves `attempt` at all. So the design's
    # second stuck signal had no counter, and this is it.
    #
    # WHAT COUNTS AS ONE CYCLE, AND WHY THE LATCH BELOW EXISTS. Under d30 a
    # failed acceptance is REPORTED at two independent seams: the WORKER runs the
    # gate in its own shell and records `status="failed"`, and the REVIEWER
    # independently re-runs it in a fresh shell and records a failing action
    # verdict. That dual gate is the healthy path, not a stuck one — so a single
    # failed cycle passing through BOTH seams must bump this counter ONCE, not
    # twice. Naive per-report bumping would fire the escalation ladder at half its
    # stated threshold and no test would notice.
    #
    # THE IDEMPOTENCE KEY IS THE DISPATCH BOUNDARY, NOT `attempt`. (action_id,
    # attempt) is the obvious key and it is WRONG: `attempt` does not advance on a
    # verify failure, so a second genuine failed cycle would carry the same key as
    # the first and be silently swallowed. A cycle instead begins where the FSM
    # stamps an action `in_progress` at dispatch (plan_fsm: both the single
    # dispatch and the ready-wave) — that is the one event that means "this action
    # is being executed afresh". `verify_failure_counted` is cleared there and set
    # by whichever seam reports first; the second seam is then a no-op.
    #
    # Both fields are emission-gated below (omitted at their defaults) so a legacy
    # plan JSON and a pre-restart extra='forbid' reader are untouched — the o6
    # standing bar. Nothing populates them until a real acceptance failure lands.
    verify_failures: int = 0
    verify_failure_counted: bool = False
    # MULTI-SPEC worker selection (2026-06-03, recipe …-s14). An action may
    # need MORE THAN ONE stack's craft (e.g. a full-stack endpoint = Java +
    # React). The CANONICAL fields are these plural lists; N=1 is simply a
    # one-element list. There is NO permanently-maintained parallel scalar
    # (amendment A1): the legacy scalar `specialization`/`spec_id` are folded
    # into these lists at LOAD time by `_fold_legacy_scalars` (so historical
    # plan JSON, written with the scalar under extra='forbid', still loads),
    # and re-emitted in the legacy SHAPE on serialize while a list has ≤1
    # entry (so the pre-restart MCP/pool holding the OLD schema can still
    # re-read any plan this code writes — see `_ser_legacy_shape`).
    #
    # phase 7 lineage: a set descriptor → the dispatcher neuron_searches each
    # and the planner STAMPS the resolved `spec_ids` via update_object; a
    # FRESH worker then loads + concatenates each spec's COMPILED doc
    # (`get_specialist_doc`) as its grounding. pool_spawn_worker's Guard B
    # refuses to spawn if ANY stamped spec has no compiled doc (fails closed).
    specializations: list[str] = Field(default_factory=list)   # human descriptors
    spec_ids: list[str] = Field(default_factory=list)          # resolved specs
    # SPECIALIZATION-LAYERED-RULESETS.md (2026-06-01), Decision 3b +
    # Decision 4: cross-cutting concerns (security / a11y / perf …) are
    # ORTHOGONAL to tech, so they are NOT in the spec's `extends`. The
    # PLANNER tags an action with the concerns it touches (e.g. an
    # endpoint handling user input → ["security"]); the worker assembles
    # universal ⊕ tech-extends-chain ⊕ these concerns. A non-tagged action
    # has the concern structurally absent (it cannot leak). Empty default.
    concerns: list[str] = Field(default_factory=list)
    # Context-diet Phase 3d — the DECLARED leg kind. The d67 dispatch guard
    # used to infer "is this a review leg?" from a name regex
    # (`review*`/`r<n>`), which reserved identifier namespace and missed the
    # real invariant: record_branch_verdict is reviewer-surface-only, so a
    # review leg dispatched as a worker cannot record its verdict AT ALL.
    # The planner now DECLARES the kind at authoring; the guard keys on the
    # declaration (capability-based) and falls back to the legacy regex only
    # for undeclared legacy actions. Emission-gated (omitted when None).
    leg_kind: Literal["build", "review", "verify"] | None = None
    # s27 Item 3A (automatic context -> worker). The dispatcher stamps the
    # recipe's LOAD-BEARING settled context (decisions tagged load_bearing,
    # banned options, hard constraints) here at spawn, so a worker receives it
    # AUTOMATICALLY via the read_object('action') it already does — closing the
    # silent hand-copy gap that let the s26 embedder-drift class through.
    # Optional; emission-gated below (omitted when empty) so a pre-restart
    # OLD-schema reader under extra='forbid' never sees the new key. Nothing
    # populates it until after the coordinated restart.
    #
    # s17 RP-A (2026-06-07): this field is now the READ-TIME RESOLVED view only
    # — a worker reading read_object('action') still receives the SAME full-text
    # dict ({"load_bearing_decisions": [text…], "banned_options": [text…]}),
    # byte-identical to the pre-RP-A worker experience. But on DISK the action
    # no longer DUPLICATES that text: the dispatcher stamps `injected_context_ids`
    # (id pointers) here-adjacent and stores each decision's text ONCE in
    # `Plan.injected_context` (a by-id map). `read_object('action')` resolves the
    # ids→text from that plan map at read time (objects.py). Old plans that still
    # carry full-text `injected_context` on the action (pre-RP-A) keep reading
    # unchanged (the resolver passes them through). See RP-A-RP-B-EVIDENCE.md.
    injected_context: dict | None = None
    # s17 RP-A by-id pointer. {"load_bearing_decisions": [decision_id…],
    # "banned_options": [rejected_id…]} — ids only, NO duplicated text. The
    # text lives once in Plan.injected_context (the by-id map shared with the
    # RP-B decisions index). Emission-gated (omitted when empty) so a pre-restart
    # OLD-schema reader under extra='forbid' never sees it; nothing populates it
    # until the post-restart dispatcher runs the RP-A stamp.
    injected_context_ids: dict | None = None
    # s26 item 6 — WHERE A REVIEWER'S VERDICT LANDS. d29/d30 make the reviewer's
    # independent re-run THE objective gate, but the verdict had nowhere to go:
    # `record_branch_verdict` resolved ONLY recipe.comprehension.branches, so a
    # reviewer stamping a verdict on a plan ACTION got "no branch <id>".
    #
    # Shape: {"verdict": str, "by": str, "at": ISO ts}. Deliberately NOT a
    # status: a reviewer records a JUDGEMENT here, the WORKER records
    # `status`/`acceptance.actual`. Keeping them in different fields is what
    # preserves d30's separation — a reviewer cannot flip an action to `done`
    # and a worker cannot bless its own action.
    #
    # Emission-gated below (omitted at the None default) so an unreviewed action
    # serializes byte-shape-identical to the pre-change schema.
    review_verdict: dict | None = None
    # DESIGN-v7 1.4 Stage A — ACTION BATCHING. Small serial chains (the
    # dominant DESIGN-v6 plan shape: ≤4 actions sharing spec_ids, each
    # depending on the previous) paid a full cold ~30s Claude-shell spawn PER
    # ACTION. Actions sharing a `batch_group` are dispatched as ONE unit: the
    # FSM (plan_fsm._batch_members) selects every pending group member whose
    # deps are satisfied — by done/skipped work or by an earlier member of the
    # SAME unit — stamps them all in_progress atomically, and emits one head
    # instruction carrying `batch_action_ids`. ONE worker shell executes the
    # members in declared order and records status per member; the spawn
    # handle stays `<plan_id>:<head_action_id>`. `plan_ready_wave` counts a
    # batch as ONE wave slot (the head). None (the default) = unbatched:
    # byte-identical dispatch behaviour to pre-v7. Emission-gated below
    # (omitted when None) so a legacy plan JSON and a pre-restart
    # extra='forbid' reader are untouched — the o6 standing bar.
    batch_group: str | None = None
    # F35 R3a#4 (2026-08-18) — BATCH DISPATCH OWNERSHIP. The whole batch
    # unit runs under the HEAD's handle (<plan_id>:<head_action_id>), but
    # live-dispatch suppression probes each MEMBER's own handle — so a
    # member reopened to pending while its head shell was still live
    # double-executed. Stamped (= head action_id) on every member at batch
    # dispatch; readiness and pool_spawn_worker suppress a pending action
    # whose recorded owner is live; cleared at terminal status and at the
    # failure-tail release. None = unowned (unbatched / legacy).
    batch_owner: str | None = None
    # v7 WS3 (2026-08-05) — OUTCOME LINEAGE (§2.5/§2.6): the star
    # expected-outcome ids this action's acceptance descends from (usually
    # inherited from its step's `serves` at authoring). Gives every action an
    # addressable "why", makes decision→action impact queries transitive in
    # the edge index, and lets test lineage (`verifies`) resolve to a real
    # outcome. [] on every legacy action = unlinked, the pre-v7 shape.
    # Emission-gated in _ser_legacy_shape (omitted when empty).
    serves: list[str] = Field(default_factory=list)
    # s17 FA3 model-tiering (2026-06-07; MODEL-TIERING-BENCHMARK.md §5 +
    # S17-FINDINGS-V2-AUTONOMY-LENS.md FA3). Optional PER-ACTION model override
    # for the WORKER shell this action dispatches. The PLANNER sets it (it
    # authored the action) and ONLY for a genuinely NARROW worker — bounded +
    # fully specified + single file-verified deliverable, NO large-surface tool
    # selection, NO open-ended judgment, NO irreversible side-effects — the one
    # class §3 MEASURED Sonnet 4.6 ("claude-sonnet-4-6") safe at quality-delta
    # ~0 / −40% cost. When None (the default) the worker launches with NO
    # --model flag → the host's default tier (Opus, "claude-opus-4-8"):
    # behaviour byte-identical to pre-FA3. Neuron / planner / reviewer /
    # specialist / advisory / heartbeat NEVER carry an override (UNMEASURED →
    # KEEP Opus; Haiku-heartbeat WITHDRAWN — the tick needs judgment). Only the
    # worker dispatch path reads this field. Emission-gated below (omitted when
    # None) so a pre-restart OLD-schema reader under extra='forbid' never sees
    # the new key — nothing populates it until after the coordinated restart.
    model: str | None = None
    # WP1 G-SKIP/G-RUNS (2026-08-12): a GATE ACTION — one whose completion
    # protects an expected outcome (serves non-empty + an executable
    # acceptance.verify check), derived by add_action or declared explicitly
    # by the planner. A gate action cannot be `skipped` without a recorded
    # user gate answer (override_ref) and cannot be `done` without >=1
    # acceptance.runs entry (real command + exit code). Emission-gated in
    # _ser_legacy_shape (omitted when False) — legacy byte-identity.
    gate: bool = False
    # WP2 inline execution (2026-08-12): HOW this action is executed —
    # "spawn" (the default: a pool worker shell is dispatched for it) or
    # "inline" (the PLANNER executes it itself in its own shell and records
    # status directly; spawning a worker for it wastes a pool slot, which
    # pool_spawn_worker surfaces as an ADVISORY, never a refusal). Kept a
    # plain str (values validated at the add_action write path) so a legacy
    # plan carrying an unexpected value still loads. Emission-gated in
    # _ser_legacy_shape (omitted at the "spawn" default) — legacy
    # byte-identity. NOT the same field as `executor_mode` (an older
    # inline/subagent distinction consumed by other surfaces).
    execution: str = "spawn"

    @model_validator(mode="before")
    @classmethod
    def _fold_legacy_scalars(cls, data):
        """Back-compat LOAD shim (amendment A1). Accept the legacy scalar
        `spec_id`/`specialization` (historical plan JSON + existing callers
        that still pass the singular kwarg) and fold each into its canonical
        list. The keys are POPPED before field validation, so extra='forbid'
        never sees an unknown field. The plural list wins if both are
        supplied (precedence: spec_ids over spec_id)."""
        if isinstance(data, dict):
            data = dict(data)   # never mutate the caller's dict
            legacy_spec = data.pop("spec_id", None)
            if legacy_spec and not data.get("spec_ids"):
                data["spec_ids"] = [legacy_spec]
            legacy_spz = data.pop("specialization", None)
            if legacy_spz and not data.get("specializations"):
                data["specializations"] = [legacy_spz]
        return data

    # QoL Phase 3 (2026-08-21) — the FORM this action's deliverable must
    # take (see Outcome.deliverable). Optional, emission-gated: legacy
    # actions round-trip byte-identically. The producer-verify guard keys
    # on it (interactive/visual forms may exercise the artifact).
    deliverable: str | None = None

    @model_serializer(mode="wrap")
    def _ser_legacy_shape(self, handler):
        """SERIALIZATION-HAZARD guard (amendment A1 + rollout safety). The
        running MCP/pool/neuron processes hold the OLD Action schema
        (extra='forbid') until the COORDINATED restart. If we emit
        `spec_ids`/`specializations` into on-disk plan JSON now, an
        old-schema process re-reading it would REJECT the unknown field and
        the plan would become unreadable. So serialize to the LEGACY scalar
        shape whenever a list has ≤1 entry (the only shape any pre-restart
        writer produced) and ONLY emit the plural key once N≥2 — which
        nothing writes until after the restart. Round-trips back through
        `_fold_legacy_scalars` on reload. Field order is preserved so an
        N≤1 action serializes byte-shape-identical to the pre-change schema
        (`…, specialization, spec_id, concerns, …`)."""
        data = handler(self)
        out: dict = {}
        for key, value in data.items():
            if key == "specializations":
                vv = value or []
                if len(vv) >= 2:
                    out["specializations"] = vv
                else:
                    out["specialization"] = vv[0] if vv else None
            elif key == "spec_ids":
                vv = value or []
                if len(vv) >= 2:
                    out["spec_ids"] = vv
                else:
                    out["spec_id"] = vv[0] if vv else None
            elif key == "injected_context":
                # s27 Item 3A emission gate: omit when empty so an N≤1,
                # no-context action serializes byte-shape-identical to the
                # pre-change schema (a pre-restart extra='forbid' reader never
                # sees the new key). Emit only once it actually carries
                # stamped context — which nothing does until post-restart.
                if value:
                    out["injected_context"] = value
            elif key == "injected_context_ids":
                # s17 RP-A emission gate: same discipline — omit when empty so
                # the on-disk action stays byte-shape-identical until the RP-A
                # stamp populates the id pointer (post-restart only).
                if value:
                    out["injected_context_ids"] = value
            elif key == "review_verdict":
                # s26 item 6 emission gate: omit when empty so an unreviewed
                # action serializes byte-shape-identical to the pre-change
                # schema (a pre-restart extra='forbid' reader never sees it).
                if value:
                    out["review_verdict"] = value
            elif key == "leg_kind":
                # Phase 3d emission gate: omit when None so an undeclared
                # (legacy) action serializes byte-shape-identical.
                if value:
                    out["leg_kind"] = value
            elif key == "deliverable":
                # QoL Phase 3 emission gate: same discipline.
                if value:
                    out["deliverable"] = value
            elif key == "batch_group":
                # DESIGN-v7 1.4 emission gate (o6): omit when None so an
                # unbatched action serializes byte-shape-identical to the
                # pre-v7 schema (a pre-restart extra='forbid' reader never
                # sees the new key). Emit only when the planner batched it.
                if value:
                    out["batch_group"] = value
            elif key == "batch_owner":
                # F35 R3a#4 emission gate: same o6 discipline.
                if value:
                    out["batch_owner"] = value
            elif key == "serves":
                # v7 WS3 emission gate: omit when empty so an unlinked
                # (legacy) action serializes byte-shape-identical.
                if value:
                    out["serves"] = value
            elif key == "model":
                # s17 FA3 emission gate: omit when None so an action with no
                # per-action model override serializes byte-shape-identical to
                # the pre-FA3 schema (a pre-restart extra='forbid' reader never
                # sees the new key). Emit only when a tier was explicitly set.
                if value:
                    out["model"] = value
            elif key == "description_ref":
                # W1/a9 tiering emission gate: omit when None so an untiered
                # action serializes byte-shape-identical to pre-tiering.
                if value:
                    out["description_ref"] = value
            elif key == "gate":
                # WP1 emission gate: omit when False so a non-gate (legacy)
                # action serializes byte-shape-identical to the pre-WP1
                # schema (a pre-restart extra='forbid' reader never sees it).
                if value:
                    out["gate"] = value
            elif key == "execution":
                # WP2 emission gate: omit at the "spawn" default so a legacy
                # (non-inline) action serializes byte-shape-identical.
                if value and value != "spawn":
                    out["execution"] = value
            elif key in ("verify_failures", "verify_failure_counted"):
                # W10b emission gate (o6): omit at the 0/False default so every
                # legacy action — and every action that never failed acceptance
                # — serializes byte-shape-identical to the pre-W10b schema. A
                # pre-restart extra='forbid' reader never sees the new keys.
                if value:
                    out[key] = value
            else:
                out[key] = value
        return out

    def effective_spec_ids(self) -> list[str]:
        """Canonical, deduped, order-preserving spec list for this action.
        The load-time fold already makes `spec_ids` canonical (legacy scalar
        absorbed); this just drops accidental duplicates (e.g. the planner
        stamping the same spec twice) while preserving first-seen order.
        `[]` → generic worker (no specialist grounding)."""
        return _dedup(self.spec_ids)

    def effective_specializations(self) -> list[str]:
        """Deduped, order-preserving human descriptors (analogue of
        `effective_spec_ids` for the unresolved `specializations`)."""
        return _dedup(self.specializations)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(min_length=1)
    recipe_id: str = Field(min_length=1)
    recipe_step_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    shape: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    state: PlanState
    actions: list[Action] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_action_ids(self):
        """F42#6 — duplicate action_ids made every by-id lookup ambiguous
        (next(...) found the first, dict comprehensions kept the last), so
        batch membership, rollback, and status writes could each resolve a
        DIFFERENT action. Refused at validation, the one seam every load
        and save passes through."""
        seen: set[str] = set()
        dupes: set[str] = set()
        for a in self.actions:
            (dupes if a.action_id in seen else seen).add(a.action_id)
        if dupes:
            raise ValueError(
                f"duplicate action_id(s) {sorted(dupes)!r} — action ids "
                "must be unique within a plan.")
        return self
    context: dict = Field(default_factory=dict)
    # Post-HITL sweep 2026-05-20: per-plan OCAK audit (scope="plan"),
    # captured after actions are authored, before dispatch. Mirrors the
    # recipe-level audit. Optional — the original framework-ocak.md
    # allows skipping for trivial plans.
    ocak_audit: dict | None = None
    # Team-architecture restoration Phase 2 (2026-05-21):
    inbox_cursor: datetime | None = None
    terminal_status: (
        Literal["succeeded", "superseded", "aborted", "partial"] | None
    ) = None
    version: int = Field(ge=1, default=1)
    # s17 RP-A (2026-06-07): STORE-ONCE by-id map for the load-bearing
    # decisions + banned options the dispatcher injects into this plan's
    # actions. {decision_id|rejected_id: text}. Each action carries only the
    # `injected_context_ids` pointers; the text is stored here ONCE instead of
    # duplicated per action (the 92.8%-of-plan offender from BASELINE-TOKEN-
    # FOOTPRINT.md). read_object('action') resolves an action's ids→text against
    # this map at read time, so a worker still receives byte-identical full
    # grounding. This is the SAME decisions-by-id model the RP-B next_action
    # pointer indexes. Optional; emission-gated below (omitted when empty) so a
    # pre-restart OLD-schema reader under extra='forbid' never sees the new key;
    # nothing populates it until the post-restart dispatcher runs the RP-A stamp.
    injected_context: dict | None = None
    # DESIGN-v6 W10b — the ESCALATE_CONSULT latch, the same shape and for the
    # same reason as W9's `Recipe.direction_review.emitted`. {action_id: [attempt,
    # verify_failures, parked]} recorded at the moment the instruction was
    # emitted. An UNLATCHED escalation would re-emit on every tick and never hand
    # back a dispatch — which is a control mechanism, and d76 forbids the FSM from
    # being one. Latched, the checkpoint costs exactly one tick.
    # Emission-gated below (omitted when empty) — o6.
    escalation_emitted: dict | None = None
    # v7 P4.2 — the DISPATCH_VERIFY_LEG latch, same shape and rationale as the
    # escalation latch above: {action_id: verdict "at" stamp} recorded when
    # the advisory was emitted, so one fixed_inline verdict advises exactly
    # ONE verify-only leg (a NEWER verdict on the same action re-arms).
    # Emission-gated below (omitted when empty) — o6.
    verify_leg_emitted: dict | None = None
    # ── DESIGN-v7 1.5.2 — the PARK recovery copy ────────────────────────────
    # Stamped by pool_close_self(park=true) as {parked_at, inbox_watermark,
    # claude_session_id}. The POOL REGISTRY IS AUTHORITATIVE (its session row
    # keeps the lock + the resume token); this field is the DURABLE recovery
    # copy so a pool that loses its registry — or a neuron reconciling after a
    # restart — can still see "this plan's planner parked at T with resume
    # token S". `claude_session_id`/`inbox_watermark` may be None when unknown
    # MCP-side (the pool cuts the real watermark inside its own park op; we
    # stamp what we have). CLEARED by the plan's next successful next_action —
    # a resumed/fresh planner touching the plan proves it is live again.
    # The reconcile RESUME_PLANNER advisory latch (`resume_advised`) also
    # lives inside this dict so it clears with the park itself.
    # Emission-gated below (omitted when None) — the o6 standing bar.
    parked: dict | None = None
    # ── DESIGN-v7 1.5.6 — the STALENESS CONTRACT provenance ─────────────────
    # `grounded_at` (ISO ts) is stamped by create_plan at authoring: the
    # moment this plan's grounding snapshot was taken. A sibling step's diff
    # landing AFTER it can invalidate this DAG (the d39 class), which is what
    # the code-computed staleness delta detects. Refreshed by
    # next_action(revalidate=true) — a revalidation IS a re-grounding.
    grounded_at: str | None = None
    # `grounding_fingerprint` — the file paths this plan's grounding brief
    # named (Phase 8's record_grounding_brief APPENDS here; nothing populates
    # it until then). The EFFECTIVE fingerprint the staleness delta
    # intersects against is this list UNION the plan's action spec_ids,
    # computed in code at delta time (tools._plan_grounding_fingerprint) —
    # spec_ids live on the actions and must not be duplicated here.
    grounding_fingerprint: list[str] | None = None
    # The revalidation gate's timestamp: the moment a NON-EMPTY staleness
    # delta was handed to the planner. While set, the plan-handle dispatch/
    # wave branch REFUSES the first dispatch until a `plan_revalidated`
    # worklog line NEWER than it exists (next_action(revalidate=true) writes
    # that line and clears this). Same "the artifact must exist to be judged"
    # shape as 3.1 — no prose-sniffing.
    staleness_delta_at: str | None = None
    # ── DESIGN-v7 Phase 8 — the grounding-brief pointer ─────────────────────
    # Relative sidecar path (`<plan_id>/grounding-brief.md` under .plans/),
    # stamped by record_grounding_brief. The dispatcher injects the brief's
    # TEXT by-id into every worker's grounding and the reviewer brief; this
    # field is the addressable pointer. Emission-gated below — o6.
    grounding_brief_path: str | None = None
    # v7 WS3 (§2.4b/§2.5b, 2026-08-05) — MEASURED review + test governance,
    # stamped at authoring. Both optional dicts, emission-gated (a legacy
    # plan serializes byte-identically):
    #   review_policy — {triggers: [risk trigger names], justify: {action_id:
    #     one-line reason}}: a review leg must be justified against a named
    #     trigger (spec-required surface, protected surface, novel decision,
    #     acceptance complexity, first-action-on-spec); blanket per-action
    #     review is the write-gate refusal class.
    #   test_budget — {unit: <scope line>, integration: [seams], e2e_max: N}:
    #     the pyramid stamped from strategy + concerns; workers cannot
    #     freelance suites beyond it (the 2000-test-SPA class).
    review_policy: dict | None = None
    test_budget: dict | None = None
    # Context-diet Phase 2 — the EXPLICIT sketch->action coverage map:
    # {<step acceptance_sketch line>: [action_id, …]}. The owning step
    # declares WHAT done looks like (RecipeStep.acceptance_sketch); the
    # planner declares WHICH actions prove each line. Explicit mapping is
    # what makes the flow-down gate testable — fuzzy text-matching would
    # manufacture coverage. Emission-gated below (omitted when empty).
    sketch_covered_by: dict | None = None

    @model_serializer(mode="wrap")
    def _ser_injected_context_gate(self, handler):
        # RP-A emission gate (mirrors the Action/Decision/Comprehension gates):
        # omit `injected_context` when empty so a plan with no stamped grounding
        # serializes byte-shape-identical to the pre-RP-A schema (a pre-restart
        # extra='forbid' reader never sees the new key). Field order is
        # otherwise preserved. W10b: `escalation_emitted` rides the same gate.
        # DESIGN-v7 1.5.2/1.5.6: `parked`, `grounded_at`,
        # `grounding_fingerprint` and `staleness_delta_at` ride it too — a
        # never-parked, pre-v7 plan serializes byte-shape-identical.
        data = handler(self)
        if not data.get("injected_context"):
            data.pop("injected_context", None)
        if not data.get("escalation_emitted"):
            data.pop("escalation_emitted", None)
        if not data.get("verify_leg_emitted"):
            data.pop("verify_leg_emitted", None)
        for k in ("parked", "grounded_at", "grounding_fingerprint",
                  "staleness_delta_at", "grounding_brief_path",
                  "sketch_covered_by",
                  # v7 WS3: review/test governance ride the same gate.
                  "review_policy", "test_budget"):
            if not data.get(k):
                data.pop(k, None)
        return data
