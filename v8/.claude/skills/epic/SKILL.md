---
name: epic
description: Trigger when you walk an epic through its lifecycle (architect), or need to know what an epic's next move is and who makes it.
---

# /epic — the epic walk (Standard workflow)

**Trigger**
You own an epic's design (architect), or need to know why it is stuck. The table is `standard@1`; for another pin follow `ticket_read(ticket_id=<epic>, include='lifecycle')` (Design tab: `/ui/design`).

**Rule**
The board carries the moves marked *board*: never `ticket_update` one. A refused move names what is missing: fix it, never force.

| # | Step | Needs | Tool (who) | Leaves it |
|---|---|---|---|---|
| 1 | Words | — | `ticket_create(kind=epic, words=…)` (owner only) | `drafted` |
| 2 | Design + criteria | `drafted` | `doc_create(design)`, `ticket_update(design_ref=…)`, `criterion_create` on the epic (architect only); *board:* `designed` once both exist | `designed` |
| 3 | Sign-off asked | `designed` | `gate_open(design_signoff, note=…)` on the epic (architect only), note = what to review, plainly | `designed` |
| 4 | Sign-off answered | `designed` | Owner approves; "request changes" is a steer: fold it in, re-open. *Board:* carries the epic on | `signed_off` |
| 5 | Stories released | `signed_off` | *Board:* unblocked stories go `ready`; then `spawn(role=engineer, ticket_id=<story>)` (architect only) | `signed_off` |
| 6 | Build starts | `signed_off` | A story goes `in_progress` (engineer); *board:* the epic follows | `in_progress` |
| 7 | All handed off | `in_progress` | Each story `in_review` (engineers); *board:* the epic follows | `in_review` |
| 8 | Acceptance | `in_review` | ONE qa once every story is in_review: the installed-build UI walk (/verify), then its verdicts close stories and the epic; else `ticket_update(status=done|partial)` (architect) | `done` |
| 9 | Gaps accepted | `in_review` | A named gap stays open: `status=partial` (architect, per qa's report) | `partial` |

**Before step 3 (architect's design duties)**
- Stories (architect only): `ticket_create(kind=story, parent_id=<epic>)`, each with `design_ref`, criteria and a `blocks` link per prerequisite; a UI story also a qa `look` criterion naming its screens. They go `drafted` → `designed` → `signed_off` by `ticket_update` (architect); `signed_off` moves a story to `ready`.
- Knowledge tickets and the /ocak audit: the architect card.

**Writes**
All of the above; each move on the epic thread.
