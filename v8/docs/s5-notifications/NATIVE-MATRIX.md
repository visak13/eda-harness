# Integrated S5 native acceptance — NOT YET EXECUTED

This is the QA/owner procedure, not a passed test report. S0's stock-Firefox single click is feasibility only. Chromium `s5-notifications.spec.ts` simulates display/click/focus to exercise feed/worker/IDB/router/drafts; it proves **no native focus behavior**. Native permission/focus/profile limits require the actual owner Windows/stock Firefox profile. Obtain new explicit consent through the architect before opening a browser, requesting permission, or changing site settings. S0 consent does not transfer.

## Safe disposable integrated board

From `v8` after a build, using the existing interpreter (no uv resync):

```powershell
npm --prefix web run build
.venv/Scripts/python.exe docs/s5-notifications/native_harness.py serve --port 19485 --manifest "$env:TEMP/s5-native-local.json"
```

This foreground process prints origin, epic and owned PID. It uses a temporary home/DB, trusted **synthetic** owner/other identities, disables fleet broker publication, binds loopback only and never opens a browser. Stop with Ctrl-C in this console only. Shared ports are refused. No production messages, credentials, token URLs, user CLI configuration or live DB changes.

After consent, manually visit the printed origin + `/ui/epic/<epic>?as=owner`. This is a **new origin** unless the owner explicitly selects it. Record it exactly: localhost and 127.0.0.1, ports, Firefox containers and profiles do not share permission/clients. A fixture-origin pass does not assert deployment-origin permission. Record Windows build, Firefox stock version, profile/container (non-sensitive alias), canonical scheme/host/port, board commit and display scaling; verify desired deployment origin separately with owner-authorized rollout. Never silently substitute headless/patched Firefox or Chromium.

Expand Notifications. Confirm no prompt before clicking Enable. Click Enable and approve only this origin. Wait for `Notifications enabled while a board tab stays open`. Existing backlog must not notify. Send test notification checks permission/display but **does not count** as an exact-request trial.

From a second console (one emission per trial, after baseline):

```powershell
.venv/Scripts/python.exe docs/s5-notifications/native_harness.py emit --manifest "$env:TEMP/s5-native-local.json"
# Genuine integrated design approval request, source/viewer path:
.venv/Scripts/python.exe docs/s5-notifications/native_harness.py emit --approval --manifest "$env:TEMP/s5-native-local.json"
```

Normal production `/v1/messages`, gate, document, ticket APIs emit the requests. The toast must say only `Board needs your attention` / generic body, never synthetic question text/title. Click the actual Windows toast with the mouse — no JS notificationclick/worker dispatch, focus stubs or simulated route helper. Expected route is `/ui/epic/<source>?request=<event>` and message hash `#m-…` for questions. Approval opens the relevant design viewer with exact source/request. Record request id from route, not a guessed trial label.

## Required matrix and per-trial record

**20 native clicks EACH**: foreground, background behind another application, minimized Firefox window, multiple board tabs. At least one real approval request in each group, with the remaining requests questions. Each trial records:

- group/index/time; canonical origin/profile/container, OS/Firefox version, commit;
- question/approval source and event/message id, expected and observed URL/viewer;
- tab count before/after; chosen eligible participant tab; focus/window result;
- source and feedback draft preservation (use distinct synthetic strings per tab), caret/attachments where relevant;
- other identity tab unchanged; outcome pass/fail and screenshot/video reference.

For dirty trials, toast focuses the eligible tab and shows `Open waiting request`; no auto navigation or moving drafts. Finish/send or explicitly clear the current draft, then click Open waiting request. A pending upload/send must also hold navigation. Record both phases. A separate tab must not overwrite another tab's draft. Do not count the pending phase as an exact-route success until the explicit navigation is verified.

Additional independently recorded cases: rapid successive native clicks (no duplicate windows), original client disappeared (one fresh shell only if no eligible client), other-participant tab not hijacked, resolved request (unavailable explanation), permission denied, permission revoked while open, insecure HTTP origin (not enabled), offline and recovery, worker/IDB unavailable (honest fallback), browser focus refusal (no duplicate-window retry). A new shell carries only participant/request selectors and reauthorizes; credentials are never copied. Unknown/unresponsive board clients fail closed rather than guessing identity/opening extra windows.

Native behavior after all tabs/Firefox are closed is **not delivery scope**. An already displayed toast can reopen a shell when its original client disappeared; that is not Web Push/background delivery. Browser/OS policy can refuse focus/opening: record a failure, not a fabricated pass.

## Evidence and cleanup

Store one JSON/CSV row per trial with the fields above plus screenshots outside credentials/private UI. Report exact totals: 80 required standard cases plus failure cases; never extrapolate from one trial. QA independently checks `c-62b9921733` and `c-b950658c10`. Current engineering status is **0/80 integrated native trials executed**, no native acceptance claim.

Close only the fixture's tabs, stop its foreground owned process, remove only its manifest. With owner permission revoke the disposable origin's test notification permission and unregister its `/ui/notifications-worker.js`/delete its `edp8-notifications-v1` IDB. Do not unregister other workers or clear the owner's general browser data. Production disable is per participant/origin and does not erase draft data. No shared-service restart authorization is implied.
