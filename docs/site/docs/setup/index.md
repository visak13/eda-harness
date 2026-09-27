# Setup guide

This guide takes you from a fresh download to a working board with your first agent seats.
Each step has its own page. Do them in order; the later steps are optional.

## Before you start

Heronry runs on your own computer. It starts a few local services (the board, the broker, the pool,
the MCP server and the bridge) and your agent CLIs. You work with it in a browser tab or in the
**Heronry Desktop** window.

You need:

- Windows 10/11, macOS (Apple Silicon or Intel), or Linux (Ubuntu 24.04+, Debian 13).
- At least one agent CLI: **Claude Code** (`claude`) or **OpenAI Codex CLI** (`codex`), signed in
  with your own account. The installer can fetch them for you.
- `git` and `node`. The installer checks for these too and offers to install what is missing.

Docker is not needed. Every service runs as a local process.

## 1. Install: GUI or cmd

Pick one. Both install the same product, and each can do everything the other does.

| Way | What you get | Start with |
|---|---|---|
| **GUI** | The **Heronry Desktop** app (`.msi`, `.dmg` or `.deb`) with a tray or menu-bar icon. It also puts `heronry` on your PATH. | Open the app. The setup wizard opens in its window. |
| **cmd** | The `heronry` command-line tool, installed by a one-line script. | Run `heronry init`, then `heronry start`. Your browser opens the setup wizard. |

Download links and the per-OS steps (including what to click when your OS warns about an unsigned
app) are on the [Download page](../download.md).

!!! note "Your data survives reinstalls"
    Both ways keep your board data and settings in your user profile, not in the install folder.
    A reinstall, an update or an uninstall leaves them in place.

## 2. First run

The first start opens a six-step setup wizard: **Sign in**, **Your tools**, **Harnesses**,
**Remote access**, **First teammate** and **Done**. It signs you in as the board's owner, checks the
tools on your machine, and ends on the board.

Read [First run](first-run.md).

## 3. Choose your harnesses

A seat is a role card plus one set of board tools; the model in the chair is your choice. Pick
Claude Code, Codex, or both. Pi seats can add any model provider, including local models.

Read [Harnesses](harnesses.md). It also explains the adversary risk notice you see when Codex is
not selected.

## 4. Remote access and teammates (optional)

Out of the box only your computer can open the board. To reach it from your phone or laptop, or to
invite teammates, turn on remote access over Tailscale.

Read [Remote access](remote-access.md).

## 5. Integrations (optional)

Connect Slack pings, the VS Code extension, the in-browser Code tab and a Plane mirror.

Read [Integrations](integrations.md).

## After setup

- Start your first epic from the **Epics** page with **New epic**. See [Concepts](../docs/concepts.md)
  for what happens next.
- Change how epics run in the [Design tab](../docs/design-tab.md).
- Learn how the app and your agent CLIs are kept current in [Updates](../docs/updates.md).
- If something does not work, see [Troubleshooting](../docs/troubleshooting.md) or run
  `heronry doctor`.
- Every command is listed in the [CLI reference](../reference/cli.md), and every setting in the
  [settings reference](../reference/settings.md).

## Quick command summary

```sh
heronry init        # first-time setup: folders, config, tokens, agent home, harnesses
heronry start       # start the services and the supervisor
heronry status      # one row per service: state, pid, port, url, uptime
heronry doctor      # check prerequisites, harnesses, ports and secrets
heronry stop        # stop the services
```
