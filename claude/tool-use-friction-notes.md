# EDP tool-use friction & docs-improvement notes

Running log of friction, errors, and doc/instruction gaps hit while operating as a
spawned `/agentic-plan` planner. Goal: improve the harness docs/guides and tool
ergonomics so future decision-making is faster and less error-prone.

Started: 2026-05-28 (recipe `recipe-improve-c-projects-learning-new-trends-f-2e15e2`, step s2).
Status: LIVE — append new friction as encountered through the rest of the recipe.

---

## 1. Deferred-tool discovery requires the full `mcp__edp-claude__` prefix
- **What happened:** First `ToolSearch` with `select:get_guide,create_plan,...`
  (the short names used throughout the planner guide) returned
  *"No matching deferred tools found."* Only `select:mcp__edp-claude__get_guide,...`
  worked.
- **Friction:** The planner guide refers to tools by short name (`create_plan`,
  `add_action`, `next_action`), but `ToolSearch select:` matches the fully
  qualified registered name.
- **Suggested fix:** Either (a) make `select:` resolve short names/aliases, or
  (b) note in the guide that deferred EDP tools must be selected with the
  `mcp__edp-claude__` prefix.

## 2. `create_plan` does not echo the resulting `plan_id`
- **What happened:** `create_plan(...)` returned only `{"version": 2}`. Had to
  infer `plan_id = "<recipe_id>-<step_id>"` from the guide to call `add_action`.
- **Friction:** Minor, but a wrong guess would have silently mis-targeted actions.
- **Suggested fix:** Return `{plan_id, domain, version}` from `create_plan`
  (the guide says "the tool fills plan_id" — so just surface it).

## 3. *** CORE FAILURE *** verify `command` runs in the host shell (Windows cmd.exe), not bash
- **What happened:** Authored `add_action(..., verify={check:"command", cmd:"node --check ... && grep -q ... && ..."})`.
  Workers completed correctly, but the gate failed:
  `'grep' is not recognized as an internal or external command`.
  The deterministic gate executes the cmd in **Windows cmd.exe**, where `grep`
  and `&&`-chaining behave differently / are absent. A sibling action using a
  single `node -e "..."` command (no grep, no &&) passed fine.
- **Friction:** Nothing in the planner guide or the verify-block docs warns that
  `command` verifies run in the *host* shell. The guide's mental model ("a fast
  test/lint command", grep-like checks) implicitly assumes POSIX. On Windows this
  silently breaks otherwise-correct work.
- **Suggested fix (high value):**
  - Document that `command` verify runs in the platform shell (cmd.exe on
    Windows) and MUST be cross-platform. Recommend `node -e` / a script runner
    over `grep`/`&&`/`|` pipelines.
  - OR run verify commands through a bundled bash/`sh -c` on all platforms so
    POSIX one-liners work everywhere.
  - Provide a couple of cross-platform verify recipes in the guide
    (e.g. `node -e "const s=require('fs').readFileSync(p,'utf8'); if(!s.includes(x))process.exit(1)"`).

## 4. A stored `verify` cannot be patched mid-flight without a full replan
- **What happened:** To fix the broken grep verify I tried `add_action` with the
  same `action_id` → refused:
  *"plan ... is dispatching; actions can only be added while drafted."*
  The lambda `PlanLens` exposes `reset_action / set_action_done / set_action_failed /
  verify_action` but **no setter for `acceptance.verify`**. The only documented way
  to change a stored verify is `record_plan` (full plan rewrite).
- **Friction:** A one-line, platform-bug fix to a single verify string forces a
  hand-authored full-plan rewrite (error-prone; risks clobbering sibling action
  statuses/evidence). It also can't be done while the plan is dispatching.
- **Suggested fix:** Add a targeted `update_action(action_id, verify=..., description=...)`
  intent tool (allowed in dispatching), or a `PlanLens.set_action_verify(aid, verify)`
  lambda method. Mirrors how `add_action` is preferred over `record_plan` for authoring.

## 5. `set_action_done` / `record_action_status(done)` re-run the stored verify with no override
- **What happened:** Worker's `record_action_status(done)` was hard-blocked by the
  broken gate even though the deliverable was objectively complete and
  independently verified. The planner has no "accept-with-evidence / override a
  spurious gate" path — and since the only fix (replan) was undesirable, the
  complete work was stuck.
- **Friction:** A buggy verify (esp. a platform bug, #3) becomes a hard deadlock
  for genuinely-done work, with no escape hatch short of rewriting the plan.
- **Suggested fix:** Allow a planner-level override (`set_action_done(aid, evidence,
  override_verify=true)`) that records the override + evidence in the worklog for
  auditability, OR let the planner replace/clear a single action's verify cheaply
  (see #4).

## 7. Reaping a worker does NOT bypass the verify gate; phantom-heal `set_action_done` re-runs it
- **What happened:** Per user direction ("don't rewrite the plan — reap the workers
  and close their part"), I `pool_reap`'d a1 and a2 (locks freed; both became
  phantoms: in_progress, no live worker). Then `s.plan(pid).set_action_done(aid,
  evidence)` for each still **ran the stored grep verify and refused** with
  `tool_precondition` — the same cmd.exe/grep failure. The error explicitly states:
  *"If the verify path is wrong, the planner must fix the action's acceptance.verify."*
- **Friction:** There is **no** way to truthfully close a genuinely-complete action
  as `done` while its verify is broken — not via worker record, not via planner
  `set_action_done`, not even after reaping. The intuitive operator move ("reap and
  close it out") does not exist as a done-path; the system funnels you back to
  editing `acceptance.verify`, which requires `record_plan` (a "rewrite") or
  `add_action` (blocked while dispatching). The only ungated terminal is
  `set_action_failed`, but that would **misrepresent successful work as failed** and
  likely fail the whole step — so it is not a real option for done-but-gate-broken work.
- **Suggested fix:** This is the crux. Provide an auditable planner override for a
  spurious/broken gate (e.g. `set_action_done(aid, evidence, override_verify=true)`
  that logs the override), AND/OR a cheap single-field verify setter usable in the
  `dispatching` state (see #4/#5). Without one, a platform-incompatible verify (#3)
  is an unrecoverable deadlock for correct work unless you rewrite the plan.

## 6. Lambda sandbox: no Python builtins (e.g. `hasattr`)
- **What happened:** `work_via_lambda` body using `hasattr(s.broker,'peek')` →
  `NameError: name 'hasattr' is not defined`.
- **Friction:** Expected — the sandbox blocks builtins — but I reached for
  `hasattr` to probe a lens before reading its guide. Error message was clear and
  pointed me to `get_lambda_guide`.
- **Suggested fix:** Minor — the lambda guide could list which builtins (if any)
  are available, so one doesn't probe defensively.

---

## What worked well (keep)
- `inspect_worker` (liveness=alive/dead) — clear slow-vs-hung signal; the inline
  "do NOT force-fail a live shell" note is genuinely useful.
- `work_via_lambda` + `verify_action` (run the gate WITHOUT recording status) —
  exactly the right tool to diagnose the grep failure precisely.
- `broker.check_inbox` (read-only peek, doesn't move the FSM cursor) — let me see
  pending worker questions without disturbing flow.
- `get_lambda_guide(topic=...)` per-lens docs — concise and accurate.

---

## OPEN ISSUE carried forward (this recipe)
- a1-widely-known-stubs and a2-just-launched-stubs: deliverables complete & correct
  (independently confirmed) but cannot reach `done` because their stored verify uses
  grep on cmd.exe (#3) and the verify can't be cheaply patched (#4) / overridden (#5).
  Workers told to HOLD. Awaiting a chosen unblock mechanism (verify-only record_plan,
  skip-gate + manual accept, or a new update-verify path).

---

# Orchestrator (`/neuron`) findings — appended 2026-05-28

Friction hit from the recipe-owner / orchestrator role (not the planner) during the
same recipe. These are about specialist consultation, sub-shell spawning, and FSM
state-truth — complementary to the planner-side notes above.

## O1. `branch_specialist` crashes when the specialist's base session lives in another folder
- **What happened:** Branched the trained specialist `ai-ml-interview-prep-gap-curator-0b5fbe`
  (base_session_id `dada7ee2…`) twice from this working dir. Both forks spawned, returned a
  handle, then died on load — no broker reply ever arrived; `check_inbox` stayed empty. The
  user diagnosed it: *"the conversation doesn't exist in this folder."* `branch_specialist`
  tries to `--resume`/`--fork` the base session, which was recorded in a different project
  directory, so the child shell can't load it.
- **Friction:** No pre-flight check that the base session is resumable from the current cwd;
  failure is silent (a handle is returned, then nothing). Cost two full wait cycles + reaps.
- **Suggested fix:** (a) `branch_specialist` should verify the base session exists/resumable
  from cwd and return an explicit error if not; (b) document that a trained specialist is
  only branchable in the folder it was trained in; (c) offer a session-less fork mode that
  loads knowledge via `get_specialization` instead of resuming the chat.
- **Workaround that worked:** spawn a plain worker (Agent / `pool_spawn_worker`) and have it
  load the trained knowledge via `get_specialization(spec_id=…)` — no session resume, no crash.

## O2. `get_specialization` needs the SPEC id, not the NEURON id — silent `spec:null`
- **What happened:** Briefs initially passed the neuron id (`ai-ml-interview-prep-gap-curator-0b5fbe`)
  to `get_specialization`, which expects `spec_id="spec-ai-ml-interview-prep-gap-curator-0b5fbe"`.
  It returned `spec:null` with NO error, so workers proceeded WITHOUT the load-bearing knowledge.
- **Friction:** The id mismatch (`neuron_id` vs `spec-`-prefixed `spec_id`) is easy to conflate,
  and the null return is silent — you only notice when output quality is generic.
- **Suggested fix:** (a) `get_specialization` should error (or auto-resolve) when handed a known
  neuron_id instead of a spec_id; (b) `neuron_search`/`neuron_get` results already carry both —
  the guides should stress passing the `spec_id` field specifically.

## O3. `consult_specialist` is a synchronous knowledge pull, not a live forked SME
- **What happened:** `consult_specialist` returns the specialist's stored spec entries
  synchronously for the ORCHESTRATOR to reason over — it does not spawn a separate reasoning
  shell. The user reasonably expected "consult" to mean a live shell was asked, and was
  skeptical ("Did you really launch a consult shell and ask?").
- **Friction:** The verb "consult" overloads two very different mechanics (sync knowledge pull
  vs `branch_specialist`'s live fork). Easy to mis-set user expectations.
- **Suggested fix:** Rename/clearly document: `consult_specialist` = "load this specialist's
  knowledge for you to use"; `branch_specialist` = "spawn the specialist as a live shell that
  reasons and replies." A one-line contrast in the phase-B guide would prevent the confusion.

## O4. FSM `done` count advances on a PARTIAL step close (state-truth is rough)
- **What happened:** After s2 closed PARTIAL (a1/a2 marked FAILED by the broken grep gate, work
  actually correct on disk), `next_action` reported `steps done=2` and immediately offered
  `spawn_planner` for s3. The rough FSM status treated the partial close as a completed step.
- **Friction:** A planner forced into a PARTIAL close by a spurious gate (#3/#5/#7) is
  indistinguishable, at the FSM level, from a clean completion — the orchestrator must
  independently verify deliverables on disk (Grep/Read) to know the truth before proceeding.
- **Mitigation used:** verified all 14 new slugs present in the bucket files + topics.json via
  Grep before allowing s3 to dispatch; passed a "do NOT re-seed — treat as present" warning
  downstream to avoid duplicate entries.
- **Suggested fix:** Surface partial-vs-clean in `next_action`'s recap (e.g.
  `steps done=2 (1 partial)`), and/or carry the failed-action evidence forward so the next
  step's planner is told what's actually on disk.

## O5. Spawned workers can die on a Claude Code harness API bug (`'thinking' blocks … cannot be modified`)
- **What happened:** The s1 a3 browser-verification worker died TWICE on
  *"`thinking` blocks in the latest assistant message cannot be modified."* The planner
  recovered by running the verification INLINE in its own shell (headless chromium via the
  bundled Playwright) and healed a3 with evidence.
- **Friction:** A transient harness/API bug can repeatedly kill a spawned sub-shell; without a
  fallback the step deadlocks.
- **Suggested fix (operational):** when a spawned worker dies on this specific harness error,
  inline the work in the planner/orchestrator shell rather than re-spawning into the same bug.
  (Documented here so the pattern is reused, not rediscovered.)

## What worked well (orchestrator side, keep)
- `work_via_lambda` + `PlanLens.effective_status/worklog/phantoms` — gave true ground state
  (which actions are really done, which workers are alive) when the FSM's rough status was
  ambiguous; the worklog's `lambda_reset_action` / `crash_recovery` entries told the real story.
- `ScheduleWakeup` heartbeat for self-re-polling `next_action` — kept the recipe progressing
  without handing polling back to the user.
- The persistent two-way curiosity (`consult_curiosity` once + `reply`/follow-up by
  `curiosity_id`) converged comprehension cleanly to `status=done`.
