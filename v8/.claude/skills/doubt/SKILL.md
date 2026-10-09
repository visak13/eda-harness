---
name: doubt
description: Trigger when you would otherwise assume, override, or widen scope on a decision you do not own.
---

# /doubt

**Do**
Before you proceed on a guess: name the owner of the decision. Ask one question, stating the options you see. End your
turn — do not keep working past the point the decision is needed.

**Writes**
`message_send(kind=question, to=<owner|architect|sme>)` on the ticket thread.
