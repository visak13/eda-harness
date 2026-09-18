# First native Firefox feasibility observation — 2026-09-18

**ONE owner-reported success, not a retained-log trial or full criterion pass.**

Owner m-5e59c44c21 authorized testing now. Preflight 1496 MiB free; S1 generation had
finished according to architect. Launched scoped Node fixture PID **27936** at
**http://127.0.0.1:49329/** and stock Firefox launch PID **27496**, dedicated profile
`C:/Users/aksou/AppData/Local/Temp/edp8-s0-native-dcins4l_/profile`.
Stock installed binary inventory was Firefox **156.0**, Windows **10.0.26200.0**;
no retained browser-user-agent log from this trial independently confirms the displayed version.
Normal owner Firefox tabs/profile and shared board origin were untouched.

Owner instructions m-82d2bfd229: enable notifications, A/foreground, draft `S0 draft KEEP`,
send one toast, click actual Windows notification; report same tab/focus/no extra tab,
draft intact, pending destination button. Owner m-374db8d5ea replied:

> I accidentally closed the firefox window without downloading the trial results.
> This did work as you described though

This supports **one owner-observed native feasibility success** for the described path.
It does NOT provide trial UUID, measured tab counts, independent focus/caret trace,
exact permission dialog history, or a downloaded JSON log. Do not invent those details.
No statement that the complete 20 foreground trials, other groups, or failure matrix passed.

## Log recovery

The fixture's `entries` array exists only in page memory. It uses no localStorage,
IndexedDB, server log ingestion or transcript cache. The service worker also keeps no
trial ledger. Closing the page loses those entries unless the user exported them.
Read only the owned server log: it contains the ready URL/PID line, no trial events.
No recoverable fixture trial record was identified; no unrelated browser profile inspected.
Scratch profile/receipt/server log retained, not deleted. No fabricated reconstruction.

## Owned cleanup

On architect instruction m-f28b4742c6, verified launch PID **27496** had exited and no
Firefox process command line referenced the unique dedicated profile. Verified PID **27936**
was node.exe running the scoped manual-server.cjs before stopping only that process.
No image-name kill, shared process restart, broad cleanup, or desktop reopening.

## Authorized repeat — one retained native click

Owner m-6e4db95d3d allowed reopening, freed memory m-67bb5872fd; architect coordinated
S1 hold m-c84cdae09a. Preflight 2120 MiB free. Repeat used Node PID36380 / Firefox
launch PID35440, origin **http://127.0.0.1:64988**, dedicated profile
`C:/Users/aksou/AppData/Local/Temp/edp8-s0-repeat-smw8k5c5/profile`.

Owner m-39e288ab70 supplied Downloads/s0-native-trials.json. Preserved byte-for-byte as
`native-repeat-20260918.json`; SHA256
`0da91106edfea38def405022f734dfa2d87f564ea52650fdac03e1f62a81b153`.
It records actual Firefox **156.0** UA and permission **granted**.

ONE retained click, trial **1cc41a0c-356f-49e2-8db2-f7cd4acf6e14**, at
**2026-09-18T09:48:13.167Z**, actor **B**, group label **failure-case**:
`synthetic:false`, `outcome:reused`, same-origin clients
**1→1**. `pending_destination` records matching request hash, `draftPreserved:true`,
`focused:true`, `visible:visible`. This demonstrates the native-click/pending-draft seam,
not real board authorization or total all-origin browser tab count.

The first five A sends (one each labelled foreground/background/minimized/multiple-tabs/
failure-case) were followed by test_notifications_closed and have NO click outcomes.
They are not passed click trials. A selected group label alone does not prove actual OS
window state. No explicit pending-button navigation/caret event was exported for the B click.

Repeat cleanup: verified Firefox launch PID35440 already exited; verified node.exe PID36380
was scoped manual-server.cjs and stopped only it. Original Downloads file, both scratch
profiles/receipts/server logs retained; no active owned test process. Owner told the precise
log result m-f9d9323975; architect cleanup/result m-89a83c78da.

## Remaining proof

First owner-reported success plus ONE retained repeat are not the required 20x4/failure
matrix. Schedule further native trials only with coordinated timing, or obtain an explicit
revised acceptance scope; never substitute headless/API evidence silently. Production
participant authorization, board route integration and attachment safety remain S5
responsibilities, not proven by synthetic A/B identities and hash destinations.
