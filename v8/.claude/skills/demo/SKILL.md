---
name: demo
description: Trigger as soon as an artifact exists that the owner should see.
---

# /demo

**Do**
As soon as it exists, not at story end: show it in this shell (link or file). Ask the owner for a reaction. Record what they say.

**Writes**
`artifact_create(...)` (architect/engineer/adversary only) + `message_send(kind=status, to=owner)` on the ticket thread.
