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
role cards, skills and guides (`v8/`), the pool and seat launchers (`edp-pool/`, codex/pi seats) and
the consult bridge. A bug in the project repo your ticket builds (a game, an asset pipeline, any
other repo) is NOT pain: report it on your ticket thread (`message_send`) or fix it in the story.

**Do**
1. `python scripts/pain.py list --area <area>` (open records only, one line each) — an open record with the same symptom
   already exists? File nothing new; add yours as `"dup_of": "<id>"` (step 2) so the count grows.
2. `python scripts/pain.py file '<one JSON object>'` with `{"role","handle","severity":"high|medium|low",
   "area":"prompts|tools|gates|board|memory|wake|spawn|broker|other","symptom","expected","evidence",
   "workaround","cost"}` — plus `"supersedes":"<id>"` when correcting an earlier record of yours.
   The script assigns the id and prints one line; say that line and continue where you left off.
If it also blocks you, escalate via /doubt — this record is telemetry, not a request for help.
Never read `.pain/pain-points.jsonl` directly: it is append-only and holds every resolved record.
`list` hides resolved records and the duplicates of resolved records; they are fixed from outside
the framework, and the fix names the commit.

**Writes**
One line appended to `v8/.pain/pain-points.jsonl` by `scripts/pain.py`.
