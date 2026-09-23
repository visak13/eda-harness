---
name: learn
description: Trigger when you find something reusable beyond the current ticket.
---
<!-- roles: architect, engineer, qa, sme, adversary -->

# /learn

**Trigger**
You find a fact, pitfall, or better approach that is true beyond this one ticket — it
belongs in the Library, not just in this ticket's report.

**Do** — file it yourself, in the Library, addressed to nobody:
- **A lesson** (a fact, pitfall, host or tool trap): `lookup(scope=<your ticket>, question=<the fact>)`
  first — already there? stop. Else `record_lesson(domain, topic, text, evidence=[<ids>])`, text one
  sentence; lookup surfaces it to every later epic.
- **A bar in a strategy/domain doc is missing or wrong** (the brief's `index` names the doc): `doc_read`
  it, then `doc_create(doc_type=<its doc_type>, title=<its title>, body_md=<the full next version>,
  scope=<its scope>, status="proposed", proposes=<its id>, ticket_id=<your ticket>)`. Change only the
  bar your evidence touches and keep its `## Enforced` section.
- **A new topic no doc covers**: `doc_create(..., status="proposed")` without `proposes`.
The owner approves or rejects proposals in the Library; you never wait on it. An sme is
spawned only for a big new topic the owner asks for — never as the /learn inbox.

**Writes**
A lesson (`record_lesson`) or a proposed doc (`doc_create status=proposed`); one line naming its
id in your report.
