# Specialist guide: estimation

Estimate an action's duration using seed priors and prior-plan
actuals; surface unreliable estimates that should be split.

## When to consult

During plan authoring (per-action), or when a worklog drift entry
shows an action took >3× its estimate (feedback — revise the seed
prior).

## Criteria

Seed priors (starting points, not algorithms):

- **trivial bookkeeping** (rename, simple flag flip, single-file edit
  with no tests): 60-300s
- **substantive coding** (new function with tests, refactor across
  2-3 files): 600-2400s
- **integration** (touches multiple services or external systems):
  1800-7200s
- **research/experimentation** (POC, unknown territory): wide range;
  default to 3600s and flag low confidence.

Reason about which prior applies given the action description, then
adjust up/down based on signals you read from the action's scope and
prerequisites. `recall("estimation history for <action_type>")` to
pull prior actuals when available.

Useful signals: action description verbs (rename → quick, integrate
→ slow), test requirements, prerequisite count. Useless signals: how
the action sounds (excited prose ≠ harder); whether other actions in
the plan are similar.

## Verdict shape

```json
{
  "action_id": "<aid>",
  "estimate_seconds": <int>,
  "confidence": 0.0-1.0,
  "should_split": <bool>,
  "split_rationale": "<one sentence — only when should_split=true>",
  "seed_prior_used": "trivial" | "substantive" | "integration" | "research",
  "evidence": "<one-line summary>"
}
```

## Anti-patterns

- Don't anchor on a magic number. Pick a seed prior, justify the
  adjustment, return the result with honest confidence.
- Don't refuse to estimate. Wide ranges are valid; "I don't know"
  isn't actionable. Use confidence < 0.5 to signal uncertainty.
