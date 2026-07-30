# Derived per-role tool inventory (ROLE_TOOLSETS floor)

**Derived 2026-07-04 from the role command files + guides** (the contract sources: `.claude\commands\*.md`, `docs\guides\neuron-phase-a..e.md`, `neuron-protocol-reference.md`, `planner-phase-*.md`, all 7 `planner-shape-*.md`, `architecture-vocabulary.md`, `environment-discovery.md`, `reactive-streams*.md`, `framework-ocak.md`, `coding-standards.md`).

**Rule (DESIGN-v6 W4):** each role's toolset floor is the union of tool references in its own guides. This file is the audited snapshot; the derived-floor unit test regenerates it from the guide files and must reproduce it (post-W6.4 sweep, minus the swept verbs). Harness (non-MCP) tools flagged **[H]** — those are not ROLE_TOOLSETS entries but must not be blocked by any future harness policy.

## NEURON

`ensure_orchestrator`, `ensure_universal`, `get_specialization`, `add_spec_entry`*, `get_guide`, `describe_objects`, `read_object`, `query_objects`, `update_object`, `create_object`, `delete_object`, `read_worklog`, `status_ping`, `supersede_decision`, `reconcile`, `next_action`, `observe`, `check_inbox`, `reply`, `resolve_recipe`, `start_recipe`, `record_recipe` (escape hatch — referenced by phase-a/e anti-patterns), `consult_curiosity`, `seed_comprehension_specialists`, `neuron_search`, `consult_specialist`, `record_specialist_consult`, `record_outcome`, `record_comprehension_signoff`, `add_step`, `consult_goal_keeper`, `pool_spawn_planner`, `branch_reviewer`, `train_specialist`, `append_revision`, `remember`†, `record_decision`†, `list_spec_learnings`, `resolve_spec_learning`†, `mark_outcome_met`, `close_recipe`, `suspend_recipe`§, `resume_recipe`§, `consult_pattern_observer`, `run_ocak_audit`, `record_audit_verdict`, `record_user_answer`, `record_step_result`, `broker_send`, `update_specialist`*

**[H]** Monitor, CronCreate, CronList, CronDelete, TaskStop, AskUserQuestion, EnterPlanMode/ExitPlanMode. (ScheduleWakeup referenced only as deprecated.)

CRUD object-types instructed: recipe, step, action (status/verify healing), outcome, decision, spec*, neuron (train).

\* W4/W15 carve-out: `add_spec_entry`/`update_specialist` move to SPECIALIST_ONLY — sweep neuron.md:40/315 + phase-d references in the same change (the neuron spawns the specialist instead).
† Consolidated by W6.4 (`record_context`, batch `resolve_spec_learnings`) — sweep the guide references in the same change.
§ W11 suspend/resume — **neuron-only**, and so by construction: `_NEURON` is *derived* (`_ALL_TOOL_NAMES - SPECIALIST_ONLY - _CONSOLIDATED_OUT`), and no other role's explicit allowlist names either verb. `tests/test_w11_docs_sync.py` holds every surface that enumerates these toolsets to `ROLE_TOOLSETS`.

## PLANNER

`get_guide`, `whoami`, `observe`, `reconcile`, `next_action`, `check_inbox`, `reply`, `ask_above`, `notify_above`, `status_ping`, `emit_recipe_event`, `read_object`, `create_plan`, `add_action`, `record_plan` (replan path — KEEP), `neuron_search`, `update_object` (action: spec_id/status/verify/description — drive:30/135), `delete_object` (action — drive:169), `describe_objects`, `query_objects` (session/lock/action — drive:121-134), `pool_spawn_worker`, `pool_reap`, `inspect_worker`, ~~`broker_send`~~◊, `get_specialist_doc`†, `recall`, `pool_close_self`

⚑ **`invoke_skill` REMOVED from this floor (s26/a2, d70).** It was never a tool — it is an `InstructionKind` (`schemas/instruction.py:25`) that `plan_fsm.py:168` **emits to** the planner in `ACCEPTANCE_REVIEW`. `planner-phase-drive.md:55` documents it correctly, under *"Instruction kinds:"* and **not** in call form; that line is a correct description of live FSM behaviour and stays. Transcribing a *received instruction* into a *callable-tool floor* is the drift: `build_mcp` fails **closed** on unregistered names, so it would take the MCP server down at startup for every shell. `tests/test_s26_guide_tool_names.py` now fails if any live guide *calls* a name that is not a registered tool.

◊ **NOT granted (s25/a4, ruling on a1-vs-a2).** `broker_send` was instructed by `planner-phase-drive.md:56,109` (ask_neuron + the plan-close broadcast) and `environment-discovery.md:51`, but it fails the derived-floor precedent's own precondition: it takes an **arbitrary `to=`**, where the planner's `reply`/`notify_above`/`ask_above`/`emit_recipe_event` are all lineage-scoped. Granting it would hand every planner unrestricted addressing. All three call sites addressed the planner's **parent**, and for a planner the parent IS the `<recipe_id>` — so the GUIDES were fixed to the exact equivalents the planner already holds: `notify_above(kind="plan_closed", …)` and `ask_above(audience="neuron")`. Verified: `plan_closed` and `question` are both in `edp_contracts.CORE_KINDS`, and `NotifyAbove._run` sends `to=parent` with an arbitrary kind. Zero reach change; planner floor 32→34 (`status_ping` + `neuron_search` only).

**[H]** Monitor, CronCreate, CronList, CronDelete, TaskStop, WebSearch/WebFetch (creative-production shape), AskUserQuestion (poc-iterate gate — ⚠ conflicts with "never prompt user"; resolve in W6.5).

CRUD object-types: plan, action ONLY (matches W4 scope guard).

## WORKER

`get_guide`, `whoami`, `observe`, `check_inbox`, `emit_recipe_event` (status_ping/learning/discovery/blocker), `notify_above`, `ask_above` (parent + audience=neuron), `read_object`, `get_specialist_docs`, `get_specialist_doc`†, `propose_spec_learning`†, `assemble_ruleset` (s25/a4 — the `concerns=[X]` composition path; read-only, see REVIEWER ‡), `record_action_status`, `describe_objects`, `query_objects`, `recall`, `pool_close_self`

**[H]** Monitor, CronCreate, CronDelete, TaskStop (+ the working tools: Bash/Edit/Read etc.).

CRUD: read-only + `record_action_status` on its own action (matches W4).

## REVIEWER

`check_inbox`, `whoami`, `get_specialist_docs`, `assemble_ruleset`‡, `notify_above`, `reply`, `emit_recipe_event` (review_finding), `propose_spec_learning`, `read_object`, `pool_close_self`

**[H]** Read/Bash/Edit (reviewer.md Step 2/2.5 — reads AND fixes deliverables in-session).

CRUD: read-only; file edits via harness tools, no object mutations.

‡ **RESOLVED (s25/a4, neuron ruling d62 option (a)).** `assemble_ruleset` was MISFILED in SPECIALIST_ONLY — that set is defined by *authoring* (o7), and `AssembleRuleset` (`_tools.py:6842-6868`) is `idempotent=True`, "Pure lookup, byte-stable per inputs", whose only store access is `ctx.specs.load`. It writes nothing. It is now granted explicitly to the reviewer, the worker and the specialist, and flows into the derived `_NEURON`. Reviewer floor 15→17 (also `propose_spec_learning`). **The blocker on reviewer-scope enforcement is lifted**; reviewer scope is no longer gated on this question. (Enforcement itself remains blocked for the *other* reasons in `enforce-readiness-verdict.md`.)

s25/a4 also fixed `reviewer.md:62`, which prescribed the singular `get_specialist_doc(spec_id=…)` — a verb the reviewer does not hold — to the plural `get_specialist_docs`, the multi-aware path and a pass-through for one spec.

## SPECIALIST

`check_inbox`, `notify_above`, `create_specialization`, `neuron_set_base_session`, `add_spec_entry`, `assemble_ruleset`, `write_specialist_doc`, `record_spec_version`, `neuron_set_status`, `get_specialization`, `get_guide`, `reply`, `pool_close_self`

**[H]** WebSearch/WebFetch/Read.

CRUD object-types: spec, neuron — exactly W4's SPECIALIST_ONLY set (confirms the carve-out).

## CURIOSITY

`check_inbox`, `read_object` (recipe, digest→full), `notify_above`, `reply`, `pool_close_self`, `get_guide`, `observe`

**[H]** Monitor, CronCreate, CronDelete, TaskStop.

CRUD: read-only.

## GOAL-KEEPER / PATTERN-OBSERVER (on-demand advisories)

goal-keeper: `check_inbox`, `read_object`, `reply`, `pool_close_self`. pattern-observer: + `query_objects`, `recall`.

### These three roles now HAVE `ROLE_TOOLSETS` rows (s25/a4 — a1 blockers 4 + 6)

Until s25/a4 this doc carried these sections while `roles.py` carried **no rows**, so `toolset_for_role` returned `None` and `build_mcp` **failed open** to the full 86-tool registry — in *both* warn and enforce. These shells held `close_recipe`, `delete_object`, `pool_spawn_planner` and the o7 `SPECIALIST_ONLY` verbs while the six named roles were scoped. An over-**grant**, not a break: nothing failed, which is why it stayed invisible. **The doc was right; the code was incomplete.**

**The key is the UNDERSCORE form.** This doc heads them with hyphens and their activators are `/goal-keeper` / `/pattern-observer`, but `EDP_ROLE` is stamped `goal_keeper` / `pattern_observer` (`clients/http_pool.py:99,107`). A row keyed `"goal-keeper"` would never match and the fix would **silently do nothing while looking landed**. `test_every_pool_spawned_role_has_a_toolset` derives the keys from `http_pool.py`'s source, so the next role the pool learns to spawn cannot fail open.

Two corrections to the inventory above, derived from what the command files actually **call**:

- `pattern_observer_analyze` (named here previously) is **not a registered tool**. `build_mcp` fails CLOSED on such drift (`mcp_server.py:150-158`), so naming it in a role's frozenset would take the MCP server down at startup for **every** shell. **FIXED (s26/a2, d70):** the call form is deleted from `pattern-observer.md:28` — the observer scans via `query_objects("worklog", …)` / `read_object("worklog", …)` and aggregates itself. The same landmine sits in this doc's other floors: `ensure_orchestrator`, `append_revision` and `branch_specialist` are **still unregistered** (`invoke_skill` is removed above — it was an instruction kind, not a tool). Do not transcribe a floor from this doc into `roles.py` verbatim.
- `read_worklog` is listed for pattern-observer but `pattern-observer.md` never calls it, so it is not in the row. If the guide starts instructing it, `test_every_tool_a_roles_own_guides_instruct_it_to_call_is_in_its_toolset` will say so.

---

† = verb consolidated by W6.4; the floor entry migrates to the replacement verb when the guide sweep lands (same change).
