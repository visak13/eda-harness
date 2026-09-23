# edp8 — the board and its services (operator reference)

What the project is, the UI, the memory layer and the quick start are in the
[root README](../README.md). This page is the operator detail.

- `.env` (copy of `.env.example`) — the one config file for every service.
- `.mcp.json` — the edp8 MCP server; a seat's identity comes from `EDP8_PARTICIPANT` (or the pool's `EDP_HANDLE`).
- `.claude/commands/<role>.md` — the role cards; `.claude/skills/` — the skills; `guides/` — guides a seat fetches on demand.

## The services

| service | port | what it is for |
|---|---|---|
| **board** | 9400 | the source of truth: tickets, docs, criteria, records, events; serves the web app at `/ui` |
| **broker** | 9300 | the wake plane: seat inboxes, channels, server-sent events; wakes parked seats |
| **pool** | 9301 | starts, parks and stops the seat sessions (Claude Code, or Codex for `EDP_CODEX_ROLES`) |
| **mcp** | 9402 | the one shared MCP server every seat's board tools talk to |
| **bridge** | — | Slack doorbell (no port): broker inbox growth → a Slack ping (needs `slack_map.json`) |
| **supervisor** | — | probes every 15 s and restarts a service after three failed probes |

On Windows, `..\edp.ps1` is the only way to start, stop, restart or update them:
`.\edp.ps1 status | start | stop | restart <board|broker|pool|mcp|bridge|supervisor|all> | update`,
with `-WhatIf` to print the plan and change nothing. It stops a service by its own process chain,
never by image name and never with a tree kill (every seat is a child of the pool), and it refuses to
stop the pool without `-Force` because that takes the seats offline. Details: `guides/edp-ps1.md`.

Seats never start, stop or restart a shared service. A test that needs a board starts a private one on
a spare port with its own `EDP8_HOME`/`EDP8_DB`.

## Linux

1. Install [uv](https://docs.astral.sh/uv/) and [Node ≥ 24](https://nodejs.org).
2. `git clone https://github.com/visak13/eda-harness.git && cd eda-harness/v8`
3. `uv sync --extra dev`
4. `cp .env.example .env` — then edit if needed.
5. `chmod +x start.sh stop.sh && ./start.sh` — builds the web app if it is missing, then starts everything.
6. Open `http://127.0.0.1:9400/ui`. `./start.sh --restart <service>` makes a code change live; `./stop.sh` brings it all down.

A missing `uv` or `node` makes the launcher exit non-zero with a one-line message naming the tool.

## Reach from another machine (public mode)

Set `EDP8_PUBLIC_URL` in `.env` (e.g. your Tailscale hostname). Then:

- the board binds `0.0.0.0` by default (`EDP8_HOST` still overrides), and
- Slack deep links are built from `EDP8_PUBLIC_URL`, so a tagged person on another machine lands on
  the web app with their identity.

**Public mode fails closed.** The board refuses to start unless `EDP8_ADMIN_TOKEN` is non-default
**and** `tokens.json` holds a credential for every human and at least one agent (the pool mints agent
tokens at spawn). A request from another host that carries only `X-Participant` (no valid `X-Token`)
is refused with `401`, for agents and humans alike. **TLS terminates at a reverse proxy** (nginx,
Caddy, a Tailscale HTTPS front, …): the board speaks plain HTTP on its bind address, so put it behind
the proxy and point `EDP8_PUBLIC_URL` at the proxy's `https://` URL. `tokens.json` (next to `.env`, or
`EDP8_TOKENS`) shape:

```json
{ "owner": "<owner-secret>", "agents": { "engineer.s-abc": "<seat-secret>" } }
```

## Tests

Run from `v8/` with the venv interpreter (`uv run` re-syncs and cannot replace a running board's
`edp8-board.exe`):

- `.venv\Scripts\python -m pytest -q` — board, tools, memory layer, tripwire.
- `npm --prefix web test -- --run` — web unit tests.
- `npx --prefix web playwright test e2e/<spec>.ts` — one browser spec at a time; each spec starts its
  own private board. The full browser suite is heavy (its own board plus chromium per worker) and is
  run once, by qa.
