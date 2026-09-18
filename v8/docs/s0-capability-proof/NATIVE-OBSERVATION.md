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

## Minimal next proof

A repeat with retained log is desirable, not assumed authorized. Reopen only on coordinated
owner timing, use the same isolated fixture, repeat ONE actual click and export the log
before closing. Then schedule the remaining 20x4 and failure cases; the repeated first
trial still does not waive those. If owner prefers less manual effort, ask architect for
an explicit revised acceptance scope instead of silently substituting headless/API tests.
Production participant authorization, board route integration and attachment safety remain
S5 responsibilities, not proven by synthetic A/B fixture identities and hash destinations.
