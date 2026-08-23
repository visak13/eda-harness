---
name: verify
description: Trigger before handing a ticket over, or whenever checking a criterion.
---

# /verify

**Trigger**
Before handing a ticket to in_review/done, or whenever you need to check a criterion's
current status — the report is a claim until it has been re-run.

**Do**
For each criterion on the ticket: run its check (command | path | look | verdict) yourself,
record the actual result, do not trust a prior claim without re-running it.

**Writes**
`doc_update` (report section) + `criterion_update(evidence_ref, verdict)` per criterion.
