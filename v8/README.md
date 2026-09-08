# edp8 — v8 board

Ten objects, six invariants, role-scoped MCP bundles. Spec: `../claude/docs/design/FRAMEWORK-V8-DRAFT-v2.md`.

- `start.ps1` / `start.sh` (+ `stop.*`) — one-command fleet launcher, reads one `.env` (S17).
- `.mcp.json` — the edp8 MCP server; identity from `EDP8_PARTICIPANT` (or the pool's `EDP_HANDLE`).
- `.claude/commands/<role>.md` — the cards; `.claude/skills/` — the skills; `guides/` — on-demand guides.
- `uv run pytest -q` — board tests; `npm --prefix web test -- --run` — web unit tests.

## The five services (one line each)

| service | port | what it is for |
|---|---|---|
| **board** | 9400 | the source of truth — tickets, docs, criteria, events; also serves the SPA at `/app` |
| **broker** | 9300 | the wake plane — shell inboxes, channels, SSE events; wakes parked shells |
| **pool** | 9301 | spawns / parks / reaps the Claude shells, one per seat |
| **mcp** | 9402 | the one shared MCP server every shell's tools talk to |
| **bridge** | — | Slack doorbell (no port): broker inbox growth → a Slack ping (needs `slack_map.json`) |

The launcher owns these. **Seats never start, stop or restart a shared service** (design §22) — a
test that needs a server starts a private instance on a free port (`edp8-board --port 0 --data <tmp>`).
`start.* --restart <service>` is the only supported way to make a code change live; it records a
`service_restarted` event on the board. `edp8 status` shows each service's pid, port, git rev,
uptime and last restart; a service whose port is listening reads **up** even when it was not
launcher-started (no pid file). `start.*` leaves a supervisor that probes every 15 s and restarts a
service after three failed probes (or when its process is alive but its listener is gone); it also
watches the port-less bridge by process liveness, **but only a bridge this fleet itself started** —
a fleet never adopts, restarts or stops a Slack bridge it did not launch (each fleet acts only on
the pids recorded in its own `EDP8_RUN_DIR`, so a private/test fleet can never touch the live one).

## Fresh machine — Windows

1. Install [uv](https://docs.astral.sh/uv/) and [Node ≥ 24](https://nodejs.org).
2. `git clone https://github.com/visak13/eda-harness.git; cd eda-harness\v8`
3. `uv sync --extra dev`   — Python deps into `.venv`.
4. `npm --prefix web ci`   — web deps.
5. `npx --prefix web playwright install chromium`   — only if you will run the win32 visual/e2e specs.
6. `copy .env.example .env`   — then edit ports/secrets if the defaults do not suit.
7. `.\start.ps1`   — brings up board, broker, pool, mcp, bridge; prints pids + URLs; builds the SPA if `src\edp8\webapp\dist` is missing.
8. Open the printed board URL (`http://127.0.0.1:9400/app`). `.\stop.ps1` brings it all down.

## Fresh machine — Linux

1. Install [uv](https://docs.astral.sh/uv/) and [Node ≥ 24](https://nodejs.org).
2. `git clone https://github.com/visak13/eda-harness.git && cd eda-harness/v8`
3. `uv sync --extra dev`
4. `npm --prefix web ci`
5. `npx --prefix web playwright install chromium`   — only for local Playwright runs (CI skips them).
6. `cp .env.example .env`   — then edit if needed.
7. `chmod +x start.sh stop.sh && ./start.sh`   — builds the SPA if its dist is missing, then starts everything.
8. Open `http://127.0.0.1:9400/app`. `./stop.sh` brings it all down.

A missing `uv` or `node` makes `start.*` exit non-zero with a one-line message naming the tool.

## Reach from another machine (public mode)

Set `EDP8_PUBLIC_URL` in `.env` (e.g. your Tailscale hostname). Then:

- the board binds `0.0.0.0` by default (`EDP8_HOST` still overrides), and
- Slack deep links are built from `EDP8_PUBLIC_URL`, so a tagged person on another machine lands on
  the SPA (`/ui/ticket/{id}?as=you`) with their identity.

**Public mode fails closed.** The board refuses to start unless `EDP8_ADMIN_TOKEN` is non-default
**and** `tokens.json` holds a credential for every human and at least one agent (agents are minted
at spawn by the pool). A request from another host that carries only `X-Participant` (no valid
`X-Token`) is refused with `401` — for agents and humans alike. **TLS is expected to terminate at a
reverse proxy** (nginx, Caddy, a Tailscale HTTPS front, …) in front of the board; the board itself
speaks plain HTTP on the bind address, so put it behind the proxy and point `EDP8_PUBLIC_URL` at the
proxy's `https://` URL. `tokens.json` (next to `.env`, or `EDP8_TOKENS`) shape:

```json
{ "owner": "<owner-secret>", "agents": { "engineer.s-abc": "<seat-secret>" } }
```
