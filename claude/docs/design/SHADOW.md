# SHADOW — the per-shell sidecar contract (WS7, v7)

Ruling (2026-08-06): protocol liturgy must not live in tokens. Every
pool-spawned shell gets a SHADOW — a small supervised python process,
spawned WITH it, that owns the deterministic lifecycle at zero LLM cost
while the agent keeps understanding, inspection, and repair. Pattern:
the service-mesh sidecar (Envoy) / the autonomic nervous system. The
NEURON SEAT is explicitly out of scope (a human owns that console);
seat-shadow is a later opt-in.

Rollback point for this whole build: git 241aa70.

## 1. Process model — the shadow is the shell's PARENT

The pool no longer launches shells directly. It launches the SHADOW,
and the shadow launches its shell (reusing pty_launcher/console_launcher
verbatim) — so the shadow naturally holds the console's input pipe and
ready-marker stream. One shadow ↔ one shell ↔ one handle, for life.

    pool (Istio role: spawn/supervise/config)
      └─ shadow <handle>            (python, ~zero footprint)
           ├─ shell (claude.exe)    (the mind)
           ├─ rx driver             (reactive/driver.py — child, supervised)
           └─ ledger + cmd files    (durable truth, below)

Why parent, not sibling: typing into a console requires owning its input
pipe; the launcher owns it. Making the shadow the launcher removes every
attach problem on the happy path.

BOTH MODES ARE SHADOWED (2026-08-06, user ruling: monitor is the
operator's default and the shadow must not be a headless-only feature).
Two wake pipes, one shadow:

* **headless** (ConPTY): the original v1 path — the shadow owns the PTY
  and types framed wakes via `send_line` (PtyLaunch.send_activation).
* **monitor** (visible console): the first line (activation + brief +
  wiring frame) rides argv as claude's initial prompt — claude submits
  it when ready, so there is no readiness race and no drain log needed.
  Later wakes are injected into the child's console input buffer via a
  detached helper process (`edp_pool.console_input`: FreeConsole →
  AttachConsole(pid) → WriteConsoleInputW KEY_EVENTs + Enter). The
  helper is a separate process because AttachConsole is process-global
  — the multithreaded pool cannot borrow a child's console. A wake that
  lands before the TUI is ready just queues in the console input
  buffer. Delivery failure is fail-open: recorded in the ledger, never
  fatal to shell or shadow.

`EDP_SHADOW=0` restores the legacy un-shadowed spawner for both modes.

## 2. The ledger — durable truth per handle

`edp-pool/.shadows/<safe-handle>.json`, atomic-write on every change:

    {
      "handle": "plan-x:a3", "role": "worker",
      "nonce": "4f2a9c",                    // provenance secret (see §5)
      "shell": {"pid": 123, "session_id": "…", "state":
                "launching|ready|busy|idle|parked|closed|crashed"},
      "driver": {"pid": 456, "spec": "rx.merge(…)", "armed_at": ts,
                 "fires": 47, "last_fire": ts, "restarts": 1},
      "heartbeat": {"interval_s": 300, "band": "heads-down",
                    "last_tick": ts},
      "wakes": [{"seq": 47, "kind": "mail", "ts": …, "delivered": true}],
      "mode": "auto|silenced",              // reflex(silence) → manual
      "updated_at": ts
    }

Rules: the ledger is written ONLY by the shadow; `reflex` reads it and
writes commands to `<safe-handle>.cmd.jsonl` (append-only), which the
shadow tails. No new ports, restart-safe, inspectable with any editor.

## 3. Lifecycle the shadow owns (agent turns: ZERO)

SPAWN   pool → shadow(handle, role, spec-template, brief-ref, nonce)
        → shadow launches shell → waits ready-marker → types ONE
        activation message: `/role` + handle line + THE BRIEF INLINE
        (fetched from the store/dispatcher — kills check_inbox/
        read_object boot turns) + `[shadow :nonce] wiring live: <spec
        summary>` → publishes `ready` to the broker (kills
        notify_above(ready)).
WATCH   hosts the rx driver (same code, same per-role spec template
        from loop-and-heartbeat — now pool config data). Driver dies →
        shadow re-arms it, increments `restarts` (the deaf-subscription
        trap becomes supervised + visible).
WAKE    driver emission / heartbeat due → shadow types a FRAMED line
        (§5) when the shell is idle; if busy, the line queues in the
        console input and lands at turn end (the July prompt_async
        semantics). Every wake logged with seq in the ledger.
PACE    the shadow polls the engine's pacing state for its handle
        (recipe/plan pacing is derived, deterministic) and adjusts its
        own heartbeat to the band. The agent obeys wait_hint by simply
        ending its turn — cadence machinery is no longer operated.
PARK    (planner) shell parks/is parked → shadow KEEPS the driver
        alive. Mail lands → shadow asks the pool to resume the shell,
        then types the re-ground line. The resume rewire dance is
        deleted: wiring never died.
CLOSE   shadow observes the terminal condition (worker: own action
        terminal; planner: plan terminal; curiosity: `clear` reply) →
        drains one final inbox check → releases via the pool
        (close_when_idle) → marks ledger `closed`. Agent close ritual:
        none. Forgetting: impossible.
CRASH   shell dies unexpectedly → shadow publishes the existing
        `crashed` flowback and keeps the ledger for the re-dispatch.

## 4. Sovereignty — the `reflex` MCP tool (every spawned role)

    reflex(verb="status")   → the ledger, verbatim (armed vs fired vs
                              delivered — deafness is READABLE)
    reflex(verb="rearm")    → command the shadow to restart its driver /
                              re-derive its spec
    reflex(verb="observe", spec=…, bindings=…)
                            → register an EXTRA subscription with the
                              shadow (replaces agent-run monitor_cmd;
                              observe() gains shadow mode)
    reflex(verb="pace", interval_s=…)  → manual heartbeat override
    reflex(verb="silence") / reflex(verb="resume_auto")
                            → take/return manual control: silenced =
                              shadow only logs, agent runs its own
                              wiring the old way (the on-the-fly escape
                              hatch when shadow code is wrong)
    reflex(verb="wake_check", seq=N)   → paranoia: did MY shadow send
                              wake #N? (verification, not trust)

Boot-doc cost of all of this: one ~50-token paragraph. Everything else
about shadows lives HERE, not in any role's context.

## 5. Provenance — how the agent knows its own senses

Every shadow-typed line after activation is FRAMED:

    [shadow <handle> #<seq> :<nonce>] <kind>: <digest> (<pointer>)

- `nonce`: random per spawn; the pool puts it in the shell's env
  (EDP_SHADOW_NONCE) and gives it to the shadow. Console typists don't
  know it → a framed+nonced line is verifiably the agent's own sense.
- Grammar is SENSORY only (`mail:`, `tick:`, `flowback:`, `resumed:`)
  — never imperative. Senses are data; authority still arrives only via
  the broker (`from: panel`) per the existing provenance doctrine.
- Wrong/missing nonce on a framed line → the agent treats it as
  untrusted input and reports it (one turn).

## 6. Failure matrix (who dies → what happens)

| dies       | recovery                                                        |
|------------|-----------------------------------------------------------------|
| driver     | shadow re-arms it from the ledger spec; `restarts` incremented  |
| shadow     | pool supervisor respawns it; it re-reads its ledger. The old    |
|            | console pipe is gone, so it restores by REBIRTH: park+resume    |
|            | the shell under itself (proven machinery). Shell state survives |
|            | (session resume); wiring state survives (ledger).               |
| shell      | crash flowback (existing); ledger retained for re-dispatch      |
| pool       | shadows are independent processes — they keep watching, waking, |
|            | closing. Pool re-attaches to shadows via ledgers on restart.    |
| everything | ledgers + session ids on disk = full cold restore, per handle   |

## 7. What gets DELETED once shadows hold (the payoff)

- Boot-doc sections: arm-the-wake-plane, close sequence, epoch/monitor
  re-arm mechanics → replaced by the ~50-token shadow paragraph
  (worker boot doc ~2.3k → ~1.2k tokens; planner similar).
- Agent-run `monitor_cmd` for spawned shells (observe → shadow mode).
- CronCreate/CronDelete/Monitor/TaskStop from spawned-role surfaces
  (the seat keeps them).
- The planner resume-rewire dance.
- worker-close-nudge escalates from backstop to near-vestigial.
- Every leaked-cron/driver/slot failure class.

## 8. Build order (each step suite-green before the next)

1. `edp-pool/src/edp_pool/shadow.py` — the process: ledger, launch
   (reuse pty_launcher/console_launcher), driver hosting, framed
   typing, cmd tailing. Unit tests with FakeShell.
2. Pool integration: SubprocessSpawner launches shadows; spawn API
   unchanged upward (engine/tools untouched). Supervisor + re-attach.
3. `reflex` MCP tool + observe() shadow mode + role floors/ceilings/
   catalog.
4. Pacing poll endpoint (engine exposes derived band per handle).
5. Boot-doc diet (guides-src edits + recompile; prose-contract tests
   updated WITH their lessons moved to this file where they become
   shadow-owned).
6. Drill row updates in V7-RUNBOOK.md (drills 2/4/6 change shape:
   leaks now assert on ledgers).

Non-goals now: seat shadow, cross-shell shadow mesh, shadow-to-shadow
comms. One shadow, one shell, one handle.

## 9. V1 deviations (recorded at build, 2026-08-06)

* **In-process shadows.** V1 shadows are supervised THREADS inside the
  pool process (ShadowSpawner), not separate processes — pool death =
  shadow death. The restore shape is unchanged: ledgers are durable;
  on pool restart, non-closed handles are rebirthed (park+resume) under
  fresh shadows. Process isolation is v2.
* **Pacing is reflex-manual in v1.** The engine's pacing bands are
  computed inside edp_claude, which the pool does not import; until an
  engine endpoint exposes the derived band per handle, the shadow keeps
  its role-default heartbeat and the agent adjusts it with
  `reflex(verb="pace", interval_s=…)` — one turn per band change,
  already cheaper than the classic CronDelete+CronCreate pair.
* **Curiosity closes itself.** Its terminal condition (`clear`) lives
  in a reply body, not in stored state, so its shadow never
  auto-closes it; Step 4b stays agent-owned.
* **Brief injection covers worker/reviewer.** Planners ground
  themselves from the digest (their brief IS the recipe); curiosity
  gets its consult from the inbox as before.
* **Monitor wake delivery is console-input injection** (added
  2026-08-06 when monitor became shadowed). The plumbing is unit-tested
  with fakes; WriteConsoleInputW delivery into claude's live TUI needs
  one live-drill verification (watch the first heartbeat wake appear in
  a visible console). If a TUI build ever rejects injected KEY_EVENTs,
  the fallback is flipping that role to headless — the shadow itself is
  mode-agnostic.
