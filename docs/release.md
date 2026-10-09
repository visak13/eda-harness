# Cutting a release

`scripts/build_release.ps1` is the only release build. It replaces the hand-made `heronry-rc\<version>\build-<version>.bat`
files: do not write another one.

```powershell
powershell -NoProfile -File scripts\build_release.ps1 -Version 0.10.3 -Ref <commit> -Out <release-dir>\0.10.3
```

| Parameter | Meaning |
|---|---|
| `-Version X.Y.Z` | the version every package, the board and the MSI must carry |
| `-Ref` | the commit to build (a sha, branch or tag); the resolved sha is printed and logged |
| `-Out` | a new or empty folder; the script refuses a folder with files in it |
| `-BuildEnv` | optional: an existing venv holding briefcase 0.4.5 and pip, passed to the MSI build |
| `-CheckOnly` | stop after the version check on the clean worktree: no web build, no wheels, no MSI |
| `-KeepWorktree` | keep `<Out>\work` for inspection (otherwise it is removed) |

## What it does

1. Resolves `-Ref` and creates a **clean worktree** of that commit under `<Out>\work` (`git worktree add --detach`), so no
   untracked or modified file reaches the build. The live board's variables (`EDP8_BOARD_URL`, `EDP8_TOKEN`,
   `EDP8_MCP_URL`, `EDP8_RUN_DIR`, `EDP_HOME`) are cleared for the build.
2. Fails unless `edp-contracts`, `edp-pool`, `edp-broker`, the board (`edp8`) and the desktop app all carry `-Version`
   (each `pyproject.toml` version and each `__version__`).
3. Builds the SPA (`npm ci`, `npm run build`, into the worktree's own dist, never the shared one), the four wheels
   (`uv build --offline --wheel`) and the MSI (`v8\desktop\scripts\build_windows.ps1 -Fresh`).
4. Copies the MSI, the wheels and `scripts\install-heronry.cmd` (the by-hand installer, with CRLF line ends) to
   `<Out>\release`, then fails unless every wheel's file name and its `__version__`,
   the board's included, and the MSI's `ProductVersion` equal `-Version`.
5. Writes `<Out>\release\SHA256SUMS` (lowercase hex, two spaces, one file per line) and prints every sha256.

The log is `<Out>\build-release.log`. The script builds only: it installs nothing, starts nothing and never touches a
running Heronry. Run it as one visible call (a build outlives the tool timeout, so a seat asks the owner or the
architect to run it).

## After the build

Publish `<Out>\release` as the GitHub release assets (the MSI, the wheels, `install-heronry.cmd`, `SHA256SUMS`); `heronry update` and
`install.ps1`/`install.sh` verify every file against `SHA256SUMS` before they install anything.
