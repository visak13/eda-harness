---
name: learn
description: Trigger when you find something reusable beyond the current ticket.
---

# /learn

**Trigger**
You find a fact, pitfall, or better approach that is true beyond this one ticket — it
belongs in craft or domain knowledge, not just in this ticket's report.

**Do**
Write one note: what you found, where it applies, the evidence for it. Address it to the
domain's sme — a learning that changes a strategy becomes a new doc version, decided by the
sme, not by you.

**Writes**
`message_send(kind=note, to=sme)` on the ticket thread.
