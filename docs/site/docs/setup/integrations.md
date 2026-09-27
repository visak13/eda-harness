# Integrations

Integrations are optional extras once the board runs. Open **Admin → Integrations**. Each card
explains, top to bottom:

1. **What it does** for Heronry.
2. **What you need.**
3. **Where to get it.**
4. **Once connected**, what changes.
5. A status line: not set up, set up but not tested, connected (tested), or an error with its reason.

Most cards have a **Test** button. An action that needs another step first is disabled, and a line
next to it names that step.

## Seat harnesses

The programs that run Heronry's agents (seats): Claude Code, Codex and Pi.

- **You need** at least one installed on this computer and signed in with its own account (Claude,
  ChatGPT, or a provider key for Pi). Pick which ones in **Admin → Seats & models**.
- **The table** shows each harness's installed version, the latest version, whether it is signed in,
  and its live seats. **Test** probes every harness again.
- **Update when idle** runs the vendor's own update command, only while no seat of that harness is
  live. Heronry never updates claude, codex or pi on its own.

See [Harnesses](harnesses.md).

## VS Code

Work the board from VS Code: tickets, chat with seats and the diff of each seat's changes, beside your
code.

- **You need** VS Code on the teammate's computer, the Heronry VS Code extension (a `.vsix` from the
  latest release; see [Download](../download.md)), and that teammate's
  sign-in link.
- **The card** shows the **Board URL** and one **Sign-in** link per teammate. Invite teammates in
  **Admin → Teammates** first; see [Remote access](remote-access.md).
- **Once connected**, the teammate opens their link once and the extension talks to this board.

Inside VS Code you can tag a code selection to a person or seat (**EDP: Tag selection on board…**),
quote code or doc passages into a chat message, and use the **EDP Chat** panel.

!!! note "Version match"
    The extension checks the board's version. When they differ, it warns and offers the one command
    that installs the matching extension. See [Updates](../docs/updates.md).

## Slack

Pings people in Slack when the board needs them (a question, a sign-off, a blocked seat), with a link
back.

- **You need** a Slack workspace where you can add an app: an
  [incoming webhook](https://api.slack.com/messaging/webhooks) (one channel), a
  [bot token](https://api.slack.com/apps) (`xoxb-…`, for direct messages), or both.
- **Fields:** **Bot token**, **Default webhook** and **Board URL in messages**. Press **Save Slack**,
  then send a test to a person.
- **People the bridge pings** lists who gets pinged. Each person can also set their own Slack under
  **Settings → Slack**.
- **Once connected**, the bridge service posts pings within a minute.

## Plane

Mirrors the board's tickets into a [Plane](https://plane.so) project, so people who plan in Plane see
the same work.

- **You need** a Plane workspace (cloud or self-hosted), a project in it, and an API key
  (Plane → Profile settings → API tokens).
- Fill in the fields, press **Save Plane**, then **Test**.
- **Once connected**, new and changed tickets appear in the Plane project. The board restarts to turn
  the mirror on.

## code-server (the Code tab)

Puts a full VS Code in the browser under the **Code** tab, on the board's working tree.

- **You need** [code-server](https://coder.com/docs/code-server/install) installed on the board's
  computer.
- **The card** shows its port and **Test**. It is loopback only: never exposed on the tailnet. The
  Code tab embeds it through the board.
- **Once connected**, the Code tab opens the editor instead of explaining how to start it.

### Using the Code tab

- **Board computer only.** code-server has no password of its own (its terminal is a shell on your
  computer), so the tab works only in a browser on the board's computer. Other machines see "Code runs
  on the board host only".
- **The owner only.** The board signs your browser in to the editor with a one-time, 60-second code.
  Agent seats and other callers are refused. After the code service restarts, reload the tab.
- **Browsers:** Chrome, Edge and Firefox. In Firefox, VS Code's Markdown preview stays blank (an
  upstream code-server bug); the EDP Chat panel and doc reader work in both.
- **Shared tree.** Agent seats edit the same working copy you see. Expect files to change under you,
  and do not run `git clean`, `git stash`, `git reset --hard` or `git checkout -- <path>` there: they
  delete or revert the seats' uncommitted work. For your own copy, use a `git worktree`.
- **Extensions** come from Open VSX, so Microsoft-only extensions (Pylance, C/C++ tools, Live Share)
  are absent. Heronry pins replacements such as basedpyright and clangd.
- **Lost the menus?** The editor is in Zen mode. Press **Reset layout** in the Code tab's top strip,
  or `Ctrl+K Z` in the editor.
- **Guarded git.** Prefer **EDP: Checkout… (guarded)**, **EDP: Merge… (guarded)** and
  **EDP: Pull (guarded)**; they list live seats and dirty files before running git. VS Code's own
  Source Control panel is not guarded.

## Other connections

- **Remote access** and **teammates** have their own tabs; see [Remote access](remote-access.md).
- **Browser notifications** for questions and approval requests are a per-person setting in your own
  **Settings**.
- Every integration setting is also listed in the [settings reference](../reference/settings.md).
