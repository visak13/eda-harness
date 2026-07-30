# Orchestration Debug Log — new-trends "add one more topic" (s5)

> Purpose: a detailed, debuggable trace of the **/neuron orchestrator** session that added one
> topic (`agent-memory-systems`) to the new-trends SPA. Captures the conversation flow, every
> MCP/tool call with intent + result, the incidents, and a what-worked / what-didn't analysis.
> A companion planner-side log is requested from the s5 planner (see end).

- **Recipe:** `recipe-improve-c-projects-learning-new-trends-f-2e15e2`
- **Step added this session:** `s5` (one-topic increment), planner `planner:b850132d-6e27-4526-88e3-915a7fc6586c`
- **Date:** 2026-05-29
- **Working dir:** `C:\Projects\Learning\eda-base3\claude` (recipe deliverables under `C:\Projects\Learning\new-trends`)
- **Orchestrator role:** router only — comprehension→user, research→gap-curator, execution→planner/workers
- **Status at time of export:** topic authored + render-verified; gap-curator reviewer pass (`a5-review`) still in flight; recipe NOT yet closed.

---

## 1. User goal (this continuation)

> "continue the new-trends edit recipe but add just one more topic. I want to review the output once again"

Clarified via `AskUserQuestion` into:
- **Which topic / how chosen:** gap-curator picks the single highest-value missing topic.
- **Review scope:** "I just want to review the **added topic**" — NOT the full batch, NOT finished-output. One topic, fully authored, for the user's review.

---

## 2. Entry state vs reality (the first important finding)

The FSM/recap claimed the recipe was mid-`s3` ("planner in progress"). Ground-truth inspection
via the object surface contradicted that:

| Step | FSM said | Pool/disk truth |
|---|---|---|
| s1 (exemplar + schema + delta) | done | done ✓ (`agent-evaluation` exemplar, `artifacts.js` sidecar schema, `topics-list-delta`) |
| s2 (seed 14 catalog stubs) | done | done ✓ (`topics.json` 45→59 slugs) |
| s3 (bulk-author all topics) | **in_progress, "planner in progress"** | **PHANTOM** — no s3 planner session, no s3 worker, no s3 lock; `artifacts.js` had only the exemplar. The bulk authoring **never ran**. |
| s4 (review) | pending | pending |

**Lesson reinforced:** the FSM's `status` is a recorded hint, not ground truth. Only the pool
knows what's alive. The phantom `s3 in_progress` would have misled a blind re-dispatch into
re-running full bulk authoring (not what the user wanted).

**Reshape decision:** since `update_object` is not supported for `step` (couldn't re-scope s3),
added a NEW step `s5` carrying the narrow one-topic brief and dispatched its planner explicitly
via `pool_spawn_planner` (per the recorded anti-pattern about driving a specific step without
fighting FSM step-ordering). Left phantom s3 + s4 untouched, to reconcile honestly at close.

---

## 3. Chronological tool / MCP call log

Legend: ✅ worked · ⚠️ worked-with-friction · ❌ failed

### Setup
1. ❌ `ToolSearch("select:ensure_orchestrator,...")` — "No matching deferred tools found". Short names don't resolve.
2. ✅ `ToolSearch("select:mcp__edp-claude__ensure_orchestrator,...")` — fully-qualified names required; loaded 7 tools.
3. ✅ `ensure_orchestrator()` → `{created:false}` (already existed).
4. ✅ `get_specialization("spec-orchestrator")` → loaded 16 entries (anti-patterns incl. the new-trends-specific ones: curiosity single-channel, branch_specialist cross-folder crash, spec_id-vs-neuron_id, Windows verify-gate bug).
5. ✅ `get_guide("architecture-vocabulary")`.
6. ✅ `resolve_recipe(...)` → `decision:confirm`, `recipe_id:...-2e15e2` (correctly matched the open recipe out of 14).

### Grounding the state
7. ⚠️ `next_action(recipe)` → `wait`, phase d, "planner in progress" (the misleading phantom signal).
8. ✅ `query_objects("step", scope={recipe_id})` → 4 steps; revealed s3 in_progress / s4 pending.
9. ❌ `query_objects("session", where={}, scope={recipe_id})` → result 61,854 chars, **exceeded token limit**. Had to narrow.
10. ⚠️ `query_objects("session", where={role:planner}, scope={recipe_id})` → **scope did NOT filter to the recipe**; returned ALL planners across every recipe. Eyeballed: s1/s2 planners done, **no s3 planner**.
11. ❌ `query_objects("plan", ...)` → "query not supported for 'plan'".
12. ⚠️ `query_objects("session", where={role:worker}, scope={recipe_id})` → again unscoped (all workers). Confirmed s1/s2 workers done, no s3 worker.
13. ✅ `Glob("**/*.{js,json}", new-trends)` → file inventory.
14. ✅ `Bash(grep artifacts.js / count topics.json slugs)` → `artifacts.js` had ONLY `agent-evaluation`; `topics.json` = 59 slugs. Confirmed s3 never produced artifacts.

### Clarify with user
15. ✅ `AskUserQuestion` (2 Q) → "gap-curator picks" + "I just want to review the added topic".

### Reshape + dispatch
16. ✅ `get_guide("neuron-phase-d")`.
17. ⚠️ `query_objects("lock", scope={recipe_id})` — unscoped again (all recipes); confirmed **no s3 lock** (so no phantom lock blocking). · ✅ `neuron_get(gap-curator)` → `spec_id = spec-ai-ml-interview-prep-gap-curator-0b5fbe`, base session `dada7ee2…` (the cross-folder crasher → must use get_specialization-into-worker, never branch_specialist).
18. ✅ `check_specialist_decay(gap-curator)` → `stale:[]` (fresh, safe to reuse). · ✅ `describe_objects("step")` → fields don't include description (foreshadows #19).
19. ❌ `update_object("step", s3, patch={status,description})` → "update not supported for 'step'". Steps are immutable via CRUD → had to add a new step instead.
20. ✅ `ToolSearch(add_step, record_step_result, record_step, pool_spawn_planner, check_inbox, reply)`.
21. ✅ `add_step(recipe, "ADD ONE gap-curator-recommended topic… [full self-contained brief]", spawn_planner)` → `step_id: s5`.
22. ✅ `pool_spawn_planner(recipe, s5)` → `planner:b850132d…`.
23. ✅ `ScheduleWakeup(270s)`.

### Wait/poll cycles (heartbeat loop)
24. `check_inbox` → only historical s1/s2/curiosity messages (no s5 yet). `read_object(session s5)` = alive; `next_action` = wait (steps=5). `ScheduleWakeup`.
25. `check_inbox` empty; `read_object(session s5)` alive. `ScheduleWakeup`.
26. ✅ `check_inbox` → **s5 `question`**: gap-curator recommends `multi-agent-orchestration` (just-launched, agents-mcp, must-know) + alternatives [agent-memory-systems, llm-observability-tracing, agentic-rag-graphrag].
27. ✅ `AskUserQuestion` → user **SUBSTITUTED**: chose **Agent memory systems**.
28. ✅ `reply(msg 94c2867f, decision:substitute, confirmed_topic:agent-memory-systems, …)`. `ScheduleWakeup`.
29. `check_inbox` empty; `read_object(session s5)` alive; `Bash` disk = artifacts still exemplar-only. `query_objects(worker, step s5)` → `a1-recommend` done, `a3-author` **active**. `ScheduleWakeup`.
30. `check_inbox` empty; `read_object(session s5)` alive; `Bash` = nothing new on disk. `ScheduleWakeup`.
31. ⚠️ **Incident detected:** `read_object(session a3-author = ebfdbb92)` = state **done**, but `Bash`/`find -mmin 20` = **nothing written**, and `read_object(action a3-author)` = **in_progress**. Session "done" ≠ deliverable present → suspected author-worker crash (the Claude Code thinking-block harness bug, same as s1 a3 which died twice).
32. ✅ **Recovery confirmed:** `read_object(session s5)` = planner alive; `query_objects(lock, recipe)` → lock on `a3-author` now held by a **different, ALIVE** worker `1aa498ce…`. The planner had **auto-re-dispatched** the author worker. No phantom lock → not the deadlock case → no intervention needed (force-failing a live worker is the known lock-deadlock trigger). `ScheduleWakeup`.
33. ✅ `Bash` → `topics.json` + `just-launched.js` modified, now contain agent-memory refs; `artifacts.js` still 11,632 bytes (artifact entry pending; gate needs ≥16,000). `read_object(action)` = in_progress. `ScheduleWakeup`.
34. ✅ `Bash` → `artifacts.js` now 23,991 bytes / 179 lines, contains `agent-memory-systems`. `read_object(action a3-author)` = **done**, verify gate `file_min_bytes ≥16000` **PASS**. `ScheduleWakeup`.
35. ⚠️ `next_action` → wait, **"3 cycles, escalate"** nudge — false-stuck signal: step was progressing at the action level. `query_objects("action", scope={plan_id s5})` → a1/a2/a3/a4 done, **a5-review in_progress** (gap-curator reviewer fork running). Gave user the view instructions + re-armed.
36. (this turn) Wrote this debug file + messaged the planner.

---

## 4. Planner-side action trace (`s5` plan, from action objects)

| Action | Exec | Status | Notes |
|---|---|---|---|
| `a1-recommend` | subagent worker | done | Worker loaded gap-curator via `get_specialization(spec_id=…)`; wrote `.s5-recommendation.md` (picked multi-agent-orchestration). Gate `file_exists` ✓. |
| `a2-confirm` | inline | done | Surfaced pick to orchestrator via broker question; recorded user's SUBSTITUTE → `agent-memory-systems`. |
| `a3-author` | subagent worker | done | **1st worker crashed** (thinking-block harness bug, nothing written); planner re-dispatched; 2nd worker authored 3 ADD-ONLY edits (`topics.json` 60 slugs, `just-launched.js` full topic body+svg+4 sources, `artifacts.js` 7-artifact set). Grounded sources via WebFetch/WebSearch (mem0 2.0.4, MemGPT arXiv 2310.08560, LangGraph memory taxonomy). Gate `file_min_bytes ≥16000` ✓ (23,991 B). Fixed 2 escape bugs (over-escaped `\'` and backticks). |
| `a4-verify-render` | subagent worker | done | Drove `file://index.html` in bundled Playwright Chromium (host `chrome` channel not installed). ALL 4 checks PASS: topic + 7 artifacts render; zero console errors; no regression (exemplar + originals intact, 60 cards); no new CDN/build dep. Report at `_verification/s5-render-check.md`. |
| `a5-review` | inline | **done (pivoted)** | `branch_reviewer` of gap-curator **crashed on startup** (`reviewer:9d40fcee` dead — same cross-folder base-session crash as `branch_specialist`). Planner verified no duplicate spawns and **pivoted** to the workaround: an ordinary worker loading the spec via `get_specialization`, reviewing only `agent-memory-systems`. **Verdict: PASS** (all 9 bars + schema conformance; 2 non-blocking nits, no re-author). Evidence: `_verification/s5-review-verdict.md`. |

**s5 plan closed `succeeded` (2026-05-29):** topic `agent-memory-systems` added; reviewer PASS; render PASS. Planner debug log written to `_verification/s5-planner-debug.md`.

**Deliverable (agent-memory-systems):** bucket=just-launched, axis=agents-mcp, gap_priority=must-know.
Body covers short/long-term, semantic/episodic/procedural, vector-backed recall, summary/compaction,
MemGPT-Letta/mem0/LangGraph-LangMem, + 5 production failure modes. Artifacts: 4 reading links,
learning-path, ~5 hr hands-on, 8 Q&A (easy→hard), pinned snippet `mem0ai==2.0.4` (21 lines), 5
numbered gotchas, 10 flashcards.

---

## 5. What worked

- **Object surface as ground truth.** `query_objects`/`read_object` against pool + disk repeatedly
  beat the FSM's rough `status` — caught the phantom s3, the session-done-but-action-in-progress
  crash, and the live-worker recovery.
- **Phantom detection before action.** No planner + no lock + empty disk = s3 never ran → avoided a
  destructive blind re-dispatch of bulk authoring.
- **Explicit dispatch of a re-scoped step** (`add_step` + `pool_spawn_planner`) cleanly sidestepped
  the immutable-step limitation and the FSM's confused step-ordering.
- **Windows-safe verify gate.** Planner used `file_min_bytes` (not POSIX `grep`/`&&`) → no false-fail,
  unlike s2 which closed PARTIAL purely from a `grep`-in-cmd.exe gate bug.
- **Planner self-recovery from worker crash.** Re-dispatch with a live lock holder; orchestrator
  correctly did NOT force-fail (which would have orphaned the lock and deadlocked the plan).
- **Heartbeat loop (`ScheduleWakeup`).** Kept the recipe advancing across ~10 cycles without ever
  handing polling back to the user.
- **HITL gates honored.** Confirm-the-pick gate (user substituted the topic) and present-for-review.

## 6. What didn't work / friction (tool & harness bugs to fix)

1. **`ToolSearch` short names return nothing** — must use fully-qualified `mcp__edp-claude__…`.
2. **`query_objects("session"/"lock", scope={recipe_id|plan_id|step_id})` ignores scope** — returns ALL
   objects across every recipe. Forced manual eyeballing; the unscoped `session` query also blew the
   token limit. *Highest-value fix.*
3. **`query_objects("plan", …)` unsupported.**
4. **`update_object("step", …)` unsupported** — can't re-scope/retarget an existing step; must add a new one.
5. **Claude Code "thinking-block" harness crash** recurring on spawned authoring workers (s1 a3 ×2, s5
   a3 ×1). Self-recoverable via planner re-dispatch, but costs a full worker attempt each time.
6. **FSM `status` phantoms** — `s3 in_progress` with no backing session/lock; the recap kept replaying a
   stale "cleared to proceed: s2…s3 batch-authors" decision that no longer matched the live plan shape.
7. **FSM "3-cycles → escalate" false positive** — fired while the step was actively progressing at the
   action level (author→render→review). Escalation heuristic is step-granular, blind to sub-action progress.
8. **Host browser channel** — `chrome` channel not installed; render checks fall back to bundled
   Playwright Chromium (works, but worth noting for reproducibility).
9. **`branch_reviewer` cross-folder crash** — forking a reviewer of a specialist whose base session
   lives in a different working dir crashes the fork on startup (`reviewer:9d40fcee` dead), exactly
   like `branch_specialist`. Recovered by pivoting to get_specialization-in-a-worker. Recorded to the
   orchestrator spec (v17). Review steps for cross-folder specialists must avoid branch_reviewer.

## 7. Final state / resume note (session ended; user continues in a later session)

- **s5 increment COMPLETE & verified.** `agent-memory-systems` authored to exemplar quality;
  render PASS + gap-curator review PASS (2 non-blocking nits, no re-author). Catalog now **60 slugs**.
- **Recipe deliberately NOT closed.** User chose to continue in another session.
- **Truly done:** s1, s2, s5. **OUTSTANDING — do NOT treat as done:**
  - `s3` = bulk-author the 7-artifact layer across the other ~58 topics. **NEVER RAN.** FSM shows it
    `in_progress` but that is a **phantom** (no planner/worker/lock ever existed; `artifacts.js` holds
    only `agent-evaluation` + `agent-memory-systems`). A future session must verify via pool/disk, not FSM.
  - `s4` = full review+verify before close. pending; not run.
- **FSM lag warning:** after the s5 `plan_closed (succeeded)`, the recap may still show
  `steps=5 (done=2)` / "planner in progress". That is recorded-state lag — trust pool/disk.
- **Resume pointers:** this file (orchestrator side) + `_verification/s5-planner-debug.md` (planner side)
  + `_verification/s5-review-verdict.md`. Orchestrator spec bumped to **v17** (branch_reviewer crash).

---

## 8. Operating-ergonomics assessment (requested by user)

### 8.1 The rxjs/lambda reactive layer (`observe` + `Monitor`)
- **In principle: good design.** Push-not-poll is the right model; merging the broker + pool planes
  into one `rx.merge(rx.broker(me, kinds=[…]), rx.pool())` subscription is expressive.
- **In practice it's a string-encoded mini-language** embedded in a tool arg — no schema, no
  validation until runtime, not introspectable without the guide. Constructing it correctly is a
  guess-and-check exercise.
- **The composition with `ScheduleWakeup` was never clear.** Each wake fires a *fresh* `/neuron` turn;
  whether a `Monitor` stream started in one turn survives to wake later cold re-invocations is
  undocumented. Monitor (push) and ScheduleWakeup (timer) appear to overlap and compete for the
  single foreground, while the guide also says "never block the foreground on a stream."

### 8.2 Why I did NOT use it (the honest answer)
I used `ScheduleWakeup(~270s)` + `check_inbox` pull instead of `observe`+`Monitor`. **Yes — it was
partly that the reactive layer was not clear**, specifically how a long-lived Monitor composes with
the wake/re-invoke loop. I chose the pull because it is **deterministic and idempotent**: it works
identically regardless of session continuity, and I understood its failure modes exactly. It worked
(every message was caught) but cost ~10 polling cycles a push would have saved.

### 8.3 Objects + CRUD clarity
- **Model is clear and genuinely useful** — `describe → read/query → update`, and "FSM owns flow,
  objects own state-truth" repeatedly beat the FSM's stale status this session.
- **Silent edge failures hurt:** `query_objects` `scope` doesn't filter sessions/locks (returns all,
  no error); unscoped session query blows the token limit; `update` unsupported for `step` and
  `query` unsupported for `plan` despite both being listed as full-CRUD "mutate objects". The stated
  model contradicts reality at the edges, and the contradictions fail silently or only error on use.

*(Recorded to orchestrator spec v18 + v19.)*

---
*Generated by the /neuron orchestrator shell from in-context conversation + tool results. Companion
planner-side log requested separately (see message to `…-s5`).*
