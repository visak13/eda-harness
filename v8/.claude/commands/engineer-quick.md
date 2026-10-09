# /engineer-quick — the owner's single task · plan, then build

The QUICK flow: no epic, no architect, no second opinion, no design sign-off. The owner's `words` are the brief and start the work.

**Boot / heartbeat:** `get_guide('shared-host-rules')` § Seat basics; resumed: `resume_self()`; heartbeat: `context_delta(cursor=…)`, `get_guide('context-refresh')`.

**1 · PLAN.** Read the code. `doc_create(doc_type=note, title='Plan: …')`: what you will change and why, how (files, approach), what you will NOT do, open questions. `criterion_create` ONE or TWO criteria — facts a checker can confirm by looking or by running one command.
**2 · BUILD.** `ticket_update(status=in_progress)` → work → commit by path → report doc (`doc_create(doc_type=report)`) + `evidence_ref` on every criterion → `ticket_update(status=in_review)` → CLOSE. Scope grows? Update the plan note and tell the owner.
Questions: `message_send(kind=question, to=owner)`. A fail verdict sends it back to in_progress: fix, re-evidence, hand off again.
NEVER IDLE MID-PLAN: an idle wake while in_progress = build the next unbuilt item of the plan note.

**COMMIT** by path, both trailers (`shared-host-rules`).
**SKILLS** /ticket · /verify · /demo · /doubt · /learn · /pain · /doc-write · /doc-read
