---
name: handoff
description: Trigger when the shell is about to close or compact mid-work.
---

# /handoff

**Do**
Write status, what is done, what is next, and any open questions — complete enough that a
fresh shell can run boot and continue without asking you anything.

**Writes**
(not owner) `record_status(status=handed_off, note=…)` on the ticket thread.
