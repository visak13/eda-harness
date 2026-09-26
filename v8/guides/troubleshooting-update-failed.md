# Troubleshooting: a failed update / compat check
<!-- roles: doctor -->

**Symptom.** `heronry update --apply` or Admin → Updates stopped with an error, or the services did not
come back after an update.

**Evidence.**
- `doctor_logs("update")`: the last update's log (`doctor_logs("update-run")` for an update started from Admin). It names the stage that failed: download and
  checksum, the compat check, "seats are live", stop, upgrade, or start.
- `doctor_health`: the installed version and whether the services are up.
- For a compat failure, `workflow_check(ref)` on each workflow the log names.

**Causes and fixes.**
- **Checksum or download failed.** Nothing changed. Retry later; if it repeats, the person reports it with
  `heronry doctor --bundle`.
- **Compat check failed.** A custom workflow does not validate against the new release, and nothing
  changed. `workflow_check` shows the problem. Suggest publishing a fixed version of that workflow, then
  updating. A workflow pin never changes: propose a fixed workflow version for new epics, or the gate or
  checker action that unblocks a stuck one.
- **Refused because seats are live.** Wait for the seats to finish, or the person reruns it with force,
  which takes them offline.
- **Stopped after the upgrade.** A service did not start: see `troubleshooting-service-down`, and propose
  `{kind: "service.start", service: "<name>"}`. The backup taken before the upgrade is named in the update
  log.

**Verify.** `doctor_health` shows the new version and every service running.
