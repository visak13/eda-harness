# Feed format

A feed is the merged stream `subscribe()` delivers to one participant: messages `to` it,
events on its tickets, gate openings it must answer, and shell deaths of its children. It
is not stored as its own object — it is a live subscription over Message and Event.

Each line delivered to a shell is NDJSON, one JSON object per line, one of two shapes:

```json
{"event": {"subject_id": "...", "kind": "status_changed|gate_opened|gate_answered|assigned|doc_updated|shell_dead|shell_stalled", "data": {...}}}
```

```json
{"message": {"ticket_id": "...", "to": "...", "kind": "question|answer|steer|status|finding|deviation|note", "text": "...", "reply_to": "..."}}
```

What each kind means:
- `event.status_changed` / `assigned` / `doc_updated` — board state moved; read-only,
  informational unless it makes work ready for you.
- `event.gate_opened` — a human decision is pending; answer if you are the owner, or hold
  if you are not.
- `event.gate_answered` — the gate above is resolved; proceed.
- `event.shell_dead` / `shell_stalled` — a child session needs `resume()` or `reap()`.
- `message.question` / `steer` / `deviation` / `finding` — someone needs a response from
  you; reply on the same ticket thread.
- `message.answer` / `status` / `note` — informational; no reply required.

**No line = nothing to do.** An empty feed is not an error and not a signal to poll harder;
it means wait on the monitor. Cron is a backstop only, reconciling when the monitor itself
has gone stale — it is not the primary path.
