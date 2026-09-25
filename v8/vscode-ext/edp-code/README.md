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

Layout: `src/core` is pure (no `vscode` import) and holds all anchor/API/seat/git logic; `src/vscode` adapts
editor objects. The extension runs in the Node extension host (`extensionKind: ["workspace"]`).
