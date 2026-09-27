---
name: pain
description: Trigger when a tool or guide is wrong versus reality, mid-work, any role.
---

# /pain

**Trigger**
A tool refused you against your card/guide, named a phantom verb, silently dropped a
kwarg, failed to wake you when it should have, the record contradicted reality, you had to
improvise around the framework, or two authoritative texts disagreed and you picked one.
Not for your own mistakes or task-domain problems.

**Scope — what a pain record addresses:** the EDP framework only — the board and its MCP tools,
role cards, skills and guides (`v8/`), and the pool and seat launchers (`edp-pool/`, codex/pi
seats). A bug in the project repo your ticket builds (a game, an asset pipeline, any other repo) is NOT pain: report it on your ticket thread (`message_send`) or fix it in the story.

**Do**
1. `pain(action='query', q='<symptom words>')` (open records, newest first; `area=` narrows) — an open record
   with the same symptom already exists? File nothing new; file yours with `dup_of='<id>'` (step 2) so the count grows.
2. `pain(action='file', severity='high|medium|low', area='prompts|tools|gates|board|memory|wake|spawn|broker|other',
   symptom=..., expected=..., evidence=..., workaround=...)` — plus `supersedes='<id>'` when correcting an earlier
   record of yours. The board stamps your role, handle, time and id; say the returned id and continue where you left off.
   A missing required field is named in the error.
If it also blocks you, escalate via /doubt — this record is telemetry, not a request for help.
`pain(action='read', id=...)` shows one record with its resolution and duplicates. Never read
`.pain/pain-points.jsonl` directly. Resolving (`action='resolve'`, status fixed|invalid|superseded) is the
owner's and the doctor's; the fix names the commit.

**Writes**
One line appended to the pain log (`<home>/.pain/pain-points.jsonl`) by the board.
