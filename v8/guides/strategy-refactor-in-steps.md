# strategy_hl: refactor-in-steps

**Intent + why.** A refactor that changes structure and behavior at once is unreviewable
and unsafe to bisect if something breaks; keeping behavior fixed while structure changes
(and vice versa) makes every step independently verifiable.

**When it applies.** work_type=chore/feature stories whose goal is internal structure
(module boundaries, dependency direction, naming, dedup) without an intended behavior
change; also the structural portion of a bug fix.

**Phases**
1. Characterize — confirm or add tests that pin current behavior, if the coverage needed
   for step 4's re-verification does not already exist.
2. Step plan — break the target structure change into small steps, each independently
   revertable, each preserving behavior.
3. Execute — one step at a time; run the pinning tests after each step before starting the
   next.
4. Verify — full check suite green at the end; behavior identical to before unless the
   story explicitly scoped a behavior change too.

**Exit condition.** Structure matches the design's target; the pinning tests (and the
story's criteria) pass unchanged throughout.

**Typical gates.** None by default; a refactor touching a shared/critical seam may warrant
an early reviewer look on the step plan before executing.
