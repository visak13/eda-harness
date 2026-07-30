# FINDINGS — the cross-shell liveness hole (HITL #8)

**Source:** neuron / planner / worker session debug logs, 2026-05-19.
**Status:** the single most important architectural hole. Needs a design
decision (fork below) before implementation.

## What worked (state it plainly)
- **Neuron:** flawless v5 flow — resolve_recipe→confirm (asked
  correctly), start_recipe (zero friction), FORCED 7-branch OCAK with
  genuinely substantive verdicts (not "ok"), declare_outcome,
  declare_step, spawn_planner, wait. Context injected every call. No
  retry storms anywhere.
- **Planner:** read env brief, authored a real 3-action DAG (research →
  synthesize → verify) with acceptance per action, dispatched a1,
  spawned a worker.
- **Worker:** read env brief, read the plan, did 12 WebSearches +
  WebFetch with ≥2-source cross-verification, wrote a real dossier,
  `record_action_status(a1, done)` with rich evidence → `{ok:true}`.

The agents are correct. The information **reached disk** (the plan file
has a1=done). It never reached the **running planner context**.

## Root cause: there is no cross-shell WAKE / RECEIVE
1. **No broker-receive tool.** `broker_send` exists; nothing reads an
   inbox. The planner searched 3× for a receive/poll tool — none. Its
   `question` to `my-neuron` was a **dead letter** (`my-neuron.jsonl`
   written; neuron never reads it; planner can't read a reply). The only
   broker *consumption* anywhere is `next_action`'s internal
   `_advance_executing` polling for `plan_closed` to the recipe handle.
2. **No wake when a child completes (the killer).** After `wait`/
   repeated dispatch, the planner correctly **ends its turn** (no
   busy-spin). The worker later finishes and writes a1=done to disk —
   but **nothing re-invokes the planner**. It never re-calls
   `next_action(plan)` → never dispatches a2/a3 → never closes the plan
   → never sends `plan_closed` → neuron's `_advance_executing` never
   sees it → `next_action(recipe)` returns `wait` **forever**. Exactly
   the user's symptom.

We dropped the old edp_shell PTY-injection wrapper (correctly) but never
replaced its *wake* function. The pool spawns shells; nothing re-pokes
them. "Shells communicate as a team" (the user's stated goal) is
half-built: send without receive/wake.

## Design fork (decide before building)
- **(A) Pool injects into the parent shell** — reintroduces PTY input
  injection we deliberately deleted. Rejected (contradicts v4/v5).
- **(B) Monitor on the broker inbox (RECOMMENDED).** Each spawned shell's
  activator arms a Claude Code `Monitor` tailing its broker inbox file;
  it ends its turn; an inbox message wakes it via task-notification.
  Needs: (1) broker-receive surface — the broker already has
  `/v1/inbox/{recipient}` + `/v1/events` SSE; (2) a `broker_recv` tool
  and/or activator-armed Monitor; (3) the **pool posts a `child_done`
  event to the parent's inbox on every worker/planner exit** (pool knows
  the parent via the alias registry); (4) "end turn → Monitor wakes"
  pattern in every activator. This is the old ADR-021 "non-blocking
  driver comms" pattern, design-consistent, no PTY injection.
- **(C) Timed /loop re-poll** — works for the human-driven neuron, not
  for spawned planner/worker shells that have ended their turn (the old
  "wait_for_instruction freezes the model" failure).
- **(D) Tool-triggered resume** — a tool call can't resume a different
  idle shell. Not viable alone.

**Recommendation: (B).** It is the heart of "team communication," matches
the proven old pattern, and needs no PTY injection.

## Secondary defects
- **Planner brief discovery flailing (~20 calls).** `next_action(plan)`
  precondition-fails until `record_plan` (chicken-and-egg); the
  activator never says "your brief = the recipe step on disk." Cheap
  `agentic-plan.md` fix: read `.recipes/<rid>/recipe.json`, find step
  `<step_id>` from `EDP_HANDLE`, that's your goal; author the plan; then
  loop. (Independent of the wake fork — safe to do alongside.)
- **`broker_send` `from` defaults to `"neuron"`** → planner's message
  mis-attributed. Small provenance bug; fix opportunistically (derive
  `from` from `EDP_SPAWN_SESSION_ID`/`EDP_ROLE`).

## Resume question (user's, answered in the analysis)
resolve_recipe matched OpenAI/Musk↔US-Iran at **84%** (shared sentence
template) → `confirm` → user asked → "start fresh". This is the
deterministic-Jaccard blind spot (lexical overlap ≠ semantic sameness),
**already flagged** `# TODO(resume-fuzzy)` and covered by the v5 promotion
of the masked-LLM/embedding layer. The confirm-fallback is conservative-
correct (it did NOT wrongly resume); the refinement is to route the
"same goal?" decision through semantic judgement. User's instinct is
right, with the v5 framing (judgement *behind a tool*, not LLM-free-rein).
