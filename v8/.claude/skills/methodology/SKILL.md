---
name: methodology
description: Trigger when starting a story, before writing any code.
---

# /methodology

**Trigger**
You are starting a story and have not yet chosen how to approach it.

**Do**
Read the strategy_hl docs linked for the story's work_type (poc-then-iterate,
diagnose-with-logs-and-traces, research-then-build, walking-skeleton, refactor-in-steps,
creative-reference-then-build, …). Choose one. Record the choice and why before starting
work — do not silently default.

**Writes**
`doc_create(doc_type=note or plan section: strategy, why)` linked to the story.
