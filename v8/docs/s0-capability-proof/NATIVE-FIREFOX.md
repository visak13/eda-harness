# Installed Firefox native trial (controlled manual fixture)

**Not yet executed.** Start with ONE click, then decide whether to schedule the full matrix.
This proof uses synthetic participants A/B and synthetic request destinations. It is not
authentication or production board integration evidence. No real owner tabs are eligible
because this is a different origin and a dedicated profile. No credentials are needed.

## Run, owner-controlled

In one PowerShell terminal:

```powershell
node C:/Projects/Learning/eda-base3/v8/docs/s0-capability-proof/manual-server.cjs
```

It prints `S0 fixture ready http://127.0.0.1:<port>/ owned_pid=<pid>`. Record the
port/PID and keep this terminal running; no fixed shared port is used.
In another PowerShell, substitute that exact printed origin below:

```powershell
$url = 'http://127.0.0.1:<port>/'
$profile = Join-Path $env:TEMP ('edp8-s0-firefox-' + [guid]::NewGuid())
New-Item -ItemType Directory -Path $profile | Out-Null
$firefox = Start-Process -FilePath 'C:/Program Files/Mozilla Firefox/firefox.exe' -ArgumentList @('-no-remote','-profile',"`"$profile`"",$url) -PassThru
Write-Output "Dedicated profile=$profile launched_pid=$($firefox.Id)"
```

The new profile deliberately does not share sign-in, history, cookies or notification
permission with your normal Firefox. Do not pass your usual profile directory. No driver,
extension, login, production-server edit, or global preference change is required.
The fixture displays actual browser user agent and permission; stock installed version
observed on disk was 156.0. Record what the opened test page actually reports.

## First native click

1. Enable notifications via the fixture's explicit button and accept Firefox's prompt.
2. Select actor A / foreground, type exactly `S0 draft KEEP` in the textarea.
3. Click Send one test toast; click the actual Windows toast. Do not emulate the click in
   DevTools. If Windows suppresses it, report that (including Do Not Disturb state if known).
4. Expect the SAME tab/window focused, unchanged tab count, draft intact, a visible pending
   destination button. The URL must not change until that explicit button is chosen.
5. Click pending destination; draft stays, synthetic request hash changes.
6. Download synthetic trial log. Report actual Windows foreground/focus and total tab count
   before/after; JavaScript's clients count is only same-origin clients, not all browser tabs.

No new tab may be opened as a fallback merely because focus failed. The headless synthetic
check hit exactly that failure and kept two tabs unchanged; native clicking is needed to
supply browser user activation and actually test the intended path.

## Full matrix after first click works

Twenty REAL notification clicks each: foreground; this test window behind another window;
this test window minimized; multiple copies of the test origin in this dedicated profile.
Keep a fixed synthetic draft in candidate A tabs; add B tab via selector to prove it isn't
routed as A. Export logs from every test tab before closing/reloading (logs are in memory).
Count failures too, never replace failed trials to inflate the pass count.

For every trial record: trial UUID/group, browser/OS/origin/profile, permission, total tabs
before/after, same-origin client counts, actual foreground/focus, destination shown/hash,
draft/caret before/after and observed result. The log records worker route result and draft
preservation; external tab/focus/OS state needs the observer's note. Do not include private
screens or text. Synthetic worker events are labelled synthetic:true and NEVER count.

Separately exercise denied/revoked permission, rapid clicks, target client disappearance,
only participant B remaining, identity change between send and click, and focus failure.
The fixture supports these observations but does not claim production feed dedup, real
participant authorization, attachments, background delivery or cross-container behavior.
Unknown/nonresponsive clients fail closed instead of opening additional windows. Browser
openWindow/focus rejection is recorded, not hidden. Production-origin reuse still needs
S5 integrated evidence; this fixture can prove only the native platform seam.

## Cleanup

Use Close test toasts first. Close ONLY this dedicated test Firefox window/profile, never
kill firefox.exe by image. Ctrl+C the fixture server terminal. Remove only the `$profile`
directory created above after that dedicated browser closes. No normal Firefox setting,
board service or CLI configuration was modified. Keep exported synthetic logs for evidence.

## Automated preparation evidence

`node docs/s0-capability-proof/manual-smoke.cjs` passed on patched Firefox 153.0 headless:
synthetic dispatch -> `focus_failed_no_new_tab`, two clients before/after, A draft intact,
B destination untouched. This is fixture behavior validation, NOT a native-click pass.
