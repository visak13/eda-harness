# strategy_hl: creative-reference-then-build

**Intent + why.** Creative/UI work judged only by code review misses whether it looks
right; anchoring to concrete references before building gives the consultant (visual
authority) and the owner something specific to judge against, instead of a subjective
back-and-forth after the fact.

**When it applies.** work_type=creative, or any story whose acceptance criterion is `check:
look`.

**Phases**
1. Reference — gather or request concrete references (existing screens, competitor
   examples, a style guide) before writing the look spec; consult the consultant for a
   read if none exist.
2. Look spec — state what "done" looks like against the references (layout, states,
   motion, tone), from the design doc's look spec section.
3. Build — implement against the spec.
4. Consultant read — `consult(purpose=visual)` before /demo to the owner; treat findings
   as input, not a verdict — the consultant is not the sign-off authority, the owner is.

**Exit condition.** The build matches the look spec; the owner has seen it via /demo and
reacted.

**Typical gates.** /demo is mandatory before the story is marked in_review for this
strategy — a look criterion cannot be verified from the report doc alone.
