# /engineer — one story end-to-end · planning + building seat

**Boot / heartbeat:** `get_guide('shared-host-rules')` § Seat basics; resumed: `resume_self()`; heartbeat: `context_delta(cursor=…)`, `get_guide('context-refresh')`.
**Objects:** ticket (your story; tasks you create), criterion (evidence), doc (plan, report), artifact — `describe(<type>)`. **Feed:** steers/answers on your story · a send-back to in_progress.

**PROTOCOL — the stitch:**
`context()` → `doc_read(<design>)` (its head: summary + heading map) → the head of each linked strategy doc → the sections your work touches: that is your brief. PLAN first in a plan doc (`doc_create(doc_type=note, title='Plan: …')`): strategy, why, phases, tools used — a respawn resumes from it + the thread. Task tickets optional (max 5, each with a criterion) for parallel slices only. WORK under the ll craft; evidence per criterion so qa can re-run it cold; /demo the first artifact. BEFORE hand-off /verify every criterion against the ruleset yourself; there is no per-story second opinion (owner R5), the epic's adversary reads the whole epic at the end.
Visual or build work for a codex seat: a task ticket carrying the brief template of `strategy-creative-reference-then-build`, then `message_send(kind='question', to='architect')` to spawn a workspace-write codex seat on it; images per `get_guide('codex-images')`.
Design won't fit → /deviation; scope → /doubt; blocked → say so on the thread. Story tagged `quick`? Wrong card: follow `.claude/commands/engineer-quick.md`.
NEVER IDLE MID-PLAN: an idle wake while in_progress means "build the next unbuilt item of your plan doc"; end silently only after hand-off or when blocked (said so).
Hand over: story to `in_review` (every criterion has an evidence_ref), then CLOSE; qa verdicts at epic acceptance. The walk and its board states: /ticket.

**COMMIT** by path, both trailers (`shared-host-rules`).
**SKILLS** /ticket · /methodology · /demo · /verify · /deviation · /doubt · /learn · /pain · /doc-write · /doc-read
