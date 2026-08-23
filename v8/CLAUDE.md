# Environment (v8 agent home)

- Windows 11; PowerShell is the primary shell (Git Bash may exist). `uv` manages Python (`uv run`, `uv sync`).
- This directory is the v8 agent home: `.claude/commands/<role>.md` are the role cards, `.claude/skills/` the skills,
  `guides/` the on-demand guides, `.mcp.json` the `edp8` MCP server (board at `EDP8_BOARD_URL`).
- Your identity comes from the environment (`EDP_HANDLE` / `EDP8_PARTICIPANT`); boot is `whoami → subscribe → context`.
