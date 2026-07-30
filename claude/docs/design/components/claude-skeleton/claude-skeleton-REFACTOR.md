# REFACTOR — claude/ skeleton (component #2, stage S3b)

**Stage:** S3b — after S3a Dev, before S3c Tests (methodology). Mandate:
extract constants, evaluate enums, detect interface/ABC opportunities, and
**sweep every TODO** (METHODOLOGY §4a — no S3b pass with un-triaged TODOs).

---

## 1. Constants extracted (hard-coded → named)

| Constant | Module | Replaced |
|---|---|---|
| `SKILL_OCAK`, `SKILL_CRITIC` | `fsm/recipe_fsm.py` | inline `"ocak"`/`"critic-review"` skill literals (×4) |
| `SKILL_ACCEPTANCE` | `fsm/plan_fsm.py` | inline `"acceptance-review"` |
| `_TERMINAL_ACTION_STATUS` | `tools/_tools.py` | inline `("done","failed","skipped")` |
| `_KIND_PLAN_CLOSED` | `tools/_tools.py` | inline `"plan_closed"` broker-kind literal |

## 2. Enum evaluation

- **Reused, not re-created:** `RecipeState`/`PlanState`/`InstructionKind`
  are already `StrEnum` (schemas) and the FSM uses `InstructionKind` via the
  `K` alias. No new enum needed there.
- **Declined (documented so it isn't re-analysed):** `Action.status` /
  `RecipeStep.status` / `Branch.status` stay Pydantic `Literal`. Same
  precedent set in base-contracts S3b — `Literal` is the idiomatic Pydantic
  field type and gives identical validation; a `StrEnum` would only add an
  import. The *logic groupings* the tools branch on are extracted as the
  named tuples/sets in §1 instead.

## 3. Interface / ABC review

- Ports (`PoolPort/BrokerPort/MemoryPort/FsmPort`) are already ABCs;
  `_ClaudeTool` is the shared tool base; `Tool` (edp-contracts) is a real
  ABC. No missing seam.
- **Considered + declined:** a `DomainModule` Protocol over
  `kg_filter`/`success_criteria`. The two functions are resolved by
  `domains/__init__.py` via `import_module`; a Protocol would add type
  ceremony without removing duplication (there are exactly two domains and
  the contract is two functions). Re-evaluate if a third domain lands.

## 4. LLD deviations flagged (METHODOLOGY §5.4)

1. **Tool files consolidated.** LLD §1 listed one file per tool
   (`next_action.py`, `record_recipe.py`, …). Implemented as `tools/base.py`
   + `tools/_tools.py` (one cohesive module) + `tools/__init__.py`
   registry. Same 15-tool surface, far less file ceremony. Deliberate;
   revertible. **Gate decision:** accept consolidation or split.
2. `next_action` is documented in the LLD as "read-only". It in fact
   **persists pure bookkeeping state advances** (created→comprehending,
   planning→executing, etc.) — without that, a resumed process couldn't
   make progress. Behaviour is correct (the /clear-test proves resume
   determinism); the LLD wording is the thing that's stale. **Gate
   decision:** amend LLD wording ("next_action may persist a pure state
   advance") — recommended.

## 5. TODO sweep (METHODOLOGY §4a — every TODO triaged)

| TODO | Owner | Disposition |
|---|---|---|
| `stub_fsm.py` — replace with HttpFsm | **edp-fsm (#5)** | Re-deferred: blocked on component #5 by design (build order). Legitimate. |
| `file_memory.py` — swap to KG facade | **edp-memory-svc** | Re-deferred: KG is explicitly post-launch (DESIGN-v4 §5; user "text file may suffice"). Legitimate. |
| `server.py` — real MCP transport wiring | **claude-skeleton (this)** | Re-deferred *with reason*: not load-bearing for WALK-1 (tests drive tools directly) and depends on an MCP-SDK choice not yet made. Tracked as a named follow-up before the first real shell needs MCP. Allowed under §4a (explicit owner+reason). |
| `software_engineering/__init__.py` — capabilities.yaml / default_shapes.yaml | **claude-skeleton (this)** | Re-deferred *with reason*: only consumed by a shape pipeline, none exists yet. Add when the first shape consumes them. |
| `_tools.py` — consolidate record_decision/assumption/rejected_option | **revisit (#2)** | Re-deferred *with reason*: explicit user directive 2026-05-17 to keep 3 tools now, revisit once usage frequency is known. |
| `goal-keeper-check.md` / `critic-review.md` — richer backend | **cluster/edp-fsm** | Re-deferred: skeleton ships the verdict shape; full protocol arrives with later components. |

No TODO is un-triaged; none is silently deferred. All re-defers carry an
explicit owner + reason here, per §4a.

## 6. Verification

- Full suite re-run after refactor: see S3c result in PROGRESS / gate log.
- No behavioural change intended by §1–§3; the 13 tests (incl. WALK-1) are
  the regression guard.
