---
name: doubt
description: Trigger when you would otherwise assume, override, or widen scope on a decision you do not own.
---

# /doubt

**Trigger**
You are about to assume, override, or widen scope on a decision that belongs to someone
else (owner, architect, or sme) rather than proceed on a guess.

**Do**
Name the owner of the decision. Ask one question, stating the options you see. End your
turn — do not keep working past the point the decision is needed.

**Writes**
`message_send(kind=question, to=<owner|architect|sme>)` on the ticket thread.
