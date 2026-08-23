---
name: handoff
description: Trigger when the shell is about to close or compact mid-work.
---

# /handoff

**Trigger**
Your shell is about to close or compact while work is unfinished — the next shell (or your
resumed self) has no memory beyond what is written down.

**Do**
Write status, what is done, what is next, and any open questions — complete enough that a
fresh shell can run boot and continue without asking you anything.

**Writes**
`message_send(kind=status)` on the ticket thread.
