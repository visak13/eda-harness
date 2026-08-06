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
    #   docs/guides/*.md) and ZERO callers in src/. The one live-code reference is
    #   `InstructionKind.RECORD_STEP` (schemas/instruction.py:31) — a declared
    #   instruction kind that NO FSM emits (unlike `invoke_skill`, which
    #   plan_fsm.py:168 really does emit). A dead enum member is not a call site;
    #   it is left alone here and reported as a finding.
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

# Every verb retired from every role surface. DERIVED, so a consumer (the
# guide-corpus gate, the neuron subtraction) can never hand-copy a list that
# drifts from this one — the same argument test_w4_roles makes for importing
# _CONSOLIDATED_OUT rather than re-spelling it.
RETIRED_VERBS: frozenset[str] = (
    _CONSOLIDATED_OUT | _SUPERSEDED_OUT | _OPERATOR_RETIRED)

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
    "read_object", "query_objects", "describe_objects", "observe", "list_subscriptions", "unobserve",
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
    # v7 follow-up (2026-07-16) — Sol authors visual/3D/image ASSETS the worker
    # cannot verify by hand. Sol writes ONLY under a validated asset dir (never
    # code); the worker is Sol's eyes (render -> capture -> feed back via -i).
    "sol_author_asset",
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
    "read_object", "query_objects", "describe_objects", "observe", "list_subscriptions", "unobserve",
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
    "read_object", "query_objects", "observe", "list_subscriptions", "unobserve",
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
    "pool_close_self",
})

# SPECIALIST — the ONLY role that authors spec content (SPECIALIST_ONLY
# folded in). Self-trains, compiles + versions its doc. No count ceiling.
_SPECIALIST: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "describe_objects", "observe", "list_subscriptions", "unobserve",
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
    "pool_close_self",
}) | SPECIALIST_ONLY

# CONSULT — the on-demand advisory role: an inbox + the consult verbs,
# read-only over state. No authoring, no spawn. No count ceiling.
_CONSULT: frozenset[str] = frozenset({
    "whoami", "check_inbox", "reply", "notify_above", "ask_above",
    "emit_recipe_event",
    "get_guide",
    "read_object", "query_objects", "describe_objects", "observe", "list_subscriptions", "unobserve",
    "recall", "get_recipe_digest",
    # -consult_goal_keeper / -consult_pattern_observer — DEAD roles (owner
    # ruling 2026-08-04).
    "consult_specialist", "consult_curiosity",
    "record_specialist_consult",
    # W5: the two verbs `.claude/commands/consult.md` is contractually built
    # on — `get_specialist_docs` overlays the stack docs named in the spawn
    # brief's `spec_ids`, and `record_context` writes the keep-worthy finding
    # back as a decision (`by="consult"`, which the neuron then confirms).
    # Read-only-plus-record: the consult still cannot author specs or spawn.
    "get_specialist_docs", RECORD_CONTEXT,
    # v7 follow-up (2026-07-16) — the consult's independent, non-Opus perspective
    # for CREATIVE / VISUAL judgment. Sol runs READ-ONLY (sees an attached render
    # via -i, returns advice, writes nothing). This is the "consult -> Sol" wiring
    # from the model-tiering ruling: the consult shell stays an Opus Claude that
    # REACHES Sol through this tool (Sol is not a --model).
    "sol_consult",
    # v7 WS1 (2026-08-05) — one-shot CROSS-PROVIDER verdict (bias removal by
    # model family, §2.4): text in, text out, the advisor changes nothing.
    # Same read-only-plus-record posture as sol_consult; route-gated in
    # .bridge.json (unrouted = refuse).
    "consult_external",
    "pool_close_self",
})

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
    "next_action", "reconcile", "observe", "unobserve", "list_subscriptions",
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
    "check_inbox", "get_guide", "notify_above", "observe", "list_subscriptions", "unobserve", "read_object",
    "reply",
    # v7 WS1 (2026-08-05) — the curiosity role's PURPOSE is bias removal; a
    # cross-provider verdict makes that structural (a different model family
    # audits the same evidence). Read-only advisory posture unchanged;
    # route-gated in .bridge.json (unrouted = refuse).
    "consult_external",
    "pool_close_self",
})

# OWNER RULING (2026-08-04): goal_keeper and pattern_observer are DEAD roles —
# rows, toolsets, tool classes, activator cards and spawn paths all deleted
# (history at 18cac3f). `test_every_pool_spawned_role_has_a_toolset` derives
# its keys from http_pool.py, whose spawn methods went with them.

ROLE_TOOLSETS: dict[str, frozenset[str]] = {
    "worker": _WORKER,
    "planner": _PLANNER,
    "reviewer": _REVIEWER,
    "specialist": _SPECIALIST,
    "consult": _CONSULT,
    "neuron": _NEURON,
    "curiosity": _CURIOSITY,
}


def toolset_for_role(role: str | None) -> frozenset[str] | None:
    """The scoped tool-name surface for `role`, or None when the role is
    absent/unknown — in which case the seam registers the FULL registry
    (fail-open: a shell is never silently starved of tools)."""
    if not role:
        return None
    return ROLE_TOOLSETS.get(role)


# ── model tiers (DESIGN-v6 W10b, tables-as-data) ───────────────────────────
# Same discipline as ROLE_TOOLSETS above: pure data plus two tiny lookup
# helpers, no behaviour. The spawn tools read `spawn_model_for(...)` and pass
# the result (or nothing) to the pool.
#
# ONLY TWO MODELS EXIST HERE (d53, USER RULING): Opus 4.8 and Sonnet 5.
# HAIKU IS NEVER A TIER — not as a row, not as a comment, not as a fallback.
# d53 forbids it on cost/judgment grounds; the API forbids it on two more:
# Haiku 4.5 REJECTS `effort` outright and carries a 200K window against our 1M.
#
# EXACT MODEL IDS, never date-suffixed aliases. The Sonnet this table tiers to
# is `claude-sonnet-4-6` (USER RULING, 2026-07-16): Opus is the DEFAULT for
# every role, and Sonnet is opt-in "where it makes sense" — never auto-selected.
# Sonnet 5 is NOT used here: it shares Opus 4.7/4.8's tokenizer and is the
# token-HUNGRY Sonnet; 4.6 uses the older, leaner tokenizer, which is the whole
# reason to pick it for the cheaper opt-in tier. The id is overridable via
# EDP_WORKER_SONNET_MODEL for a future re-point without a code edit.
HOST_DEFAULT_MODEL = "claude-opus-4-8"   # what a spawn gets with NO --model
SONNET = os.environ.get("EDP_WORKER_SONNET_MODEL", "claude-sonnet-4-6")

# The task_class used when a caller names no narrower one. Every role has a
# row at this key: it is the role's DEFAULT tier, and `resolve_model_tier`
# falls back to it whenever a candidate is not explicitly allowed.
DEFAULT_TASK_CLASS = "*"

# TOKENIZER NOTE. DESIGN-v6 W10b's "~30% more tokens for the same text" is the
# Sonnet 4.6 -> Sonnet 5 tokenizer change: Sonnet 5 shares Opus 4.7/4.8's
# tokenizer and is the token-HUNGRY one, Sonnet 4.6 uses the older, leaner
# tokenizer. Tiering to 4.6 is therefore the token-lean Sonnet choice — which is
# exactly why it is the opt-in tier (opus-4-8 $5/$25 per MTok in/out vs
# sonnet-4-6 $3/$15). These are vendor list prices, unverified-by-measurement
# inputs, not a measured result — see MODEL-TIERING-BENCHMARK.md.
#
# A ROW IS `{model, status}` (+ `benchmark_task` on a candidate OR a measured
# row, naming the benchmark that will measure it / did). NOTHING ELSE.
# DESIGN-v6 line 490 specifies exactly that shape. a4 additionally stamped
# `thinking` and `effort` on every row; a4b DELETED them (USER RULING,
# 2026-07-10) for the reason they were never noticed: NOTHING CONSUMED THEM.
# `spawn_model_for` returns a model string; `pty_launcher.build_argv` emits only
# `["--model", model]`. Both fields were declared and dropped — the same
# disease a3 found in `record_context`'s `constraint`. They are NOT re-wired
# here: model/thinking/effort belong to the Claude Code settings+env surface the
# harness ALREADY owns (`build_argv` threads `--model`, `build_env` injects
# DISABLE_AUTOUPDATER and EDP_RTK), not to a new field in this table (d76/d77:
# where you are tempted to build a mechanism, use the one that exists).
#
# MEASURED BEHAVIOUR OF THE TWO MODELS AS THE SPAWN PATH ACTUALLY LAUNCHES THEM
# (a4b, 2026-07-10, probed via `claude -p --output-format stream-json`, NOT
# inherited from the API reference):
#   * BOTH models think ADAPTIVELY out of the box, with no flag and no env.
#     `claude-opus-4-8` emits a thinking block even on a trivial prompt;
#     `claude-sonnet-5` declines to think on a trivial prompt and DOES think on
#     a hard one. Adaptive means THE MODEL DECIDES — a trivial-prompt probe
#     showing no thinking block is NOT evidence that a model cannot think.
#   * `MAX_THINKING_TOKENS=0` suppresses thinking on both. Nothing sets it.
#
# `status` IS "default" OR "candidate". "measured" is a legal third value the
# schema/tests still recognise, but NO ROW carries it: Opus is the default for
# every role and Sonnet is opt-in only (USER RULING, 2026-07-16). a4b DID run a
# real benchmark (BENCH-WORKER-CODING, 2026-07-10) — but it measured
# `claude-sonnet-5`, and the tiered Sonnet is now `claude-sonnet-4-6`, so that
# measurement backs no live row. `MODEL-TIERING-BENCHMARK.md` records the a4b
# entry as history and states, per its own §8 ground rule 1, that no tier is
# measured and the flip is withheld — an honest negative, not an omission.
_OPUS_DEFAULT = {"model": HOST_DEFAULT_MODEL, "status": "default"}


def _candidate(benchmark_task: str) -> dict:
    """A Sonnet CANDIDATE row. Never selected unless a spawn passes
    `allow_candidate_tier=True`; each names the benchmark task that must measure
    it before any flip to a default — the measured-only-adoption discipline whose
    cautionary precedent is the withdrawn heartbeat tier (DESIGN-v6 principle 4)."""
    return {"model": SONNET, "status": "candidate",
            "benchmark_task": benchmark_task}


MODEL_TIERS: dict[tuple[str, str], dict] = {
    # ── the brains: Opus, full stop ─────────────────────────────────────────
    ("neuron", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    ("planner", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    ("specialist", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    # The consult tier the W10b escalation ladder reads. STRONGER-THAN-OPUS
    # TIERS ARE NEVER AUTO-SELECTED — a human passes one explicitly or nothing.
    ("consult", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    ("curiosity", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    # goal_keeper / pattern_observer rows deleted — DEAD roles (owner ruling
    # 2026-08-04).

    # ── worker ──────────────────────────────────────────────────────────────
    ("worker", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    # OPT-IN, NOT MEASURED (USER RULING, 2026-07-16: "keep Opus as default and
    # use Sonnet where it makes sense"). a4b DID benchmark a Sonnet coding arm on
    # 2026-07-10 (BENCH-WORKER-CODING, 5 trials/arm) and Sonnet held quality —
    # BUT it measured `claude-sonnet-5`, and this tier now resolves to
    # `claude-sonnet-4-6`, a DIFFERENT model with a different tokenizer. A
    # measurement of one model is not a measurement of another (d80), so this row
    # is a CANDIDATE: the planner opts in per task via `allow_candidate_tier`;
    # a bare spawn stays on the Opus default. Re-running BENCH-WORKER-CODING on
    # 4.6 under §8's ground rules is what a future flip to "measured" would
    # require. See MODEL-TIERING-BENCHMARK.md.
    ("worker", "coding"): _candidate("a4b/BENCH-WORKER-CODING"),
    # BENCHMARK TASK (a4b): a bounded, fully-specified, single-file-verified
    # deliverable — no large-surface tool selection, no open-ended judgment.
    ("worker", "narrow"): _candidate(
        "a4b/BENCH-WORKER-NARROW: replay a bounded single-file action (no "
        "open-ended judgment, no irreversible side-effects) on both arms."),
    # DESIGN-v7 1.3 — CANDIDATE, NOT MEASURED, and the distinction is the whole
    # entry. The verify class only RE-RUNS recorded `acceptance.verify`
    # commands and TRANSCRIBES their output verbatim ("run, record, judge
    # nothing, fix nothing" — the Phase-4 verify-only leg), which is the
    # narrowest worker shape in the system — narrower than the measured
    # ("worker","coding") row. That argument is a HYPOTHESIS, not a result:
    # v7/BENCH-WORKER-VERIFY has NOT run, so this row stays `candidate` and is
    # never selected without an explicit `allow_candidate_tier=True` — the
    # same measured-only-adoption discipline as ("worker","narrow") above,
    # whose cautionary precedent (d80: a tier labelled measured on the
    # authority of a benchmark doc that did not exist) is exactly the mistake
    # this comment refuses to repeat. The named task is carried in
    # docs/design/MODEL-TIERING-BENCHMARK.md §5's candidates table; the
    # test_w10b gates hold the doc and this table in sync.
    ("worker", "verify"): _candidate(
        "v7/BENCH-WORKER-VERIFY: replay a verify-only leg (re-run recorded "
        "acceptance.verify commands, transcribe raw output verbatim, judge "
        "nothing, fix nothing) on both arms."),

    # ── reviewer ────────────────────────────────────────────────────────────
    # DEGRADE THE SAFETY NET LAST. The reviewer's independent re-run IS the
    # objective acceptance gate (d29/d30); a spec review stays on Opus until a
    # benchmark says otherwise, and no benchmark has run.
    ("reviewer", DEFAULT_TASK_CLASS): _OPUS_DEFAULT,
    ("reviewer", "spec"): _OPUS_DEFAULT,
    # (("reviewer", "direction") was the one reviewer CANDIDATE row. Removed
    # with the direction reviewer itself — d128/d132. No reviewer class is a
    # tiering candidate now: every reviewer spawn resolves to the Opus default,
    # which is the intended "degrade the safety net last" posture anyway.)
}


def resolve_model_tier(role: str, task_class: str = DEFAULT_TASK_CLASS, *,
                       allow_candidate_tier: bool = False) -> dict | None:
    """The tier row a spawn of (`role`, `task_class`) resolves to, or None when
    the role is absent from the table (fail-open: the caller passes no model and
    the host default applies).

    A CANDIDATE row is returned ONLY when `allow_candidate_tier=True`. Otherwise
    the lookup falls back to the role's `DEFAULT_TASK_CLASS` row — which is Opus
    for every role in the table. An unknown `task_class` falls back the same way,
    so a typo degrades to the safe tier rather than to nothing.

    Pure (no IO, no env read). Returns a COPY so a caller cannot mutate the
    table through the row it was handed."""
    tier = MODEL_TIERS.get((role, task_class))
    if tier is None or (tier["status"] == "candidate"
                        and not allow_candidate_tier):
        tier = MODEL_TIERS.get((role, DEFAULT_TASK_CLASS))
    return dict(tier) if tier is not None else None


def spawn_model_for(role: str, task_class: str = DEFAULT_TASK_CLASS, *,
                    allow_candidate_tier: bool = False) -> str | None:
    """The `model` a spawn should pass to the pool, or None to pass NO model
    flag at all (the host default tier, Opus).

    The None is not a shrug: the tier table names `claude-opus-4-8` explicitly,
    and passing it on the wire would be equivalent — but every default spawn
    today omits the key, and keeping that byte-identical is what lets this land
    with no behaviour change on the roles it does not tier. A model is passed
    EXACTLY when the resolved tier differs from `HOST_DEFAULT_MODEL`, which is
    exactly when a caller opts into a CANDIDATE tier via `allow_candidate_tier`
    (e.g. the planner selecting Sonnet 4.6 for a coding or narrow action). Every
    un-opted-in spawn resolves to the Opus host default and passes no `--model`
    flag. No row is `measured`, so there is no auto-adopt path: Opus is the
    default for every role (USER RULING, 2026-07-16).

    v7 WS4 (§2.4b, 2026-08-05) — SEAT REGISTRY OVERRIDE: when `models.json`
    exists at the agent home and maps this role to a seat, the seat's exact
    pinned model WINS over the tier table (still returning None when it
    equals the host default, preserving the no-flag byte-identity). Absent
    registry / unmapped role = the legacy tier path below, unchanged — the
    staged-adoption discipline every v7 gate uses. A PRESENT-but-invalid
    registry raises SeatsError at spawn: misconfiguration is loud, never a
    silent host-default."""
    # Registry home resolves from EDP_AGENT_HOME ONLY — never cwd. A
    # coincidental-cwd config pickup is the PWD-resolution landmine class
    # (the opencode M1 lesson), and it would leak the live registry into
    # every hermetic test and stray invocation. Unset env = no registry =
    # legacy, deterministically.
    _home = os.environ.get("EDP_AGENT_HOME", "").strip()
    _seat = None
    if _home:
        try:
            from edp_contracts.seats import seat_for_role as _seat_for_role
            _seat = _seat_for_role(_home, role)
        except ImportError:
            _seat = None
    if _seat is not None:
        return None if _seat.model == HOST_DEFAULT_MODEL else _seat.model
    tier = resolve_model_tier(role, task_class,
                              allow_candidate_tier=allow_candidate_tier)
    if tier is None or tier["model"] == HOST_DEFAULT_MODEL:
        return None
    return tier["model"]


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
    "consult": frozenset(),
    # s25/a4: the advisory role is read-only over the generic verbs, closing
    # the same fail-open hole `crud_scope_violation` had for it (an ABSENT
    # role returns None = UNCONSTRAINED full CRUD). goal_keeper /
    # pattern_observer rows deleted with their roles (owner ruling 2026-08-04).
    "curiosity": frozenset(),
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
    "SPECIALIST_ONLY", "RETIRED_VERBS", "ROLE_TOOLSETS", "toolset_for_role",
    "CRUD_OBJECT_SCOPE", "crud_scope_violation",
    "MODEL_TIERS", "resolve_model_tier", "spawn_model_for",
    "HOST_DEFAULT_MODEL", "SONNET", "DEFAULT_TASK_CLASS",
]
