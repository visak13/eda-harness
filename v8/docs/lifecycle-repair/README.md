# Isolated proof: restore pre-execution gate eligibility

Owner authorized preparation/testing in `m-0fffd5a050`, answering `m-29117a7387`. **No live write is authorized or performed by this proof.** No service/app source changes, reloads, spawns, owner impersonation or gate-answer fabrication.

## Reproduce

`.venv/Scripts/python.exe docs/lifecycle-repair/probe_restore.py -v`

Result: **11 tests passed in 1.080s** on 2026-09-18. Uses fresh temporary SQLite databases with synthetic contents. Running the file invokes tests only; it has no live-database locator/CLI. Existing scratch files are untouched.

Tests cover: exactly one changed ticket; unchanged words and sibling/child rows; real Board.gate_answer succeeding afterward with a synthetic owner actor; gate remains open until that real action; honestly attributed repair event; atomic rollback on injected failure; repeat/change-of-version/started-work/evidence/execution-session/closed-gate/index-drift refusal; competing writer lock refusal; subsequent sibling writability. These do not prove full live-service concurrency behavior.

## Candidate live procedure — requires separate explicit authorization

The normal gate only accepts a designed epic. Proposed exception is a one-time, operator-controlled maintenance write, not a new agent permission:

1. Confirm exact active DB installation read-only; never assume a path from a stale environment. Read current epic, eight descendants, design v7, gate and sessions via board. Record the owner's explicit repair authorization, separate from the original design approval.
2. Quiesce **this epic's** UI/agent mutations for the short maintenance operation. No workers have been dispatched; resident architect does not change this epic during repair. If quiescence cannot be established, do not apply.
3. Existing store declares the service as single writer. A separate maintenance SQLite transaction is an explicit **exception** requiring owner authorization. SQLite writer serialization alone cannot prevent a service operation that read stale epic data from later overwriting it; same-epic quiescence is necessary. No claim of fully safe arbitrary concurrent operation.
4. A bounded BEGIN IMMEDIATE transaction rechecks exact ID/type/status/design/version/assignee, exact eight child statuses/assignments, pending evidence, absent nonresident execution sessions and still-open design gate. Short lock timeout; fail without mutation on conflict/drift. Capture the original target row privately as a before-image; do not copy/export unrelated records.
5. Change ONLY the epic status in JSON body and indexed column from in_progress to designed. Preserve row sequence, created metadata, words, description, assignments and relationships. Append ONE maintenance status_changed event attributed to the repair actor, referencing actual authorization/reason. Allocate global event sequence in the same transaction; no gate_answered event. No deletions, no replacing original messages or past audit events. FTS excludes status, so no text index change is needed.
6. Commit once. Roll back automatically before commit on any failure. Do not automatically reverse a committed operation after the owner has acted; post-commit rollback requires rereading state and a separately reviewed compensating operation.
7. Immediately read back through board tools (not just SQL): designed, gate still open, child states unchanged. Explicit page refresh may be needed: an out-of-process durable event does not run the live process's usual emit callbacks. No fake instant-notification guarantee.
8. Owner uses the **existing gate action** to approve v7, now eligible. Verify gate_answered is truly owner-authored and gate closes. Then release S0/S1/S7 through normal tools and existing dependency rules; do not mutate their statuses in the maintenance transaction.

No process/service restart or sibling session change. A SQLite write lock may briefly queue unrelated writes, so zero latency impact is NOT promised. If the owner declines a single-writer exception, the alternative is a supported in-service repair endpoint/fix with separately coordinated deployment; do not silently use direct SQL instead.
