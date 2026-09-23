---
name: harvest
description: Trigger as qa's last step on an epic, after the verdicts and the report, before CLOSE.
---
<!-- roles: qa -->

# /harvest

**Trigger**
Your epic's verdicts are in and your qa report exists. You are the one seat that read the whole
epic cold, so you are the one seat that spends tokens on self-improvement — once per epic, here.
Nobody else harvests; the board records the rest without a model call.

**Read (what you already have, plus three reads)**
- your qa report and the verdict notes you wrote;
- `message_query(ticket_id=<epic>)` — the thread: deviations, owner rulings, findings, rework;
- `assemble_ruleset(ticket_id=<epic>)` — its `index` lists every strategy doc linked to the epic;
  `doc_read(<id>)` each one you will judge.
Do not re-verify anything and do not consult: harvest is one pass over what the epic already proved.

**Do**
1. **Lessons.** For each fact true beyond this epic (a pitfall, a host limit, a tool trap, a better
   approach) that cost rework or a fail verdict here, list the candidates first, then ONE
   `lookup(scope=<epic>, question=<the candidates, one line each>)` (a lookup returns up to 16 KB;
   one per candidate multiplies the harvest's cost) — a candidate a decision or lesson already
   states is skipped. Else `record_lesson(domain, topic, text, evidence=[<message/criterion/report ids>])`,
   text one sentence. At most 5; none is a valid answer.
2. **Proposed versions.** For each linked strategy doc where this epic showed a bar MISSING (a failure
   the doc would have prevented) or WRONG (a bar that was followed and caused the failure, or that
   the owner overruled): write the whole next version of that doc and file it —
   `doc_create(doc_type=<its doc_type>, title=<its title>, body_md=<full new body>, scope=<its scope>,
   status="proposed", proposes=<its id>, ticket_id=<epic>)`. Change only the bars the evidence
   touches; keep its `## Enforced` section. The board records the source (you + the epic) and
   the Library shows the owner the diff against the active version. One proposal per doc at most;
   a doc the epic did not contradict gets none.
3. **Report.** Add a `## Harvest` section to your qa report (`doc_edit`): one row per record —
   id, kind (lesson | proposed version of <doc id>), one line of why, the evidence ids. Say
   "no lessons" / "no proposals" explicitly when that is the finding.
4. **Cost.** `.venv/Scripts/python.exe scripts/harvest_cost.py --participant <your id>` — the tokens this
   harvest spent (from your own session log) and every lesson/proposal written in its window, by author;
   put its output lines under the Harvest section.

**Writes**
Lessons (`record_lesson`) and proposed doc versions (`doc_create status=proposed`), addressed to
nobody: the owner approves or rejects each proposal in the Library, and an approval becomes the
doc's next version in every linked epic's next brief.
