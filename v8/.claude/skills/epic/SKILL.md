---
name: epic
description: Trigger when you walk an epic through its lifecycle (architect), or need to know what an epic's next move is and who makes it.
---

# /epic — the epic walk (Standard workflow)

**Trigger**
You own an epic's design (architect), or you need to know why an epic is not moving. This is the
**Standard** workflow, the board's built-in one. Every epic is pinned to one workflow version (the
`ticket.workflow` field of `ticket_read`). For the lifecycle your epic actually runs, rendered from its pinned
version, call `ticket_read(ticket_id=<epic>, include='lifecycle')`: its table replaces the one below
whenever the pin is not `standard@1`, and the Design tab (`/ui/design`) draws the same one.

**Rule**
Each step names the state the epic must be in, the tool that moves it, and who calls it. The board carries
the rows marked *board*. Never call `ticket_update` to do a move the board makes. When a row will not move,
the board's refusal names the missing piece. Fix that piece. Do not force the status.

| # | Step | Needs | Tool (who) | Leaves it |
|---|---|---|---|---|
| 1 | Words recorded | — | `ticket_create(kind=epic, words=…)` (owner only) | `drafted` |
| 2 | Design + acceptance criteria | `drafted` | `doc_create(design)`, `ticket_update(design_ref=…)`, `criterion_create` on the epic (architect only). *Board:* once the epic has both a design_ref and at least one criterion, it goes to `designed`, whichever lands last. | `designed` |
| 3 | Sign-off asked | `designed` | `gate_open(design_signoff)` on the epic (architect only). The board refuses it while the design_ref or the criteria are missing, and names what is missing. | `designed` |
| 4 | Sign-off answered | `designed` | The owner approves on the board: Needs you, the SPA reader, or the VS Code reader. Request changes is a steer, so fold it into the design and re-open. *Board:* the approval carries the epic forward. | `signed_off` |
| 5 | Stories released | `signed_off` | *Board:* unblocked `signed_off` stories go `ready`. Then `spawn(role=engineer, ticket_id=<story>)` (architect only). | `signed_off` |
| 6 | Build starts | `signed_off` | A story goes `in_progress` (engineer). *Board:* the epic follows. | `in_progress` |
| 7 | Every story handed off | `in_progress` | Each story goes `in_review` (engineers). *Board:* when every story is released, the epic follows. | `in_review` |
| 8 | Acceptance | `in_review` | ONE qa for the epic, spawned when every story is in_review. Its verdicts close stories and the epic. Where the board could not close it, `ticket_update(status=done\|partial)` (architect). | `done` |
| 9 | Accepted with gaps | `in_review` | A named gap stays open: `ticket_update(status=partial)` (architect, per qa's report). | `partial` |

**Before step 3 (the architect's design duties, all on the board)**
- Stories (architect only): `ticket_create(kind=story, parent_id=<epic>)`, each with its `design_ref`, its criteria, and a
  `blocks` link for every prerequisite. The adversarial review story comes last.
- Knowledge: up to two knowledge tickets (hl-craft, ll-craft), linked with `uses_strategy`/`uses_domain`.
- Stories go `drafted` → `designed` → `signed_off` by `ticket_update` (architect). The owner's gate answer
  releases them.
- Audit with /ocak before you open the gate.

**Why it sticks, and what to check**
- The epic sits in `drafted` with a design → it has no criterion yet. Write the acceptance criteria.
- `gate_open` is refused (architect only) → read the message: a missing design_ref or criteria, a `blocks` cycle, an
  owner-checked story criterion, or a story blocked by the review story.
- The owner's Approve does nothing → the board refused the answer, and the refusal is shown. Fix the named
  piece. A gate the owner cannot answer is never listed in Needs you.

**Writes**
The design doc, the tickets, the criteria and the links above. Each move is posted on the epic thread.
