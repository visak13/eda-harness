# Code tab FAQ

The Code tab (`/ui/code`) is a full VS Code (code-server 4.138, native Windows) running on the board
host as the `code` service on `127.0.0.1:9410`, embedded in the board. This page answers what it is
safe to do there. It grows over time (design-449b628cdd §4).

## Starting it and where it works

- **Start / stop:** `.\edp.ps1 start code` and `.\edp.ps1 stop code` from the repo root. `code` is
  started by name only; `.\edp.ps1 start all` never starts it. If the tab says "Code service is not
  running", run the start command and press Retry.
- **Board host only.** code-server listens on loopback with no password (a terminal is a shell on the
  host), so the tab works only in a browser on the board host. A browser on another machine sees
  "Code runs on the board host only" and nothing is exposed.
- **The owner only.** A guard on :9410 relays only for a browser holding its sign-in cookie. The tab
  gets that cookie through a one-time, 60-second sign-in the board issues to its human owner alone,
  and the cookie lasts until the code service restarts or the browser closes. Agent seats and other callers get 401 from
  :9410 and "The board did not open a code session" in the tab. After `.\edp.ps1 restart code`,
  reload the tab to sign in again. A bare `http://127.0.0.1:9410/` bookmark answers 401 until the
  tab has signed that browser in.
- **Chromium only** (Chrome, Edge). Firefox cannot load webviews (Markdown preview, extension panels)
  from code-server: upstream bug coder/code-server#7913.
- **Deep links:** `/ui/code?folder=<abs>&file=<rel>&line=<n>` or `line=<n>-<m>` opens a folder and
  puts the cursor on line `n` (code-server reveals the start line; the range is shown in the header).
  The "Open in Code" button on a code card uses this.
- **Open in new window** in the header opens the same editor in its own browser tab, with more room
  and native keyboard shortcuts such as Ctrl-W.

## The shared tree and live seats

The `v8` folder the tab opens by default is the **shared tree**: every agent seat on this host edits
the same working copy at the same time. Anything you save is visible to them at once, and anything
they save appears in your editor.

- Edit freely, but expect files to change under you; the editor reloads unmodified files on its own.
- Do not run `git clean`, `git stash`, `git checkout -- <path>` or `git reset --hard` on the shared
  tree: they delete or revert other seats' uncommitted work.
- Commit by path (`git commit -m "…" -- <your files>`), never `git add -A`, so you never sweep a
  seat's staged hunks into your commit.
- The EDP extension's status-bar badge shows `<branch> · N seats live` when the open folder is a shared
  tree; click it to see which seats and tickets are live.

## Git worktree: your own copy

To work without racing the seats, use a **git worktree**: a second checkout of the same repo in its
own folder, on its own branch.

```powershell
git worktree add ..\eda-base3-mine -b my-branch
```

Then open it in the tab: `/ui/code?folder=C:\Projects\Learning\eda-base3-mine`. Branch switches,
merges and resets there touch only your copy. Merge back when ready, and remove the worktree with
`git worktree remove ..\eda-base3-mine`.

## Why there is no Pylance or C/C++ (cpptools)

code-server installs extensions from **Open VSX**, not the Microsoft Marketplace; Microsoft's terms
limit the Marketplace and its closed extensions to Microsoft's own products. So Pylance, cpptools,
Live Share and the Remote-* extensions are absent by design.

What we use instead (pinned in `v8/vscode-ext/extensions.txt`, installed on service start, never
auto-updated):

| Missing | Replacement |
|---|---|
| Pylance | **basedpyright** (types, hover, go-to-definition into site-packages, rename) with ms-python.python |
| cpptools | **clangd** (needs a `compile_commands.json` for the project) |
| Live Share | the board: tag a selection to a person or seat (below) |

Other pinned extensions: ESLint, GitLens (commit and ticket links in blame hovers), Playwright Test,
PowerShell. Adding one is a commit to `extensions.txt` with its exact version.

## How tagging works

Select code, then right-click **EDP: Tag selection on board…** (or `Ctrl+Alt+M`). Where the tag goes
depends on the EDP Chat panel (edp-code 0.12.0):

- **The chat panel has been opened in this window and a thread is open:** the panel is revealed and the
  lines become a **code chip** above its composer (path, lines, commit). Type your text and press
  `Ctrl+Enter`: one message with the code anchor. The chip and a Reply target can go in the same message.
- **The chat panel is open but no thread is picked:** the thread picker opens first, then the chip lands.
- **The chat panel has never been opened in this window:** the palette chain:
  1. The first use asks for your board participant id and token. They are kept in the browser's
     secret storage, not in settings; sign in once per browser profile.
  2. Pick the **person**: any human or a live agent seat.
  3. Pick the **ticket**: that person's open tickets first, or any open ticket.
  4. Type the **note** and pick the kind: question (default), steer, finding or note.

The board message carries a code anchor: repo, path, lines, commit (or none outside git), whether the
file was dirty, and the snippet. The recipient is woken like any board message; an agent reads the
anchor in its context. On the ticket page the message shows as a code card with **Open in Code**,
which reopens those lines here. Tagging never creates tickets.

## Quote + note: collect passages, send one message

A message can carry several **quotes**, each with its own note: lines of code, a passage of a board
doc (the EDP reader, its markdown source or a version diff) and a passage of a chat message. They go
to the thread open in the EDP Chat panel, in the order you arrange, and the board checks each one
against its source when you send.

- **Code, a doc's markdown source or a diff side: the inline comment box.** Select lines and press
  `Ctrl+Alt+Q` (or right-click **EDP: Comment for chat (quote + note)**). A comment box opens under
  the lines: type a note (optional) and click **Add to chat** (**Cancel** drops it). The lines keep a
  small **EDP draft** comment marker until the message is sent; its **×** removes the draft.
- **The EDP reader:** select a passage and click **❝ Quote in chat** by the selection (or
  `Ctrl+Alt+Q`, or right-click **EDP: Quote in chat**). Type a note and click **Add to chat** (or
  `Ctrl+Enter`); `Escape` cancels. The quoted blocks stay marked in the reader until the send.
- **A chat message:** select part of a message and click **❝ Quote** (or `Ctrl+Alt+Q`), add a note,
  then **Add to chat** or `Ctrl+Enter`.
- **The draft tray:** the quotes wait as chips above the chat composer, one per quote, showing the
  source, the passage and an editable note. **↑**/**↓** reorder them and **×** removes one. While the
  chat panel is hidden the status bar shows **EDP draft: N → <thread>**; click it to show the chat.
  The drafts survive a reload of the window.
- **Mentions and paths in notes:** every note box (the comment box, the reader and message popovers, the
  chip notes) completes `@` (board people and live seats) and `#` (files and folders of the workspace)
  as the composer does.
- **Send:** press `Ctrl+Enter` in the composer (the text is optional when quotes are attached). The
  message carries every chip in order, together with any code chip, attachments or Reply target.
  If the board refuses one quote (its source changed), that chip is marked and nothing is sent;
  remove it or quote again.
- **Reading:** each quote shows as a card above the message text, here and on the board's ticket
  page. The card's source link opens the doc version on those lines, the code range, or the quoted
  message.

`Ctrl+Alt+Q` acts only while a passage is selected in a code editor, the reader or a chat message,
never while you are typing in a text field, so on keyboards where `AltGr` types a character with `Q`
(for example `@` on German layouts) typing is unaffected. The board UI uses the same `Ctrl+Alt+Q`
to open its Quote popover. `Ctrl+Shift+Q` is not used: it quits Firefox.

## The built-in git UI is not guarded

The Source Control panel (commit, checkout, pull, merge, discard) is VS Code's own, and VS Code has no
way for an extension to veto it. It runs your system `git` with your own SSH keys and credentials, at
your own risk (owner ruling m-558038e702).

- A branch switch, pull or discard in the Source Control panel on the shared tree changes files under
  every live seat immediately.
- Prefer the guarded commands: **EDP: Checkout… (guarded)**, **EDP: Merge… (guarded)** and
  **EDP: Pull (guarded)**. They list the live seats and the dirty paths and ask before running git.
- Or use a worktree (above) and nothing is shared.

## Terminals

The integrated terminal is Windows PowerShell 5.1 by default (cmd and Git Bash are in the profile
list). It is a shell on the board host, started without the fleet's `EDP_*`/`EDP8_*` variables, so a
test run does not inherit the fleet's configuration or tokens through those variables. It still runs
as your OS user and can access files that user can read. **EDP: Open external terminal here** opens a normal
console window in the folder instead.
