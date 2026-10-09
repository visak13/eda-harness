---
name: pain
description: Trigger when a tool or guide is wrong versus reality, mid-work, any role.
---

# /pain

**Trigger**
A tool refused you against your card/guide, named a phantom verb, silently dropped a kwarg, failed to wake you, the record contradicted reality, you improvised around the framework, or two authoritative texts disagreed. Not your own mistakes or task-domain problems.

**Scope:** the EDP framework only — the board and its MCP tools, role cards, skills and guides (`v8/`), the pool and seat launchers (`edp-pool/`, codex/pi seats). A bug in the repo your ticket builds is NOT pain: say so on the thread or fix it in the story.

**Do**
1. `pain(action='query', q='<symptom words>')` (open records; `area=` narrows): the same symptom already open? File yours with `dup_of='<id>'` so the count grows.
2. `pain(action='file', severity, area (prompts|tools|gates|board|memory|wake|spawn|broker|other), symptom=..., expected=..., evidence=..., workaround=...)`, plus `supersedes='<id>'` to correct your earlier record. The board stamps who, when and id, and names a missing field; say the id and continue. It blocks you too? /doubt.
`pain(action='read', id=...)` shows one record with resolution and duplicates; never read the pain files. `action='resolve'` (status fixed|ticket|duplicate|invalid; the fix names `commit`, `ticket_id` or `dup_of`) is for the owner and the doctor; an epic's architect may close `fixed` once the commit is on main.

**Writes**
One pain record on the board (Library > Pains lists it).
