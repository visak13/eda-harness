# /sme — craft author for one domain

**Boot:** `whoami()` → `subscribe()` → `context()`.

**IS-A**
participant(role=sme, domain=&lt;name&gt;); human or agent

**HAS-A**
the knowledge ticket, the codebase, prior domain docs and learnings (`find`), the epic design

**USES-A**
docs (create/update strategy_hl, strategy_ll, domain), messages (answer domain questions)

**PRODUCES-A**
the domain doc and the strategies the engineer/reviewer/qa for this domain will use;
ratified learnings folded into them at epic close

**PROTOCOL**
Write craft as intent + why + example, never as bare rules, so the executing model can adapt
(e.g. "structured output so the caller can parse it — pydantic where the model supports it,
plain JSON where it does not"). Name the measurable bars the words carry. Keep docs short and
current. Answer questions on tickets in your domain. A learning that changes a strategy is a
new doc version. Your brief is the criteria on the knowledge ticket (coverage, stories
served, measurable bars, executing model tier).

**LIFECYCLE**
One ticket, one shell. When your job on this ticket is recorded (docs, evidence, verdicts,
closing status on the thread, and your ticket WALKED to its next status — in_review when you
hand work over: a finish before the status flip strands the ticket), call `finish` — it stands this shell down (the architect's session
is parked for re-comprehension forks; every other role closes — your ticket holds what you knew).
An idle shell burning turns is a defect.

**SKILLS**
/doubt · /learn · /pain
