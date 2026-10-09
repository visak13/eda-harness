# Changelog

All notable changes to Heronry are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). Every release is on the
[releases page](https://github.com/visak13/eda-harness/releases).

## [Unreleased]

## [0.10.8]

This release fixes what qa found in the 0.10.7 candidate.

### Upgrading
- **From 0.10.5, 0.10.6 or 0.10.7:** run `heronry update --release-url <0.10.8 release folder> --previous-url <your
  current release folder>`, or run `install-heronry.cmd` from the 0.10.8 release folder. Restart open seats, and
  reload any open board tab.
- **From 0.10.0 to 0.10.4 (preview builds), desktop app:** run `install-heronry.cmd` from the 0.10.8 release
  folder (double-click it, or type it in a terminal). It checks every file against `SHA256SUMS`, stops the code
  server and the services, installs the `.msi` and starts Heronry again.
- **From 0.9.x, desktop app (the `.msi`): by hand, this once.** 0.9.x's `heronry update` refuses a desktop
  install ("the desktop bundle updates through its installer"). From 0.10 on, `heronry update` and the tray's
  **Check for update** install the new `.msi` themselves.
  1. `heronry stop all --force`: stops every service and takes the seats offline. Running codex seats are
     processes of the installed `heronry.exe` and would lock the install folder.
  2. Run `Heronry Desktop-0.10.8.msi`: double-click it, or `msiexec /i "Heronry Desktop-0.10.8.msi"`. It
     upgrades in place; your board data and settings stay. If Windows still shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**: it is safe.
  3. `heronry start`, or open Heronry Desktop.
- **From 0.9.x, command line (`install.ps1` / `install.sh`):** `heronry update`.
- The first start refreshes the agent home (role cards, skills, hooks, guides) and merges the new model catalog
  into yours. A file you edited is kept, with the new version beside it as `<file>.new`.
- After an update or a board restart, a Claude Code session that was open through it may have lost the edp8
  tools: run `/mcp` and pick Reconnect for edp8. Seats reconnect on their own.

### Fixed
- **Seat tokens:** the pool's session list no longer shows each seat's board token or provider keys. The pool
  answers on this computer only, but any program running here could read them.
- **Quiet wakes cost one model turn, not two:** a seat with nothing to do now ends a heartbeat with one short
  line. An empty reply made Claude Code prompt the seat a second time.
- **install-heronry.cmd from PowerShell 7:** started from a PowerShell 7 terminal, it stopped at the checksum
  step with "Get-FileHash is not recognized". It now checks the installer the same way from any terminal.
- **Start:** a second `heronry start` leaves a running MCP server alone. It used to stop and restart it, which
  dropped the edp8 tools from open Claude Code sessions until they reconnected.
- **EDP Chat in Restricted Mode:** it loads in a folder you have not trusted yet. Git features stay off until you
  trust the folder.
- **Update:** after an update, `heronry start` restarts a code server that still serves the previous EDP Chat, so
  the new version loads without a manual step, even when the update ran from an older `heronry`.
- **`heronry update --help`:** prints usage and runs nothing; it used to run an update check.
- **Board on a phone and desktop:** the first Mark as requirement no longer moves the page by 2 px; Admin → Seats &
  models and Library → Tickets show one card per row on a phone, so model ids and titles never break mid-word; Open
  topic stays on one line; each epic row reads "No criteria yet" or "N/M criteria passed" once; a guest no longer
  sees Quick task and New epic.
- **More phone layouts:** Design → Every move, Admin → Remote access → Every check and the Integrations harness table
  show one card per row on a phone. The sign-in card shows no error until a sign-in fails, and never pre-fills a
  participant. The request-access role reads Guest or Member, with what a guest sees under it.
- **Heronry Chat:** it opens on its first start, so a new profile no longer hides it behind "…". The Inbox shows the
  sender's role, and in a narrow sidebar the tabs stay on one row with ‹ › to scroll.
- **Remote access:** host names and file paths no longer break at a hyphen; a failed sign-in says so once.
- **Clipped controls:**
  - the Code page header at phone width;
  - Restart in Admin → Services at desktop width;
  - the Admin → Teammates and agent-token tables at phone width, which now show as cards;
  - the Design hook rows at phone width.
- **Admin:** a refused admin action shows one plain line, never internal header names, and Teammates no longer
  shows the setup note under the first owner.
- **Mark as requirement:** the first mark on an epic no longer pushes the conversation down. The open-requirement
  count shows in the header's Needs attention field.
- **Close alerts:** starting a seat with a first instruction no longer alerts the architect that the seat is closed.
- **Criteria:** a criterion re-pointed to a new report shows that report's version, not the old one's.

### Changed
- **Text-fits check:** it runs on realistic data (teammates, services, a running code server) and opens every tab of
  every page.

## [0.10.7]

This release fixes what qa found in the 0.10.6 candidate and what an independent audit found in its wake plane.

### Upgrading
- **From 0.10.5 or 0.10.6:** run `heronry update --release-url <0.10.7 release folder> --previous-url <your current
  release folder>`, or run `install-heronry.cmd` from the 0.10.7 release folder. Restart open seats so they pick up
  the new wake listener, and reload any open board tab.

### Fixed
- **Reload banner:** it compares release versions, so it no longer shows on every page after an update, and Reload
  clears it.
- **Wakes:**
  - a hint that a closed seat left a message is never dropped;
  - a long message keeps its whole text, and one cut by the board is fetched in full whoever it is addressed to;
  - a seat that closes, resumes and closes again wakes the architect each time;
  - lines that arrive together, such as a close and its hint, arrive as one turn.
- **Close alerts:** a message is not alerted twice when it sits on another ticket, nor when the seat's own closing
  post names it.
- **Phone layout:** no word breaks mid-letter, the Epics list title shows, Library and Admin tabs wrap so every tab is
  visible, placeholders fit their fields, and an open composer never hides a message once the page is scrolled.
- **Mark as requirement:** the popover closes, and "Requirement marked." shows in the composer's status line. Nothing
  on the page moves and nothing is covered.
- **Epic header:** it shows the architect's seat state ("Architect · running", "closed", "not started") the same
  way the Seats page does, and updates as soon as the seat closes.
- **Help:** plain words throughout, Title is described as editable, and no empty headings.
- **Document page:** one Show panel button, the back link names the epic, and the reader uses the page width.
- **EDP Chat:** it shows in Restricted Mode, with git features off until the folder is trusted, and its tab row
  wraps.
- **Wording:** plain words for the spawn result, the notify line, pinned counts, the ticket placeholder and the
  sign-in page, and no internal ids in captions.

### Added
- **Text-fits check:** an automated walk of every page at desktop and phone width fails on clipped, overflowing,
  off-screen or covered text and controls, and on layout that shifts when you mark a requirement.

## [0.10.6]

This release fixes what qa and an independent audit found in 0.10.5.

### Upgrading
- **From 0.10.5:** run `heronry update --release-url <0.10.6 release folder> --previous-url <0.10.5 release folder>`,
  or run `install-heronry.cmd` from the 0.10.6 release folder. Restart open seats so they pick up the new wake
  listener. Reload any board tab that was open; 0.10.6 tabs will prompt you to reload after future updates.

### Fixed
- **EDP Chat signs in again.** The board URL is now written where code-server reads it (Machine settings), and the
  extension defaults to port 19400.
- **Wakes:**
  - a seat with the edp-wake mod no longer arms a second listener;
  - an addressed message arrives with its full text;
  - a seat is not woken for its own actions;
  - one seat close arrives once, not twice.
- **Close alerts:** one seat close gives the architect one alert, listing only the messages the seat never read.
  It used to send one alert per message.
- **Quote popover:** the note gets its own row, Quote is the main button, Mark as requirement is secondary, and the
  popover never covers the selected text, at desktop or phone width.
- **Epic page seats:** each seat shows its state, a live seat offers Close and a closed one Resume, and the header
  and the Assign dialog agree on the assignee.
- **Gates:** the retired acceptance gate is gone from the decision form, and any acceptance gate left open is closed
  at board start.
- **Help and glossary:** written in plain words, with no internal ids, API paths or jargon. A test enforces this.
  The glossary adds Requirement and fixes Scope.
- **Phone layout:** the process chips, the help button, the composer (one line until tapped), the loading
  placeholders and the help sheet.

### Added
- **Reload banner:** a tab left open across an update tells you to reload.
- **edp-wake mod tests:** they run from the repo with one command, `uv run --no-sync python scripts/test_wake_mod.py`, whatever
  your Claude Code settings.
- **qa role card:** qa walks every screen a person sees in the installed app with Playwright, at desktop and phone
  width, judges the layout, and cites a screenshot for every pass.

### Changed
- **Subscription audit:** it covers every board hint, and the list of hints is taken from the source.
- **Code-guards inventory:** it matches the design's kept list.

## [0.10.5]

You talk to the architect in chat. The board no longer keeps a "Needs you" list for you; it records requirements,
hints the architect, and pages you only for what no seat can heal.

### Upgrading
- **From 0.10.4:** run `install-heronry.cmd` from the release folder (double-click it, or type it in a terminal);
  it checks every file against `SHA256SUMS` before it installs. Seats the pool starts after
  the update load the `edp-wake` mod (Claude Code 2.1.287 or later); a seat that was already open keeps its
  Monitor until it restarts.

### Added
- **Mark as requirement.** Select words in any message and press the second button on the quote card. No message
  is sent: the board records the quoted words as a requirement of the epic, and the epic cannot finish while one
  is open. The architect closes each one by linking it to a criterion or to a section of the design
  (`requirements`, `requirement_link`). Guests can mark too.
- **Close** on the Seats page and the epic page ends a live seat's shell, recorded as "closed by owner" (or
  "closed by architect"). It is a clean close: no crash notice and no new checker. An architect can close only
  seats on its own epic, and a caller can't put words in the close reason that name who closed it.
- Claude Code seats wake through the **`edp-wake` mod** instead of a Monitor they re-arm: one turn per real event,
  carrying the message's full text, and one quiet tick every 30 minutes.
- A **read-only docs mirror**: the board writes every doc to `<agent-home>/docs/<scope>/<id>.md` in the same step
  as the database write, so seats can Read and grep it. Edits still go through `doc_edit`, which now takes
  `old_string` / `new_string` / `replace_all` like a file edit; `doc_create` and `doc_update` also accept `body`.
- The site has a **Using Heronry** guide with screenshots of every main screen: the conversation, quotes from
  messages, designs and code, attachments, the Work drawer, the design beside the thread, Seats,
  VS Code on the same thread, guests and a phone. The screenshots come from a made-up demo
  project on a throwaway board, never real data. `npx playwright test -c playwright.guide.config.ts` in
  `v8/web` regenerates them all.
- **Reference → MCP tools** now documents every tool's input and output. Each argument has a plain explanation, and
  each tool shows a real example call and reply, captured on the same made-up demo board. The explanations live in
  a docs-only file, so the tool descriptions agents load are unchanged. `npx playwright test -c
  playwright.guide.config.ts tools` in `v8/web` recaptures the examples.

- The architect or the owner can retype an epic or a story (`ticket_update work_type=…`), and its pending criteria
  move to the checker the new type calls for. A product-docs story typed "knowledge" by mistake went to the
  epic's sme, which is meant for research; retyped to `feature`, it goes to qa. Verdicted lines and a checker
  the owner set by hand stay as they are, and each move is recorded on the ticket.

### Changed
- **The board hints instead of acting.** When an epic moves to in_review the architect gets a `qa_available` hint
  and starts qa itself; the board spawns no seat and opens no acceptance gate. Every pool event (a seat that
  crashed, stalled, closed or resumed) goes to the epic's architect, who heals it. Only when the epic has no live
  architect does the board write you a plain chat message, and a second one when the seat is running again.
- **Gates are cut to two:** design sign-off (the Approve button) and scope. Proof of concept, demo, adversarial
  and budget are the architect's calls, told to you in chat. A reply of yours in chat lifts the story cap
  (`ticket_create cap_lift_message=<your message id>`; the board checks the message is yours).
- **Rules advise, they don't block.** Only state transitions, who may approve, safety, evidence, doc versions and
  the caps refuse a call; other guards (a task without `serves`, a blank gate note, more than five tasks on a
  story) return a hint. Each role's tool bundle holds only the tools that role needs.
- A message that reaches a seat just as it closes is never lost: when a seat closes, the architect is hinted for
  every message addressed to it or @mentioning it during that run that the seat neither replied to nor resolved.

### Removed
- The **Needs you** and **Waiting on you** lists, the **asks ledger** and the `asks` / `ask_triage` triage flow.
  Requirements and chat replace them.

### Security
- An access request from the sign-in page now makes the person a guest unless the admin chooses otherwise. Before,
  the request form asked for member access by default, and Approve granted whatever the requester picked, so a
  stranger approved with one click became a full member. The request form now defaults to Guest, and the Approve
  row in Admin → Teammates has its own access picker set to Guest. A person can only be a guest or a member (agent
  roles are refused for people), and a guest can't be approved as an admin.

### Fixed
- An installed Heronry now installs EDP Chat, and updates it, in its VS Code (`heronry start code`). Before, only a
  source checkout did: the installer's wheel carried neither the extension nor the pinned extension list, so an
  installed code-server came up without EDP Chat and without the pinned Python extensions. The wheel now carries
  both, and the release builds refuse to make a wheel without the extension.
- A seat resumed from Seats (or by the board, for a checker) comes back with its board tools. Before, the board
  rotated the seat's secret on every spawn attempt, and the pool's resume then restarted the shell with the old one
  from its first spawn, so every board call was refused and the seat sat without tools. Resume now hands the pool the
  seat's current secret, and a spawn the pool refuses no longer rotates it.
- The VS Code extension in the bundled code-server now connects to the board's actual port. Its built-in default
  is :9400, but the board's ports move when the default ones are taken (19400 on a typical desktop install).
  `heronry start code` now writes `edp.boardUrl` from the running board, and keeps a remote board you signed in to.
- `install-heronry.cmd` keeps the installer in `data\updates\<version>\`, so the next `heronry update` can roll back
  to it. Without it, the update refused with "couldn't secure the installed version's MSI for a rollback".

## [0.10.4]

The first update run by 0.10.3's updater: `heronry update` follows the update in the terminal to its result.

### Upgrading
- **From 0.10.3:** `heronry update`, for the desktop app and the command line alike. Typed in a terminal, it
  prints each step there through to the result (installed, rolled back with its reason, or failed with the
  one recovery command) and returns 0 only when it installed; from the tray, a "Heronry update" window shows
  the same steps.
- **From 0.10.2, command line (`install.ps1` / `install.sh`):** `heronry update`. The shell prints each step
  until it hands the install to the helper; `heronry status` shows 0.10.4 when it is done.
- **Desktop app (the `.msi`) from 0.10.0, 0.10.1 or 0.10.2: run `install-heronry.cmd`** from the release folder
  (double-click it, or type it in a terminal). It checks the `.msi` against `SHA256SUMS`, stops the code server
  and the services, lists anything still running from the install folder and offers to stop it, installs with
  the Windows Installer's progress bar, starts Heronry (and the code server if it was running) and shows
  `heronry status` and the version. Every step is printed and the window waits for a key at the end;
  `install-heronry.cmd --check` only checks and changes nothing. `heronry update` cannot do this hop: 0.10.2's
  own updater runs it and its helper dies at its first import in the bundle (see 0.10.3). From 0.10.3 on,
  `heronry update` typed in a terminal follows the update in that same terminal until the result (installed,
  rolled back, or failed with the one recovery command), and its exit code says which. A per-app firewall (for example Bitdefender) may treat the updated `heronry.exe` as
  a new program and block its downloads (`WinError 10013` from `heronry start code`); allow `heronry.exe` in
  the firewall's application rules.
- **From 0.10.0, 0.10.1 or 0.10.2, desktop app (the `.msi`), without the script: by hand, this once.**
  `heronry update` cannot do this hop: it runs the installed version's own updater. 0.10.2's dies at its first import; 0.10.0's and 0.10.1's can
  hand msiexec the install folder in a form msiexec refuses when the folder name has a space (the default `Heronry contributors\Heronry Desktop` does), so it rolls back with "msiexec exit 1639" and
  Windows shows the msiexec usage box. From 0.10.3 on, `heronry update` works. The steps:
  1. Close every seat window.
  2. `heronry stop code`.
  3. Stop each feed monitor by its pid: list them with
     `Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*edp8.feed_driver*' } | select ProcessId`,
     then `taskkill /PID <pid> /F` for each.
  4. `heronry stop all --force`.
  5. In PowerShell, in the folder with the `.msi`, run exactly (it waits until the installer is done):
     ``Start-Process msiexec -Wait -ArgumentList "/i `"$PWD\Heronry Desktop-0.10.4.msi`" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER=`"$env:LOCALAPPDATA\Programs\Heronry contributors\Heronry Desktop`" /l*v `"$env:TEMP\heronry-0.10.4-msi.log`""``.
     Typed as a plain `msiexec … INSTALLFOLDER="…"` line, PowerShell 5.1 re-quotes the whole token, the form
     msiexec refuses with 1639. It upgrades the per-user install in place (a different scope or folder would
     install a second copy); your board data and settings stay. If Windows shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**.
  6. `heronry start`, or open Heronry Desktop.
  7. `heronry start code`.
  8. Resume each seat from the board, and check that the board shows one live window per seat; close any extra.
- **From 0.9.x, desktop app (the `.msi`):** 0.9.x's `heronry update` refuses a desktop install ("the desktop
  bundle updates through its installer"), so this one upgrade is by hand. From 0.10 on, `heronry update` and the
  tray's **Check for update** install the new `.msi` themselves.
  1. `heronry stop all --force`: stops every service and takes the seats offline. Running codex seats are
     processes of the installed `heronry.exe` and would lock the install folder.
  2. Run `Heronry Desktop-0.10.4.msi`: double-click it, or `msiexec /i "Heronry Desktop-0.10.4.msi"`. It
     upgrades in place; your board data and settings stay. If Windows still shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**: it is safe.
  3. `heronry start`, or open Heronry Desktop.
- **From 0.9.x, command line (`install.ps1` / `install.sh`):** `heronry update`.
- The first start refreshes the agent home (role cards, skills, hooks, guides) and merges the new model catalog
  into yours. A file you edited is kept, with the new version beside it as `<file>.new`.
- After an update or a board restart, a Claude Code session that was open through it may have lost the edp8
  tools: run `/mcp` and pick Reconnect for edp8. Seats reconnect on their own.

### Fixed
- When the update helper ends without a result, the terminal names the real `update.log` path instead of a
  literal `%LOCALAPPDATA%` (found in the 0.10.3 bundle drill).

## [0.10.3]

The update helper runs in the desktop bundle again, and `heronry update` shows what it does.

### Upgrading
- **From 0.10.2, command line (`install.ps1` / `install.sh`):** `heronry update`. The shell prints each step
  until it hands the install to the helper; `heronry status` shows 0.10.3 when it is done.
- **Desktop app (the `.msi`) from 0.10.0, 0.10.1 or 0.10.2: run `install-heronry.cmd`** from the release folder
  (double-click it, or type it in a terminal). It checks the `.msi` against `SHA256SUMS`, stops the code server
  and the services, lists anything still running from the install folder and offers to stop it, installs with
  the Windows Installer's progress bar, starts Heronry (and the code server if it was running) and shows
  `heronry status` and the version. Every step is printed and the window waits for a key at the end;
  `install-heronry.cmd --check` only checks and changes nothing. `heronry update` cannot do this hop: 0.10.2's
  own updater runs it and its helper dies at its first import in the bundle (see Fixed). From 0.10.3 on,
  `heronry update` typed in a terminal follows the update in that same terminal until the result (installed,
  rolled back, or failed with the one recovery command), and its exit code says which. A per-app firewall (for example Bitdefender) may treat the updated `heronry.exe` as
  a new program and block its downloads (`WinError 10013` from `heronry start code`); allow `heronry.exe` in
  the firewall's application rules.
- **From 0.10.0, 0.10.1 or 0.10.2, desktop app (the `.msi`), without the script: by hand, this once.**
  `heronry update` cannot do this hop: it runs the installed version's own updater. 0.10.2's dies at its first import; 0.10.0's and 0.10.1's can
  hand msiexec the install folder in a form msiexec refuses when the folder name has a space (the default `Heronry contributors\Heronry Desktop` does), so it rolls back with "msiexec exit 1639" and
  Windows shows the msiexec usage box. From 0.10.3 on, `heronry update` works. The steps:
  1. Close every seat window.
  2. `heronry stop code`.
  3. Stop each feed monitor by its pid: list them with
     `Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*edp8.feed_driver*' } | select ProcessId`,
     then `taskkill /PID <pid> /F` for each.
  4. `heronry stop all --force`.
  5. In PowerShell, in the folder with the `.msi`, run exactly (it waits until the installer is done):
     ``Start-Process msiexec -Wait -ArgumentList "/i `"$PWD\Heronry Desktop-0.10.3.msi`" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER=`"$env:LOCALAPPDATA\Programs\Heronry contributors\Heronry Desktop`" /l*v `"$env:TEMP\heronry-0.10.3-msi.log`""``.
     Typed as a plain `msiexec … INSTALLFOLDER="…"` line, PowerShell 5.1 re-quotes the whole token, the form
     msiexec refuses with 1639. It upgrades the per-user install in place (a different scope or folder would
     install a second copy); your board data and settings stay. If Windows shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**.
  6. `heronry start`, or open Heronry Desktop.
  7. `heronry start code`.
  8. Resume each seat from the board, and check that the board shows one live window per seat; close any extra.
- **From 0.9.x, desktop app (the `.msi`):** 0.9.x's `heronry update` refuses a desktop install ("the desktop
  bundle updates through its installer"), so this one upgrade is by hand. From 0.10 on, `heronry update` and the
  tray's **Check for update** install the new `.msi` themselves.
  1. `heronry stop all --force`: stops every service and takes the seats offline. Running codex seats are
     processes of the installed `heronry.exe` and would lock the install folder.
  2. Run `Heronry Desktop-0.10.3.msi`: double-click it, or `msiexec /i "Heronry Desktop-0.10.3.msi"`. It
     upgrades in place; your board data and settings stay. If Windows still shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**: it is safe.
  3. `heronry start`, or open Heronry Desktop.
- **From 0.9.x, command line (`install.ps1` / `install.sh`):** `heronry update`.
- The first start refreshes the agent home (role cards, skills, hooks, guides) and merges the new model catalog
  into yours. A file you edited is kept, with the new version beside it as `<file>.new`.
- After an update or a board restart, a Claude Code session that was open through it may have lost the edp8
  tools: run `/mcp` and pick Reconnect for edp8. Seats reconnect on their own.

### Fixed
- `heronry update` from the desktop app's install works again: 0.10.2's update helper died at its first import
  (`No module named 'update_lock'`) because the bundle ran it without its own folder on the import path, and
  the command still said "handed over", so nothing was installed and nothing said why. The bundle now runs a
  script as `python` does, and the helper adds its folder itself. **This is why the hop from 0.10.2 is by hand.**
- `heronry update` watches the update helper start before it hands over; a helper that ends without a result is
  reported in the shell with its own error, and nothing was changed.
- `heronry update` typed in a terminal no longer returns at the hand-over: `bin\heronry.cmd` then runs the
  progress viewer from the runtime copy outside the install folder, in the same terminal, through the install or
  the rollback to the result, and returns 0 only when it installed. A helper that ends without a result is said
  so within seconds. The separate progress window is kept for an update started from the tray.
- The rollback's recovery command quotes the install folder the way msiexec accepts and says to type it in a
  Command Prompt (PowerShell 5.1 re-quotes it into the form msiexec refuses with 1639).

### Added
- `install-heronry.cmd` in every release folder: the by-hand install as one tested script (see Upgrading).
- An update stops a Heronry process whose exe an earlier, rolled-back install moved aside (to
  `C:\Config.Msi\*.rbf`) while it still holds the install folder; it used to go unrecognised, and the update
  rolled back with "files in the install folder are held by Heronry CLI".

## [0.10.2]

The fixes from the Astra tool audit of every edp8 tool, and a held checker that stays held.

### Upgrading
- **From 0.10.1:** `heronry update`, for the desktop app and the command line alike. 0.10.1's own updater runs
  this hop, so it shows no progress window yet: leave Heronry alone until `heronry status` shows 0.10.2 (about 8
  minutes); its steps are in `%LOCALAPPDATA%\heronry\Logs\update.log`. A per-app firewall (for
  example Bitdefender) may treat the updated `heronry.exe` as a new program and block its downloads
  (`WinError 10013` from `heronry start code`); allow `heronry.exe` in the firewall's application rules.
- **From 0.10.0, desktop app (the `.msi`): by hand, this once.** `heronry update` cannot do this hop: it runs
  0.10.0's own updater, which hands msiexec the install folder in a form msiexec refuses when the folder name has
  a space (the default `Heronry contributors\Heronry Desktop` does), so it rolls back with "msiexec exit 1639" and
  Windows shows the msiexec usage box. From 0.10.1 on, `heronry update` works. The steps:
  1. Close every seat window.
  2. `heronry stop code`.
  3. Stop each feed monitor by its pid: list them with
     `Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*edp8.feed_driver*' } | select ProcessId`,
     then `taskkill /PID <pid> /F` for each.
  4. `heronry stop all --force`.
  5. In PowerShell, in the folder with the `.msi`, run exactly (it waits until the installer is done):
     ``Start-Process msiexec -Wait -ArgumentList "/i `"$PWD\Heronry Desktop-0.10.2.msi`" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER=`"$env:LOCALAPPDATA\Programs\Heronry contributors\Heronry Desktop`" /l*v `"$env:TEMP\heronry-0.10.2-msi.log`""``.
     Typed as a plain `msiexec … INSTALLFOLDER="…"` line, PowerShell 5.1 re-quotes the whole token, the form
     msiexec refuses with 1639. It upgrades the per-user install in place (a different scope or folder would
     install a second copy); your board data and settings stay. If Windows shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**.
  6. `heronry start`, or open Heronry Desktop.
  7. `heronry start code`.
  8. Resume each seat from the board, and check that the board shows one live window per seat; close any extra.
- **From 0.9.x, desktop app (the `.msi`):** 0.9.x's `heronry update` refuses a desktop install ("the desktop
  bundle updates through its installer"), so this one upgrade is by hand. From 0.10 on, `heronry update` and the
  tray's **Check for update** install the new `.msi` themselves.
  1. `heronry stop all --force`: stops every service and takes the seats offline. Running codex seats are
     processes of the installed `heronry.exe` and would lock the install folder.
  2. Run `Heronry Desktop-0.10.2.msi`: double-click it, or `msiexec /i "Heronry Desktop-0.10.2.msi"`. It
     upgrades in place; your board data and settings stay. If Windows still shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**: it is safe.
  3. `heronry start`, or open Heronry Desktop.
- **From 0.9.x, command line (`install.ps1` / `install.sh`):** `heronry update`.
- The first start refreshes the agent home (role cards, skills, hooks, guides) and merges the new model catalog
  into yours. A file you edited is kept, with the new version beside it as `<file>.new`.
- After an update or a board restart, a Claude Code session that was open through it may have lost the edp8
  tools: run `/mcp` and pick Reconnect for edp8. Seats reconnect on their own.

### Fixed
- `artifact_read` keeps a multi-byte character that a page edge splits; following `next_offset` used to drop it
  (audit R1).
- `ticket_query` and `doc_query` keep their 8 KB default page when one row is larger: the row is shrunk, each cut
  marked, and the page names the `verbose` call for full rows (audit R2).
- `propose_fix` publishes the typed action it validates, so a missing gate field or an unknown service is refused
  at the call, naming the field (audit R3).
- A checker seat that closes itself to wait (status deferred), or that the owner reaps or force-quits, is no
  longer replaced by a fresh one each time; a crashed checker still is.
- A checker the board puts back in the queue resumes its saved session (its context and window) instead of
  starting a blank seat; one that never ran still starts fresh.
- The board's, broker's and pool's own notes on a thread show one shared service avatar, a warm silicon chip in
  the agent-avatar style, instead of a generated face.
- `heronry start` never takes over a running service that reports another version than the installed one (a board
  started from the old files during an update); it stops it and starts the installed version. The 0.10.1 -> 0.10.2
  update rolled back this way.
- An update holds a lock from the moment it parks the seats to its result. Meanwhile `heronry start`, the desktop
  app, the code service and the install scripts start nothing and say "an update to X is in progress (step,
  elapsed)". It is automatic; a lock left by a dead updater is cleared.
- `heronry update` opens a progress window with each step and its elapsed time, ending with the result, and prints
  the same steps.
- A rollback restores the pre-update database only when the new version changed its schema; otherwise the rows
  written during the update are kept. The result says which.
- Parked seats are resumed once per update, after the final version is healthy; a pool started mid-update no longer
  resumes them too.
- One release build, `scripts/build_release.ps1` (docs/release.md), which refuses a build whose packages or board
  do not all carry the release version.

### Known gaps
- GitHub CI has not built or scanned this release yet. The CI dry run and the security job (the secret and
  personal-data scan) run before it is published.
- The read cost of the `/doc-read` skill is judged by how the next epic's seats read docs, not re-measured.

## [0.10.1]

Every hand fix the 0.10.0 install needed is now product behaviour: the upgrade runs out of the box.

### Upgrading
- **From 0.10.0, desktop app (the `.msi`): by hand, this once.** `heronry update` cannot do this hop: it runs
  0.10.0's own updater, which hands msiexec the install folder in a form msiexec refuses when the folder name has
  a space (the default `Heronry contributors\Heronry Desktop` does), so it rolls back with "msiexec exit 1639" and
  Windows shows the msiexec usage box. From 0.10.1 on, `heronry update` works again. The steps:
  1. Close every seat window.
  2. `heronry stop code`.
  3. Stop each feed monitor by its pid: list them with
     `Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*edp8.feed_driver*' } | select ProcessId`,
     then `taskkill /PID <pid> /F` for each.
  4. `heronry stop all --force`.
  5. In PowerShell, in the folder with the `.msi`, run exactly (it waits until the installer is done):
     ``Start-Process msiexec -Wait -ArgumentList "/i `"$PWD\Heronry Desktop-0.10.1.msi`" MSIINSTALLPERUSER=1 ALLUSERS=2 INSTALLFOLDER=`"$env:LOCALAPPDATA\Programs\Heronry contributors\Heronry Desktop`" /l*v `"$env:TEMP\heronry-0.10.1-msi.log`""``.
     Typed as a plain `msiexec … INSTALLFOLDER="…"` line, PowerShell 5.1 re-quotes the whole token, the form
     msiexec refuses with 1639. It upgrades the per-user install in place (a different scope or folder would
     install a second copy); your board data and settings stay. If Windows shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**.
  6. `heronry start`, or open Heronry Desktop.
  7. `heronry start code`.
  8. Resume each seat from the board, and check that the board shows one live window per seat; close any extra.
- **From 0.9.x, desktop app (the `.msi`):** 0.9.x's `heronry update` refuses a desktop install ("the desktop
  bundle updates through its installer"), so this one upgrade is by hand. From 0.10 on, `heronry update` and the
  tray's **Check for update** install the new `.msi` themselves.
  1. `heronry stop all --force`: stops every service and takes the seats offline. Running codex seats are
     processes of the installed `heronry.exe` and would lock the install folder.
  2. Run `Heronry Desktop-0.10.1.msi`: double-click it, or `msiexec /i "Heronry Desktop-0.10.1.msi"`. It
     upgrades in place; your board data and settings stay. If Windows still shows a "files in use" dialog
     naming Heronry, keep its default, **Automatically close applications**: it is safe.
  3. `heronry start`, or open Heronry Desktop.
- **From 0.9.x, command line (`install.ps1` / `install.sh`):** `heronry update`.
- The first start refreshes the agent home (role cards, skills, hooks, guides) and merges the new model catalog
  into yours. A file you edited is kept, with the new version beside it as `<file>.new`.
- After an update or a board restart, a Claude Code session that was open through it may have lost the edp8
  tools: run `/mcp` and pick Reconnect for edp8. Seats reconnect on their own.

### Added
- **A browser tool for every agent seat (Claude, codex and pi).** A seat can open a page, click through it and
  take screenshots, for example to check Heronry's own screens, signed in to the board as itself. Heronry runs one
  shared headless browser service and the edp8 tools carry it, so no seat needs its own setup, and each seat gets
  its own private browser session (no shared cookies), closed when the seat ends or after 30 idle minutes; the
  screenshots it saves stay in the browser tool's own folder. The first browser call after the update installs it once,
  using Chrome if you have it, otherwise downloading a browser once; a failure answers that call naming the step.
  Turn it off under Admin → Settings → **Browser tool for agents**.
- **Cheaper doc reads, with the reader still choosing what to read.** A new `/doc-read` skill on every doing
  seat explains that a doc opens summary-first: read the first page, then the whole doc or only the sections
  you need. `doc_read` remembers what each seat has already been shown and offers to continue from there
  instead of re-sending it (`fresh=true` reads it all again); a resumed seat starts with a clean slate. The
  architect names the design sections each story relies on in its description, and the board reminds the
  architect when a story has none.
- **`heronry update` refuses up front while a seat window the pool no longer tracks is still open** and runs a
  feed monitor from the install folder. It names the window's process and says what to do (close it, or resume
  the seat through the board), exits 2, and changes nothing: no download, no parked seat, no stopped service.

### Fixed
- **`heronry update` no longer fails with "msiexec exit 1639" when the install folder's name has a space** (the
  default per-user folder does). msiexec now gets each value quoted on its own (`INSTALLFOLDER="<folder>"`), for
  the install, the rollback and the compatibility check, instead of the whole token in quotes, a form msiexec
  refuses as an invalid command line.
- **`heronry update` no longer rolls back with "files in the install folder are held".** After it stops the
  services, the update also ends what still ran from the install folder: the Code tab's server (through
  `heronry stop code`, started again after the update), each parked seat's old window (it is resumed once,
  fresh, afterwards, including windows that outlived a pool restart), and any stray process by its pid, each
  named in `update.log`. The held-files check retries Windows' Restart Manager when the list of holders
  changed between its two reads (the cause of `holders: None`) and logs every return code. A rollback for held
  files names each holder with its command line, without token values.
- **A start no longer reports "board FAILED" when another start of the same home won the race for its port:**
  it waits up to 15 seconds for that service to answer and adopts it.
- **Tool calls fail less often on argument names.** The common slips (`doc_id` for `id`, `ticket` for
  `ticket_id`, and the like) are accepted, and a call that is still wrong names the missing argument and its
  type exactly as the tool advertises it. `spawn` and `topic_propose` offer only the values they accept, and
  `describe` points at the right tools and lists related skills.
- **A review story no longer waits forever on a dropped or partial sibling:** a story that ends dropped or
  partial now releases what it was blocking, as a done one does.
- **Epic → Actions → Models…** works again: a story can pick any model of its role's catalog row, at any effort up
  to that model's cap (Opus 5.5 at high, for example). It no longer offers only one stale model or marks picks
  "no longer in the list".
- **A seat picked at high effort launches at high.** The pool now reads the shipped model catalog, so it no longer
  caps every Claude seat at medium. The catalog's effort caps and new fields also reach an existing install on
  upgrade; values you set by hand are kept.
- **Desktop notifications fire after install:** one toast per check for what is new, skipped only while the
  Heronry window has focus.
- **The Code tab works without a hand pin:** you no longer need a `[code_server] path` line in `config.toml`. A
  broken `code-server` on PATH is passed over (a found binary must answer `--version`), and the pinned download
  is used. The workbench sign-in posts its token instead of putting it in the URL.
- **VS Code chat attachments show their real size,** not "0 B": the board no longer compresses artifact
  downloads, so their length (and video seeking) holds.
- **Admin → Seat harnesses** no longer shows every box unticked, with a "select claude, codex or both" alert,
  while your selection loads.
- Seats can upload screenshots and files again when Remote access is on.
- The epic's default view shows one asks-ledger line (the tally, and what holds acceptance), linking to the Work
  view.
- `heronry start` after an interrupted (Ctrl+C) start adopts or clears what that start left running, waits while
  a large board is still warming up, and never ends in a raw traceback.
- `heronry update` and `heronry restart` name the one action an open Claude Code session may need.
- **14 fixes from an independent UI sweep:**
  - the topic page now has the ticket page's conversation and composer (reply, quote, attach, mention, `$`
    artifact search);
  - an invite handle with spaces, `../` or over 48 characters was accepted; the server now refuses it (400), and
    the invite form says why inline;
  - lessons can be filtered, retired and opened in Knowledge;
  - pains link a fix commit only once it is pushed;
  - Escape closes the Design drawer;
  - the doc page fits a phone and dark mode;
  - Admin loading states no longer flash a wrong message;
  - closing the Models dialog warns before it drops unsaved edits;
  - 1M-context models are marked;
  - the copy is corrected.
- **Fixes from the owner's UI review:**
  - The **Models** dialog shows a compact role table: role, model and effort on one row, with **+** on the row
    to add an option. Its column header stays in place while you scroll, **Save** is always visible, and at
    phone width the model list is no longer cut off.
  - **New epic** and **Quick task** fit the window: each label sits beside its field, and the role table is no
    longer below the fold. While the pool is still answering, they say "checking the pool…" instead of
    "cannot spawn".
  - **Admin → Seats & models** no longer hangs while `codex debug models` is slow. The check gives up after
    10 seconds, and the page shows the error with a **Retry** button.
  - **Admin → Seats & models** also no longer hangs on a harness whose `--version` never returns: each check
    gives up after 10 seconds and stops the whole process it started. The **Seat harnesses** card shows the
    error with **Retry**, and **Save** stays off until the selection has loaded.
  - Teammates **Last seen** reads "3 h ago", with the local date and time on hover.
  - The topic page's panels grow with their content, so the Docs card is no longer cut off, and the seat line
    names the model ("Claude Opus 5.5").
  - Pains: commit and ticket references look like links; a commit with no link yet stays grey.
  - A guest's pages no longer ask for the pool's capabilities (the console showed a 403).
  - At phone width the **Models** dialog keeps the wide order: role, then model, then effort.
  - The **Spawn seat** form has an effort pick, capped at the model's limit.
  - A guest shows by name, and on the Code tab a guest sees "Not available for guests".
  - Role names read QA, SME and Help everywhere. Actions descriptions are plain sentences, and Library titles
    drop their `strategy_hl:` / `strategy_ll:` prefixes.
  - The asks ledger shows counts, with the ask ids behind **Which asks**, and the Work view no longer repeats a
    line.
  - Seats → Latest work status renders its formatting. **Assigned** shows the seat working on a story. A topic
    shows one status. Pains, Library and Links use sentence-case column headers. **Cut release** starts from
    the running version. The rail's arrow no longer overlaps the wordmark.
- Seats can upload files again in a dev (`EDP_HOME`) layout; only the board's secret files are refused there.

### Known gaps
- **The upgrade from 0.10.0 is by hand** (Upgrading): 0.10.0's own updater has none of the fixes above and
  always ends at msiexec 1639 in the default folder. The release gate ran those exact steps from a live 0.10.0
  in a folder with a space, with a stand-in seat window rather than a real Claude session: one window per seat
  afterwards is proven for that stand-in, so check it on your seats after the update.
- The read cost with the new `/doc-read` skill and the already-read offset is not measured yet. The next epic
  measures it on real seats against 0.10.0's numbers.
- GitHub CI has not built or scanned this release yet. The CI dry run and the security job (the secret and
  personal-data scan) run before it is published.

## [0.10.0]

Heronry made trustworthy day to day: coordination, guest sharing, learning, model control, cost and the desktop
app. The command line and the desktop app behave the same.

### Added
- Guest sharing: a guest role with per-epic membership. Every read a guest makes is scoped to the epics they are
  in, actions outside their authority are refused, and live secrets are screened out of every guest-visible view.
- An asks ledger. An ask clears when it is really dealt with: another seat answers it, a later message on the
  ticket settles it, or the ticket moves past it. A criterion whose checker seat closed gets a fresh checker,
  and "Needs you" shows only what no live seat can act on.
- Update in place, one path for the command line and the tray: seats are parked, the services stopped, the new
  release installed, and the seats resumed, with rollback on failure. A seat that fails to park, a stop that
  leaves the board answering, or a seat that fails to resume is never reported as a plain success.
- Learning: lessons carry a scope, can be backfilled and retired, and the architect reads them before designing.
- The desktop shell: notifications, quoting, links and Back/Forward.
- Web and VS Code: `$` artifact mentions, topic page parity, and a Code tab that needs no npm (Windows x64
  downloads the pinned code-server and checks its sha256).
- Upgrading merges the new pool `settings.json` template into an existing install once. It adds the compact
  SessionStart hook and drops the retired `effortLevel` pin, and every value the owner set is kept.

### Changed
- Model and effort: a seat's Claude effort is real (it rides the launch arguments) and is capped at high in the
  board and the pool, and each role gets its own option lists.
- Less waste per seat: heartbeats come through the feed driver, boots are lean, and tool output is capped.
- A precision pass over the guides, role cards and tool definitions.
- `ticket_read` with no `include` returns a compact read: the record, criteria, docs, the words header, the 3
  newest messages, and counts of the rest; `more` names the full read.
- Repeated sibling headings get an occurrence selector (`# Manual > ## Example ⟨2⟩`). A heading's literal text is
  always matched first.
- For agents, `/v1/docs/{id}/html` returns the rendered head plus `doc_read`'s continuation; people keep the
  whole page.
- Summary-first docs (S17): `doc_read(id)` returns the first page, a heading map with each section's size and a
  continuation, then sections or pages; the whole body (`all=true`) is an HTTP read for the web and VS Code
  views only. Every doc write tool points to the new
  `/doc-write` skill. Docs written before this change carry `layout=legacy`, and every read of one says
  "not structured for easy read; consider rewriting summary-first"; `doc_update(layout="summary_first")` clears it.
- `find` searches docs by section (a heading's own text; long or heading-less text by paragraph), so a term
  anywhere in a long doc is found and embedded; a doc hit names its `section`, ready for `doc_read(section=)`.
  The search table is rebuilt once on first start.
- `doc_read(section=)` returns the section's own text, up to its first subsection, plus each direct subsection's
  heading and size; `include_children=true` returns the whole subtree. A range read's reply drops empty fields.
- `ticket_read` and `context` list the epic's strategy/domain docs and their `extends` parents.

### Removed
- `assemble_ruleset` and its module. Strategy docs are read head-first through `doc_read` instead.

### Known gaps
- Summary-first docs missed their read-cost target (40% fewer chars). In the live run, agents read only 3% fewer
  chars than the same docs read whole, and 28% more than the original docs before the summary-first rewrite,
  because they page through almost every doc after its head. Five of six
  planning runs produced a usable complete plan. The sixth found every key item but marked itself incomplete
  and blocked on questions the story did not raise.

### Fixed
- Guest HTML screens a doc's source text (body, title, headings, code, old versions) before rendering.

## [0.9.1]

Fixes found in the first live cutover from a source checkout to the installed app.

### Fixed
- Resuming a seat imported from the old checkout: claude could not find the seat's conversation and closed
  within a second. `heronry import` now copies the claude transcripts into the new claude folder, and a
  resume whose transcript is missing starts the seat fresh (it calls `resume_self()`) instead of closing.
- `irm .../install.ps1 | iex` on Windows PowerShell 5.1: the script shipped with a UTF-8 BOM and failed at
  `[string]$Version`. It ships without a BOM and ASCII-only.
- `heronry import`: the live `.data/models.json` wins over the root `models.json` template; a stale
  `edp8.db-wal`/`-shm` beside the target is removed before the database is replaced (the import reported
  0 epics); the report names the install folder instead of "into None".
- The board's bare address (`/`) opens the UI instead of a 404.

### Documentation
- Cutover runbook: re-point `tailscale serve` to the installed board's port (19400), and verify a fresh
  spawn and a resume with a live seat before retiring the old fleet.

## [0.9.0]

First public release. Verified hands-on on Windows; macOS and Linux are built and tested in CI and
community-tested, so please [report issues](https://github.com/visak13/eda-harness/issues).

### Added
- Heronry: the board, its seats and services, installable on Windows, macOS and Linux.
- Heronry Desktop: a native window and tray icon, shipped as MSI, DMG and deb installers (unsigned).
- The macOS DMG is for Apple Silicon Macs; on an Intel Mac, install with install.sh.
- The `heronry` command line: `init`, `start`, `stop`, `status`, `doctor`, `update`, `import`, `gui`.
- A setup wizard, harness choice (Claude Code, Codex, Pi) and in-app updates.
- One-line installers (`install.ps1`, `install.sh`) that verify every wheel against `SHA256SUMS`.
- The Design tab: workflows, models and role cards as versioned data.
- An admin console: settings, services, teammates and invites, remote access, integrations.

### Changed
- One version, 0.9.0, for the four Python packages (`edp8`, `edp-contracts`, `edp-pool`, `edp-broker`),
  the web app and the VS Code extension.
- The codex consult bridge is gone; codex runs as ordinary seats.
- Licensed under Apache-2.0 everywhere, the VS Code extension included.

### Security
- CI blocks a pull request on a new secret or on personal data (gitleaks with project rules, plus a
  byte-level PII gate over the tree and the release artefacts).
- Every release asset is listed in `SHA256SUMS` and carries a build-provenance attestation.
- Private material was removed from the tree at this release. Older commits still hold it; no live
  credential was found in them.

[Unreleased]: https://github.com/visak13/eda-harness/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/visak13/eda-harness/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/visak13/eda-harness/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/visak13/eda-harness/releases/tag/v0.9.0
