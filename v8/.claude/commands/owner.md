# /owner — project manager (human shell)

**Boot:** `whoami()` → `subscribe()`; run the returned feed monitor once.

**IS-A**
participant(type=human, role=owner)

**HAS-A**
feed (questions, gates, demos, findings addressed to you); the board view (`board(epic)`)

**USES-A**
messages (answer, steer, tag @teammate); docs (read designs/reports)

**PRODUCES-A**
answers, steers, sign-offs — each written on the ticket that asked

**PROTOCOL**
Answer in this shell; the asker wakes on it. Sign gates here. Tag a teammate to hand them a
ticket or a question. You never relay; the board moves itself.

**SKILLS**
none
