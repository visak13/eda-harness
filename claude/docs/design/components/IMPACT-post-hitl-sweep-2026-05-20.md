# §5.5 IMPACT — post-HITL sweep (2026-05-20)

One remediation sweep from the second live `/neuron` HITL
(`scratch/project-ideas/{owner,planner,worker}-debug.md`). The run
SUCCEEDED end-to-end and the recipe closed (F1/F2 reconcile held;
**cron-wake observed working in spawned shells — the load-bearing spike
is answered PASS by user observation**). Three defects surfaced; all
verified in code, not taken on the agents' word.

## A — plan FSM never marks an action `in_progress` (wake, tool-forcing)
**Verified:** `plan_fsm.py:29-44` `DISPATCHING` returns
`DISPATCH_ACTION` for the first **`pending`** action and never stamps
it. `pool_spawn_worker._run` (`_tools.py:607`) doesn't touch the plan.
The action stays `pending` until the worker writes `done`, so
`_first_ready_action` keeps re-selecting it → the FSM re-emits
`DISPATCH_ACTION` and the `WAIT` branch (40-44) is unreachable. ∴
`_enrich_wait` on the plan handle is dead at runtime; the planner's
heartbeat was applied by **brief inference**, not tool-forced — a
DESIGN-v5 violation ("tools enforce, not prompts") and a
duplicate-dispatch risk. Empirically it worked only because the model
inferred correctly.

**Fix (FSM-mirror, user-approved):** mirror `recipe_fsm.py:123` — in
`plan_fsm` `DISPATCHING`, set `nxt.status = "in_progress"` before
returning `DISPATCH_ACTION`. Then the next `next_action(plan)` finds no
ready `pending` action, the non-terminal list is non-empty → `WAIT` →
`_enrich_wait` fires → planner heartbeat is tool-forced.
**Coupled fix (mandatory):** the plan-path save-guard
(`_tools.py:102` `if p.state != before_state or p.terminal_status`)
only persists on a *plan-state* change, so an action-level
`in_progress` stamp would not survive to the next call. Widen to a
cheap mutable-signature compare:
`before = (p.state, tuple(a.status for a in p.actions),
p.terminal_status)`; save if it changed. Mirrors the recipe path's
intent. FSM stays pure (mutates the in-memory model only; the tool
persists — same contract as the recipe layer).

## B — MCP layer is schema-less + the accidental `payload` wrapper
**Verified:** `mcp_server.py:66-84` `_make_shim` registers
`async def shim(payload: dict)` and discards `bound_tool.InputModel`.
FastMCP derives the schema from the signature → every tool advertises
an opaque `{payload: object}`; the real contract lives only in prose +
trial-by-rejection. The wrapper is not a design choice — it was a
workaround for FastMCP's `_`-name rejection + loop late-binding, leaked
into the contract. All three shells hit this; it is the v5 disease at
the MCP boundary. **No existing test exercises the wrapper** —
`base.py:71` `run()` already takes the flat dict; `conftest.env.call`
and `test_mcp_2` call `run()` flat. So blast radius is contained to
`_make_shim` + briefs + (new) a schema assertion.

**Fix (drop wrapper + expose real schema, one stroke, user-approved):**
rebuild the shim with a dynamic signature from `InputModel.model_fields`
(name, annotation, required/default) so FastMCP emits the true per-tool
schema (nested models like `Plan` resolve via their annotation; a
no-field model like `_CloseSelfIn` → empty schema, which correctly
documents "no args"). Shim collects `**kwargs` → `bound_tool.run(kwargs)`
unchanged. **Implementation risk (flagged):** FastMCP must honour
`fn.__signature__`/`__annotations__`; pinned by a new test asserting a
known tool's schema has real top-level properties and no `payload`.
Briefs: delete every "wrap args in `payload`" instruction.

## C — no `close_recipe` intent tool (brief ↔ tool contradiction)
**Verified:** every lifecycle step has an intent tool
(`start_recipe`/`record_branch_verdict`/`record_outcome`/`add_step`)
EXCEPT close. `neuron.md:20` says "you do NOT hand-author recipe JSON"
but `:58` says close via `record_recipe(<full object>, state=closed)` —
the raw strict-schema escape hatch. Owner spent **6 rejection
round-trips**: exactly the guess-and-resolve v5 kills. The recipe
already has goal/domain/steps on disk, so a load-mutate-save intent
tool satisfies every `Recipe` invariant trivially (that is *why* the
hand-authored path was painful — it re-derived all of it).

**Fix (add the missing intent tool):** new `close_recipe`
(`recipe_id`, `final_outcome: dict`) — load recipe, set
`state=CLOSED` + `final_outcome`, save. Mirrors `record_outcome`/
`add_step`. Register (21→22). `neuron.md` `done` → `close_recipe(...)`,
delete the hand-author instruction. `record_recipe` stays (still the
create/test surface) but is no longer on the neuron's close path.

## Blast radius (total)
- `plan_fsm.py` (+1 line), `_tools.py` (save-guard widen; +`CloseRecipe`
  + register), `mcp_server.py` (`_make_shim` rebuilt). FSMs stay pure.
- Briefs: `neuron.md` (close path), all three (drop `payload` prose).
- Tests: existing suites UNCHANGED (none use the wrapper); ADD
  close_recipe behaviour test + MCP-schema assertion test; bump
  tool-count 21→22 (two asserts).
- contracts/broker/pool UNTOUCHED.

## Validation
Unit/integration/pool suites are the cheap regression gate (none
change). True proof = one more live multi-shell `/neuron` HITL: confirm
(a) planner now gets a tool-forced `wait`+heartbeat (A), (b) agents
call tools flat with visible schemas + fewer rejection loops (B), (c)
neuron closes via `close_recipe` first-try (C).

## Verdict
A = v5 correctness (tool-forcing) + the fix that lets the cron path be
*forced* not inferred. B = removes the largest cross-cutting friction
at root; contained. C = completes the v5 intent-tool set. Proceed.
