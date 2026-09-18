# Context refresh

Use `context()` for full orientation at boot, after compaction if knowledge or a cursor
was lost, or when a delta returns `resync_required`. Existing ticket blocks and asks
remain intact. Save its `cursor` only with enough context to interpret later changes.

Otherwise choose `context_delta(cursor=last_cursor, ticket_id=same_scope)`.
Do not call both routinely. `changed:false` needs no read. Changes carry IDs, sequence,
read references and short messages (512 characters, with explicit truncation); read only
objects needed for action. An `orientation_changed` reference requires refreshing orientation:
legacy link/criterion/description writes do not all emit events, so a current-state fingerprint
conservatively invalidates metadata. This is explicit resynchronization, not routine double-reading.
The complete successful delta envelope is bounded to 48 KB, including its constant-size hashed
cursor. Oversized individual events yield an explicit invalidation instead of stalling pagination.
An `asks_changed` reference requires `inbox()` so resolved,
reopened and newly addressed asks are not lost. Unchanged asks remain your responsibility.

After consuming a page, save `next_cursor`; continue while `has_more`. The continuation
has a fixed through-watermark. Replay is safe; deduplicate event_id/seq. Other sessions
have independent cursors. A cursor is signed caller state, not a credential. Authentication
still applies. Cursors expire after 24 hours, on board restart, stream retention/reset,
identity/role/scope changes or assigned-ticket additions/removals: resynchronize explicitly.
Unknown/deleted objects return a resynchronization hint, never silent omission.

ContextDelta/ContextSnapshot/ContextChange schemas: `describe_objects(type=...)`.
Related objects: ticket, doc, message, event. Related skills: methodology, handoff.

A doing seat resumes its next unbuilt plan item even with no new board changes. Listening
seats may end silently. Silence is not permission to abandon an in-progress plan.

## Activation
Deploy board and MCP only through owner-coordinated maintenance. Verify tools/list contains
context_delta and run an isolated/new-session snapshot→delta. Only then explicitly replace
that session's existing cron with subscribe's choice-based heartbeat. Never update a live
cron to call a tool unavailable in its loaded schema; no automatic cron migration occurs.
