## The system in one page

One object graph — `recipe ─owns→ step ─spawns→ plan ─owns→ action
─spawns→ worker` — operated through three planes:

- **CRUD = what is true now.** `describe_objects` / `read_object` /
  `query_objects` (read) · `create_object` / `update_object` (write);
  invariants live inside each object — you never re-implement a rule.
  **NEVER read or write recipe/plan/action/step/outcome/worklog via a
  raw file path** — the on-disk shape is an implementation detail, and
  an unreachable MCP is a BLOCKED state to surface, never a cue to
  reach for files.
- **rx = what just changed.** `observe(spec="rx.broker(me, …)", …)` and
  run the returned `monitor_cmd` under the `Monitor` tool — one Monitor
  per observe, armed ONCE (not consumed on fire). Subscribe FIRST; the
  cron heartbeat is the backstop, never the primary wake. Two paid-for
  traps: a spec with no live driver is DEAF (verify after arming and
  after any restart/compaction), and a kind-filter on `rx.broker(me)`
  silently drops every directed message you did not list — filter only
  broadcast planes.
- **flow = the next legal move.** `reconcile` syncs the record to
  broker/pool/disk reality; `next_action` is a pure pacer. The loop:
  react (rx) → `reconcile` → `next_action` → obey `wait_hint`.

Action `status` enum: `pending | in_progress | verify | done | failed |
skipped | needs_review` — no `cancelled` (an invalid status wedges every
later plan load); nothing auto-parks work in `verify`/`needs_review`.

v7 lineage: steps/actions carry `serves` (the outcome ids they exist
for — orphan work is refused at declaration); decisions carry `affects`
(the handles they constrain). A `ground_delta` message means a decision
affecting YOUR handle changed: fold its digest into your ground — do
NOT full-re-ground unless it contradicts your in-flight work.
