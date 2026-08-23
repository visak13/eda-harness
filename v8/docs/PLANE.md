# Plane CE mirror

edp8's board is always the source of truth (FRAMEWORK-V8-DRAFT-v2 §4). The
Plane adapter (`src/edp8/plane_adapter.py`) is a **one-way mirror**: board
events push into Plane issues/comments, and the only path back is a webhook
that turns a human's Plane comment into a `note` Message on the ticket. Plane
never drives status, assignment, or docs — it is a portal for people who'd
rather look at a kanban board than talk to edp8 directly.

## 1. Bring up Plane CE

We don't vendor Plane's compose file — use their official installer, which
tracks their own releases:

```bash
git clone https://github.com/makeplane/plane
cd plane
./setup.sh   # or: docker compose -f docker-compose.yml up -d
```

Follow their README for the exact flags for your OS. Once it's up, open the
web UI (default `http://localhost`), finish onboarding, and:

1. Create (or pick) a **workspace** — note its slug (the part of the URL
   after `/`, e.g. `http://localhost/acme-corp` → slug `acme-corp`).
2. Create a **project** inside it — note its project id (Project Settings →
   General, or from the URL `/projects/<project_id>/`).
3. Create a **personal API token**: Workspace Settings → API Tokens → New.
   Plane sends this back as `X-API-Key` on every REST call.

## 2. Configure edp8

Set these before starting the board (or the standalone mirror process):

| var                    | meaning                                                        |
|------------------------|------------------------------------------------------------------|
| `EDP8_PLANE_URL`       | Plane base URL, e.g. `http://localhost`                          |
| `EDP8_PLANE_API_KEY`   | the API token from step 3                                        |
| `EDP8_PLANE_WORKSPACE` | workspace slug                                                   |
| `EDP8_PLANE_PROJECT`   | project id                                                       |
| `EDP8_PLANE_STATES`    | optional JSON map, our `TicketStatus` -> Plane state *name*. Default: identity (e.g. `"in_progress": "in_progress"`) — rename to match whatever states your Plane project actually has (Plane ships with `Backlog`/`Todo`/`In Progress`/`Done`/`Cancelled` by default, so you likely want something like `{"drafted": "Backlog", "ready": "Todo", "in_progress": "In Progress", "done": "Done", "dropped": "Cancelled"}`) |

## 3. Run the mirror

Two options — pick one, not both:

- **Embedded in the board** (simplest): set the env vars above, then start
  the board as usual (`uv run edp8-board`). `service.create_app` detects
  `EDP8_PLANE_URL` and starts the mirror as a daemon thread automatically,
  plus mounts the webhook route at `/v1/plane/webhook` on the board's own
  port.
- **Standalone process**: run `uv run python -m edp8.plane_adapter` next to
  (or instead of, if you don't want the webhook mounted on the board) the
  board process. It polls `board.store.events_since` every 2s from wherever
  it last got to (best-effort at-least-once; a state update Plane already
  reflects is just a harmless re-PATCH).

## 4. Register the webhook

In Plane: Project Settings → Webhooks → Add webhook, URL
`http://<board-host>:<board-port>/v1/plane/webhook`, subscribe to comment
events. When someone replies on a Plane issue, the sink checks the comment
doesn't start with `[` (our own mirrored comments are always prefixed
`[kind] from <participant>: ...`) and, if the issue is mapped to a ticket,
appends it to that ticket's thread as a `note` from `created_by="plane"`.

## What's mirrored

- `ticket_created` → `POST .../issues/` (title, kind/work_type in the
  description, `parent` if the parent ticket is already mapped, initial
  `state` if `EDP8_PLANE_STATES` maps it). The new issue id is stored in a
  `plane_map(ticket_id, issue_id)` sqlite table alongside the board's own
  data (same connection, no board schema changes).
- `status_changed` → `PATCH .../issues/{id}/` with the mapped Plane state,
  only if both the ticket and the target state name are known.
- `message_sent` → a comment, prefixed `[kind] from <participant>: <text>`.
- `doc_updated` on a **design** doc → a comment linking `doc <id> v<n>` on
  the ticket named by the doc's `scope`.
- `assigned` → a plain comment noting the new assignee (Plane assignee ids
  don't line up with edp8 participant ids, so we don't attempt to set
  Plane's own `assignees` field).

Every push is best-effort: an HTTP error (including Plane CE's occasional
500s) is logged and appended to `PlaneMirror.errors`, never raised — a flaky
Plane instance can't stall the board.

## Limitations

- Plane CE's custom fields aren't used; we only touch name, description,
  state, parent, and comments.
- No polling backfill of Plane-side changes beyond comments — status moves
  made directly in Plane's UI are invisible to edp8 by design (one-way).
- The mirror is at-least-once, not exactly-once: if the process restarts
  mid-poll, a handful of events near the restart point may replay (extra
  PATCH/comment calls), which is harmless but not perfectly idempotent for
  `create_issue` if the process crashes between the API call succeeding and
  `_map_put` committing — restarts are best kept rare, not zero-risk.
