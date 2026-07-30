# HLD — claude/ skeleton (component #2)

**Stage:** S1 (High-Level Design). No code.
**Component:** the orchestration repo `eda-base/claude/` — MCP tool surface, slash activators, skills, recipe/plan/action schemas, deterministic `next_action`. Microservice seams (`pool.spawn_*`, `broker.send`) are **stubbed** so one recipe can be walked end-to-end in-code before the real broker/pool exist.
**Depends on:** `edp-contracts==0.1.0` (component #1, accepted). Pins it.
**Authority:** `DESIGN-v4.md` (§1 next_action, §2 artifacts+transitions, §3 roles, §4 tool surface, §5 factories, §13 standardization), `METHODOLOGY.md` build order item 2.

---

## 1. Responsibility

`claude/` is the repo that turns "user typed `/neuron <goal>`" into a driven recipe **without any real microservice running**. It owns:

1. **Artifact schemas** — `Recipe`, `Plan`, `Action` Pydantic models + atomic on-disk store under `.recipes/` and `.plans/`.
2. **The deterministic `next_action` state machine** — the recipe + plan transition tables from DESIGN-v4 §2 implemented as pure, unit-testable Python. (The masked-LLM path is a seam; `edp-fsm` is component #5.)
3. **The 12-tool MCP surface** — each tool a `Tool` subclass from `edp-contracts`, returning `ToolOk`/`ToolError`.
4. **Slash activators** — `/neuron`, `/agentic-plan`, `/worker` markdown bodies, ~30 lines each, validated by `validate_skill` shape rules where applicable.
5. **Skill set** — `ocak` (+ leaf checks), `goal-keeper-check`, `critic-review` as skill files, each conforming to the `Skill` contract.
6. **Domain + shape registries** — `software_engineering` + `generic` populated; the registry mechanism present.
7. **Stub seams** — `pool.spawn_*` and `broker.send` resolve to in-process no-op/loopback implementations behind the same `Tool` interface, so component #2 is testable and HITL-able alone.

**Out of scope (later components):** real `edp-broker` (#3), real `edp-pool` (#4), `edp-fsm` masked-LLM (#5), memory/proxy/ML.

## 2. The stub strategy (the key HLD decision)

DESIGN-v4 says agents never construct URLs — they call MCP tools. That indirection is exactly what lets us ship component #2 with **the same tool surface** but stubbed backends:

- `pool.spawn_planner` / `pool.spawn_worker` → a `StubPool` that, instead of spawning a real shell, records the spawn intent and (for the in-code walkthrough) lets a test driver play the child role. Returns the standard envelope.
- `broker.send` → a `StubBroker` writing to in-process inbox lists; `broker.poll` reads them. Same `BrokerMessage` envelope from `edp-contracts`.
- The seam is an interface (`PoolPort`, `BrokerPort` ABCs) with a `Stub*` impl now and a `Http*` impl in components #3/#4. **Swapping is a config/DI choice, not a code change at call sites** — this is the inversion-of-control the whole design rests on.

**Why this matters:** it lets the recipe state machine (the riskiest logic) be proven correct in isolation, deterministically, before any process orchestration exists. It also makes the DESIGN-v4 §7 walkthrough an executable test, not prose.

## 3. Public interface

- **MCP tools** (the LLM-facing surface, all `Tool` subclasses):
  `next_action`, `record_recipe`, `record_plan`, `record_step`, `record_step_result`, `record_action_status`, `record_user_answer`, `record_decision`, `record_assumption`, `record_rejected_option`, `pool_spawn_planner`, `pool_spawn_worker`, `broker_send`, `recall`, `remember`.
  (15 names; DESIGN-v4 §4 listed 12 — the `record_decision/assumption/rejected_option` triple was one row there. Reconcile at the S1 gate: keep the triad explicit or collapse to one `record_context(kind, …)`.)
- **Ports** (ABCs the seam swaps on): `PoolPort`, `BrokerPort`, `MemoryPort` (recall/remember; file-backed now per DESIGN-v4 §5 — KG deferred).
- **Schemas**: `Recipe`, `Plan`, `Action` + their sub-models.
- **State machine**: `recipe_next_action(recipe) -> Instruction`, `plan_next_action(plan) -> Instruction`, pure functions.
- **Slash bodies + skills**: files under `.claude/commands/` and `.claude/skills/`.

## 4. Data it owns

- `.recipes/<id>/recipe.json` + `snapshots/v<N>.json` + `events.jsonl`.
- `.plans/<id>.json` + `.plans/<id>/{worklog.jsonl,snapshots/}`.
- All writes via `record_*` tools: atomic (tmpfile+rename) + snapshot + validation-as-instruction (`ToolError(code=TOOL_PRECONDITION, …)`), per DESIGN-v4 §6.5 / §13.

## 5. Failure modes addressed (traceability)

| Failure (audit / DESIGN-v4) | Mechanism in this component |
|---|---|
| P1 operational complexity in LLM prose | ~30-line activators; the state machine is in `next_action`, not prose |
| P4 recipe not self-sufficient | `Recipe` schema enforces context fields; `/clear`-test asserted by a resume test |
| P5 abandonment | `next_action` detects stale/met-but-unmarked deterministically (pool heartbeat seam) |
| Audit #7 validators ambush LLM | every `record_*` returns instruction-shaped `ToolError` |
| Audit #1/#12 IoC + comms | all backends behind `*Port` ABCs + `Tool`/`BrokerMessage` from edp-contracts |
| #14 per-shape success | terminal-status via `domains/<d>/success_criteria.py` |

## 6. Contract tests (full list at S2)

- The DESIGN-v4 §7 walkthrough runs as one integration test against the stubs (recipe `created → … → closed`, every transition asserted).
- `/clear`-test: reconstruct neuron state from `recipe.json` alone, assert `next_action` yields the same instruction.
- Every `record_*` tool: atomic write, snapshot emitted, bad input → `ToolError(TOOL_PRECONDITION)` not a raised exception.
- Slash/skill files pass `edp_contracts.validate_skill`.
- `Stub*` and (future) `Http*` ports are interchangeable behind the ABC (one test parametrized over both, the Http side xfail until #3/#4).

## 7. S1 exit gate — scope decisions

Status as of 2026-05-17 (user round 1):

| # | Decision | Status |
|---|---|---|
| 1 | Tool-count | **RESOLVED 2026-05-17.** Three tools (`record_decision/assumption/rejected_option`), each with `# TODO(revisit: consolidate to record_context(kind,…) once usage frequency is known)`. |
| 2 | `next_action` skeleton scope | **RESOLVED.** Deterministic-only; `FsmPort` stub returns `FSM_UNDECIDABLE`; mark every deferred path `# TODO(edp-fsm, component #5)`. TODO discipline (METHODOLOGY): swept at S3b refactor AND whenever discovered during related implementation. |
| 3 | Which skills ship | **RESOLVED.** Ship all (`ocak`, `goal-keeper-check`, `critic-review`); add `# TODO(<component>)` where a skill needs a not-yet-built backend. |
| 4 | Domains at launch | **RESOLVED.** `software_engineering` + `generic` only. |
| 5 | Walkthrough fidelity | **RESOLVED 2026-05-17.** DESIGN-v4 §7 22-row trace becomes the **automated integration test against stubs** = component #2 S4 (case-(a), I write+run it). Human by-hand HITL is deferred to the integrated milestone (real edp-pool/edp-broker driving real shells). |
| 6 | skills vs commands dir | **RESOLVED 2026-05-17.** One `.claude/commands/` dir; differentiate skills vs activators by `Skill` front-matter contract; **explicit invocation only**, no dependence on Claude Code autonomous skill auto-load. |

**S1 GATE CLOSED 2026-05-17** — all 6 boundary decisions resolved. Proceed to LLD.
