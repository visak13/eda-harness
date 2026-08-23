# strategy_hl: research-then-build

**Intent + why.** Building against an unfamiliar API, library, or domain without reading it
first produces rework once the real constraints surface; a bounded research pass up front
is cheaper than iterating in the dark.

**When it applies.** rnd work, or any story that depends on an external system, library, or
domain the engineer has not used in this codebase before.

**Phases**
1. Research — read docs/source/prior art (`find` first — a domain doc may already answer
   this); time-box it; the output is a short note of what's true and what constrains the
   build, not a full report.
2. Design the slice — given the research, decide the approach for this story specifically
   (not a redesign of the epic).
3. Build — implement under the story's strategy_ll craft bars.
4. Verify against research — check the build actually respects the constraints found in
   step 1 (rate limits, auth model, data shape, etc.).

**Exit condition.** The research note exists and is linked; the build matches its
constraints; criteria pass.

**Typical gates.** If research surfaces a scope-changing constraint, /deviation to the
architect before building — do not silently absorb it.
