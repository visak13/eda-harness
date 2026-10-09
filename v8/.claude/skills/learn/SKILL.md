---
name: learn
description: Trigger when you find something reusable beyond the current ticket.
---
<!-- roles: architect, engineer, qa, sme, adversary -->

# /learn

**Trigger**
A fact, pitfall or better approach is true beyond this ticket: it belongs in the Library, not only your report.

**Do** — file it yourself, addressed to nobody:
- **A lesson** (fact, pitfall, host or tool trap): `lookup(scope=<your ticket>, question=<the fact>)` first (already there? stop), else `record_lesson(domain, topic, text, evidence=[<ids>])`, text one sentence.
- **A bar in a strategy/domain doc is missing or wrong** (`context()` lists the docs linked to your ticket): `doc_read` it, then `doc_create(doc_type=<its doc_type>, title=<its title>, body_md=<full next version>, scope=<its scope>, status="proposed", proposes=<its id>, ticket_id=<your ticket>)`. Change only the bar your evidence touches; it lands in its `## Rules` (/doc-write).
- **A new topic no doc covers**: `doc_create(..., status="proposed")` without `proposes`.
The owner approves in the Library; never wait on it. Name the id in your report. An sme is spawned only for a big topic the owner asks for, never as the /learn inbox.
