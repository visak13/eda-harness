# edp8 — v8 board

Ten objects, six invariants, role-scoped MCP bundles. Spec: `../claude/docs/design/FRAMEWORK-V8-DRAFT-v2.md`.

- `scripts/start-board.ps1` / `stop-board.ps1` — local board on :9400 + default participants.
- `.mcp.json` — the edp8 MCP server; identity from `EDP8_PARTICIPANT` (or the pool's `EDP_HANDLE`).
- `.claude/commands/<role>.md` — the cards; `.claude/skills/` — the skills; `guides/` — on-demand guides.
- `uv run pytest -q` — tests.
