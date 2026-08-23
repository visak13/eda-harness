---
name: ocak
description: Trigger when a design draft exists and needs a post-reasoning completeness audit before sign-off.
---

# /ocak

**Trigger**
A design draft exists (options generated, or a goal clarified into a draft outcome) and has
not yet been audited. This is a post-reasoning check, never a thinking template — do not use
O/C/A/K to generate the draft itself.

**Do**
Audit the draft against four questions, one verdict each:
- **Observation** — what prior approach to this goal-class exists (`find`)? Did the draft
  use it? Null is fine if none exists.
- **Comprehension** — does the draft address the root cause or a symptom/proxy? State the
  real goal explicitly.
- **Awareness** — is this a class-fix or an instance-fix? If instance, name the sibling
  cases it will not survive.
- **Concerns** — effort/risk/maintenance for this draft, stated plainly.
Any "missed" answer changes the draft or becomes a question before sign-off — never after.

**Writes**
Design doc revision, or `message_send(kind=question)` when a finding needs the owner.
