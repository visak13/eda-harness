---
name: deviation
description: Trigger when the design or a strategy cannot be followed as written.
---

# /deviation

**Trigger**
The design doc or a strategy_hl/strategy_ll cannot be followed as written — a fact on the
ground contradicts it, or it does not fit the model you are running on.

**Do**
State what you cannot follow and why. Propose the alternative. Send it to the architect
(design deviations) or the sme (craft deviations). Proceed only if the deviation is
reversible, and note that you proceeded.

**Writes**
`message_send(kind=deviation, to=<architect|sme>)` on the ticket thread.
