# Heronry

<p align="center">
  <a href="https://github.com/visak13/eda-harness/releases/latest/download/heronry-demo.mp4" title="Watch the 90-second product video">
    <picture>
      <source srcset="docs/readme/storefront/hero.webp" type="image/webp">
      <img src="docs/readme/storefront/hero.gif" alt="Heronry in seven seconds: seats spawn, wake on their feed and walk an epic to done" width="720">
    </picture>
  </a>
</p>

<p align="center"><strong>Heronry: your agent team, built on decisions, checked before delivery.</strong></p>

<p align="center">
  <a href="https://github.com/visak13/eda-harness/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/visak13/eda-harness?include_prereleases&sort=semver"></a>
  <a href="https://github.com/visak13/eda-harness/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/visak13/eda-harness/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="Licence: Apache-2.0" src="https://img.shields.io/github/license/visak13/eda-harness"></a>
</p>

<p align="center">
  <a href="https://github.com/visak13/eda-harness/releases/latest"><strong>Download</strong></a> ·
  <a href="https://visak13.github.io/eda-harness/"><strong>Website</strong></a> ·
  <a href="https://github.com/visak13/eda-harness/releases/latest/download/heronry-demo.mp4"><strong>Watch the video</strong></a>
</p>

A heronry is a tree where many herons nest together: one home for many specialists.
Heronry is a board where humans and AI agents work together on one channel, for as long as the work takes.
You say what you want in your own words. A team of AI seats designs it with you, builds it, checks it
cold, and leaves every decision and proof on the board. Seats come and go; the record does not.

The command-line tool is `heronry`, and the desktop app is **Heronry Desktop**. Both run the same services
on your machine, and each can do everything the other does.

## Install

Pick the desktop app (GUI) or the command line (cmd). Both come from the
[latest release](https://github.com/visak13/eda-harness/releases/latest), and both keep your board data
in your user profile, so a reinstall or an update never touches it.

The first release is **unsigned**, so your OS warns once; the steps below say what to click. To check a
download, run `sha256sum -c SHA256SUMS --ignore-missing` next to the release's `SHA256SUMS` file, or
`gh attestation verify <file> -R visak13/eda-harness` to confirm that this repository's release workflow built it.

### Windows 10/11

**GUI**
1. Download `Heronry Desktop-<ver>.msi` from the [latest release](https://github.com/visak13/eda-harness/releases/latest).
2. Open it. SmartScreen shows "Windows protected your PC": click **More info → Run anyway**.
3. Finish the installer. It installs for you only (no admin) and puts `heronry` on your PATH.
4. Start **Heronry Desktop** from the Start menu. The setup wizard opens in its window.

**cmd** (PowerShell)
1. `irm https://github.com/visak13/eda-harness/releases/latest/download/install.ps1 | iex`
2. Open a new terminal, then run `heronry init`.
3. Run `heronry start`. Your browser opens the setup wizard.

### macOS (Apple Silicon and Intel)

**GUI**
1. Download `Heronry Desktop-<ver>.dmg` from the [latest release](https://github.com/visak13/eda-harness/releases/latest).
2. Open the DMG and drag **Heronry Desktop** to Applications.
3. Open it once. macOS says it cannot verify the developer: click **Done**.
4. Go to **System Settings → Privacy & Security**, scroll to Security and click **Open Anyway** (macOS 15 Sequoia removed the old Control-click → Open shortcut).
5. Open Heronry Desktop again and confirm **Open**. The setup wizard opens in its window.

**cmd** (Terminal)
1. `curl -LsSf https://github.com/visak13/eda-harness/releases/latest/download/install.sh | sh`
2. Open a new shell, then run `heronry init`.
3. Run `heronry start`. Your browser opens the setup wizard.

### Linux (Ubuntu 24.04+, Debian 13)

**GUI**
1. Download `heronry_<ver>-1~ubuntu-noble_amd64.deb` from the [latest release](https://github.com/visak13/eda-harness/releases/latest).
2. `sudo apt install ./heronry_*.deb` (apt pulls in the GTK, WebKit and AppIndicator packages).
3. Start **Heronry Desktop** from your app menu. The setup wizard opens in its window.

**cmd**
1. `curl -LsSf https://github.com/visak13/eda-harness/releases/latest/download/install.sh | sh`
2. Open a new shell, then run `heronry init`.
3. Run `heronry start`. Your browser opens the setup wizard.

On GNOME, the tray icon needs the AppIndicator extension. Without it, the window's menu and the CLI do the same things.

**Tested on.** CI builds and tests every release on Windows, macOS and Linux, but hands-on testing happens
on Windows. If something breaks on macOS or Linux, please [open an issue](https://github.com/visak13/eda-harness/issues);
fixes ship in a point release.

## First run

The first start opens a six-step setup wizard, in the desktop window or in your browser at
`http://127.0.0.1:9400/ui/setup`, signed in once by a one-time code. **Sign in** signs you in as the board's
owner. **Your tools** checks what Heronry needs on this machine (git, node, an agent CLI, the search
embedder) and installs anything missing with one click. **Harnesses** picks which agent CLIs run your seats.
**Remote access** optionally opens the board to your other machines over Tailscale, **First teammate**
invites a person, and **Done** takes you to the board. Later starts go straight to the board, already signed in.

## Choose your harnesses

A seat is a role card plus one set of board tools, so the model in the chair is your choice.
**Claude Code** (`claude`) and **OpenAI Codex CLI** (`codex`) are both optional, and at least one must be
selected; the wizard and `heronry init --harness claude,codex` refuse to finish with none. Seats then run
on the harnesses you picked. **Pi** seats run any provider or key you have, including local models; see
[the Pi guide](v8/guides/pi-seat.md). Heronry never updates your agent CLIs on its own: that stays your call.

> **Adversary risk notice.** The adversary seat runs one hostile review of an epic. With codex selected it
> runs on codex. Without codex it runs on **Fable** (`claude-fable-5-1`), whose safety safeguards are strict,
> so an adversarial or security review may be declined or softened. Review its findings before trusting
> a clean result. The wizard shows this notice once and records your acknowledgement.

## See it work

These stills come from the product video. Every frame is drawn in code in the Heronry palette with
invented demo data; none is a screenshot of anyone's machine.

**The pool spawns seats.** Every agent is a live shell with a role (claude, codex or pi), watched by the
pool: alive, parked, resuming.

![The pool spawns an architect, an engineer and a qa seat as live shells](docs/readme/storefront/still-1-pool.png)

**Context, engineered.** A seat boots from one bounded context pack, then reads only what changed since
its cursor. Recall brings back past decisions and lessons, and linked strategy docs layer the rules.

![A 40 KB context pack, a context delta and the layered strategy docs](docs/readme/storefront/still-2-context.png)

**The board walks the epic.** The board moves work on facts, not on anyone's memory. When every checker's
verdict passes, the epic is done automatically.

![An epic moving from drafted to done once all verdicts pass](docs/readme/storefront/still-3-board.png)

## Why this architecture

**1. Many humans and many agents, one channel.** No side chats, no lost context. Owner, architect,
engineers, reviewer and qa all speak on the same thread, and every message, decision, criterion and
piece of evidence lives on the board where anyone can read it later.

![Many humans and many agents on one channel](docs/readme/why/01-one-channel.png)

**2. Agents that keep working for weeks and months.** A seat is a terminal session; sessions crash,
hit limits, get closed. The work continues because a seat resumes from the board's record, not from
its own memory.

![Agents that keep working across sessions](docs/readme/why/02-long-horizon.png)

**3. A context layer that improves itself.** Instead of re-reading a thousand messages, a seat asks
one question and gets a small pack of the decisions, claims and lessons that matter. The board
measures how good those packs are with a fixed exam, and a tripwire watches for regressions every
time the records or the retrieval code change. Read more: [the memory layer](docs/readme/memory-layer.md)
and [self-improvement](docs/readme/self-improvement.md).

![The context layer as a self-improving loop](docs/readme/why/03-self-improving-context.png)

**4. Any provider can take a seat.** A seat is a role card plus one tool set. A seat runs on Claude Code,
OpenAI Codex or Pi, and the framework does not care which model sits in the chair. Read more:
[two harnesses](docs/readme/harnesses.md).

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

Seats are started, woken and closed for you; you work in the browser or the desktop window.

## Heronry Desktop

- **Tray / menu-bar icon:** Open board, Status, Start, Stop and Restart services, Check for update,
  *Stop services on quit*, Quit. Closing the window hides it; Quit leaves the services running unless that option
  is ticked. Each item runs the same `heronry` command you can type in a terminal.
- **Updates:** Heronry checks for a new release once a day. *Check for update* (or `heronry update --apply`) backs
  up your board, stops the services, installs the new release and starts it again.
- **Uninstall:** Settings → Apps (Windows), drag to Trash (macOS), `sudo apt remove heronry` (Linux).
  Your board data and settings are kept for a later install.
- **VS Code:** the Heronry extension warns when its version and the board's differ, and offers the one
  command that fixes it.

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

Controlled-folder protection (Windows Security's *Controlled folder access*, Bitdefender *Safe Files*) may
also block an unsigned app from writing to protected folders. Heronry writes only to its own data folder;
if you move that folder somewhere protected, allow `Heronry Desktop.exe` and `heronry.exe` there.

## Services

`heronry start` (or **Start** in the tray) runs four local services, a fifth when Slack is configured, and a
supervisor that restarts any that crash. They listen on `127.0.0.1` only, unless you turn on remote access.

| Service | Default port | What it does |
|---|---|---|
| board | 9400 | the web app (`/ui/`), the REST API and the database |
| mcp | 9402 | the board tools every seat calls |
| pool | 9301 | spawns, watches, parks and resumes the seat shells |
| broker | 9300 | delivers messages and wake-ups to seats |
| bridge | — | relays a Slack channel to the board; runs only when Slack is configured |

- `heronry status` prints one row per service (state, pid, port, uptime, last restart); `--json` for scripts.
- `heronry stop` stops everything and checks that nothing is left. It refuses while seats are live;
  `--force` takes them offline, `--keep-seats` leaves their shells running.
- `heronry restart <svc>` restarts one service through the supervisor.
- Ports taken? `heronry init --ports 9500` moves the whole block (board N, mcp N+2, pool N-99, broker N-100),
  or set one with `--board-port` and the like.

## Updates

Heronry updates itself from this repository's GitHub Releases, and only when you say so.

- The CLI checks once a day and prints a one-line notice when a release is out (`HERONRY_NO_UPDATE_CHECK=1`
  turns it off). `heronry update --check` reports the installed and latest versions.
- `heronry update` (or **Check for update**) downloads the release, verifies `SHA256SUMS`, checks your
  custom workflows against the new version, backs up the board, stops the services, upgrades and starts again.
  `--dry-run` stops after the download and checks.
- It refuses while seats are live, and when it cannot secure the installed version's wheels for a rollback.
  If the new version does not start, it reinstalls the previous one and restores the backup.
- The VS Code extension and your agent CLIs (claude, codex, pi) are not updated by Heronry. The extension
  offers its own one-line fix when its version differs from the board's.

## Troubleshooting

| Symptom | Try |
|---|---|
| The browser does not open, or `/ui/` does not load | `heronry status`; if the board is down, `heronry restart board`; then open `http://127.0.0.1:9400/ui/` |
| `heronry` is not found after install | open a new terminal: the installer changed your PATH |
| Seats spawn and die at once | the harness is not signed in on this machine: run `claude` (or `codex login`) once, then `heronry doctor` |
| A port is in use | `heronry doctor` checks the ports; move Heronry with `heronry init --ports <N>` |
| An update failed | the services are back on the previous version; `heronry doctor --bundle` writes a redacted zip for an issue |
| The antivirus removed the app | see **Antivirus** above |
| Anything else | `heronry doctor`, or `heronry doctor --agent "<what you see>"` to ask the Help seat, which proposes fixes you approve |

When you open an [issue](https://github.com/visak13/eda-harness/issues), attach the zip from
`heronry doctor --bundle`. It removes tokens, keys, email addresses, your username and user-profile paths.

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

## More

- **[Website](https://visak13.github.io/eda-harness/)**: the setup guide, concepts, the update model and the generated reference.
- **Docs in this repo:** [the memory layer](docs/readme/memory-layer.md), [self-improvement](docs/readme/self-improvement.md),
  [two harnesses](docs/readme/harnesses.md), [the Pi guide](v8/guides/pi-seat.md), and the
  [service map, Linux and public mode](v8/README.md).
- **[Changelog](CHANGELOG.md)** · **[Contributing](CONTRIBUTING.md)** (developing from source) · **[Licence](LICENSE)** (Apache-2.0) · **[Notice](NOTICE)**
- The product video is made with [Remotion](https://www.remotion.dev); its sources and credits are in
  [v8/docs/video](v8/docs/video/README.md).
