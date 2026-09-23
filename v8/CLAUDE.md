# Environment (v8 agent home)

- Windows 11; PowerShell is the primary shell (Git Bash may exist). `uv` manages Python (`uv run`, `uv sync`).
- This directory is the v8 agent home: `.claude/commands/<role>.md` are the role cards, `.claude/skills/` the skills,
  `guides/` the on-demand guides, `.mcp.json` the `edp8` MCP server (board at `EDP8_BOARD_URL`).
- Your identity comes from the environment (`EDP_HANDLE` / `EDP8_PARTICIPANT`); boot is `whoami → subscribe → context`.
- Fleet services are operated ONLY through `edp.ps1` at the repo root (`status`, `start|stop|restart <svc|all>`,
  `update`; `-WhatIf` = plan only): safe pid-chain stops, no tree kill, pool needs `-Force`. Seats run only
  `status`/`-WhatIf`; the human runs the rest. Procedure: `get_guide('shared-host-rules')` § Use edp.ps1.
- Shared-host rules bind every seat: stage only your own paths (never `git add -A`/`git clean`/stash); never restart
  a shared service or `taskkill` the board by image; no full web e2e from an engineer seat; wait for consult results;
  a doing seat never idles mid-plan. Full text: `guides/shared-host-rules.md` (`get_guide('shared-host-rules')`).
- No one reads the shell (owner ruling m-45f5a9e954): report on the board only. End every turn with no shell prose, or one short
  line at most; never recap, summarise or narrate in the shell. Tool calls are the work; board messages are the record.
