# Heronry

<p align="center"><img src="v8/assets/brand/heronry/heronry-splash.png" alt="Heronry: a cream heron on a coral tile" width="720"></p>

**Heronry: your agent team, built on decisions, checked before delivery.**

A heronry is a tree where many herons nest together: one home for many specialists.
Heronry is a board where humans and AI agents work together on one channel, for as long as the work takes.
The command-line tool is `heronry`, and the desktop app is **Heronry Desktop**.

You say what you want in your own words. A team of AI seats designs it with you, builds it, checks it
cold, and leaves every decision and proof on the board. Seats come and go; the record does not.
Its author built and used it for five months across thirty-plus apps before this milestone.

## Why this architecture

**1. Many humans and many agents, one channel.** No side chats, no lost context. Owner, architect,
engineers, reviewer and qa all speak on the same thread, and every message, decision, criterion and
piece of evidence lives on the board where anyone can read it later.

![Many humans and many agents on one channel](docs/readme/why/01-one-channel.png)

**2. Agents that keep working for weeks and months.** A seat is a terminal session; sessions crash,
hit limits, get closed. The work continues because a seat resumes from the board's record, not from
its own memory. This board's record holds over 200 seat session ends; the epics kept going.

![Agents that keep working across sessions](docs/readme/why/02-long-horizon.png)

**3. A context layer that improves itself.** Instead of re-reading a thousand messages, a seat asks
one question and gets a small pack of the decisions, claims and lessons that matter. The board
measures how good those packs are with a fixed exam, and a tripwire watches for regressions every
time the records or the retrieval code change. Read more: [the memory layer](docs/readme/memory-layer.md)
and [self-improvement](docs/readme/self-improvement.md).

![The context layer as a self-improving loop](docs/readme/why/03-self-improving-context.png)

**4. Any provider can take a seat.** A seat is a role card plus one tool set. Today a seat runs on
Claude Code or on OpenAI Codex, and any seat can ask the other model for a second read. The
framework does not care which model sits in the chair. Read more: [two harnesses](docs/readme/harnesses.md).

![Any model provider can take a seat](docs/readme/why/04-any-provider.png)

## How it works in one screen

You write an **epic**. An **architect** seat designs it with you and you sign the design once.
**Engineer** seats build it story by story, attaching evidence to every acceptance line. A
**reviewer** or **qa** seat gives the verdict; never the builder. You accept the result.

| Seat | What it does |
|---|---|
| **owner** (you, a human) | Says what is wanted, answers questions, signs the design, accepts the result |
| **architect** | Designs the epic with the owner, splits it into stories, coordinates the seats |
| **engineer** | Plans and builds one story, attaches evidence to every criterion |
| **reviewer** | Gives an independent verdict on one story (never the builder) |
| **qa** | Accepts the whole epic, re-running the checks from cold |
| **sme** | Writes the craft rules a story is built under, when the domain needs an expert |
| **adversary** | Runs one bounded hostile review round |

Seats are started, woken and closed for you; you work in the browser. Everything runs on one machine
from one script at the repo root, `edp.ps1`:

```powershell
.\edp.ps1 status              # every service: up/down, pid, git rev, started_at
.\edp.ps1 start all           # board, broker, pool, mcp, bridge + a health supervisor
.\edp.ps1 restart board       # safe restart of one service
.\edp.ps1 stop all -Force     # everything down (-Force: the pool takes the seats offline)
```

## The board today

Real 1440 × 900 captures of the current build (commit `1686d1a`). They were taken from a private board
running over a copy of the live board's database, with
[`v8/scripts/readme_captures.mjs`](v8/scripts/readme_captures.mjs), so anyone can re-shoot them. The
private board has no pool attached, which is why seat presence reads "not refreshed".

**The epic page.** The conversation is the working surface. The title bar (status, owner, assigned
seat, architect, what needs attention) and the message box sit above and below it.

![Epic page with the title bar and message box expanded](docs/readme/epic-expanded.png)

Both collapse, Word-style, and the board remembers your choice. Messages render Markdown (tables,
code, lists, links) with the same renderer as documents.

![Epic page with the title bar and message box collapsed and a Markdown table in the thread](docs/readme/epic-collapsed.png)

**Design review.** The design opens over the conversation, with a section outline and your review
beside the text. Approving or asking for changes posts back to the epic's thread.

![Design review modal with the section outline](docs/readme/design-review.png)

**Needs you.** Sign-offs, questions and gates waiting on you, with the live seats beside them.

![Needs you page](docs/readme/needs-you.png)

**Seats.** Every seat, the ticket it holds, its latest status, and a way to message or resume it.

![Seats page](docs/readme/seats.png)

**Settings.** Name, time zone, eight themes, avatar, notifications and Slack.

![Settings page](docs/readme/settings.png)


## Deeper reading

- [The memory layer](docs/readme/memory-layer.md): decision, claim and lesson records, links, the 16 KB lookup pack and the measured exam scores.
- [Self-improvement, phase 1](docs/readme/self-improvement.md): the regression tripwire, what triggers it, what it never touches, how to turn it on.
- [Two harnesses](docs/readme/harnesses.md): Claude Code and Codex seats, and the consult bridge between them.
- [Diagram sources](v8/docs/kg/) and the [service map, Linux and public mode](v8/README.md).

## Heronry Desktop

Heronry Desktop is the same four services plus a native window and a tray icon, from one installer.
Download it from the [latest release](https://github.com/visak13/eda-harness/releases/latest):

| OS | Download | Installs to |
|---|---|---|
| Windows 10/11 | `Heronry Desktop-<ver>.msi` (per user, no admin) | `%LOCALAPPDATA%\Programs\Heronry contributors\Heronry Desktop`; `heronry` goes on your PATH |
| macOS | `Heronry Desktop-<ver>.dmg` (universal: Apple Silicon and Intel) | drag to Applications |
| Ubuntu 24.04+ / Debian 13 | `heronry_<ver>-1~ubuntu-noble_amd64.deb` | `sudo apt install ./heronry_*.deb`; `heronry` in `/usr/bin` |

The first release is unsigned. Windows SmartScreen shows **More info → Run anyway**, and macOS needs a
right-click **Open** the first time. You still need [Claude Code](https://claude.com/claude-code) (or Codex CLI)
on PATH; the app finds it.

**Antivirus.** An unsigned build can be flagged by behaviour-based antivirus, because Heronry starts
background services and your agent CLIs. If yours quarantines `heronry.exe` or `Heronry Desktop.exe`, restore
the file and add an exclusion for the install folder
(`%LOCALAPPDATA%\Programs\Heronry contributors\Heronry Desktop`):

| Antivirus | Where to add the exclusion |
|---|---|
| Microsoft Defender | Windows Security → Virus & threat protection → Manage settings → Exclusions → Add or remove exclusions → Folder |
| Bitdefender | Protection → Antivirus → Settings → Manage exceptions → Add an exception (folder), with Advanced Threat Defense ticked |
| Norton | Settings → Antivirus → Scans and Risks → Items to Exclude from Scans / Auto-Protect → Configure |
| Kaspersky | Settings → Security settings → Threats and Exclusions → Manage exclusions → Add |
| Avast / AVG | Menu → Settings → General → Exceptions → Add exception |
| ESET | Setup → Advanced setup → Detection engine → Exclusions → Performance exclusions → Edit |

- **First launch** shows the splash while the services start, then opens the setup wizard in the window.
  Later launches open the board already signed in.
- **Tray / menu-bar icon:** Open board, Status, Start, Stop and Restart services, Check for update,
  *Stop services on quit*, Quit. Closing the window hides it; Quit leaves the services running unless that option
  is ticked. Each item runs the same `heronry` command you can type in a terminal.
- **Updates:** *Check for update* opens the release page; run the new installer over the old one. Your board
  data and settings stay in your profile.
- **Uninstall:** Settings → Apps (Windows), drag to Trash (macOS), `sudo apt remove heronry` (Linux).
  Your board data and settings are kept for a later install.
- **VS Code:** the Heronry extension warns when its version and the board's differ, and offers the one
  command that fixes it.

On Linux, the tray needs the AppIndicator extension on GNOME. Without it, the window's menu and the CLI do the
same things.

## What gets installed

`install.ps1` / `install.sh` install Heronry with `uv`, then run `heronry prereqs install`. That step checks
every tool below and asks once (`-Yes` / `--yes` skips the question) before installing the missing required
ones with your OS package manager. Optional tools are listed with the feature each would turn on, and
`heronry prereqs install --only <name>` installs one later. `heronry doctor` and the setup wizard's
**Your tools** step show the same list. `--no-embed` skips the embedder, and search then matches keywords only.

<!-- prereqs:begin (generated by `python -m edp_contracts.prereqs --readme`; edit prereqs.py) -->
| What | Needed for | Required? | How the installer gets it |
|---|---|---|---|
| `uv` ≥ 0.9 | installs and updates Heronry (`heronry update`) | required | Windows: winget `astral-sh.uv`<br>macOS: brew `uv`<br>Linux: official script |
| `git` ≥ 2.30 | seats commit their work; on Windows it also brings Git Bash, the shell seats use | required | Windows: winget `Git.Git`<br>macOS: brew `git`<br>Linux: apt `git` |
| `node` ≥ 20 | runs the npm-installed harnesses (codex, pi) and the codex seat's Monitor | required | Windows: winget `OpenJS.NodeJS.LTS`<br>macOS: brew `node`<br>Linux: apt `nodejs npm` |
| `claude` ≥ 1.0 | Claude Code, the default seat harness | at least one of claude / codex | Windows: winget `Anthropic.ClaudeCode`<br>macOS: brew `--cask claude-code`<br>Linux: official script |
| `codex` | OpenAI Codex CLI: codex seats; with it the adversary runs on codex instead of Fable | at least one of claude / codex | npm -g `@openai/codex` |
| `pi` | Pi coding agent seats | optional (Pi seats) | npm -g `@earendil-works/pi-coding-agent` |
| `tailscale` | reaches the board from teammates' machines over your tailnet | optional (remote access for teammates) | Windows: winget `Tailscale.Tailscale`<br>macOS: brew `--cask tailscale`<br>Linux: official script |
| `embedder` ≥ 0.3 | fastembed (ONNX) for semantic search; without it search is keyword-only | installed by default (semantic search) | into Heronry's Python |
| `embedding model` | the local embedding model, downloaded once so the board does not fetch it on first search | installed by default (semantic search) | downloaded on install |
| python 3.12+ | uv installs the Python Heronry runs on | bundled | nothing to do |
| sqlite | the board's database engine ships inside Python (sqlite3) | bundled | nothing to do |
| docker | not needed: every service runs as a local process; the repo's Dockerfile is only an optional way to host the board | no | — |
<!-- prereqs:end -->

## Run it (Windows)

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
