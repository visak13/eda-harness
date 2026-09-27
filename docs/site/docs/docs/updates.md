# Updates

Heronry has four layers, and each updates in its own way. The short version: Heronry updates
itself when you say so, and your agent CLIs are always your call.

| Layer | Who decides | How it updates |
|---|---|---|
| **The app** (board, pool, broker, MCP, web UI, desktop app) | Heronry, as a GitHub Release | You apply it from **Admin → Services**, the tray, or `heronry update` |
| **Seat harnesses** (claude, codex, pi) | You | Never automatic. **Update when idle** in **Admin → Integrations** |
| **VS Code extension** | Heronry, shipped with each release | The extension offers the matching version |
| **Libraries** (Python and npm) | Heronry | Pinned in each release; kept current upstream |

## The app

### Checking for a release

Heronry asks GitHub for the latest release at most once a day, and quietly on `heronry start`. The
check is silent when you are offline. To turn it off, set `HERONRY_NO_UPDATE_CHECK=1`.

When a newer release exists:

- **Admin → Services** shows "Version X is available", with a **Release notes** link and an
  **Apply** button.
- Heronry Desktop's tray or menu-bar icon has **Check for update**.
- `heronry update --check` prints the current and latest versions.

### What Apply does

**Apply** and `heronry update` run the same steps (so does **Check for update** in the desktop app,
once you confirm):

1. **Download and verify.** The release is downloaded and every file is checked against the
   release's `SHA256SUMS`. An older release is refused.
2. **Compatibility check.** Your custom workflows are checked against the new version (see below).
3. **Seats.** The update waits for live seats: it refuses while seats are live, so let them finish
   first. `--force` takes them offline instead.
4. **Back up.** The board database is backed up and its integrity checked. The last five backups
   are kept in the `backups` folder of your data folder.
5. **Stop.** The supervisor and every service stop.
6. **Install.** A detached helper, running outside Heronry's own environment, installs the new
   release, then starts the services and checks their health. Heronry runs this step apart because
   the running app holds its own files open.
7. **Migrate and restart.** The board applies its database migrations on start, and seats can
   respawn.

If the install or the start fails, the helper rolls back to the previous version and the database
backup.

Progress goes to the update log in your logs folder. `heronry status` shows the services when the
update is done.

!!! note "Desktop app"
    Where Heronry runs as the installed desktop bundle, it updates through its installer instead.
    **Check for update** offers to open the release page; download the new `.msi`, `.dmg` or `.deb`
    (see the [download page](../download.md)) and run it. Your board data and settings stay.

### `heronry update`

| Command | What it does |
|---|---|
| `heronry update` | Check, download, verify and install the latest release |
| `heronry update --check` | Only report the current and latest versions |
| `heronry update --dry-run` | Check, download and verify, then stop before changing anything |
| `heronry update --force` | Reinstall the same version, or update with live seats (takes them offline) |
| `heronry update --allow-downgrade` | Install an older release |
| `heronry update --skip-compat` | Skip the custom-workflow compatibility check |
| `heronry update --release-url URL` | Update from this release instead of the latest |

See the [CLI reference](../reference/cli.md) for every command.

## The custom-workflow compatibility check

A custom workflow you published in the [Design tab](design-tab.md) must still be valid on the new
version. Before anything changes, the update runs the new release's own check on a scratch copy of
your database: it applies the new migrations and validates every published custom workflow version
and every epic's pin to one.

- **All pass:** the update goes on.
- **Any fail:** the update stops with a report per workflow. Nothing has changed: your database,
  services and version are as before. Publish a fixed version of that workflow, then update again.
- **The check cannot run:** the update refuses. `--skip-compat` updates without it.

Drafts are not checked. You can run the same check yourself:

```sh
heronry workflows check --db <path-to-board-db> --json
```

It prints one row per workflow version, `{workflow, version, ok, errors}`. It exits 0 when all pass,
1 when any fails, and 2 on a usage error.

Running epics keep their pinned workflow version through an update.

## Seat harnesses are your call

Heronry never updates claude, codex or pi on its own, and seats never update themselves mid-run.

**Admin → Integrations → Seat harnesses** shows each harness: installed version, latest version,
whether it is signed in, and how many seats run on it.

**Update when idle** runs the vendor's own update command, but only while no seat of that harness is
live. Tick **wait for live seats to finish instead of refusing** to have it wait. Afterwards the
version is checked again and seats can respawn.

You can also update a harness yourself, the usual way for that tool. See
[Harnesses](../setup/harnesses.md).

## VS Code extension

The Heronry extension ships with each release, as a `.vsix` release asset. It reads the board's
version and warns when its own version differs. It then offers the one command that installs the
matching extension.

## Libraries

The Python and npm libraries are pinned by lock files, and a release ships exactly those versions.
Dependabot opens pull requests for new versions and security advisories, and CI tests them on
Windows, macOS and Linux before a release rebuilds from the locks.

## When an update fails

See [Troubleshooting](troubleshooting.md). For a report, attach the zip from
`heronry doctor --bundle` to a GitHub issue.
