"""Tool catalog one-liners (context-diet Phase 4).

ONE lean clause per registered tool — purpose + the one constraint whose
absence caused a live defect. The empirical ruling stands (mcp_server.py:
"verbose tool descriptions demonstrably regress the planner tool catalog"),
so these stay single clauses, never the 20-80-line docstrings.

THE ROLE TAG IS NOT WRITTEN HERE. build_mcp derives it from ROLE_TOOLSETS at
registration and prepends "[role,role] " — so the tag can never drift from
roles.py, and this file carries only the hand-written semantics. A registered
tool missing from this dict is a TEST FAILURE (test_mcp_server), not a silent
placeholder.
"""

TOOL_ONE_LINERS: dict[str, str] = {
    # ── identity / lifecycle ────────────────────────────────────────────
    "whoami": "Report this shell's role, self/parent address and lineage (reads env; enforces nothing).",
    "start_recipe": "Create a new recipe from goal+domain; returns recipe_id. Check resolve_recipe first — creating blindly orphans open work.",
    "resolve_recipe": "Match a typed goal against open recipes: resume / confirm / create decision, never silent creation.",
    "resume_recipe": "Reopen a suspended recipe: manifest + digest + rewire hand-back for the resuming shell.",
    "suspend_recipe": "Park a recipe: reap shells, write the suspension manifest with the resume command.",
    "close_recipe": "Terminal-close a recipe (succeeded/abandoned); refuses while outcomes/steps are open.",
    "record_recipe": "Validate+save a whole Recipe object — the escape hatch; prefer start_recipe/add_step intent verbs.",
    # ── comprehension / outcomes ────────────────────────────────────────
    "record_comprehension_signoff": "Record the user's proceed-signoff (or an explicit skipped+reason) — the gate out of COMPREHENDING.",
    "record_user_answer": "Record the user's verbatim answer to an open question; diff it against active decisions before writing.",
    "record_outcome": "Declare one expected outcome; refused until curiosity cleared or the user signed off.",
    "mark_outcome_met": "Flip one outcome to met with evidence; the honest close needs every outcome met.",
    "record_audit_verdict": "Record the OCAK audit verdict on the recipe trail.",
    "run_ocak_audit": "Run the OCAK framework audit over the recipe and return findings.",
    "seed_comprehension_specialists": "Spawn the comprehension advisor set (curiosity/goal-keeper/pattern-observer) for a fresh recipe.",
    "consult_curiosity": "Ask the persistent comprehension curiosity; put FACTS in `question` — context/framing fields are not delivered.",
    "consult_goal_keeper": "Ask the goal-keeper whether current work still serves the north star.",
    "consult_pattern_observer": "Ask the pattern-observer for cross-recipe drift/pattern findings.",
    "consult_specialist": "Read a compiled specialist doc inline for one question — consult, never author.",
    "record_specialist_consult": "Log that a specialist consult happened (trust/decay bookkeeping).",
    # ── map: steps / decisions / context ────────────────────────────────
    "add_step": "Declare a step (execution, depends_on, concerns, acceptance_sketch). description = scope, HARD CAP 1200 chars; mid-flight needs justification — CRUD an existing step first; a step costs a planner + N shells.",
    "record_step_result": "Record a step's terminal result + outputs; refreshes the state synthesis.",
    "record_context": "Routed memory-write by kind. text = the statement, HARD CAP 1200 chars (author within it on the FIRST call); why goes in rationale, detail in a sidecar ref; LB writes refuse past the fold threshold.",
    "fold_decisions": "Atomically supersede a settled decision cluster with ONE summary decision (history preserved; folded members stop reaching workers).",
    "supersede_decision": "Retire one decision with a replacement pointer; the single-decision fold.",
    "confirm_direction_constraints": "Activate proposed constraint-bearing bans (neuron authority; reviewers only propose).",
    "ensure_universal": "Ensure the universal base ruleset spec exists.",
    "recall": "Read facts by lineage scope (bounded window).",
    "search_context": "Semantic search over the recipe's decisions/assumptions/bans — the targeted re-ground; use it before pulling full objects.",
    # ── grounding reads ─────────────────────────────────────────────────
    "get_recipe_digest": "The <10k-token code-assembled re-ground packet: north star, recap, outcomes, decisions index, open steps, events. Ground from THIS, not raw recipe.json.",
    "read_object": "Read ONE object (recipe/plan/action/step/...); detail='digest' to orient cheaply; oversize recipe reads degrade to the digest unless confirm_oversize.",
    "query_objects": "Filtered, count-first windowed list of objects; page with offset=cursor.",
    "describe_objects": "Schema/required-ids catalog for the readable object types.",
    "read_worklog": "Tail/since window over a plan's worklog events.",
    "get_guide": "Load a role/phase guide by name (mtime-cached); pull on demand, don't re-paste.",
    "neuron_search": "Search the neuron DB (resolve a specialization descriptor to a spec_id before dispatch).",
    # ── drive loop / wiring ─────────────────────────────────────────────
    "next_action": "Pure phase pacer: next legal move + wait_hint; pass reconcile_changed to collapse an idle tick to a one-line no_change payload — then END the turn with zero prose.",
    "reconcile": "Sync the record to broker/pool/disk reality; returns {changed,...}+wait_hint. Feed changed into next_action.",
    "observe": "Arm one reactive subscription (RUN the returned monitor_cmd — a spec with no live driver is deaf).",
    "unobserve": "Remove one persisted subscription spec.",
    "list_subscriptions": "List this handle's persisted subscription specs.",
    "emit_recipe_event": "Append a typed event (learning/review_finding/discovery/...) to the recipe trail; kind=learning auto-proposes to the spec sidecar.",
    "arm_external_driver": "Register an external (non-Claude) driver for a handle's subscriptions.",
    "disarm_external_driver": "Unregister an external driver.",
    # ── comms ───────────────────────────────────────────────────────────
    "check_inbox": "Read new broker mail from a persisted cursor (budgeted bodies); do NOT kind-filter your own inbox.",
    "reply": "Reply to a broker message by msg_id.",
    "broker_send": "Send a broker message to an arbitrary handle; prefer ask_above/notify_above for your own parent.",
    "ask_above": "Ask your parent (planner→neuron, neuron→operator) a question that blocks you.",
    "notify_above": "Notify your parent without blocking (grounding echoes, done flowback).",
    "status_ping": "One-line child check: liveness + last worklog line (no dump) — the cheap probe.",
    # ── children / dispatch ─────────────────────────────────────────────
    "pool_spawn_planner": "Spawn the planner shell for a step; refuses past the decision fold ceiling — fold first.",
    "pool_resume_planner": "Resume a parked planner from its recorded session.",
    "pool_spawn_worker": "Dispatch one action (or batch) to a fresh worker/reviewer shell; injects budgeted grounding; review legs require role='reviewer'.",
    "pool_reap": "Reap dead/finished shells from the pool registry.",
    "pool_close_self": "Close THIS shell's pool seat (park=true keeps the shell; only park=false advances the FSM).",
    "inspect_worker": "Deep probe of one child shell (expensive; prefer status_ping).",
    "branch_reviewer": "Branch an independent reviewer for a comprehension/scope target.",
    "record_action_status": "Pure write of status+evidence (no gate runs here); workers need a prior grounding echo; reviewers may close only their OWN leg.",
    "record_branch_verdict": "Record a reviewer's verdict on a branch or plan action — judgement, never status.",
    # ── plan authoring (planner) ────────────────────────────────────────
    "create_plan": "Create an empty drafted plan for a step (tool fills plan_id/domain); then add_action per action.",
    "add_action": "Append one action (acceptance, verify, concerns, leg_kind, batch_group). description = the WHAT, HARD CAP 1200 chars (how -> grounding brief); past the ceiling only batched appends land — an action costs a shell.",
    "record_plan": "Validate+save a whole Plan; refuses when step concerns/acceptance_sketch are uncovered (flow-down gate).",
    "record_grounding_brief": "Write the plan's grounding brief sidecar (injected into every worker, capped at delivery — keep it tight).",
    "update_object": "Patch fields on your OWN objects (role-scoped by object type); read back what you wrote.",
    "delete_object": "Delete an object you own (role-scoped by object type).",
    "create_object": "Generic object create (escape hatch; prefer the intent verbs).",
    # ── specialists ─────────────────────────────────────────────────────
    "train_specialist": "Spawn/refresh a specialist's training for a descriptor — the DELEGATION verb; the neuron never authors spec content.",
    "get_specialist_docs": "Load+concatenate compiled docs for spec_ids — a specialist worker's grounding.",
    "get_specialization": "Read one spec's metadata/extends chain.",
    "check_specialist_decay": "Report which specs have decayed past their re-train threshold.",
    "list_spec_learnings": "List a spec's quarantined learning proposals.",
    "resolve_spec_learnings": "Batch-accept/reject learning proposals; accepts append entries + bump the version once.",
    "record_spec_version": "Record a compiled spec doc version stamp.",
    "assemble_ruleset": "Pure lookup: compose universal + tech-extends + concerns layers into one effective ruleset.",
    "register_rule": "Register one rule in the shared ruleset store.",
    "list_rules": "List rules in the shared ruleset store.",
    "add_spec_entry": "Append one entry to a spec (specialist authoring surface).",
    "update_specialist": "Re-train/update a specialist's spec content (specialist authoring surface).",
    "write_specialist_doc": "Write/compile the specialist's doc (specialist authoring surface).",
    "create_specialization": "Create a new specialization spec (specialist authoring surface).",
    # ── neuron DB rows ──────────────────────────────────────────────────
    "neuron_get": "Read one neuron-DB row.",
    "neuron_list": "List neuron-DB rows.",
    "neuron_touch": "Touch a neuron-DB row's freshness stamp.",
    "neuron_flag": "Flag a neuron-DB row.",
    "neuron_set_base_session": "Bind a specialist's base session id to its row (what makes it usable).",
    "neuron_set_status": "Set a neuron-DB row's status (HITL approval gate).",
    # ── Sol bridge ──────────────────────────────────────────────────────
    "sol_consult": "Ask Sol (read-only, sees renders via -i) for creative/visual judgment.",
    "sol_author_asset": "Delegate a visual/3D/image asset to Sol; writes ONLY under the validated asset dir, never code.",
}
