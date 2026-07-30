# Planner shape: research-synthesize

> **OPTIONAL ACCELERATOR** — a pitfall checklist for a DAG you already
> drew (planner-phase-author Step 1). Never contort work to fit this
> file; a DAG matching no shape is normal — proceed with your DAG.

**When this shape applies:** pure analysis, surveys, comparisons,
literature reviews — "what do we know about X." The deliverable is
**structured reasoning**, not code or external action.

This shape often does NOT need a full plan with worker dispatch — see
"single-shell mode" below.

## Decide first — single-shell vs full plan

A full plan (with dispatched workers) is warranted ONLY when:

- The deliverable is a structured artifact (report, comparison table,
  ADR draft) that will be referenced by future work.
- AND the research naturally splits into independent investigations
  that benefit from parallel work.

If neither applies, this is a **single-shell synthesis** — the planner
itself does the reasoning + writes the answer directly. One action
with `executor_mode="inline"`, acceptance = "deliverable produced."

If both apply, the plan has 3 sub-shapes:

### Survey (1-N actions, parallel-OK)

Each action investigates one source / dimension. Worker actions have
`{"kind": "summary_produced", "expected": "<deliverable shape>"}`
acceptance. Output: per-source notes / extracts.

### Synthesize (1 action)

Take the surveyed material and produce the structured artifact.
Inline-mode (planner does it) unless the synthesis itself is
mechanical enough for a worker.

### Verify (1 action)

Check the synthesis against the user's stated criteria. If the
user asked for "5 ideas," there are 5 ideas. If they asked for
"sources cited," sources are cited. Honest verification.

## Anti-patterns

- **Spawning workers for trivial research.** If you can produce the
  answer in your own reasoning in 5 minutes, that's a single inline
  action, not a multi-worker plan.
- **Synthesizing without a structure.** A research deliverable
  without a table-of-contents or comparison axis is prose-soup.
  Define the structure first, then fill it.
- **Citing the LLM's own knowledge as the source.** Pure model-recall
  is fine for analysis, but flag it as such ("based on general
  knowledge, not specific sources"). Don't fake citations.
