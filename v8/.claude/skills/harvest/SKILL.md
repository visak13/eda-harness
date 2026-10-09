---
name: harvest
description: Trigger as qa's last step on an epic, after the verdicts and the report, before CLOSE.
---
<!-- roles: qa -->

# /harvest

**Trigger**
Your verdicts and qa report exist: the one seat that reads the epic cold for self-improvement, once.

**Read**
Your qa report; `message_query(ticket_id=<epic>)` (deviations, rulings, findings, rework); `context(ticket_id=<epic>)` lists the linked strategy docs; `doc_read` each you will judge (its head carries the `## Rules`; read the sections a finding touches). Re-verify nothing; do not spawn a checker.

**Do**
1. **Lessons.** For each fact true beyond this epic (a pitfall, host limit, tool trap, better approach) that cost rework or a fail verdict: list the candidates, then ONE `lookup(scope=<epic>, question=<candidates, one line each>)` (one call, not one per candidate); skip any a decision or lesson already states. Else `record_lesson(domain, topic, text, evidence=[<message/criterion/report ids>])`, text one sentence. At most 5; none is a valid answer.
2. **Proposed versions.** For each linked strategy doc with a bar MISSING (a failure it would have prevented) or WRONG (followed and caused the failure, or the owner overruled): write the whole next version and file it — `doc_create(doc_type=<its doc_type>, title=<its title>, body_md=<full new body>, scope=<its scope>, status="proposed", proposes=<its id>, ticket_id=<epic>)`. Change only the bars the evidence touches; each lands in its `## Rules` (/doc-write). One proposal per doc at most; an uncontradicted doc gets none.
3. **Report.** Add `## Harvest` to your qa report (`doc_edit`): one row per record (id, kind lesson | proposed version of <doc id>, one line of why, evidence ids); "no lessons" / "no proposals" when that is the finding.
4. **Cost.** `harvest_cost(participant_id=<your id>)` (`since=` when the trigger is not in the log); totals under Harvest.

**Writes**
Lessons and proposals, addressed to nobody; the owner approves each in the Library, and an approval is the doc's next version in every linked epic's brief.
