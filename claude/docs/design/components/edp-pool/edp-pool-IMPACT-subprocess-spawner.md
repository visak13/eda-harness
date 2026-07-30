# IMPACT ANALYSIS — real SubprocessSpawner (change to built component #4)

**Trigger:** user decision 2026-05-17 — "port the old wrapper/edp_shell.py
PTY approach; port the *launching logic* only, everything else per our
protocol/design." Takes up the `# TODO(integration,#9)` on
`SubprocessSpawner`. METHODOLOGY §5.5 requires this note before the change.

## What changes
- **New module `edp_pool/pty_launcher.py`** — a *minimal* PTY launcher,
  ported (not copied) from `evolving-deep-agent/wrapper/edp_shell.py`.
  Ported pieces (pure launch mechanics, design-agnostic):
  - `resolve_claude_bin()` — override → `EDP_CLAUDE_BIN` → `which` →
    npm `.cmd` shim → bare `claude`.
  - ConPTY spawn via `winpty.PtyProcess.spawn(argv, cwd, dimensions, env)`.
  - TUI-ready detection: first `❯` in PTY output ⇒ keyboard handler live.
  - One activation write (the role slash command) after ready.
  - `is_alive()` / `terminate()`.
- **`SubprocessSpawner`** (was a `NotImplementedError` stub) now delegates
  `launch/alive/kill` to `pty_launcher`.
- **`edp-pool` gains `pywinpty`** as a platform dependency
  (`sys_platform == 'win32'`).
- **Env contract the pool sets for the shell** (our design, NOT the old
  protocol): `EDP_SPAWN_SESSION_ID` (correlation — kept), `EDP_ROLE`,
  `EDP_HANDLE`, `EDP_BROKER_URL`. The activator slash command
  (`/agentic-plan` or `/worker`) reads these and drives itself via the
  **edp-broker MCP tools** — there is NO PTY-injected broker stream.

## What is deliberately NOT ported (old protocol — replaced by ours)
- Human stdio proxy (reader/writer threads, raw console mode, win32
  input decode, meta `:` parser) — pool workers are headless; output is
  drained to a per-session log for debugging only.
- The old `BrokerClient` WS subscription + inbox-cursor files under
  `.plans/.sessions/` — superseded by edp-broker `/v1/*` + `BrokerMessage`.
- The in-process HTTP-injection POC.

## Blast radius
- **edp-pool only.** `FakeSpawner` is untouched → all 9 existing pool
  tests stay green; `create_app()` still defaults to `FakeSpawner` for
  tests/CI. `main.py` already wires `SubprocessSpawner` for real runs.
- **No consumer change.** `HttpPool`, `edp-claude`, broker, contracts
  unaffected — the `Spawner` ABC signature is unchanged.
- **No edp-contracts change** → no version bump, no cross-repo ripple.

## Risk + mitigation
- `pywinpty` is Windows-only → platform-marked dep; non-Windows raises a
  clear error from `SubprocessSpawner.launch` (documented).
- The real spawn launches an interactive `claude` process — **not
  unit-testable in this environment** (no claude binary; interactive). By
  design this is exactly the **manual-HITL surface** (#9). S3c covers the
  *testable* logic with `pywinpty` mocked: bin-resolution priority, argv
  assembly, env contract, ready-detection state, terminate path.
- Activation timing (write before TUI ready ⇒ dropped) — mitigated by the
  ported `❯`-readiness wait with a bounded timeout.

## Test plan (S3c delta)
Mock `winpty`: SUB-1 bin resolution (4 priorities), SUB-2 argv = `[bin,
"/<role>"]` + extras, SUB-3 env contract keys set, SUB-4 ready-wait
returns on `❯` / times out cleanly, SUB-5 alive/kill delegate, SUB-6
non-Windows → clear error. FakeSpawner suite unchanged (regression guard).

## Verdict
Localized, no ripple, regression-guarded. Proceed S3a.
