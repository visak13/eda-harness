# Runbook: cut this host over from the source checkout to the installed Heronry

The dogfood cutover (design-e963c656f5 §4.13, story S9). Until now the fleet has run from the source checkout:
`EDP_HOME=<repo>/v8`, services through `edp.ps1`, and state in `v8/.data`. After the cutover the fleet runs the
installed release (`heronry`, 0.9.0 or later) on the same board state. The source checkout stays untouched, and
rolling back means starting it again.

**Rehearse it first on a copy** (step 0). The rehearsal is `v8/scripts/drill_cutover_copy.ps1`. It passed on
2026-09-27, and its transcript is the S9 evidence.

## 0. Rehearse on a copy (no downtime)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File v8\scripts\drill_cutover_copy.ps1 [-Keep] [-Shots <dir>]
```

The drill touches neither the live fleet nor the checkout's state:

1. **Copy the state.** It copies the v8 state into `%TEMP%\heronry-cutover-*`. The DB goes by SQLite online backup
   from a read-only connection, and the rest by robocopy.
   - `pool-state.json` is left out: its rows hold the live fleet's pids.
   - `slack_map.json` is left out: the bridge would relay the live channel.
2. **Build the wheels.** It builds the four wheels offline from `git archive HEAD`. The SPA is built privately into
   the archive; the shared `webapp/dist` is never used or rebuilt.
3. **Install privately.** It installs them into a private venv with a private `EDP_HOME` and spare ports.
   - `EDP*`, `SLACK*` and `UV_*` variables are scrubbed.
   - Host, public URL, RSI and the resume watchdog are pinned in env, which beats the imported config.
   - Seats would run a stub harness.
4. **Walk the procedure and check it.** It runs `heronry init`, `heronry import --from <copy>` as a dry run and then
   with `--apply`, `heronry start`, and `heronry stop`. It checks:
   - the row counts match the copy;
   - every service is up;
   - `/v1/health` reports 0.9.0 and `/ui` serves the SPA;
   - an imported owner token signs in;
   - nothing is left running and every port is free;
   - the copy is unchanged (file manifest compared before and after).

On a host where uv cannot reach the network, the drill installs the dependencies from a wheelhouse repacked from the
checkout's own venvs (`v8/scripts/repack_wheelhouse.py`).

## 1. Before the window

| Check | How |
|---|---|
| The release is available | a published GitHub release `v0.9.0` (install.ps1 fetches it), or a local folder with the four wheels and `SHA256SUMS` for `-ReleaseUrl` |
| Disk | free space of at least twice `v8/.data` (the import copies it; this host: about 3.5 GB) |
| Nobody is mid-story | every seat has handed off. Close or reap the seats (Seats page, or the architect). The pool state then holds no live or parked rows for the new install to resume |
| The owner is present | the cutover stops the board for a few minutes, and the owner signs in again afterwards |

## 2. Stop the old fleet (the window starts)

From the repo root:

```powershell
.\edp.ps1 stop all          # add -Force only once every seat is closed
.\edp.ps1 stop code         # code-server, if it was running
.\edp.ps1 status            # every service down
Get-NetTCPConnection -State Listen -LocalPort 9400,9402,9300,9301,9410 -ErrorAction SilentlyContinue   # prints nothing
```

Never kill services by image name (`taskkill /IM`), because other processes share those images.

## 3. Install the release

```powershell
irm https://github.com/visak13/eda-harness/releases/download/v0.9.0/install.ps1 | iex
# or, offline:  .\install.ps1 -ReleaseUrl <folder with the wheels and SHA256SUMS>
```

Open a new terminal, then run `heronry version`. It should print `Heronry 0.9.0`.

Run `heronry` from a terminal that does **not** set `EDP_HOME` (the checkout's `start.ps1` sets it). With
`EDP_HOME` pointing at the checkout, `heronry` runs in dev mode, and `import` refuses.

## 4. Initialise, then import (dry run first)

```powershell
heronry init --harness claude,codex --owner owner --yes
heronry import --from C:\path\to\repo\v8                 # dry run: prints what goes where, writes nothing
```

Read the dry-run report before applying:

- **The DB line** shows the epic, ticket and participant counts, which should match the old board. The copy
  uses SQLite's backup API.
- **Everything else in `.data`** is listed: uploads, broker data, pool state and the rest. Logs, pids, locks and
  SQLite side files are not copied.
- **Secrets:** `tokens.json` and `human-tokens.txt` go to the private secrets folder.
- **Settings files:** `models.json`, `ui-settings.json`, `ui-avatars.json` and `slack_map.json` go to their
  settings paths.
- **`.env` → `config.toml`:** on this host these carry `board.host`, `network.public_url` (the tailnet URL),
  `pool.codex_by_model` and `rsi.enabled`. The admin token goes to its private file, never to config.toml.
  Anything skipped is listed with the reason.

Then apply:

```powershell
heronry import --from C:\path\to\repo\v8 --apply         # refuses while this install's board is running
```

It ends with `imported: {epics, tickets, participants}` and `The source was not modified`.

## 5. Start and verify

```powershell
heronry start
heronry status          # board, broker, pool and mcp up, rev v0.9.0 (bridge up only with a Slack map)
heronry doctor          # harnesses, ports, secrets, claude folder trust for the new agent home
```

- **Board version:** `http://127.0.0.1:9400/v1/health` reports `"version": "0.9.0"` and the new `home`.
- **Sign in:** the owner's old sign-in still works, because the tokens were imported.
  - The first start after an import prints a one-time `/ui/setup?code=…` link. The wizard's "done" marker is not
    part of the old checkout, so finish the wizard once.
  - The link signs in the init human (`--owner owner`, the same handle as the fleet owner).
- **Board content:** epics, tickets and threads are all present.
- **Remote access:** Tailscale serve still points at port 9400, so the tailnet URL works unchanged.
- **Seats:** spawn one seat and check that it boots.
  - Installed seats read their role cards from the installed agent home, not from `v8/.claude`.
  - `heronry doctor` reports whether claude trusts that folder.
- **VS Code:** the extension's version prompt offers `edp-code-0.9.0.vsix` from the release.

## 6. Roll back (if anything above fails)

```powershell
heronry stop
.\edp.ps1 start all     # from the repo root: the old checkout on its untouched v8/.data
```

The old checkout never lost anything, because the import only read it. Board activity after the cutover exists only
in the installed home. To keep that activity, stay on the installed release and fix forward; a later
`heronry import` is one way only.

## 7. After a clean week

- Stop using `edp.ps1` and `start.ps1` for the fleet. `heronry start|stop|restart|status|update` replaces them.
- Updates come through `heronry update`: backup, then stop, upgrade and start, with automatic rollback.
- Keep `v8/.data` until the owner decides to archive it.
