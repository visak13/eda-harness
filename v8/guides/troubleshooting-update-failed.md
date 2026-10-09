# Troubleshooting: a failed update / compat check
<!-- roles: doctor -->

**Symptom.** `heronry update` or Admin → Updates or the tray's Install update stopped with an error, reported
"Rolled back" or "Failed", or the services did not come back after an update.

**Evidence.**
- The outcome, in plain words: the tray shows it once ("Updated to X", "Rolled back to X: <reason>" or "Failed:
  <reason> - <how to recover>"). The same record is `update-result.json` (`<home>/update/` for the desktop
  installer, the run folder for a `uv tool` install) and a board event from the updater.
- `doctor_logs("update")`: the last update's log (`doctor_logs("update-run")` for an update started from Admin). It
  names the stage that failed: download and checksum, the compat check, stop, install, health check, or rollback.
  The installer's own logs (`msiexec-*.log`) sit beside it.
- `doctor_health`: the installed version and whether the services are up.
- For a compat failure, `workflow_check(ref)` on each workflow the log names.

**Causes and fixes.**
- **Checksum or download failed.** Nothing changed. Retry later; if it repeats, the person reports it with
  `heronry doctor --bundle`.
- **Compat check failed.** A custom workflow does not validate against the new release, and nothing
  changed. `workflow_check` shows the problem. Suggest publishing a fixed version of that workflow, then
  updating. A workflow pin never changes: propose a fixed workflow version for new epics, or the gate or
  checker action that unblocks a stuck one.
- **Refused: the pool cannot say which seats are live.** Live seats are not a reason to wait: the update parks them
  and the pool resumes them afterwards. Start the pool (`heronry start pool`) and retry, or rerun with `--force`.
- **Refused: Windows Installer is busy, or an update is already staged.** Another installation or an earlier update is
  running. Wait a minute; a staged update with no outcome after an hour stops counting.
- **Rolled back.** The new version did not install or did not come up healthy, and the previous one was put back with
  the database backup. Nothing is lost: the reason is in the message. Fix that (a file held open by another
  program, a full disk) and update again.
- **Failed, "the previous version did not come back".** The rollback itself could not finish. The desktop (MSI)
  install: reinstall the previous version from its cached installer,
  `msiexec /i "<data>/updates/<old version>/<installer>.msi" MSIINSTALLPERUSER=1`, then `heronry start`. A
  `uv tool` install: `heronry update --release-url <the old release> --allow-downgrade --force`, or run the
  install script again. The database backup is in `<data>/backups/`.
- **Manual recovery, when nothing else works.** Download the installer of the last version that worked from the
  releases page and run it (it replaces the broken one in place, and your board data and settings stay), then
  `heronry start`. If the database is damaged, stop the services and copy the newest `edp8-<version>-<time>.db`
  from `<data>/backups/` over the board database.
- **Stopped after the upgrade.** A service did not start: see `troubleshooting-service-down`, and propose
  `{kind: "service.start", service: "<name>"}`. The backup taken before the upgrade is named in the update
  log.

**Verify.** `doctor_health` shows the new version (or the one rolled back to) and every service running; the parked
seats are working again.
