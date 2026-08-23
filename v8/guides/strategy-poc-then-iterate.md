# strategy_hl: poc-then-iterate

**Intent + why.** Prove the riskiest assumption cheaply before investing in the full build.
Applies when the story has one uncertain core mechanism (an API's real behavior, a
library's fit, a performance ceiling) and the rest of the work is routine once that is
known — spending full craft effort before the unknown is resolved risks throwing it away.

**When it applies.** feature/rnd work where a spike answers "will this approach work at
all" faster than designing it properly would.

**Phases**
1. Spike — the smallest code that exercises the risky mechanism, disposable, no craft bar.
2. Judge — does the spike answer the question? If no, spike again on a different approach
   or escalate (/doubt) if the uncertainty is a scope question, not a technical one.
3. Iterate — throw away or harden the spike into production code under the story's real
   strategy_ll craft bars (tests, errors, docs).

**Exit condition.** The risky mechanism's behavior is known and recorded (a plan doc note),
and the production version meets the story's criteria.

**Typical gates.** POC review is often a human gate (§2 invariant 4) before iterate begins,
especially when the spike changes the design's assumptions — flag via /deviation if so.
