# Environment (v8 agent home)

- Windows 11; PowerShell is the primary shell (Git Bash may exist). `uv` manages Python (`uv run`, `uv sync`).
- This directory is the v8 agent home: `.claude/commands/<role>.md` are the role cards, `.claude/skills/` the skills,
  `guides/` the on-demand guides, `.mcp.json` the `edp8` MCP server (board at `EDP8_BOARD_URL`).
- Your identity comes from the environment (`EDP_HANDLE` / `EDP8_PARTICIPANT`); your role card gives the boot sequence.
- Shared-host rules bind every seat (git tree, services and `edp.ps1`, host capacity, consult, idle wakes):
  `get_guide('shared-host-rules')`.
- No one reads the shell (owner ruling m-45f5a9e954): report on the board only. End every turn with no shell prose, or one short
  line at most; never recap, summarise or narrate in the shell. Tool calls are the work; board messages are the record.
