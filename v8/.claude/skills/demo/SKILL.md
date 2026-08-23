---
name: demo
description: Trigger as soon as an artifact exists that the owner should see.
---

# /demo

**Trigger**
An artifact (image, file, url, app, repo_ref) exists that the owner should look at before
you go further — do not wait for the story to finish.

**Do**
Show it in this shell (link or file). Ask the owner for a reaction. Record what they say.

**Writes**
`artifact_create(...)` + `message_send(kind=status, to=owner)` on the ticket thread.
