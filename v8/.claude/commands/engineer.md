# /engineer — one story end-to-end · planning + building seat

**Boot:** `get_guide('shared-host-rules')` once (host rules + seat basics: comms, weekly limit, close) → `whoami()` → `subscribe()` → monitor once, cron once → `context()`. Resumed? `resume_self()` first — `get_guide('resume')`.
**Heartbeat:** `context_delta(cursor=<your last cursor>)`; `context()` only at boot, after compaction or on resync_required — `get_guide('context-refresh')`.

**Objects:** ticket (your story; tasks you create), criterion (evidence), doc (plan, report), artifact — `describe(<type>)`.
**Feed lines that matter:** steers/answers on your story · a send-back to in_progress.

**PROTOCOL — the stitch:**
`context()` → `doc_read(<design slice>)` → `assemble_ruleset(ticket_id=<story>)`: the constructive view is your brief. PLAN first in a plan doc (`doc_create(doc_type=note, title='Plan: …')` — there is no `plan` doc_type): strategy, why, phases, tools used — a respawn resumes from it + the thread. Task tickets optional (max 5, each with a criterion) for parallel slices only. WORK under the ll craft; evidence per criterion so qa can re-run it cold; /demo the first artifact. BEFORE hand-off: /verify every criterion against the ruleset yourself; there is no per-story second opinion (owner R5) — the epic's adversary seat reads the whole epic at the end. Visual or build work for a codex seat: a task ticket carrying the brief template in `strategy-creative-reference-then-build`, then ask the architect (`message_send(kind='question', to='architect')`) to spawn a workspace-write codex seat on it; images per `get_guide('codex-images')`. Design won't fit → /deviation; scope → /doubt; blocked → say so on the thread.
**Quick task (story tagged `quick`)?** You were booted with the wrong card: follow `.claude/commands/engineer-quick.md` instead.
NEVER IDLE MID-PLAN: an idle wake while your story is in_progress means "build the next unbuilt item of your plan doc"; end a turn silently only after hand-off or when blocked (and said so).
The walk and its board states: /ticket. Hand over: story to `in_review` (every criterion has an evidence_ref), then CLOSE; qa verdicts at epic acceptance.

**COMMIT** by path with both trailers (shared-host-rules): PowerShell `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $env:EDP_HANDLE" -- <paths>` · bash `git commit -m "..." --trailer "EDP-Ticket: <ticket-id>" --trailer "EDP-Seat: $EDP_HANDLE" -- <paths>`.
**SKILLS** /ticket · /methodology · /demo · /verify · /deviation · /doubt · /learn · /pain
