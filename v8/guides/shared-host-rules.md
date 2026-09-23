# Shared-host rules (every seat, every machine)

These rules were learned on the fleet host and used to live only in one seat's private memory.
They are framework behaviour, so they live here; CLAUDE.md and every role card point at them.

## The shared git tree
- Many seats edit one working tree. Stage ONLY the paths you own (`git add <path>`); never
  `git add -A`, `git add .`, `git stash`, `git clean` or `git checkout -- <not-yours>`. A sibling's
  untracked files vanish under `git clean`; commit your generated assets immediately.
- Cannot build-verify a change (RAM, tools missing)? Do not leave broken source in the tree:
  stage it as a patch file in your asset subtree, checkout the source clean, and apply+build+commit
  when it compiles.
- Reading a sibling's transcript or files is fine; editing them is a hand-off through the board.

## Shared services (design §22 of epic-1b289d63f9, now framework-wide)
- A seat NEVER restarts the shared board (:9400), the MCP proxy (:9402), the pool (:9301) or the
  broker (:9300). If one is down, post `kind=blocked` with the evidence and wait; the human
  restarts it with `edp.ps1` (below). A board that is down often self-heals in
  ~2 minutes after an ephemeral-port flood; re-probe before escalating.
- Never `taskkill /IM edp8-board.exe` (kills the fleet board too). The fleet board's pid is the one in
  `.run/board.json` - never kill it or its children. Identify a board YOU spawned by its port or its
  EDP8_HOME/EDP8_DB (`Get-CimInstance Win32_Process | select ProcessId,CommandLine`), never by
  guessing among `edp8-board`/python processes (2026-09-08: an engineer killed the fleet board this way).
- The MCP proxy loads its code at boot: a merged bridge/tool fix reaches only shells that boot
  after the proxy restart. Say so in your hand-off when your change touches `mcp_server`,
  `bundles`, `consult` or `client`; after such a bridge chore lands, the proxy is respawned (owner
  call) and EVERY consult-using seat respawns — a running shell never sees the fix.

## Use edp.ps1
`edp.ps1` at the repo root is the only way to start/stop/restart/update services; the human/owner
runs it. A seat runs only `.\edp.ps1 status` and `-WhatIf`. What it does and why: `get_guide('edp-ps1')`.

## Host capacity
- Never run the full web e2e suite (`npx playwright test`) from an engineer seat: it spawns its
  own board + chromium and has OOM-killed the host and reaped the fleet board. Run the specs you
  changed; the full run is qa's, one seat at a time.
- Under RAM pressure (free < ~2 GB) consult calls crash with codex OOM; serialise consult-heavy
  seats. A burst of reason-less `shell_dead` events across many seats is ephemeral-port
  exhaustion (TIME_WAIT ~16k), not deaths; check pool liveness before reacting.
- `uv run` re-syncs and cannot replace a running `edp8-board.exe`; run pytest via
  `.venv/Scripts/python.exe` while the fleet board is up.

## Consult
- `consult(purpose=second_opinion)` results can land after your shell closes; WAIT
  (`consult_status`) before hand-off. A `provider_model=unavailable` or 600 s cap is a named gap
  in your report, not a retry loop. Never delete or restore a path your own consult run's log
  does not name.
- A consult failure at ~90% host RAM (codex OOM) or under the codex 5-hour usage cap is the HOST
  or the QUOTA, not the bridge: the result's `lane` line (`quota: capped until HH:MMZ` / `lane: ok`,
  also in `consult_status`) says which — do non-consult work until the reset, do not re-file the bridge.

## Idle wakes
- The idle-wake rule is your card's NEVER IDLE MID-PLAN line (doing seats); listening seats (architect after
  sign-off, owner) idle on a quiet board.
- A turn that returns the harness's weekly-limit text ("You've hit your weekly limit … resets HH:MM")
  is a BLOCKER, not a quiet end: `record_status(status=blocked)` with the reset time plus a blocker
  `message_send` (`kind=deviation` to the architect / `question` to the owner). qa lost 40 h to a silent
  end, 2026-09-08/09.

## Seat basics (every role card points here)
- COMMS — an event not sent is work nobody can see: `status` at milestones (to owner); blockers =
  `deviation` (to architect) or `question` (to owner); every done/answer/HITL via `message_send`.
- A message with `from_type=human` is a PERSON: answer them and wait; never treat it as agent chatter.
  Need a human reviewer/expert? `participants(role=…)` lists the team (humans marked); message the
  closest role and their Slack fires.
- CLOSE (doing seats, in order, pure tools): `inbox()` → act on each until clear →
  `record_status(status=…)` → `close_self()`. Then stop calling tools. The architect and the owner never
  close_self.
