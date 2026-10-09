---
name: ticket
description: Trigger when you work a single ticket through its lifecycle, either a story inside an epic or a standalone quick ticket with no epic, or need to know its next move.
---

# /ticket — one ticket's walk (Standard workflow)

**Trigger**
You do or check one ticket, or need its next move. A **story** has a `parent_id` (the architect designs it, qa checks it); a **quick ticket** has no epic (owner-created, tag `quick`; the engineer's design note is the owner's sign-off point, the owner checks it).
The tables are `standard@1`; for another `ticket.workflow` follow `ticket_read(ticket_id=<ticket>, include='lifecycle')` (Design tab: `/ui/design`). The epic around a story: /epic.

**Rule**
A refused move names the missing piece: fix it, never force the status. The checker is derived (`checker_for`): qa on a story, the owner on a quick ticket, never the assignee.

## A · Story inside an epic

| # | Step | Needs | Tool (who) | Leaves it |
|---|---|---|---|---|
| 1 | Written | — | `ticket_create(kind=story, parent_id=<epic>)` (architect only) | `drafted` |
| 2 | Designed | `drafted` | `ticket_update(design_ref=…)`, `criterion_create`, `status=designed` (architect only) | `designed` |
| 3 | Signed off | `designed` | `status=signed_off` (architect, quoting the owner's design_signoff on the epic) | `signed_off` |
| 4 | Released | `signed_off` | *Board:* `ready` once the epic's sign-off is answered and every `blocks` prerequisite is released; then `spawn(role=engineer, ticket_id=…)` (architect only) | `ready` |
| 5 | Build | `ready` | `status=in_progress`, a plan doc, work committed by path (engineer) | `in_progress` |
| 6 | Hand-off | `in_progress` | `criterion_update(evidence_ref=…)` on every criterion, `status=in_review`, CLOSE (engineer) | `in_review` |
| 7 | Checked | `in_review` | qa's passes at epic acceptance; *board:* the last pass closes it | `done` |
| 8 | Sent back | `in_review` | A fail verdict with a note: fix, re-evidence, hand off again (engineer) | `in_progress` |
| 9 | Blocked | `in_progress` | `status=blocked` and say why on the thread; resume with `status=in_progress` (engineer) | `blocked` |

## B · Standalone quick ticket (no epic)

Owner creates it (`ticket_create(kind=story, tags=[quick], words=…)`, no parent, or the quick-task endpoint) → `ready`. (engineer only) The engineer's walk is `engineer-quick.md`: plan note, build, report + `evidence_ref` on every criterion, `in_review`, CLOSE. The owner verdicts each criterion from the ticket page; the last pass closes it (`done`).

## Last step · hand the owner a link (knowledge and quick tickets)

When the owner is the checker (`checked_by: owner` knowledge criterion, or a quick ticket) the hand-off lets them act in one click; never "go find it".
- Base: `whoami()` → `ui_url`, never a typed host. Work view `<ui_url>/ticket/<ticket-id>?view=work`; each evidence doc `<ui_url>/doc/<doc-id>`; each link on its own line or followed by a space.
- Name the button: **Approve criterion** (Pass) or **Needs work** (Fail, with a note).

Template (`message_send(to=owner, kind=status)`):

```
Ready for your verdict: <one line on what it is>.
Open <ui_url>/ticket/<ticket-id>?view=work and press Approve criterion (Pass) or Needs work (Fail) on the criterion card.
Evidence: <ui_url>/doc/<doc-id> (one line each)
```

**Writes**
The plan or design note, evidence and the moves above, posted on the thread.
