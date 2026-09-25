# EDP (edp-code)

The EDP extension for the Code tab's code-server (design-449b628cdd §4, epic-91fcd3b370 S5).

| Command | What it does |
|---|---|
| `EDP: Sign in to board` / `Sign out of board` | Participant id + token, checked against the board, kept in VS Code secret storage only (per browser profile on code-server). |
| `EDP: Tag selection on board…` (`Ctrl+Alt+M`, editor context menu) | Person (humans + live agent seats) → ticket (theirs first, then any open) → note → kind → a board message with `code_context` (path, lines, HEAD, dirty, snippet). |
| Status bar `⎇ <branch> · N seats live` | Shown on the fleet's shared tree: the repo whose root is, or contains, a path in `edp.sharedTreePaths` (default the v8 root the service runs for, so the eda-base3 repo); alive agent sessions on this board; click for the list. |
| `EDP: Checkout… / Merge… / Pull (guarded)` | A modal listing live seats and `git status --porcelain` paths, then system git. The built-in Source Control view is NOT guarded and cannot be vetoed. |
| `EDP: Open external terminal here` | Launches `edp.externalTerminal` (pwsh / cmd / git-bash, a real `.exe`) detached in the folder. |

Settings: `edp.boardUrl` (default `http://127.0.0.1:9400`; creds go only to loopback or https), `edp.sharedTreePaths`, `edp.externalTerminal`
(default Windows PowerShell 5.1 by absolute path; pwsh 7 is not installed on this host). All three are **machine-scoped**:
in code-server set them in `<user-data>/Machine/settings.json` (Settings → "Remote" tab). A machine setting in
`User/settings.json` is not reliably applied in a remote window (measured in the S5 smoke: the badge and board URL fell back to
the defaults).

The external terminal is started with `cmd.exe /d /c start "" /D "<folder>" "<exe>"`, so it gets a console of its own (a shell
spawned directly with no stdio reads NUL and exits at once). A folder or exe path holding a cmd metacharacter
(`" % ^ & | < > !`) is refused rather than escaped.

## Build, test, install

```powershell
cd v8\vscode-ext\edp-code
npm ci
npm test            # vitest over src/core, no VS Code download
npm run package     # tsc + esbuild -> dist/extension.js -> edp-code.vsix (here, where S2's hook looks)
```

`scripts\start-code.ps1` (the `code` service) installs the newest `*.vsix` in this folder into the service's own
extensions dir on every start; restarting the service (`.\edp.ps1 restart code`, an owner action) or
"Developer: Reload Window" after it picks up a new build. Bump `version` in package.json with each rebuild.

## Install on a teammate machine (desktop VS Code)

For a teammate who works in their own desktop VS Code on their own clone, not in this host's Code tab
(code-server :9410 stays loopback-only). Board side (tailnet access, participant, token) is the owner's
runbook: `guides/tailnet-public-mode.md` §5 "Add a teammate".

1. **Get the vsix.** Download the `edp-code-<version>.vsix` artifact from the board (story
   s-6a52d6545a, or the newest one on the epic), or build it from a clone with `npm ci; npm run package` here.
2. **Install it.** VS Code 1.138 or newer (`engines.vscode`). Extensions view → `…` → **Install from VSIX…**,
   or from a terminal: `code --install-extension edp-code-<version>.vsix --force`. It needs the built-in Git
   extension (enabled by default). Remove it with `code --uninstall-extension edp.edp-code`.
3. **Open your clone of the repo** as the workspace folder (File → Open Folder…, the folder that holds `.git`).
   Code cards and change cards resolve by the repo-relative path inside *this* clone; the host's absolute
   path in a card is never used. A card for a commit you have not pulled yet says
   **"… is not in this clone; pull to see this change."** — pull, then click again.
4. **Point it at the board.** *Available after the tailnet switch* (public mode is not live yet; the
   owner turns it on): install Tailscale, sign in to the tailnet you were invited to, then in
   **Settings → User** set **`edp.boardUrl`** to `https://msi.tail884b19.ts.net`. In `settings.json`:
   ```json
   "edp.boardUrl": "https://msi.tail884b19.ts.net"
   ```
   **The token rule:** the extension sends your participant id and token only to a loopback URL
   (`http://127.0.0.1…`, `localhost`, `[::1]`) or an `https://` URL; any other URL — e.g.
   `http://msi:9400` or `http://100.x.y.z:9400` — is refused before a request is made
   (`unsafeBoardUrl` in `src/core/api.ts`). Redirects are not followed, so the token never leaves that origin.
5. **Sign in.** Command palette → **EDP: Sign in to board** → your participant id (e.g. `ravi`), then the
   token the owner sent you privately. Both are checked against the board and kept only in VS Code's
   SecretStorage (never in settings or logs). **EDP: Sign out of board** removes them.
6. **Open the chat.** **EDP: Open chat** (the chat view sits in the secondary side bar, right of the editor;
   **View → Appearance → Secondary Side Bar** if it is hidden) → **EDP: Chat: open a ticket or epic thread…**.

Differences from the host's Code tab: the `⎇ … seats live` badge and the guarded git commands name
the fleet's shared tree (`edp.sharedTreePaths`), which is not on your machine, so the badge stays hidden
unless you list your clone there; the "Uncommitted changes" card shows *your* clone's uncommitted edits.

## Install on the host's Code tab (:9410)

`scripts\start-code.ps1` reinstalls the newest vsix here on every service start. To replace the
installed build in place without restarting code-server (then **Developer: Reload Window** in the tab),
from `v8\`:

```powershell
# the service's own dirs (start-code.ps1: $serverDir, $node, $userDir, $extDir); never the default code-server dirs
$srv = ".tools\code-server\4.138.0\code-server-4.138.0-windows-amd64"   # vscode-ext\code-server.lock.json
$env:EXTENSIONS_GALLERY = "{}"                                           # no gallery fetches on a CLI install
& "$srv\lib\node.exe" $srv --user-data-dir .data\code\user --extensions-dir .data\code\extensions --install-extension vscode-ext\edp-code\edp-code.vsix --force
& "$srv\lib\node.exe" $srv --user-data-dir .data\code\user --extensions-dir .data\code\extensions --list-extensions --show-versions   # edp.edp-code@<version>
# uninstall: & "$srv\lib\node.exe" $srv --user-data-dir .data\code\user --extensions-dir .data\code\extensions --uninstall-extension edp.edp-code
```

Layout: `src/core` is pure (no `vscode` import) and holds all anchor/API/seat/git logic; `src/vscode` adapts
editor objects. The extension runs in the Node extension host (`extensionKind: ["workspace"]`).
