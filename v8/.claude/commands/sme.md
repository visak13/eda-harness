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

**SKILLS**
/doubt · /learn · /pain
