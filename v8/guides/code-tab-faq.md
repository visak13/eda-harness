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

Select code, then right-click **EDP: Tag selection on board…** (or `Ctrl+Alt+M`):

1. The first use asks for your board participant id and token. They are kept in the browser's
   secret storage, not in settings; sign in once per browser profile.
2. Pick the **person**: any human or a live agent seat.
3. Pick the **ticket**: that person's open tickets first, or any open ticket.
4. Type the **note** and pick the kind: question (default), steer, finding or note.

The board message carries a code anchor: repo, path, lines, commit (or none outside git), whether the
file was dirty, and the snippet. The recipient is woken like any board message; an agent reads the
anchor in its context. On the ticket page the message shows as a code card with **Open in Code**,
which reopens those lines here. Tagging never creates tickets.

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
test run in it cannot touch the fleet's tokens. **EDP: Open external terminal here** opens a normal
console window in the folder instead.
