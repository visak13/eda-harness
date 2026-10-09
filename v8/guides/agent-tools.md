# Agent tool workflows

`describe_objects()` lists object names; `describe(<type>)` gives one; `describe('enums')` lists the fixed vocabularies. IDs, tags, models and free text are never enums.

## Docs
doc_create → link_create → doc_read → doc_edit(id, expected_version, edits) (architect/engineer/qa/adversary only). Each `old_text` must match the ORIGINAL body exactly once; an overlap, a miss, an ambiguity or a stale version writes nothing. One success is one new version. doc_update also returns a receipt (`compact=false` returns the doc). Every write tool echoes a body over 240 chars clipped, with `echo.bytes` and `echo.read`, the exact call that returns it whole. `doc_read(limit=8192)` reads a range: follow the returned continuation exactly, version included; `section` is a unique Markdown heading line and offsets are relative to it. Without range arguments doc_read returns the whole body.

## Files
artifact_upload(path, note) stages a file; message_send(artifacts=[id]) finalizes it (architect/engineer/adversary only). If artifact_upload answers `unavailable`, post `message_send(kind='deviation', to='architect')` with the path: never curl the board with a token, never a `workspace:` artifact_create ref (the board holds no bytes for one). Uploads go through artifact_upload only; no `artifact_id` back means it is not attached, so retry before claiming it.
(engineer/qa/adversary only) `artifact_read(id)` returns an image as an image block and text 6 KB at a time (`offset=next_offset`). Never paste image base64 into an argument.

## Retrying a create
ticket_create, doc_create, artifact_create, criterion_create, message_send, record_decision, record_claim, record_lesson, topic_propose and propose_fix take an optional `idempotency_key`. The same key and args return the FIRST result (`value.replay: true`, same id) for 24 h; the same key with different args is a `conflict`. Without a key an identical create by the same seat within 10 minutes also replays, but that window resets when the MCP proxy restarts. Pass a key whenever you retry after a timeout; a new key makes a deliberate twin.

## Review handoff
Attaching evidence, editing a doc or posting a status never moves work to review. After you verify, call `ticket_update(status='in_review')`; every criterion needs evidence. Returning work to in_progress needs a new explicit hand-off even when old evidence refs remain.

## Feed lines
`subscribe()` gives one NDJSON line per item; no line means wait on the monitor, never poll harder.
- `{"event": {subject_id, kind, data}}`: `status_changed`, `assigned`, `doc_updated` are board state (act only if they make work ready for you); `gate_opened` is a human decision (answer if you are the owner, else hold); `gate_answered` means proceed; `shell_dead` / `shell_stalled` means a child session needs `resume()` or `reap()` (owner/architect only).
- `{"message": {ticket_id, to, kind, text, reply_to}}`: `question`, `steer`, `deviation`, `finding` need a reply on the same thread; `answer`, `status`, `note` need none.
- `{"heartbeat": {reason, changes, ticket, next}}`: `changes` → `context_delta(cursor=…)`; `resync` → `context()`; `liveness` (doing seats with an in_progress ticket only) → resume the next unbuilt item of your plan. A quiet tick prints nothing.
