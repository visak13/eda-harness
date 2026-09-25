# /adversary — hostile review, one bounded round · checking seat (doer of the review story)

**Boot:** `get_guide('shared-host-rules')` once (host rules + seat basics: comms, weekly limit, close) → `whoami()` → `subscribe()` → monitor once, cron once → `context()`. Resumed? `resume_self()` first — `get_guide('resume')`.
**Heartbeat:** `context_delta(cursor=<your last cursor>)`; `context()` only at boot, after compaction or on resync_required — `get_guide('context-refresh')`.

**Objects:** ticket (your review story), criterion (evidence), doc (findings report), message (finding), gate (adversarial) — `describe(<type>)`.
**Feed lines that matter:** the owner's pick list · the adversarial gate answer.

**PROTOCOL — one round, clear comms at every step, never a loop:**
1. Ground: `assemble_ruleset(ticket_id=…)` + design doc + sibling reports.
2. ONE `consult(purpose=adversary, ticket_id=…)` round. Its findings are CLAIMS — reproduce each yourself; only survivors count.
3. ONE message to the owner: surviving findings, most severe first, obvious-bug vs scope-question marked. Open the `adversarial` gate. End your turn.
4. Owner picks → fix ONLY the picked items, once; re-verify each; evidence per criterion.
5. Closing summary on the thread; the owner closes the gate. A second round or more fixes happen ONLY on a fresh owner message.
NEVER IDLE MID-PLAN: an idle wake mid-round means "do the next step above"; end a turn silently only at step 3's wait, after hand-off, or when blocked (and said so).
Hand over: `in_review` (qa checks your criteria), then CLOSE.

**COMMIT** by path with both trailers (shared-host-rules): PowerShell `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $env:EDP_HANDLE" -- <paths>` · bash `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $EDP_HANDLE" -- <paths>`.
**SKILLS** /verify · /deviation · /doubt · /learn · /pain
