# edp-chat-spike (C1, s-a8f1b90d2f): throwaway

Measures, on the live code-server :9410, what the EDP chat (C3) depends on. Not the chat.
Report: the C1 report doc on s-a8f1b90d2f. Evidence: `v8/.data/code/spike/c1/` (logs, screenshots) and the host log `v8/.data/code/spike/c1-probe.log`.

- View: `viewsContainers.secondarySidebar` → one `webviewView`, CSP `default-src 'none'` + nonce; assets either via `asWebviewUri` (default) or inlined (`EDP: Spike: assets inline`), `…padded` inlines N KB to probe a size ceiling.
- `EDP: Spike: open WebviewPanel beside`: the fallback placement.
- `EDP: Spike: feed probe`: `GET /v1/feed?watch=true` from the Node host (participant + optional token in input boxes, memory only, never logged); matching `message_sent` events for `edpSpike.ticket` are pushed to the view.
- `EDP: Spike: diff probe` / `changes probe`: `vscode.diff` / `vscode.changes` on `git:` URIs (`toGitUri`) for `edpSpike.commit`.

Build (reuses edp-code's devDependencies): `node esbuild.mjs && ../edp-code/node_modules/.bin/vsce package --no-dependencies --allow-missing-repository --skip-license -o edp-chat-spike.vsix`.
Install on the live service: add `"edp.edp-chat-spike": true` to `extensions.allowed` in `v8/.data/code/user/User/settings.json` (start-code.ps1 rewrites it on restart), then the code-server CLI `--install-extension` with the service's `--user-data-dir`/`--extensions-dir`. Remove: `--uninstall-extension edp.edp-chat-spike`.

Re-run the measurements: `node measure/c1-measure.cjs <chromium|firefox|stockff> <outdir> view,inline,panel,reload,feed,diff,changes,pad`
and `node measure/c1-spa.cjs <chromium|stockff> <outdir>` (`stockff` = the installed Firefox via Playwright's `moz-firefox` BiDi channel, temp profile).
