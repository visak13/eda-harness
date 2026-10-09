---
name: verify
description: Trigger before handing a ticket over, or whenever checking a criterion.
---

# /verify

**Do**
Run each criterion's check (command | path | look | verdict) yourself; record the actual result, never a prior claim.

**`look` / owner-visible change: the UI walk** (a seat's `look` pass needs an image on the ticket)
1. INSTALLED app, `EDP8_BOARD_URL`/ui/, owner's real config, read-only; no fixtures or dev server.
2. The browser tool (`browser_*`), signed in as you on the board; no token in a URL, log or shot.
3. Click the owner's exact path; create nothing permanent.
4. Screenshot each step; check each, mask secrets and private windows.
5. Upload, attach (`message_send(artifacts=[...])`), name them in the report.

**Writes**
`doc_update` (report section) + `criterion_update(evidence_ref, verdict)` per criterion (not owner).
