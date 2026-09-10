# Shared-host rules (every seat, every machine)

These rules were learned on the fleet host and used to live only in one seat's private memory.
They are framework behaviour, so they live here and in CLAUDE.md; a card points at them.

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
  broker (:9300). If one is down, post `kind=blocked` with the evidence and wait; the human or the
  launcher (`start.ps1 -Restart <service>`) restarts it. A board that is down often self-heals in
  ~2 minutes after an ephemeral-port flood; re-probe before escalating.
- Never `taskkill /IM edp8-board.exe` (kills the fleet board too). The fleet board's pid is the one in
  `.run/board.json` - never kill it or its children. Identify a board YOU spawned by its port or its
  EDP8_HOME/EDP8_DB (`Get-CimInstance Win32_Process | select ProcessId,CommandLine`), never by
  guessing among `edp8-board`/python processes (2026-09-08: an engineer killed the fleet board this way).
- The MCP proxy loads its code at boot: a merged bridge/tool fix reaches only shells that boot
  after the proxy restart. Say so in your hand-off when your change touches `mcp_server`,
  `bundles`, `consult` or `client`; after such a bridge chore lands, the proxy is respawned (owner
  call) and EVERY consult-using seat respawns — a running shell never sees the fix.

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
- A doing seat (engineer, sme, qa) with unbuilt plan items resumes the next item on an idle wake;
  only listening seats (architect, owner) idle on a quiet board. See the card line NEVER IDLE
  MID-PLAN and `_heartbeat_prompt` in `bundles.py`.
- A turn that returns the harness's weekly-limit text ("You've hit your weekly limit … resets HH:MM")
  is a BLOCKER, not a quiet end: `record_status(status=blocked)` with the reset time (qa lost 40 h to
  a silent end, 2026-09-08/09). Every card carries this line.
