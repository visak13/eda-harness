---
name: ticket
description: Trigger when you work a single ticket through its lifecycle, either a story inside an epic or a standalone quick ticket with no epic, or need to know its next move.
---

# /ticket — one ticket's walk (Standard workflow)

**Trigger**
You are the doer or the checker of one ticket, or you need to know why it is not moving. A ticket is one
of two things:
- a **story inside an epic**: it has a `parent_id`, the architect designs it, and qa checks it;
- a **standalone quick ticket**: the owner creates it with no epic and the tag `quick`. It has no architect.
  The engineer's design note is the owner's sign-off point, and the owner checks it.

This is the **Standard** workflow. The lifecycle your ticket actually runs, rendered from its epic's
pinned workflow version, is `ticket_read(ticket_id=<ticket>, include='lifecycle')`; when the `ticket.workflow`
field is not `standard@1`, follow that table instead of the one below (the Design tab `/ui/design` draws
the same one). For the epic around a story, see /epic.

**Rule**
Each step names the state the ticket must be in, the tool that moves it, and who calls it. The board
refuses a move whose precondition is missing, and its message names the missing piece. Fix that piece. Do
not force the status. The checker is the one the board derives (`checker_for`): qa on a story, the owner on
a quick ticket. Never the assignee.

## A · Story inside an epic

| # | Step | Needs | Tool (who) | Leaves it |
|---|---|---|---|---|
| 1 | Story written | — | `ticket_create(kind=story, parent_id=<epic>)` (architect only) | `drafted` |
| 2 | Designed | `drafted` | `ticket_update(design_ref=…)`, `criterion_create`, then `ticket_update(status=designed)` (architect only) | `designed` |
| 3 | Signed off | `designed` | `ticket_update(status=signed_off)` (architect, quoting the owner's design_signoff on the epic) | `signed_off` |
| 4 | Released | `signed_off` | *Board:* goes ready once the epic's sign-off is answered and every `blocks` prerequisite is released. Then `spawn(role=engineer, ticket_id=…)` (architect only). | `ready` |
| 5 | Build | `ready` | `ticket_update(status=in_progress)` (engineer), then a plan doc and the work, committed by path | `in_progress` |
| 6 | Hand-off | `in_progress` | `criterion_update(evidence_ref=…)` on every criterion, then `ticket_update(status=in_review)`, then CLOSE (engineer) | `in_review` |
| 7 | Checked | `in_review` | qa's passing verdicts at epic acceptance, from the evidence. *Board:* the last pass closes it. | `done` |
| 8 | Sent back | `in_review` | A fail verdict with a note. Fix, re-evidence, hand off again (engineer). | `in_progress` |
| 9 | Blocked | `in_progress` | `ticket_update(status=blocked)` and say why on the thread (engineer). Resume with `ticket_update(status=in_progress)`. | `blocked` |

## B · Standalone quick ticket (no epic)

| # | Step | Needs | Tool (who) | Leaves it |
|---|---|---|---|---|
| 1 | Asked | — | `ticket_create(kind=story, tags=[quick], words=…)` with no parent (owner only), or the one-step quick-task endpoint | `ready` |
| 2 | Design note | `ready` | `doc_create(doc_type=note, title='Design: …')`, `ticket_update(design_ref=<note>)`, `criterion_create` (engineer only), read-only until signed | `ready` |
| 3 | Sign-off asked | `ready` | `gate_open(design_signoff, note='<what to review, in plain words>')` on the ticket (engineer only; a blank note is refused). The board refuses it while no design note is set. | `ready` |
| 4 | Sign-off answered | `ready` | The owner approves on the board, or sends quoted comments: fold them into the note with `doc_edit` and re-open the gate (engineer only). | `ready` |
| 5 | Build | `ready` | `ticket_update(status=in_progress)` (engineer). The board refuses it until the owner has answered the sign-off. | `in_progress` |
| 6 | Hand-off | `in_progress` | a report doc, `evidence_ref` on every criterion, then `ticket_update(status=in_review)`, then CLOSE (engineer) | `in_review` |
| 7 | Checked | `in_review` | The owner verdicts each criterion from Needs you, as the derived checker. *Board:* the last pass closes it. | `done` |
| 8 | Sent back | `in_review` | A fail verdict with a note. Fix, re-evidence, hand off again (engineer). | `in_progress` |

## Last step · hand the owner a link (knowledge and quick tickets)

When the owner is the checker (a knowledge ticket's `checked_by: owner` criterion, or a quick ticket), the
hand-off message is the last step, and it must let the owner act in one click. Never send "see Needs you".
- Take the link base from `whoami()` → `ui_url` (the board's EDP8_PUBLIC_URL, else the address you reach it
  on). Never type a host or port by hand.
- Link the ticket with its Work view open, where the criterion cards are: `<ui_url>/ticket/<ticket-id>?view=work`.
  Link each evidence doc: `<ui_url>/doc/<doc-id>`.
- Name the button to press on the criterion card: **Approve criterion** (Pass) or **Needs work** (Fail, with a note).
- Put each link on its own line or follow it with a space. Do not end the sentence right after it.

Template (`message_send(to=owner, kind=status)`):

```
Ready for your verdict: <one line on what it is>.
Open <ui_url>/ticket/<ticket-id>?view=work and press Approve criterion (Pass) or Needs work (Fail) on the criterion card.
Evidence: <ui_url>/doc/<doc-id> (one line each)
```

**Why it sticks, and what to check**
- `in_progress` is refused on a quick ticket → the owner has not answered its design_signoff yet.
- `gate_open(design_signoff)` is refused (architect/engineer only) → a quick ticket has no design note. On a story, the gate belongs
  on the epic.
- `in_review` is refused → a criterion has no evidence_ref.
- The owner's Approve does nothing → read the refusal the reader shows. A gate the owner cannot answer is
  never listed in Needs you.

**Writes**
The plan or design note, the evidence, and the status moves above, each posted on the ticket's thread.
