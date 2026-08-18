"""Role → tool-surface table (DESIGN-v6 W4, tables-as-data).

Mirrors fsm/state_machines.py: pure data plus a tiny lookup helper, no
behaviour. The build_mcp seam (mcp_server.build_mcp) reads EDP_ROLE, calls
toolset_for_role(role) and — when it returns a set — registers only the
tools whose `name` is in that set. An absent/unknown role yields None, and
the seam then registers the FULL registry (fail-open: a shell is never
silently starved of tools).

Every name here is a real registered tool `name` (see ALL_TOOL_CLASSES in
tools/_tools.py) — including `record_context`, the DESIGN-v6 memory-write
consolidation verb (RecordContext, now registered) that supersedes the
four memory-write verbs in _CONSOLIDATED_OUT. Those old verb classes stay
REGISTERED globally — so the unit tests and the absent-role full set keep
working — they are simply absent from every role's scoped surface. This
module holds the DATA table only; the build_mcp seam does the wiring.
"""

import os

from ._tools import ALL_TOOL_CLASSES

# ── spec-authoring carve-out (SPECIALIST_ONLY) ─────────────────────────────
# Authoring spec CONTENT is the specialist's job alone (discipline invariant
# o7). These verbs appear in NO other role's surface — not even the
# neuron's, which triages and spawns specialists but never authors specs.
SPECIALIST_ONLY: frozenset[str] = frozenset({
    "add_spec_entry",
    "update_specialist",
    "write_specialist_doc",
    "create_specialization",
})
# s25/a4 (neuron ruling, d62 option (a)) — `assemble_ruleset` was MISFILED here.
# This set is defined by AUTHORING (o7), and assemble_ruleset authors nothing:
# AssembleRuleset (_tools.py:6842-6868) is `idempotent = True`, its docstring
# says "Pure lookup, byte-stable per inputs", and its _run's only store access
# is `ctx.specs.load`. It WRITES NOTHING. Its docstring even opens "Resolve a
# WORKER's EFFECTIVE ruleset" — naming the role it was withheld from. Under
# enforce, no worker could assemble the ruleset for a `concerns=[X]` action,
# though planner-phase-author.md and neuron.md both describe exactly that.
# It is now granted explicitly to _WORKER, _REVIEWER and _SPECIALIST (which had
# inherited it through the `| SPECIALIST_ONLY` union below and would otherwise
# have silently LOST it). o7 is untouched: the four remaining verbs are the
# spec-authoring surface, and they stay disjoint from every other role.
# Consequence, accepted by the neuron: _NEURON is DERIVED as
# _ALL_TOOL_NAMES - SPECIALIST_ONLY - _CONSOLIDATED_OUT, so the neuron surface
# gains it automatically (77 -> 78). Consistent with "the neuron drives
# everything EXCEPT authoring spec content", and the verb is read-only.

# The consolidated memory-write verb. `record_context(kind=…)` replaces the
# four write verbs in _CONSOLIDATED_OUT on every role surface; its class
# (RecordContext) is registered in ALL_TOOL_CLASSES, so the `| {RECORD_CONTEXT}`
# union in _ALL_TOOL_NAMES below is now redundant but harmless (idempotent).
RECORD_CONTEXT = "record_context"

# ── the memory-write consolidation ─────────────────────────────────────────
# These four write verbs collapse into record_context and so appear in NO
# role surface. `recall` (the READ side) is untouched and stays. The classes
# remain registered globally for the unit tests + the absent-role fallback.
_CONSOLIDATED_OUT: frozenset[str] = frozenset({
    "record_decision",
    "record_assumption",
    "record_rejected_option",
    "remember",
})

# ── W6.4: the SUPERSEDED verbs ─────────────────────────────────────────────
# Same shape as _CONSOLIDATED_OUT above, one milestone later. Each of these has
# a live successor that reaches strictly further; the verb is retired from every
# role surface (including the DERIVED _NEURON) while its CLASS stays registered,
# so the unit tests and the absent-role full set keep working.
#
# ATOMICITY IS THE WHOLE POINT (DESIGN-v6 W6.4). Retiring a verb from a toolset
# while a guide still INSTRUCTS it recreates the planner-CRUD regression class
# (d14): under enforce the role cannot follow its own guide. So each entry here
# landed together with the guide sweep that removed its last call form, and
# `tests/test_s26_guide_tool_names.py::test_no_live_guide_calls_a_retired_verb`
# is the standing guard that keeps it that way.
_SUPERSEDED_OUT: frozenset[str] = frozenset({
    # → get_specialist_docs(spec_ids=[…]). The plural is a strict superset: it
    #   is a pass-through for the single-spec case and the ONLY verb that can
    #   compose a MULTI-spec (cross-stack) action's grounding.
    "get_specialist_doc",
    # → emit_recipe_event(kind="learning", body={…}), which AUTO-PROPOSES to the
    #   spec's quarantined sidecar (W3; _tools.py:5822 `_autopropose_learning`,
    #   wired at :5985). The explicit verb is, in the words of its own call site,
    #   "no longer load-bearing".
    #   DISCLOSED DELTA (not a silent narrowing): the auto-propose path writes the
    #   W3 record shape (rule_text/tag/overrides/source — spec_store.py:234) and
    #   carries NO `kind`, so a learning can no longer be classified
    #   `kind="anti_pattern"` AT PROPOSE TIME; `adherence` survives as `tag`, and
    #   resolve_spec_learnings defaults a kind-less record to a neutral
    #   `checklist` entry on accept (spec_store.py:293-297).
    "propose_spec_learning",
    # → resolve_spec_learnings (BATCH). The plural is a genuine semantic upgrade,
    #   not a rename: the singular only marked promoted/rejected and left the
    #   entry-append + recompile to a human; the batch verb carries rule_text/tag/
    #   overrides forward, appends the rule to `spec.entries` and bumps the
    #   version ONCE (spec_store.py:273-299).
    "resolve_spec_learning",
    # → add_step / update_object("step", …) / record_step_result, the guarded
    #   intent verbs its own docstring points at (_tools.py:3480-3486: "This tool
    #   replaces the matching step VERBATIM … no guards, no advisories — so a
    #   malformed dict here corrupts the map").
    #   RETIRED ON AN EMPTY AUDIT, as DESIGN-v6 W6.4 requires ("only retire
    #   record_step if the call-site audit comes back empty"). The audit: ZERO
    #   call sites in the live shell-facing corpus (.claude/commands/*.md +
    #   docs/guides/*.md) and ZERO callers in src/. The one live-code reference
    #   WAS `InstructionKind.RECORD_STEP` — a declared instruction kind that NO
    #   FSM ever emitted (unlike `invoke_skill`, which plan_fsm.py really does
    #   emit); the dead enum member and the RecordStep class were deleted in the
    #   2026-08-12 dead-surface retirement.
    "record_step",
})

# ── OPERATOR RETIREMENT (2026-07-25) ───────────────────────────────────────
# Retired by explicit operator ruling, NOT because a successor reaches further.
# The operator's stated reason: "I found it useless and will burn tokens. the
# consults were meant to plug in a higher level model but I dont see the need
# for one right now."
#
# DISCLOSED COST, accepted by the operator after it was put to them: this is the
# ONLY response W10's escalation ladder had to a stuck action. `next_action`
# still EMITS `ESCALATE_CONSULT` (plan_fsm.escalate_consult) — the instruction is
# advisory and holds no dispatch (d76), so nothing blocks — but its rationale is
# reworded here-adjacent to stop naming a verb no role holds, per the d14 rule
# that a role must never be instructed to call a tool it cannot see.
#
# WHAT SURVIVES: `consult_specialist` (read a compiled specialist doc inline) and
# `consult_curiosity` (the persistent comprehension neuron) are untouched — this
# retires only the SPAWNED higher-tier consult shell.
#
# REVERSIBLE: delete this set from the RETIRED_VERBS union below and restore the
# `_PLANNER` entry to bring it back; the tool CLASS stays registered, as with
# every other retirement here.
_OPERATOR_RETIRED: frozenset[str] = frozenset({
    "convene_consult",
})

# ── DEAD-SURFACE RETIREMENT (2026-08-12) ───────────────────────────────────
# Superseded by the provider-bridge delegates (tools/bridge.py, v7 WS1):
#   sol_consult      → consult_external (one-shot cross-provider verdict)
#   sol_author_asset → delegate_generate (route-gated delegation)
# Both tool CLASSES are deleted from _tools.py along with their registrations
# and catalog entries. The sol_bridge.py ENGINE survives untouched — it is the
# live `cli` backend of the bridge (bridge.py imports run_sol), so retiring
# the two direct verbs removes surface, never capability. The standalone
# consult SHELL ROLE was retired in the same sweep (its only spawn verb,
# convene_consult above, went 2026-07-25); the LIVE consult_* tools
# (consult_specialist / consult_curiosity / consult_external /
# record_specialist_consult) are untouched.
_BRIDGE_SUPERSEDED: frozenset[str] = frozenset({
    "sol_consult",
    "sol_author_asset",
})

# Every verb retired from every role surface. DERIVED, so a consumer (the
# guide-corpus gate, the neuron subtraction) can never hand-copy a list that
# drifts from this one — the same argument test_w4_roles makes for importing
# _CONSOLIDATED_OUT rather than re-spelling it.
RETIRED_VERBS: frozenset[str] = (
    _CONSOLIDATED_OUT | _SUPERSEDED_OUT | _OPERATOR_RETIRED
    | _BRIDGE_SUPERSEDED)

# ── F1 (2026-08-17): the DELIBERATELY-UNSCOPED registered verbs ────────────
# Every registered tool must appear in >=1 role surface OR be named here —
# tests/test_f1_role_registration_drift.py enforces it, so a NEW tool can
# never silently fall outside the role map (it fails CI until someone scopes
# it or consciously lists it). These five are documented cuts:
#   * create_object — the planner creates via create_plan/add_action, the
#     neuron via add_step; the generic verb serves only the role-less
#     foreground/test shells (absent-role full set).
#   * neuron_get/list/touch/flag — neuron-DB row verbs no role guide calls
#     (the 2026-07-30 neuron positive-list cut); kept registered for the
#     absent-role full set + unit tests.
UNSCOPED_OK: frozenset[str] = frozenset({
    "create_object",
    "neuron_flag", "neuron_get", "neuron_list", "neuron_touch",
})

# ── per-role scoped surfaces (tool NAMES) ──────────────────────────────────
# WORKER — execute ONE action + report: read state, load spec docs, record
# status/context/facts, talk to the planner, close self. Ceiling <=21 (W6.4:
# -get_specialist_doc, -propose_spec_learning; both in _SUPERSEDED_OUT).
_WORKER: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    # `emit_recipe_event(kind="learning", …)` is ALSO the worker's spec-flowback
    # verb now (W3 auto-propose), which is what retired `propose_spec_learning`.
    "emit_recipe_event", "status_ping",
    "get_guide",
    "read_object", "query_objects", "describe_objects", "observe", "arm_wiring", "list_subscriptions", "unobserve",
    "record_action_status", RECORD_CONTEXT, "recall", "search_context",
    "read_worklog",
    "get_specialist_docs",
    # s25/a4 — the coder's own ruleset-composition verb (see SPECIALIST_ONLY).
    # NO NEW REACH: the worker already holds read_object/query_objects over the
    # readable `spec` object type, so it can walk the extends-chain and compose
    # the union by hand — expensively, without cycle detection or byte-stability.
    # This is the CHEAP, correct path to data the role can already obtain. Same
    # form as the get_recipe_digest and status_ping arguments.
    "assemble_ruleset",
    "consult_specialist",
    # (sol_author_asset retired 2026-08-12 — see _BRIDGE_SUPERSEDED above.
    # Visual/asset delegation rides delegate_generate below.)
    # v7 WS1 (2026-08-05) — the delegation layer: bulk generation routed to a
    # cheap external model (frontier plans, cheap executes, the WORKER
    # verifies). Route-gated in .bridge.json — an unrouted (role, task_class)
    # refuses with "do this work yourself", so holding the verb grants nothing
    # until a human routes it. The draft returns as TEXT; the worker still owns
    # integrate/build/test/record — no reach beyond work it already does.
    "delegate_generate",
    # v7 WS3 (§2.5b) — the worker REGISTERS every test it writes (verifies +
    # covers). Write-only over the derived graph sidecar; refusing a test
    # that verifies nothing is the false-security gate. No new reach — it
    # describes work the worker already did.
    "record_test_lineage",
    # v7 WS7 (SHADOW.md §4) — the shadowed shell's sovereignty seam:
    # inspect/repair/override the sidecar that runs your wiring. Reads a
    # ledger file + appends commands; no object reach. Refuses outright in
    # an unshadowed shell, so the grant is inert on the legacy path.
    "reflex",
    "pool_close_self",
})

# PLANNER — uphold the plan FSM: next_action/reconcile, author the plan,
# spawn+reap workers, report the step result up. Ceiling <=34 — the DERIVED
# floor, and the surface sits exactly on it. (s29/a4 REVIEW: this line read
# "<=32" and was stale; s25/a4 had already raised the floor 32->34 with
# `status_ping` + `neuron_search`, both DERIVED-FLOOR entries below, and
# test_w4_roles.CEILINGS has said 34 since. The code was right; the comment
# rotted.)
_PLANNER: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "describe_objects", "observe", "arm_wiring", "list_subscriptions", "unobserve",
    # d17 (W11/a6, neuron ruling e0cdcfe2) — a LATENT enforce-mode BREAK.
    # THREE planner guides instruct the planner to call this
    # (planner-phase-ground.md, planner-phase-drive.md, planner-phase-author.md:
    # "after a compaction, off `get_recipe_digest`"), yet it sat only in
    # _CONSULT and reached the neuron through the _ALL_TOOL_NAMES subtraction.
    # Under EDP_ROLE_SCOPE=enforce the planner's post-compaction reground would
    # be REFUSED, and its only fallback — read_object('recipe') — is 169k chars
    # for a mature recipe and does not fit in a tool result. The role that most
    # needs the digest would have had no viable reground.
    #
    # DERIVED FLOOR, not a relaxation (same grounds as this surface's 27->29,
    # 14->15, 29->30 and 30->31 precedents): a verb a role's OWN guides REQUIRE
    # it to call cannot be folded away the way prose can, so the floor moved
    # 31->32. It grants NO new reach — the planner already holds read_object /
    # query_objects / search_context over the same recipe; the digest is only a
    # CHEAPER path to data it can already obtain expensively.
    "get_recipe_digest",
    # s25/a4 (B3) — two more DERIVED-FLOOR entries on the SAME grounds as
    # get_recipe_digest above. Both are instructed by the planner's OWN guides
    # and both were VERIFIED to be latent enforce-mode breaks (a1 blocker 3,
    # a2 findings 2+4). Neither grants new reach:
    #   * status_ping — planner-phase-drive.md:174 ("Cheap child checks") and
    #     environment-discovery.md:20 instruct it per child, and reconcile's own
    #     wait_reason tells the planner to run it. The planner already holds
    #     inspect_worker, the EXPENSIVE probe over the same child; status_ping is
    #     the CHEAP one. Reaching strictly less, not more.
    #   * neuron_search — planner-phase-author.md:112 + planner-phase-drive.md
    #     instruct it to resolve a declared `specialization` to a spec_id BEFORE
    #     dispatch. This is the HARD one: PoolSpawnWorker._run's guard B
    #     (_tools.py:4038) REFUSES to spawn while any declared specialization is
    #     unresolved, so without this verb the planner's entire specialist
    #     dispatch path is dead under enforce. It is a read-only search over the
    #     neuron DB — no reach beyond the reads the planner already holds.
    # NOT granted here: `broker_send`. Its two guide call sites both address the
    # planner's own parent, which `notify_above`/`ask_above` already do — and it
    # takes an ARBITRARY `to=`, so granting it WOULD widen reach and fails the
    # precedent's own test. The guide is fixed instead; see planner-phase-drive.md.
    "status_ping", "neuron_search",
    # F5 (2026-08-17) — the routed correction verb. The card's law
    # ("corrections are STEERS") used to prescribe a broker send this
    # surface never held; steer_worker resolves the live worker's address
    # from the planner's OWN plan and records the send for ack correlation.
    "steer_worker",
    "next_action", "reconcile", "create_plan", "record_plan", "add_action",
    # v7 P8 — the planner AUTHORS the grounding brief its own guides mandate
    # (planner-phase-ground.md: write the map once; every worker + the
    # reviewer brief receive it via injection). Derived floor: writes only
    # the planner's OWN plan sidecar/fields — no new reach beyond the plan
    # CRUD it already holds.
    "record_grounding_brief",
    # W4 remediation (d14/d15): the planner MUST keep the generic object-CRUD
    # verbs to mutate its OWN plan's actions/steps at runtime (deps/status/
    # verify/description healing, deleting an obsolete action) — the regression
    # was that W4 dropped these, so a spawned planner could only re-author the
    # whole action set. Scope is enforced PER OBJECT-TYPE in-tool (plan+action
    # only) via CRUD_OBJECT_SCOPE below, NOT by withholding the verb. Matches
    # docs/design/v6-audit/role-toolsets-derived.md PLANNER floor: update_object
    # + delete_object, and NOT create_object (the planner creates via
    # create_plan/add_action, never the generic create_object).
    "update_object", "delete_object",
    "record_action_status", "record_step_result",
    "pool_spawn_worker", "pool_reap", "inspect_worker", "read_worklog",
    RECORD_CONTEXT, "recall", "search_context",
    # -consult_pattern_observer — the role is DEAD (owner ruling 2026-08-04).
    "consult_specialist",
    # v7 WS1 (2026-08-05) — the ADVERSARIAL pass on the planner's OWN
    # pre-ratification plan (§2.2b): Sol attacks the DAG/acceptance through a
    # named lens and returns FINDINGS-ONLY data the planner adjudicates through
    # the normal write-gates. The delegate holds no shell, no broker sender
    # beyond `challenge` kinds, no write path — attacking one's own draft
    # grants no reach. Route-gated in .bridge.json (unrouted = refuse).
    "adversarial_challenge",
    # v7 WS3 (§2.5b) — the planner reads the dead-test report to author
    # retirement actions and the impacted set to size review legs. Read-only
    # over the derived graph index.
    "test_lineage_report",
    # v7 WS3 (§2.6c) — the planner estimates at declaration and re-checks
    # planned-vs-actual when sizing waves. Read-only.
    "budget_status",
    # v7 WS7 (SHADOW.md §4) — the shadowed shell's sovereignty seam:
    # inspect/repair/override the sidecar that runs your wiring. Reads a
    # ledger file + appends commands; no object reach. Refuses outright in
    # an unshadowed shell, so the grant is inert on the legacy path.
    "reflex",

    # W5 (DESIGN-v6 §W5) granted the planner `convene_consult` so it could
    # convene a consult for a stuck action. RETIRED 2026-07-25 by operator
    # ruling — see `_OPERATOR_RETIRED` above for the reason, the disclosed cost
    # (W10's ladder loses its only response to a stuck action) and how to
    # revert. Left as a comment rather than deleted so the W5 provenance, and
    # the fact that this was a deliberate removal rather than an oversight,
    # survive in the file the toolset is read from.
    "pool_close_self",
})

# REVIEWER — load the specialist doc, judge the target, record the verdict,
# close. Deliverable fixes land via the harness editor, not an MCP verb.
# (W15 +search_context — reviewers can ASK the recipe too. W6.4
# -propose_spec_learning — see the withdrawal note on that entry. d128/d132
# -record_direction_verdict: W9's direction MODE is removed, and that verb's
# only producer went with it. Ceiling <=17 — s29/a4 REVIEW tightened it from 18,
# which was the PRE-a2 floor: a2's deletion took this surface to 17 while the
# guard still permitted 18, i.e. one unit of silent regrowth. The ceiling is the
# floor, never headroom.)
#
# record_context SURVIVES the direction-mode removal, on its own merits: a
# reviewer PROPOSES a constraint-shaped finding with
# `record_context(kind="rejected_option", constraint={…})`, and
# RecordRejectedOption lands every constraint-bearing ban as status="proposed"
# for EVERY caller — so the grant cannot become steering. The ONLY path to
# "active" is confirm_direction_constraints, which is neuron-scoped and is
# deliberately NOT in this set.
# NOT granted: confirm_direction_constraints, pool_spawn_worker, any CRUD verb.
_REVIEWER: frozenset[str] = frozenset({
    RECORD_CONTEXT,
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "observe", "arm_wiring", "list_subscriptions", "unobserve",
    "get_specialist_docs", "search_context",
    # W6.4 — `propose_spec_learning` WAS granted here by s25/a4 as a DERIVED
    # FLOOR (reviewer.md:141 instructed it). That grant is now WITHDRAWN, and the
    # withdrawal is the OTHER branch of the same d62 remedy test that created it:
    # d62(b) FIX THE GUIDE. Reviewer flowback is still a designed feature and is
    # NOT lost — reviewer.md now instructs `emit_recipe_event(kind="learning", …)`,
    # which AUTO-PROPOSES to the spec's quarantined sidecar (W3). The reviewer
    # keeps `emit_recipe_event`, so the capability survives the verb.
    # s25/a4 — neuron-phase-e.md:58: "the reviewer assemble_ruleset`s the FULL
    # layered ruleset". Read-only; same no-new-reach argument as _WORKER's.
    "assemble_ruleset",
    "record_branch_verdict", "read_worklog",
    # v7 P4.1 — the reviewer closes its OWN review leg. The verb is granted
    # WITH an in-tool scope guard: under EDP_ROLE=reviewer,
    # RecordActionStatus refuses any action whose `<plan_id>:<action_id>`
    # differs from EDP_HANDLE — the reviewer can never flip a reviewed
    # action or overwrite a worker's evidence (the d30 independence stands;
    # this answers the objection that kept the verb off this floor and
    # forced review legs to run as role="worker", the d67/d100 no-op class).
    "record_action_status",
    # v7 WS1 (2026-08-05) — cheap cross-family PRE-SCREEN of an artifact
    # against its acceptance. The delegate's verdict never decides — the
    # reviewer adjudicates in record_branch_verdict exactly as before, so this
    # is a cheaper path to scrutiny the reviewer already performs, not new
    # reach. Route-gated in .bridge.json (unrouted = refuse).
    "delegate_review",
    # v7 WS3 (§2.5b) — the impacted-test set for the diff under review (run
    # these, not the world) + the dead-test report. Read-only over the
    # derived graph index.
    "test_lineage_report",
    # v7 WS7 (SHADOW.md §4) — the shadowed shell's sovereignty seam:
    # inspect/repair/override the sidecar that runs your wiring. Reads a
    # ledger file + appends commands; no object reach. Refuses outright in
    # an unshadowed shell, so the grant is inert on the legacy path.
    "reflex",
    "pool_close_self",
})

# SPECIALIST — the ONLY role that authors spec content (SPECIALIST_ONLY
# folded in). Self-trains, compiles + versions its doc. No count ceiling.
_SPECIALIST: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "describe_objects", "observe", "arm_wiring", "list_subscriptions", "unobserve",
    RECORD_CONTEXT, "recall",
    "train_specialist", "record_spec_version",
    # s25/a4 (B3) — DERIVED FLOOR. `.claude/commands/specialist.md:137`
    # prescribes neuron_set_base_session(…) under a bold "This call is what
    # makes you USABLE — do not skip it", and :294/:303 prescribe
    # neuron_set_status(…) for the HITL approval gate. Without both, a specialist
    # cannot COMPLETE ITS OWN TRAINING under enforce. Both act only on the
    # specialist's OWN neuron row — no new reach.
    # NOT granted: `update_object`. specialist-training.md:31's
    # `update_object(type="spec")` is DESCRIPTIVE of append-only API semantics,
    # not an instruction; no role (not even the neuron) carries "spec" in
    # CRUD_OBJECT_SCOPE, so the verb would register and then be refused by
    # _guard_object_crud. The specialist's real authoring path is add_spec_entry
    # (SPECIALIST_ONLY, below). The guide sentence is fixed instead.
    "neuron_set_base_session", "neuron_set_status",
    # W6.4: -get_specialist_doc (superseded by the plural, a pass-through for
    # the single-spec case) and -resolve_spec_learning (superseded by the BATCH
    # resolve_spec_learnings, which also appends the entry + bumps the version).
    "get_specialist_docs", "get_specialization",
    "list_spec_learnings", "resolve_spec_learnings",
    "check_specialist_decay",
    # s25/a4 — RE-ADDED EXPLICITLY. It used to arrive via the
    # `| SPECIALIST_ONLY` union below; now that it has (correctly) left that
    # set, the specialist would SILENTLY LOSE the verb its own
    # specialist.md:218 calls. Named here so the grant is visible, not inherited.
    "assemble_ruleset",
    "record_specialist_consult", "register_rule", "list_rules",
    # v7 WS1 (2026-08-05) — the adversarial pass on the specialist's OWN spec
    # `decision` entries (§2.6: chosen-option + alternatives + revisit_when —
    # exactly where wrong-option-baked-in lives). Findings-only, adjudicated by
    # this same role through resolve_spec_learnings/recompile; no write path in
    # the delegate. Route-gated in .bridge.json (unrouted = refuse).
    "adversarial_challenge",
    # v7 WS7 (SHADOW.md §4) — the shadowed shell's sovereignty seam:
    # inspect/repair/override the sidecar that runs your wiring. Reads a
    # ledger file + appends commands; no object reach. Refuses outright in
    # an unshadowed shell, so the grant is inert on the legacy path.
    "reflex",
    "pool_close_self",
}) | SPECIALIST_ONLY

# (CONSULT — the standalone convened-consult SHELL ROLE — was retired in the
# 2026-08-12 dead-surface sweep. Its only spawn verb, `convene_consult`, went
# 2026-07-25 (_OPERATOR_RETIRED above), which left the role unreachable: no
# registered tool spawned role="consult" and .claude/commands/consult.md was
# an activator no shell could receive. The toolset row, the activator card,
# the models.json seat mapping and the edp-pool shadow entries were deleted
# together. The LIVE consult verbs — consult_specialist, consult_curiosity,
# consult_external, record_specialist_consult — are untouched; they belong to
# the surviving roles' surfaces.)

# NEURON — POSITIVE LIST (context-diet Phase 3b, 2026-07-30). The old
# derived-subtractive form (`_ALL_TOOL_NAMES - SPECIALIST_ONLY -
# RETIRED_VERBS`) auto-granted every NEW tool to the neuron and left it
# holding 83 of 87 verbs — including the specialist's read/consult internals
# and the planner's authoring verbs, which is how the neuron came to DO
# specialist work instead of delegating it (operator complaint, 2026-07-30).
#
# CURATION BASIS: the audited guide floor — every verb the neuron's OWN
# corpus (.claude/commands/neuron.md + docs/guides/neuron*/orchestrator*/
# loop-and-heartbeat/channel-coordination/framework-ocak/external-neuron/
# environment-discovery/verification-craft) instructs with a call form
# (54 names, audit 2026-07-30) — plus the operational verbs below that no
# guide spells with parens but the role demonstrably needs. The d14 rule
# holds: no guide instructs a verb this surface lacks.
#
# CUT (22): the planner's authoring surface (add_action, create_plan,
# record_plan, record_grounding_brief, create_object), the reviewer's verdict
# verb (record_branch_verdict), the specialist's craft/read surface
# (assemble_ruleset, get_specialist_docs, get_specialization,
# record_spec_version, register_rule, list_rules, check_specialist_decay,
# neuron_set_base_session, neuron_set_status), Sol authoring/consult
# (sol_author_asset, sol_consult), the expensive child probe
# (inspect_worker — status_ping is the neuron's probe), and the neuron-DB
# row verbs no neuron guide calls (neuron_flag, neuron_get, neuron_list,
# neuron_touch). The neuron DELEGATES: it train_specialist's, it never
# authors or assembles spec content.
#
# CEILING IS THE FLOOR (test_w4_roles discipline): 61 today. The DESIGN-v6
# "<=45" target is now reachable but requires the Phase-5 guide triage
# first — several floor entries (record_action_status, pool_spawn_worker,
# record_recipe, run_ocak_audit) are believed to be DESCRIPTIVE mentions
# that the card rewrite will delete; each deletion lowers the floor and the
# ceiling together. Do not re-add a cut verb without a guide call form.
_ALL_TOOL_NAMES: frozenset[str] = frozenset(
    cls.name for cls in ALL_TOOL_CLASSES
) | {RECORD_CONTEXT}
_NEURON: frozenset[str] = frozenset({
    # identity + lifecycle of the recipe itself
    "whoami", "start_recipe", "resolve_recipe", "resume_recipe",
    "suspend_recipe", "close_recipe", "record_recipe",
    # comprehension + outcomes
    "record_comprehension_signoff", "record_user_answer", "record_outcome",
    "mark_outcome_met", "record_audit_verdict", "run_ocak_audit",
    "seed_comprehension_specialists",
    # the map: steps + decisions + context hygiene
    "add_step", "record_step_result", "update_object", "delete_object",
    RECORD_CONTEXT, "fold_decisions", "supersede_decision",
    "confirm_direction_constraints", "ensure_universal",
    # grounding reads
    "get_recipe_digest", "read_object", "query_objects", "describe_objects",
    "recall", "search_context", "read_worklog", "get_guide", "neuron_search",
    # the drive loop + wiring
    "next_action", "reconcile", "observe", "arm_wiring", "unobserve", "list_subscriptions",
    "emit_recipe_event", "arm_external_driver", "disarm_external_driver",
    # comms
    "check_inbox", "reply", "broker_send", "ask_above", "notify_above",
    # children: spawn planners, probe cheaply, reap, resume
    # OWNER RULING (2026-08-04): -branch_reviewer — should never have been on
    # the neuron's surface at all (d128's absolute reading confirmed); the
    # neuron delegates review, it does not convene reviewers itself.
    "pool_spawn_planner", "pool_resume_planner", "pool_spawn_worker",
    "pool_reap", "status_ping", "record_action_status",
    # advisors + specialist DELEGATION (never authoring)
    # -consult_goal_keeper / -consult_pattern_observer — DEAD roles (owner
    # ruling 2026-08-04); their tool classes are deleted with them.
    "consult_curiosity",
    # F31 — the FSM's DISPATCH_ACCEPTANCE instruction is obeyed with this.
    "dispatch_acceptance",
    "consult_specialist", "record_specialist_consult", "train_specialist",
    "list_spec_learnings", "resolve_spec_learnings",
    # v7 WS3 (§2.6c) — planned-vs-actual budget, code-assembled (star budget
    # + step estimates + delegate audit sidecars). Read-only; feeds the G6
    # budget gate at reconcile. No reach beyond reads the neuron holds.
    "budget_status",
    "pool_close_self",
})

# ── the ADVISORY role (s25/a4, B3) ─────────────────────────────────────────
# `clients/http_pool.py` spawns curiosity and `pty_launcher.py:400` stamps its
# EDP_ROLE; a role spawned without a row here makes `toolset_for_role` return
# None and `build_mcp` FAIL OPEN to the full registry — the over-grant trap
# this row exists to close. THE KEY IS THE UNDERSCORE FORM, from
# `http_pool.py`; `test_every_pool_spawned_role_has_a_toolset` derives the
# keys from that source so a mismatched key cannot silently do nothing.
# The set is the union of the verbs the role's OWN command file calls, plus
# `pool_close_self`. Read-only: no authoring, no spawn, no mutation.
# (goal_keeper / pattern_observer, the other two advisory roles this block
# once defined, are DEAD — owner ruling 2026-08-04; see below.)
_CURIOSITY: frozenset[str] = frozenset({
    "check_inbox", "get_guide", "notify_above", "observe", "arm_wiring", "list_subscriptions", "unobserve", "read_object",
    "reply",
    # v7 WS1 (2026-08-05) — the curiosity role's PURPOSE is bias removal; a
    # cross-provider verdict makes that structural (a different model family
    # audits the same evidence). Read-only advisory posture unchanged;
    # route-gated in .bridge.json (unrouted = refuse).
    "consult_external",
    # v7 WS7 (SHADOW.md §4) — the shadowed shell's sovereignty seam:
    # inspect/repair/override the sidecar that runs your wiring. Reads a
    # ledger file + appends commands; no object reach. Refuses outright in
    # an unshadowed shell, so the grant is inert on the legacy path.
    "reflex",
    "pool_close_self",
})

# OWNER RULING (2026-08-04): goal_keeper and pattern_observer are DEAD roles —
# rows, toolsets, tool classes, activator cards and spawn paths all deleted
# (history at 18cac3f). `test_every_pool_spawned_role_has_a_toolset` derives
# its keys from http_pool.py, whose spawn methods went with them.

# ── F31 (2026-08-18, owner ruling): the ACCEPTOR — the final goal-vs-
# delivery pass, run by the advisor seat (Fable) in ITS OWN shell. It
# verifies the whole delivery against the VERBATIM goal + any artifact the
# goal names, fixes what it safely can (file edits ride the harness tools,
# not MCP verbs), and records the verdict via emit_recipe_event(kind=
# 'acceptance_verdict') — the artifact G-ACCEPT gates close on. This closes
# the Sol-review #2 hole: the checker fetches its OWN evidence instead of
# grading what the neuron hands it. Read-only over the object graph; its
# only "writes" are the verdict event, context notes, and test lineage for
# tests it adds while fixing.
_ACCEPTOR: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "describe_objects",
    "observe", "arm_wiring", "list_subscriptions", "unobserve",
    RECORD_CONTEXT, "recall", "search_context", "read_worklog",
    "get_recipe_digest", "get_specialist_docs", "assemble_ruleset",
    "test_lineage_report", "record_test_lineage",
    # cross-family second opinion on a close call — never the verdict itself
    "consult_external", "delegate_review",
    "status_ping", "reflex",
    "pool_close_self",
})

ROLE_TOOLSETS: dict[str, frozenset[str]] = {
    "worker": _WORKER,
    "planner": _PLANNER,
    "reviewer": _REVIEWER,
    "specialist": _SPECIALIST,
    "neuron": _NEURON,
    "curiosity": _CURIOSITY,
    "acceptor": _ACCEPTOR,
}


def toolset_for_role(role: str | None) -> frozenset[str] | None:
    """The scoped tool-name surface for `role`, or None when the role is
    absent/unknown. F37#5: the seam (mcp_server.build_mcp) now fails CLOSED
    on None — full registry only for a role-less NON-spawned operator
    console; unknown role or spawned-without-role refuses to build."""
    if not role:
        return None
    return ROLE_TOOLSETS.get(role)


# ── spawn model resolution (v7 WS4 seat registry) ──────────────────────────
# DEAD-SURFACE RETIREMENT (2026-08-12): the DESIGN-v6 W10b MODEL_TIERS table
# and its lookups (`resolve_model_tier`, `HOST_DEFAULT_MODEL`, `SONNET` /
# EDP_WORKER_SONNET_MODEL, `DEFAULT_TASK_CLASS`) are DELETED. The seat
# registry (edp_contracts.seats over models.json at EDP_AGENT_HOME) has been
# the authoritative role→model binding since v7 WS4 §2.4b; the tier table was
# its dormant fallback and — with no measured row and Opus the default for
# every role — resolved to "pass no --model flag" for every un-opted-in
# spawn. The pool config dir pins its own default model
# (.claude-pool/settings.json "model"), so a no-flag spawn still never falls
# to the ACCOUNT default. History: git tag checkpoint-pre-harness-improvements.
def spawn_model_for(role: str, task_class: str = "*", *,
                    allow_candidate_tier: bool = False) -> str | None:
    """The `model` a spawn should pass to the pool, resolved ONLY via the v7
    seat registry (models.json at EDP_AGENT_HOME), or None to pass NO model
    flag at all (the shell then falls to the pool config's pinned default,
    never the account default).

    `task_class` and `allow_candidate_tier` are accepted for call-site
    compatibility (pool_spawn_worker threads them) and IGNORED: the retired
    tier table was their only consumer. A mapped seat's exact pinned model is
    returned VERBATIM — explicit beats implicit at the spawn seam. Unset
    EDP_AGENT_HOME / absent registry / unmapped role → None. A
    PRESENT-but-invalid registry raises SeatsError at spawn: misconfiguration
    is loud, never a silent default.

    Registry home resolves from EDP_AGENT_HOME ONLY — never cwd. A
    coincidental-cwd config pickup is the PWD-resolution landmine class (the
    opencode M1 lesson), and it would leak the live registry into every
    hermetic test and stray invocation. Unset env = no registry = None,
    deterministically."""
    del task_class, allow_candidate_tier    # legacy tier-table params, unused
    _home = os.environ.get("EDP_AGENT_HOME", "").strip()
    if not _home:
        return None
    try:
        from edp_contracts.seats import seat_for_role as _seat_for_role
    except ImportError:
        return None
    _seat = _seat_for_role(_home, role)
    return _seat.model if _seat is not None else None


# ── per-role object-CRUD object-type scope (tables-as-data, DESIGN-v6 W4) ────
# The generic object-mutation verbs (create_object / update_object /
# delete_object) are governed PER ROLE and PER OBJECT-TYPE — restoring the
# verb to a role (planner regains update/delete above) is NOT the same as
# letting it mutate ARBITRARY objects. A role's value here is the exact set of
# object-types it may create/update/delete through those verbs. Mirrors
# docs/design/v6-audit/role-toolsets-derived.md CRUD lines: planner = plan +
# action ONLY (line 24); the neuron additionally recipe/step/north_star
# (the recipe owner); every other role is read-only over the generic verbs
# (they mutate state only through their own role verbs — worker via
# record_action_status, specialist via the SPECIALIST_ONLY authoring verbs).
# Reading conventions used by `crud_scope_violation`:
#   role PRESENT, object_type in the set  → allowed
#   role PRESENT, object_type NOT in set  → violation (incl. an empty set =
#                                           read-only role: every type refused)
#   role ABSENT from the table / EDP_ROLE unset/unknown → UNCONSTRAINED
#     (fail-open: the human foreground shell keeps full CRUD, matching the
#     build_mcp absent-role full-set rule).
CRUD_OBJECT_SCOPE: dict[str, frozenset[str]] = {
    "planner": frozenset({"plan", "action"}),
    "neuron": frozenset({"plan", "action", "recipe", "step", "north_star"}),
    "worker": frozenset(),
    "reviewer": frozenset(),
    "specialist": frozenset(),
    # ("consult" row deleted with its role — 2026-08-12 dead-surface sweep.)
    # s25/a4: the advisory role is read-only over the generic verbs, closing
    # the same fail-open hole `crud_scope_violation` had for it (an ABSENT
    # role returns None = UNCONSTRAINED full CRUD). goal_keeper /
    # pattern_observer rows deleted with their roles (owner ruling 2026-08-04).
    "curiosity": frozenset(),
    # F31: the acceptor judges and fixes FILES (harness tools), never the
    # object graph — read-only over the generic CRUD verbs.
    "acceptor": frozenset(),
}


def crud_scope_violation(role: str | None, object_type: str) -> str | None:
    """PURE predicate (no I/O, no env read). None when `role` may mutate
    `object_type` through the generic object-CRUD verbs; otherwise a
    refuse-and-explain message naming the role and its allowed object-types.

    An absent/unknown role is unconstrained (the human foreground shell keeps
    full CRUD) → None. A KNOWN role with an empty grant is read-only → every
    object-type is a violation. The CALLER (tools/_tools.py) decides warn-log
    vs enforce-refuse via EDP_ROLE_SCOPE; this only says whether the (role,
    object_type) pair is on-scope."""
    if not role:
        return None
    allowed = CRUD_OBJECT_SCOPE.get(role)
    if allowed is None:
        return None  # role not governed here → fail-open (full CRUD)
    if object_type in allowed:
        return None
    shown = ", ".join(sorted(allowed)) if allowed else "none (read-only role)"
    return (
        f"role {role!r} may not mutate object-type {object_type!r} via the "
        f"generic object-CRUD verbs; allowed object-types: {shown}"
    )


__all__ = [
    "SPECIALIST_ONLY", "RETIRED_VERBS", "UNSCOPED_OK", "ROLE_TOOLSETS",
    "toolset_for_role",
    "CRUD_OBJECT_SCOPE", "crud_scope_violation",
    "spawn_model_for",
]
