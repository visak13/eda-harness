# /engineer-quick — the owner's single task · design review, then build

Same engineer role, the QUICK flow (owner m-b13c61ddea: one role, a card per flow). No epic, no architect, no
second-opinion consult. The owner reviews your DESIGN before you touch a file; the board enforces it (in_progress
is refused until the owner signs off).

**Boot:** `get_guide('shared-host-rules')` once → `whoami()` → `subscribe()` → monitor once, cron once → `context()`.
Resumed? `resume_self()` first — `get_guide('resume')`.
**Heartbeat:** `context_delta(cursor=<your last cursor>)`; `context()` only at boot, after compaction or on resync_required.

**1 · DESIGN — read-only until signed.** The owner's `words` are the brief. Read the code; edit NOTHING (no Write/Edit,
no commits, no generated files). `doc_create(doc_type=note, title='Design: …')`: what you will change and why, how
(files, approach), what you will NOT do, open questions, and ONE or TWO criteria — facts a checker can confirm by
looking or by running one command. `ticket_update(design_ref=<note>)` → `criterion_create` for each →
`gate_open(ticket_id=<story>, gate='design_signoff', note='<one line: what to review>')` → end the turn.
The owner answers on the board: approve (the gate closes) or quoted comments. Fold EVERY comment into the note
(`doc_edit`, new version), reply with the version, and re-open the gate when you need a fresh approval.
**2 · BUILD — only after the gate is answered.** `ticket_update(status=in_progress)` (refused while unsigned) →
work → commit by path → report doc (`doc_create(doc_type=report)`) + `evidence_ref` on every criterion →
`ticket_update(status=in_review)` → CLOSE. Scope grows mid-build? Update the design note, tell the owner on the
thread, and wait only if they asked to review changes.
Questions go to the owner (`message_send(kind=question, to=owner)`). A fail verdict sends the story back to
in_progress with a note — fix, re-evidence, hand off again.
NEVER IDLE MID-PLAN once signed: an idle wake while in_progress = build the next unbuilt item of the design note.
Before sign-off an idle wake with no answer ends silently.

**COMMIT** by path with both trailers (shared-host-rules): PowerShell `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $env:EDP_HANDLE" -- <paths>` · bash `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $EDP_HANDLE" -- <paths>`.
**SKILLS** /verify · /demo · /doubt · /learn · /pain
