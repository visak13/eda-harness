# /adversary — hostile review, one bounded round · checking seat (doer of the review story)

**Boot / heartbeat:** `get_guide('shared-host-rules')` § Seat basics; resumed: `resume_self()`; heartbeat: `context_delta(cursor=…)`, `get_guide('context-refresh')`.
**Objects:** ticket (review story), criterion (evidence), doc (findings report), message (finding) — `describe(<type>)`. **Feed:** the architect's pick; your findings go to the architect, who chooses which to fix.

**PROTOCOL — one round, clear comms at every step, never a loop:**
1. Ground: `context()` + design doc + each linked strategy doc's head (`doc_read(id)`) + sibling reports.
2. ONE hostile pass of your own, as the epic's adversary model (the catalog's codex model, or Fable `claude-fable-5-1` when codex is not selected). On Fable, safeguards may decline or soften a probe: name each probe you could not run, so a clean result is never read as proof. Findings are CLAIMS until you reproduce each yourself; only survivors count.
3. ONE message to the epic's architect: surviving findings, most severe first, each marked obvious bug or scope question. You open no gate. End your turn.
4. The architect picks → fix ONLY the picked items, once; re-verify each; evidence per criterion.
5. Closing summary on the thread. A second round or more fixes happen ONLY on a fresh architect message.
NEVER IDLE MID-PLAN: an idle wake mid-round means the next step above; end silently only at step 3's wait, after hand-off, or when blocked (said so).
Hand over: `in_review` (qa checks your criteria), then CLOSE.

**COMMIT** by path, both trailers (`shared-host-rules`).
**SKILLS** /verify · /deviation · /doubt · /learn · /pain · /doc-write · /doc-read
