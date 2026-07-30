# IMPACT — monitor mode = real visible console (change to built #4)

**Trigger:** user 2026-05-18 chose Option A after the log-tail monitor
proved fundamentally wrong (a linear tail cannot render an in-place
animating TUI; static frames were fine post-BOM, animations were garbage).
§5.5 impact note before the change.

## What changes
- **New `edp_pool/console_launcher.py` — `ConsoleLaunch`:** plain
  `subprocess.Popen([claude, "/<role>", *extra], cwd=agent_home, env=...,
  creationflags=CREATE_NEW_CONSOLE)`. A real visible Windows console; the
  TUI renders natively (no PTY, no drain, no tail, no mojibake, no
  animation scramble). Activation is the **initial prompt arg** (argv) —
  valid here because the worker is autonomous via the edp-broker MCP
  tools; no post-boot PTY injection is needed (that was the old
  wrapper's reason to avoid argv, and it doesn't apply to first-prompt
  activation, already proven: `/worker` ran fine when delivered).
  `is_alive()` = `proc.poll() is None`; `terminate()` = `proc.terminate()`.
- **`SubprocessSpawner.launch` branches on mode:**
  - `headless` → **unchanged** `PtyLaunch` (ConPTY + drain-to-log, BOM
    kept for forensic `Get-Content`). For scale / no-window runs.
  - `monitor` → `ConsoleLaunch` (visible window, argv activation). No
    `wait_ready`/`send_activation` (argv carries it), no drain log,
    no log-tail viewer.
- **Removed:** `SubprocessSpawner._open_monitor` (the log-tail viewer
  console) and its viewer-encoding shim — superseded; the visible claude
  console *is* the monitor now.

## Blast radius
- edp-pool only. `Spawner` ABC unchanged (`mode` already a param).
  `FakeSpawner` + all logic/HTTP tests unaffected (default headless;
  FakeSpawner ignores mode). `PtyLaunch` + its tests untouched
  (headless regression intact). No contracts/broker/claude change.
- Tests: replace the 2 old monitor-viewer tests with ConsoleLaunch
  tests (Popen called with CREATE_NEW_CONSOLE, argv includes the role
  command, alive/terminate via poll). Net test delta, not a regression.

## Risk + mitigation
- `CREATE_NEW_CONSOLE` is Windows-only → existing win32 guard at
  `launch()` top covers it; tests mock `subprocess.Popen` + force
  `sys.platform`.
- argv-activation reliability: already empirically validated (the
  PTY-delivered `/worker` executed correctly; first-prompt argv is at
  least as reliable and is the standard claude CLI entry).
- The real visible spawn is still the manual-HITL surface (no claude
  binary here) — S3c covers the Popen wiring with `subprocess.Popen`
  mocked.

## Test plan (S3c delta)
CON-1 monitor→`ConsoleLaunch.spawn` calls `Popen` with
`creationflags=CREATE_NEW_CONSOLE`, cwd=agent_home, argv `[bin,"/worker"]`,
env carries EDP_*. CON-2 alive/terminate via `poll`/`terminate`.
CON-3 headless still uses `PtyLaunch` (unchanged path, regression).
Replace old `test_sub_mode_monitor_*` viewer tests.

## Verdict
Smaller + correct vs the broken tail; bounded to edp-pool; headless
regression-guarded. Proceed.
