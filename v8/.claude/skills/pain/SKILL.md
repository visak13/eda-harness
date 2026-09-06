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

**Do**
1. `python scripts/pain.py list --open --area <area>` — an open record with the same symptom
   already exists? File nothing new; add yours as `"dup_of": "<id>"` (step 2) so the count grows.
2. `python scripts/pain.py file '<one JSON object>'` with `{"role","handle","severity":"high|medium|low",
   "area":"prompts|tools|gates|board|memory|wake|spawn|broker|other","symptom","expected","evidence",
   "workaround","cost"}` — plus `"supersedes":"<id>"` when correcting an earlier record of yours.
   The script assigns the id and prints one line; say that line and continue where you left off.
If it also blocks you, escalate via /doubt — this record is telemetry, not a request for help.
Resolved records are invisible to you unless you ask (`list --all`): they are fixed from outside
the framework, and the fix names the commit.

**Writes**
One line appended to `v8/.pain/pain-points.jsonl` by `scripts/pain.py`.
