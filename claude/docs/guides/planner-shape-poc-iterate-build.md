# Planner shape: poc-iterate-build

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** novel or uncertain coding goals where the
riskiest assumption (performance, integration, library compatibility,
ML feasibility) is **not pre-validated**. The chess-engine session is
the canonical case: a 12-action build was kicked off without first
confirming Python alpha-beta could hit the target NPS — every action
looked done, but the system-level requirement quietly failed at
action 13.

The fix is **explicit POC stages with acceptance gates** before
scaling to the full implementation.

## Plan structure: Stage A (POC) → Gate → Stage B (full build)

**Stage A — POC**
- Smallest possible implementation that exercises the riskiest
  assumption end-to-end.
- 1-4 actions.
- Each action has a measurable `acceptance` signal.
- **Final Stage-A action is a benchmark or smoke test that produces a
  single number / outcome comparable to the goal's stated
  requirement.**

Example Stage-A final action:
- Description: "Benchmark depth-3 negamax on 5 random positions;
  record nodes-per-second."
- Acceptance: `{"kind": "metric", "expected": "avg_nps >= 50000"}`

**Gate** (between Stage A and Stage B)
- Surface the Stage-A benchmark result to the neuron via
  `notify_above(kind="observation", body={...})` (or to the user via
  AskUserQuestion if the threshold judgement is theirs).
- The Stage-A acceptance is a **metric** — the filesystem can't verify
  whether the number is real or whether it actually means the risk is
  retired. For a borderline or high-stakes result, dispatch your OWN
  review leg (`role="reviewer"`) against the relevant specialist's
  compiled doc (domain review replaced the generic critic in v2.4).
  This is the non-deterministic counterpart to the outcome-verify file
  gate: a metric claim gets external review, not self-attestation.
- If the result clears the threshold → continue to Stage B.
- If it doesn't → `ask_above(question="POC underperformed: X vs
  required Y. Pivot, abort, or extend?")`. Do NOT silently proceed.

**Stage B — Full build**
- Only authored AFTER Stage-A clears. The full implementation
  (potentially many actions).
- Built on the POC's foundation; same architecture, scaled out.

## Anti-patterns

- **Building Stage B before Stage A clears.** This is the chess-
  engine failure mode. The entire point of this shape is the gate.
- **Stage-A acceptance that doesn't measure the risk.** "Stage-A test
  passes" without a metric tells you nothing. The acceptance must
  reference the system-level number that mattered.
- **Treating the gate as ceremonial.** If Stage A barely clears
  (e.g., 51k NPS for a 50k threshold with messy variance), surface
  it — don't paper over.
