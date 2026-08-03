# Planner shape: diagnose-fix-verify

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** bug fixes — "X is broken / slow / wrong /
500-ing." The work is **investigative before it is constructive**:
enumerate hypotheses, reproduce, diagnose, patch, verify. The "fix
slow server" use case is the canonical example.

The worklog is the centerpiece — observations and tried-and-rejected
hypotheses are the trail of evidence for the fix and the regression
test.

## Mandatory pre-step — success criteria question

Before authoring the plan, the neuron/user must have stated what
"fixed" looks like. If not yet established:

```
ask_above(question="What does success look like for this fix?",
          body={"proposed": [
            "/health responds in < 200ms",
            "no 500 errors in last 1000 requests",
            "<some other concrete criterion>"
          ]})
```

Without this, you won't know when to stop investigating.

## Plan structure: D → F → V

**D — Diagnose (1-3 actions)**
- Reproduce the bug (locally if possible; record the steps).
- Enumerate hypotheses (each a candidate root cause).
- Investigate each — the action's acceptance is "ruled in" or "ruled
  out" with evidence.

**F — Fix (1-3 actions)**
- Only authored AFTER diagnosis is done. The fix targets the
  identified root cause, not symptoms.
- Each action has a code-level acceptance (`tests_pass` or similar).

**V — Verify (1-2 actions)**
- Reproduce the bug again — confirm it's gone.
- Add a regression test that would have caught the bug, so future
  reverts surface immediately.
- "Fixed" is a `tests_pass` / behavioural claim the filesystem can't
  fully verify. For a non-trivial fix, dispatch your OWN review leg
  (`role="reviewer"`, named `r<n>`/`review-…`) against the relevant
  specialist's compiled doc to judge whether the fix addresses the root
  cause or just the reproduced symptom (the Comprehension question in
  `framework-ocak`). Self-attesting "it's fixed" is the trap; external
  review is the counterpart to the outcome-verify file gate for
  non-deterministic acceptance.

## Action acceptance shapes

- D-actions: `{"kind": "hypothesis_resolved", "expected": "ruled_in
  | ruled_out", "actual": "<evidence summary>"}`
- F-actions: `{"kind": "tests_pass"}` plus a one-line note in
  evidence.
- V-actions: `{"kind": "regression_test_added"}` + reproduce-the-
  original-failure test.

## Anti-patterns

- **Jumping to F before D is done.** "I think I know what it is" is
  a hypothesis, not a diagnosis. Verify before fixing.
- **Patching the symptom.** If the user's "slow API" is really a
  hot-path lock-contention bug, adding a cache is symptom-patching
  that'll regress under different load. Diagnose root cause.
- **Skipping V.** Without regression coverage, the same bug returns
  silently next refactor. The verify step IS the fix's durable
  value.
- **No `ask_above` when diagnosis points elsewhere than the stated
  bug.** If your investigation reveals the user's "bug" is actually
  expected behaviour under a misunderstood spec, escalate; don't
  silently fix something the user didn't ask for.
