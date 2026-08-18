## The system in one page

One object graph — `recipe ─owns→ step ─spawns→ plan ─owns→ action
─spawns→ worker` — operated through three planes:

- **CRUD = what is true now.** `describe_objects` / `read_object` /
  `query_objects` (read) · `create_object` / `update_object` (write);
  invariants live inside each object — you never re-implement a rule.
  Read the schema of the objects you operate ONCE at boot
  (`describe_objects(<object>)` or the `edp://schema/<object>` MCP
  resource) and reference it thereafter — refusals always name the
  legal values, so guessing is never cheaper than reading once.
  `read_object(type="recipe", detail="brief")` is the READABLE
  one-call map (goal verbatim → outcomes → decisions → bans → steps).
  **NEVER read or write recipe/plan/action/step/outcome/worklog via a
  raw file path** — the on-disk shape is an implementation detail, and
  an unreachable MCP is a BLOCKED state to surface, never a cue to
  reach for files.
- **rx = what just changed.** `arm_wiring()` composes your role's
  subscription server-side — run the returned `monitor_cmd` under the
  `Monitor` tool (one Monitor, armed ONCE, not consumed on fire) and
  the returned cron as backstop; wakes arrive as Monitor TOOL output
  naming what changed. Subscribe FIRST; the cron heartbeat is the
  backstop, never the primary wake. A spec with no live driver is DEAF
  — verify after arming and after any restart/compaction
  (`list_subscriptions`, re-arm is idempotent).
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
