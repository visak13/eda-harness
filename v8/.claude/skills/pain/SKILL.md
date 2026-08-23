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
Append one single-line JSON record (create the file if missing; never rewrite existing
lines): `{"ts","role","handle","severity":"high|medium|low","area":"prompts|tools|gates|
board|memory|wake|spawn|broker|other","symptom","expected","evidence","workaround","cost"}`.
Say one line (`pain point filed: <area> — <symptom>`) and continue the task where you left
off. If it also blocks you, escalate the blocker separately via /doubt — this record is
telemetry, not a request for help.

**Writes**
One line appended to `v8/.pain/pain-points.jsonl`.
