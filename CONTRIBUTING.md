# Contributing to Heronry

Thanks for helping. Issues and pull requests are welcome at
[github.com/visak13/eda-harness](https://github.com/visak13/eda-harness/issues). Hands-on testing happens on
Windows; a report from macOS or Linux, with `heronry doctor --bundle` attached, is especially useful.

Heronry is Apache-2.0 licensed ([LICENSE](LICENSE), [NOTICE](NOTICE)). By contributing you agree your work
is released under the same licence.

## Develop from source

Installing a release is covered in the [README](README.md#install). To work on the code, run the services
from a checkout instead. Everything is driven by one script at the repo root, `edp.ps1`:

```powershell
.\edp.ps1 status              # every service: up/down, pid, git rev, started_at
.\edp.ps1 start all           # board, broker, pool, mcp, bridge + a health supervisor
.\edp.ps1 restart board       # safe restart of one service
.\edp.ps1 stop all -Force     # everything down (-Force: the pool takes the seats offline)
```

### Run it (Windows)

You need [uv](https://docs.astral.sh/uv/), [Node ≥ 24](https://nodejs.org),
[Claude Code](https://claude.com/claude-code) (`claude` on PATH) and git. Codex CLI is optional.
Run these in Windows PowerShell from any folder:

```powershell
git clone https://github.com/visak13/eda-harness.git
cd eda-harness
.\setup.ps1                              # web + Python dependencies for every service; builds the web app
copy v8\.env.example v8\.env             # the defaults run everything on 127.0.0.1
.\edp.ps1 start all -WhatIf              # print the plan, change nothing
.\edp.ps1 start all                      # board, broker, pool, mcp, bridge + supervisor
.\edp.ps1 status
```

Open **http://127.0.0.1:9400/ui**. `.\edp.ps1 restart <service>` makes a code change live,
`.\edp.ps1 update` pulls and restarts in order, and `.\edp.ps1 stop all -Force` stops everything.

`v8/.env` keys (every one has a safe default):

| Key | Default | What it is |
|---|---|---|
| `EDP8_PORT` | 9400 | board: tickets, docs, criteria, events; serves the web app at `/ui` |
| `EDP_BROKER_PORT` | 9300 | broker: wakes seats when something is addressed to them |
| `EDP_POOL_PORT` | 9301 | pool: starts, parks and stops seat sessions |
| `EDP8_MCP_PORT` | 9402 | the one MCP server every seat's board tools talk to |
| `EDP8_ADMIN_TOKEN` | `dev` | admin token for pool/registry routes; change it before exposing the board |
| `EDP8_OWNER` | `owner` | the human owner's handle |
| `EDP8_PUBLIC_URL` | unset | serve the board to other machines (fails closed without real tokens) |
| `EDP8_HOME`, `EDP8_DATA`, `EDP8_RUN_DIR` | `v8`, `v8/.data`, `v8/.run` | where the database, logs and pid files live |
| `EDP8_RSI` | unset | `1` turns on the regression tripwire above |
| `EDP_CODEX_ROLES` | unset | roles to run as Codex seats |

Linux, public mode behind a reverse proxy, the service map and the test commands are in
[`v8/README.md`](v8/README.md).

## Before you open a pull request

- Run the tests of the package you changed (each package's README lists its commands), for example
  `.venv\Scripts\python -m pytest -q` in `v8/` and `npm test` in `v8/web/`.
- Keep personal data out of the tree: no user-profile paths, e-mail addresses or tokens. CI scans for them.
- Commit only the paths you changed, with a message that says why.
