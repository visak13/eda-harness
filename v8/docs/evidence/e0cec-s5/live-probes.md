# e0cec S5 live probes (guest token, private board)

Board http://127.0.0.1:19477, token mode, EDP8_BIND cleared. Guest `gina` is a member of epic-8b9b5d3d1e only.

| class | call | expect | got | code | ok | note |
|---|---|---|---|---|---|---|
| gate answer | `POST /v1/gates/s-ec3f114036/demo/answer` | 403 | 403 | http | yes | a guest may not use POST /v1/gates/{ticket_id}/{gate}/answer (gate open/answer) |
| criterion verdict | `POST /v1/me/verdict` | 403 | 403 | http | yes | a guest may not use POST /v1/me/verdict (criterion verdict) |
| criterion verdict (PATCH) | `PATCH /v1/criteria/c-13157f108c` | 403 | 403 | http | yes | a guest may not use PATCH /v1/criteria/{id_} (criteria create / verdict) |
| spawn | `POST /v1/sessions/spawn` | 403 | 403 | http | yes | a guest may not use POST /v1/sessions/spawn (spawn/reap/resume/close: seat authority) |
| reap | `POST /v1/sessions/reap` | 403 | 403 | http | yes | a guest may not use POST /v1/sessions/reap (spawn/reap/resume/close: seat authority) |
| resume | `POST /v1/sessions/resume` | 403 | 403 | http | yes | a guest may not use POST /v1/sessions/resume (spawn/reap/resume/close: seat authority) |
| status transition | `PATCH /v1/tickets/s-ec3f114036` | 403 | 403 | http | yes | a guest may not use PATCH /v1/tickets/{id_} (ticket create / status transition / edit) |
| ticket create | `POST /v1/tickets` | 403 | 403 | http | yes | a guest may not use POST /v1/tickets (ticket create / status transition / edit) |
| doc create | `POST /v1/docs` | 403 | 403 | http | yes | a guest may not use POST /v1/docs (doc create/edit/approve/import) |
| link write | `POST /v1/links` | 403 | 403 | http | yes | a guest may not use POST /v1/links (link writes would widen the closure) |
| membership edit | `PUT /v1/epics/epic-8b9b5d3d1e/members` | 403 | 403 | http | yes | a guest may not use PUT /v1/epics/{epic_id}/members (epic edits incl. membership (owner)) |
| admin | `GET /v1/admin/teammates` | 403 | 403 | http | yes | 'gina' is not an admin |
| settings | `GET /v1/admin/settings` | 403 | 403 | http | yes | 'gina' is not an admin |
| models | `GET /v1/models` | 403 | 403 | http | yes | a guest may not use GET /v1/models (models / harness / pool: owner configuration) |
| Code tab | `GET /v1/code` | 403 | 403 | http | yes | a guest may not use GET /v1/code (Code tab and chat (owner ruling R6)) |
| Code chat (VS Code) | `POST /v1/code/session` | 403 | 403 | http | yes | a guest may not use POST /v1/code/session (Code tab and chat (owner ruling R6)) |
| workflows | `GET /v1/workflows` | 403 | 403 | http | yes | a guest may not use GET /v1/workflows (workflow definitions are owner configuration) |
| operator aggregate: library | `GET /v1/library` | 403 | 403 | http | yes | a guest may not use GET /v1/library (operator aggregates the guest UI never calls) |
| operator aggregate: recall | `GET /v1/recall` | 403 | 403 | http | yes | a guest may not use GET /v1/recall (operator aggregates the guest UI never calls) |
| operator aggregate: activity | `GET /v1/activity` | 403 | 403 | http | yes | a guest may not use GET /v1/activity (operator aggregates the guest UI never calls) |
| message kind (steer) | `POST /v1/messages` | 403 | 403 | forbidden | yes | a guest posts a question or a note, not a steer |
| scoped: ticket | `GET /v1/tickets/s-5994d73d8b` | 404 | 404 | not_found | yes | ticket 's-5994d73d8b' does not exist |
| scoped: missing ticket | `GET /v1/tickets/s-0000000000` | 404 | 404 | not_found | yes | same body as non-member |
| scoped: doc | `GET /v1/docs/note-5b749b7949` | 404 | 404 | not_found | yes | object 'note-5b749b7949' does not exist |
| scoped: message | `GET /v1/messages/m-24948c6e2b` | 404 | 404 | not_found | yes | message 'm-24948c6e2b' does not exist |
| scoped: board | `GET /v1/board/epic-a0c27cebf5` | 404 | 404 | not_found | yes | ticket 'epic-a0c27cebf5' does not exist |
| scoped: lookup | `GET /v1/lookup` | 404 | 404 | not_found | yes | ticket 'epic-a0c27cebf5' does not exist |
| scoped: post on non-member | `POST /v1/messages` | 404 | 404 | not_found | yes | ticket 's-5994d73d8b' does not exist |
| allowed: read epic | `GET /v1/board/epic-8b9b5d3d1e` | 200 | 200 |  | yes |  |
| allowed: read story | `GET /v1/tickets/s-ec3f114036` | 200 | 200 |  | yes |  |
| allowed: question | `POST /v1/messages` | 200 | 200 |  | yes |  |
| allowed: note | `POST /v1/messages` | 200 | 200 |  | yes |  |
| allowed: upload | `POST /v1/artifacts/upload` | 200 | 200 |  | yes |  |
| allowed: finalise on member epic | `POST /v1/artifacts/finalize` | 200 | 200 |  | yes |  |
| secret screen | `POST /v1/messages` | 422 | 422 | secret | yes | error names the class (github-token) |
| r2 B1: context_delta (A blocks B) | `GET /v1/context_delta` | 200 | 200 |  | yes | B text or ids in the delta: False |
| r2 B2: tickets/table count oracle | `GET /v1/tickets/table?q=quokka` | 200 | 200 |  | yes | count=0 rows=0 |
| r2 #3: quote a B message | `POST /v1/messages (quotes)` | 422 | 422 | quote_source_missing | yes | same error as a missing source: True |
| r2 #4: ?around=<B message> | `GET/POST /v1/messages?around=` | 404 | 404 | not_found | yes | body identical to a missing id: True |
| r2 #4: reply_to=<B message> | `GET/POST /v1/messages (reply_to)` | 404 | 404 | not_found | yes | body identical to a missing id: True |
| r2 #5: one-hop doc scope | `GET /v1/docs/note-4ae444a228` | 200 | 200 |  | yes | scope=None |
| r2 #6: /v1/seats | `GET /v1/seats` | 200 | 200 |  | yes | B seat or ids listed: False |
| r2 #7: screen host-path | `POST /v1/messages` | 422 | 422 | secret | yes | names (host-path) |
| r2 #7: screen api-key-header | `POST /v1/messages` | 422 | 422 | secret | yes | names (api-key-header) |
| r2 #7: screen token-assignment | `POST /v1/messages` | 422 | 422 | secret | yes | names (token-assignment) |
| r2 #7: EDP8_OWNER-style value passes | `POST /v1/messages` | 200 | 200 |  | yes |  |
| r2 #7: read boundary (status note) | `GET /v1/messages` | 200 | 200 |  | yes | host path withheld at read |
| r2 nit: link delete revokes the hop | `GET /v1/docs/note-4ae444a228` | 404 | 404 | not_found | yes | object 'note-4ae444a228' does not exist |
| r2 nit: to=<out-of-scope seat> | `GET/POST /v1/messages (to)` | 404 | 404 | not_found | yes | body identical to a missing id: True |
| aggregate: find | `GET /v1/find` | 200 | 200 |  | yes | B ids leaked: none |
| aggregate: context | `GET /v1/context` | 200 | 200 |  | yes | B ids leaked: none |
| aggregate: attention | `GET /v1/me/attention` | 200 | 200 |  | yes | B ids leaked: none |
| aggregate: events | `GET /v1/events` | 200 | 200 |  | yes | B ids leaked: none |
| legacy /ui path (SPA shell) | `GET /ui/tickets` | 200 | 200 |  | yes | board ids in the page: none |
| aggregate: SSE feed | `GET /v1/feed?watch=true` | 200 | 200 |  | yes | A's new ticket seen: True; B's: False |

55/55 probes as expected.
