# Authorized one-time live restoration — 2026-09-18

Owner authorization: **m-f5feec237a**, “@architect.epic-44a0576511 yes I authorize”, answering the exact procedure request **m-e53be35e24**. Previous permission was for preparation/testing only.

Extended isolated proof to verify exact authorization record and exclusive before-image creation: **13 tests passed in 1.191s**. The proof file's default execution still runs temporary synthetic tests only. Candidate helper now has explicit authorization/before-image parameters; a separately invoked one-off operator command used those after permission. No reusable live CLI was added.

Identified the running :9400 listener as PID **17500** and read its EDP8_DB environment (rather than assuming the current shell's default). Confirmed active path `C:/Projects/Learning/eda-base3/v8/.data/edp8.db`. Board tools independently showed the expected v7 epic/children/open gate immediately before maintenance.

One `BEGIN IMMEDIATE` transaction, 1s lock timeout, all tested prerequisites rechecked, exclusive before-image written, changed only epic-44a0576511's status JSON/index from `in_progress` to `designed` and appended maintenance status event **ev-28f799b21a**, attributed to architect.epic-44a0576511 and referencing m-f5feec237a. Event sequence allocated atomically. No owner/gate impersonation, no deletion or rewrite of old history. Transaction measured **0.0289s**; this is duration, not a claim of zero concurrent latency impact.

Private before-image (NOT committed): `.run/repairs/epic-44a0576511-before-20260918T0803.json`. It is a recovery snapshot, not an automatic rollback instruction.

Read-back through **ticket_read** confirmed `designed`, `design-f716d0d138` v7, original words, same eight children (S0/S1/S7 blocked, other five signed_off), design_signoff still open. Board PID unchanged; no service or sibling process was restarted/killed. Only the owner may answer the actual gate now. Message **m-0008904b03** gives the epic gate-form instructions and promises no more status transitions before the real answer.

No application implementation dispatched. This is a narrowly authorized exception to service-only writing, NOT a standard agent pattern. Earlier README/proof preparation records remain historical; this receipt records the subsequent permission and actual operation.
