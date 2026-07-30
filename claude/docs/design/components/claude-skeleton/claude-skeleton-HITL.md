# S4 — Acceptance (claude/ skeleton, component #2)

**Shape:** case (a) automated (METHODOLOGY S4). The skeleton has no
real user-facing behaviour yet (pool/broker are stubs); the binding
evidence is the automated DESIGN-v4 §7 walkthrough. Human by-hand HITL is
deferred to the **integrated milestone** (real edp-pool/edp-broker driving
real shells) — confirmed with the user 2026-05-17.

## Evidence
- **WALK-1 (binding):** the DESIGN-v4 §7 22-row trace runs end-to-end over
  the stubs; the exact instruction spine is asserted:
  `invoke_skill → ask_user → invoke_skill → run_inline → spawn_planner →
   wait → dispatch_action → dispatch_action → done → run_inline → done`,
  with every recipe/plan state transition checked. **PASS.**
- 19/19 tests pass: WALK-1, per-row FSM (incl. the F4.c "done-but-unproven
  ⇒ partial, not succeeded" guard), the P4 /clear-test (two independent
  fresh contexts resuming from disk agree), tool preconditions &
  validators-as-instruction, file-memory + kg_filter, the FSM-abstention
  seam.
- Ruff clean (incl. flake8-print). Coverage 91% total; load-bearing paths
  (FSM, tools, stores, walkthrough) ≥85–100%.
- `edp-contracts==0.1.0` pinned (uv path source).

## Gate decisions carried from S3b REFACTOR §4 (need user verdict)
1. **Tool files consolidated** into `tools/_tools.py` (LLD §1 said one file
   per tool). Same 15-tool surface. Accept consolidation, or split?
2. **`next_action` persists pure state advances** (LLD called it
   "read-only"). Behaviour is correct and proven by the /clear-test; the
   LLD *wording* is stale. Recommend: amend LLD wording. Confirm?

## Verdict
**ACCEPTED 2026-05-17** under the user's standing directive ("continue
implementing; only surface for open questions or manually-testable HITL").
Component #2 is internal/stubbed (case-a) — not manually testable, no open
question — so it is accepted on the automated evidence. The 2 carried
decisions resolved by recommendation (revertible):
1. Tool-file consolidation **accepted** (`tools/_tools.py`; surface
   unchanged; revert = split into 15 files if ever needed).
2. LLD `next_action` wording **amended** (LLD §5 row updated: persists pure
   state advances; idempotent at rest, not across a transition).
Component #2 DONE → component #3 (`edp-broker`) enters S1.
