# PORT-OPENCODE — the edp engine drives opencode/gpt-5.6 shells

**Ruling (user, 2026-07-18):** the lean-harness track is retired as the
orchestrator. The requirement is THE EDP HARNESS's behavior — multi-step
parallel driving, concurrent workers, bidirectional rx comms, cross-cutting
concern propagation, goal-in-recipe, recipe/plan read-write optimization,
dispatch optimization, agent-determined recipe/plan lifecycle — for
opencode-hosted gpt-5.6 shells. Nothing approximated, nothing re-pictured.

**The load-bearing finding (traced, file:line in the full map):** the entire
behavioral surface lives ABOVE the pool's HTTP seam. Only
`edp-pool/{pty_launcher.py, spawner.py}` + three spots in `service.py` touch
the `claude` binary. Everything else reaches the pool through `PoolPort` →
`HttpPool` (`/v1/spawn|release|resume|liveness|sessions`) and is
**backend-blind**.

## REUSED UNCHANGED (the whole engine)

- Waves & parallelism: `recipe_ready_step_wave` (recipe_fsm.py:102),
  `plan_ready_wave` (plan_fsm.py:165), batch dispatch, EDP_MAX_* caps
  (service.py:56-72; caps count rows, not binaries).
- Bidirectional comms: full CORE_KINDS (edp-contracts broker.py:46-91),
  ROLE_WAKE_KINDS (reactive/runtime.py:48-85), reply/steer/steer_ack/
  grounding-echo/ask_above envelopes/flowback, the RxPY runtime + observe/
  compile_spec — all pure broker/HTTP composition.
- Cross-cutting concerns: injection seam (~_tools.py:5017), spec_ids,
  briefing delta, grounding briefs, decisions-by-id.
- Lifecycle, agent-determined: resolve_recipe / start_recipe / suspend /
  resume / close_recipe, digests, tiering/sidecars, ack-ledger/epochs,
  north_star, comprehension signoff — MCP tools, identical for any client.
- Dispatch optimization: park/fork-resume model + **ResumeWatchdog (exists,
  resume_watchdog.py; started service.py:609)** — inbox-depth > watermark →
  service.resume. Escalation ladder, reviewer/verify legs, dual-gate.
- The Gen-2 external-turn pattern (codex neuron: arm_external_driver +
  neuron_heartbeat.py, --cmd template with {PROMPT}) — already proves the
  exits-at-turn-end backend model this port generalizes.

## NEEDS-VARIANT (the whole port surface — small)

New `edp-pool/src/edp_pool/opencode_launcher.py` + `OpencodeSpawner(Spawner)`:

| claude path | opencode variant |
|---|---|
| resolve_claude_bin (+219MB self-repair machinery) | resolve_opencode_bin; DELETE the repair subsystem outright |
| build_argv `[claude, --dangerously-skip-permissions, --model]` | `[opencode, run, <message>, --agent, edp-<role>, --variant, medium, *session, --title]` — activation rides ARGV, not PTY keystrokes |
| build_session_args `--resume/--session-id/--fork-session` | `--session <id>` / `--continue` / `--fork` (probe: caller-pinned ids?) |
| build_env | REUSE EDP_ROLE/HANDLE/BROKER_URL/POOL_URL/AGENT_HOME/LOG_DIR; drop CLAUDE_CONFIG_DIR/AUTOUPDATER/OTel-CLAUDE keys; add opencode config-dir pin |
| PtyLaunch ConPTY + ready-markers + send_activation | DROPS AWAY — one-shot subprocess, drained stdout log (reuse drain/BOM code), pid, tree-kill, run-timeout |
| _transcript_path/_wait_transcript_flush | probably DROPS (an exited one-shot has flushed) — probe storage path |
| _ROLE_ACTIVATOR slash commands | role → `--agent edp-<role>` map (planner→edp-agentic-plan) |

Turn models: worker = one-shot (identical, simpler — exit==done). Planner =
park-between-turns AS THE ONLY MODE; re-turns driven by the EXISTING
ResumeWatchdog + heartbeat backstop (neuron_heartbeat.py, --cmd already
backend-parametrized). Pause/suspend (WMI freeze) N/A for one-shots.

## GENUINELY MISSING (net-new, bounded)

1. `.opencode/agents/edp-*.md` (9 role wrappers pointing at the EXISTING
   `.claude/commands/*.md` guides — files win) + `opencode.json` (edp-claude
   MCP server, gpt-5.6 models + limits + medium effort).
2. `OpencodeSpawner` + `opencode_launcher.py`.
3. Backend selection: `EDP_SHELL_BACKEND=claude|opencode` in create_app —
   MIXED FLEETS ALLOWED (per-role routing).
4. opencode session-id capture IF ids aren't pinnable (model on
   .codex/hooks/capture-session.py).
5. Workspace decision: in-place (verify .opencode agents win over existing
   AGENTS.md/.claude) vs a separate fleet workspace (the codex neuron-sol
   pattern).

## M0 probe results (2026-07-18, opencode 1.18.3, live)

1. **EDP_ROLE env→MCP inheritance: PASS (the crux).** Process env
   (EDP_ROLE/HANDLE/SPAWN_SESSION_ID) reaches MCP stdio children verbatim
   (probed via a FastMCP env_probe tool). Per-spawn role scoping works
   byte-identically to Claude shells.
2. **Caller-pinned session ids: REJECTED** (`--session <new-uuid>` →
   "Session not found"). Port takes the CAPTURE path.
3. **Storage: SQLite** (`<XDG_DATA_HOME>/opencode/opencode.db`, WAL). The
   `session` table has id/title/agent/model/directory + tokens_*/cost
   columns → capture session id by the pool-stamped `--title`, AND free
   per-shell usage telemetry. Transcript-flush machinery DROPS (WAL).
4. **Fleet-store isolation: XDG_DATA_HOME pin WORKS**, with one requirement:
   seed `auth.json` into the fleet store once (auth lives in the data dir;
   an unseeded store falls back to demanding an API key).
5. **Workspace:** separate `opencode-fleet/` dir created (the neuron-sol
   pattern) — no AGENTS.md/.claude collision by construction. Contains
   opencode.json (gpt-5.6 models, limits, medium effort, probe MCP) +
   .opencode/agents/ + .fleet-data/ (isolated store, auth-seeded).
6. `--fork` fork-not-mutate semantics: DEFERRED to M2 (planner resume).

## M1 status (2026-07-18): spawner built + smoke-tested

`edp-pool/src/edp_pool/opencode_launcher.py` — `OpencodeSpawner` (Spawner-ABC
compatible) + `CompositeSpawner` (mixed fleet, routes by EDP_OPENCODE_ROLES,
default worker) + argv/env builders + sqlite session-id capture. Smoke
(python parent, as the pool runs): launch → alive/pid → protocol-following
turn (read .claude/commands/worker.md, correct reply) → exit → capture. Fleet
workspace `opencode-fleet/` carries opencode.json + edp-worker agent wrapper.

**Landmines found and fixed (each cost a bisect):**
- **PWD, the big one:** opencode resolves its PROJECT from the `PWD` env var,
  NOT the process cwd. Shell parents maintain PWD; python parents leave it
  stale → the fleet project/agents are never found and a custom `--agent`
  dies as an opaque "UnknownError: Unexpected server error". Fix: `--dir
  <workspace>` on argv + `env["PWD"]` pin (both).
- Never launch the npm `.CMD`/`.ps1` shim from Popen — resolve the real
  platform exe (`opencode-windows-*/bin/opencode.exe`).
- Strip `VIRTUAL_ENV`/`UV_*`/`PYTHONPATH`/`PYTHONHOME` from the child env
  (the pool runs under edp-pool's uv venv; leakage poisons python children).
- `--auto` required for unattended runs (headless permission ask = death).
- MCP commands in opencode.json use the claude venv python DIRECTLY
  (`.venv/Scripts/python.exe -m edp_claude.mcp_server`), not `uv run`.
- Auth lives in the data dir: seed `auth.json` into any fresh fleet store.

**M1 COMPLETE (2026-07-18):** CompositeSpawner wired into main.py
(EDP_OPENCODE_ROLES opt-in, default empty = 100% Claude; knob documented in
start-stack.bat). LIVE ROUND TRIP PASSED through the real stack:
`pool_spawn_worker` (MCP) → pool → composite routes worker → OpencodeSpawner
→ opencode/gpt-5.6-terra shell → grounded via the SAME edp-claude MCP →
created the proof artifact → passed the grounding-echo gate →
`record_action_status(done)` with honest read-back evidence →
`pool_close_self`. The full worker.md lifecycle, zero engine changes.
Validation recipe: recipe-m1-live-round-trip-…-0cf597 (scratch, kept as the
acceptance record). Pool test suite: 248 passed (1 pre-existing live-stack
test unrelated).

## M2 COMPLETE (2026-07-18): park/resume + the 1:1 operational layer

**The seam:** `service.resume` now asks the spawner for a backend-native
resume token — `spawner.session_token(sid)` (duck-typed getattr, claude
spawner unaffected) — and after a successful resume re-captures it into the
row's `claude_session_id` slot. `OpencodeSpawner.session_token` resolves via
the in-memory launch record, falling back to an exact-title sqlite lookup so
parked shells SURVIVE POOL RESTARTS. `CompositeSpawner` delegates by
`knows()`, trying the opencode store for unknown ids (post-restart case).
Resume argv: `--session <token> --continue` (same session, context
preserved).

**LIVE DRILL PASSED** (action a2 on the -0cf597 scratch plan): opencode
worker read its two-turn instruction → obeyed HARNESS.md wait rule →
`pool_close_self(park=true)` → row `state=parked`, process reaped, 0 tokens
idle → `broker_send(steer)` to the handle → ResumeWatchdog `resume_start`/
`resume_done` within seconds → the SAME opencode session (store shows exactly
one id for the pool sid) woke, re-grounded citing "the explicit resumed-turn
instruction from a2 and the neuron steer" (first-turn context intact), wrote
proof2.txt, recorded honest read-back evidence, echoed `ack_epoch` on its
final `check_inbox`.

**`--fork` probe PASSED:** `--session <base> --fork` answered a
first-turn-recall question correctly INTO A NEW session titled
`<title> (fork #1)`; the base id is untouched. So `--continue` is the normal
resume (proven, mutates-by-appending, re-resumable after a crash) and
`--fork` is the recovery escape hatch — the claude `--fork-session` analog.
Because the fork's title differs, `capture_session_id`'s exact-title lookup
never confuses fork and base.

**The 1:1 operating procedure** (user directive: "1:1 truly on all fronts"):
`opencode-fleet/HARNESS.md` is the translation table — 7 numbered deviations
only (never arm observe/Monitor/Cron FOR POOL-SPAWNED SHELLS — the pool owns
their wake planes; SEAT shells self-arm the NATIVE edp-drivers tools per
HARNESS.md "Native driver tools", 2026-07-24; obey
EVERY wait by park; parked-question protocol = ask_above → brief poll →
fyi worklog → end turn WITHOUT terminal status; AskUserQuestion→ask_above;
ack_epoch echo discipline; skip rewire/monitor_cmd blocks, honor
reload_role_guides) + diagnosis discipline + the no-blanket-kill rule. All 8
role wrappers under `.opencode/agents/` point at HARNESS.md FIRST, then the
canonical `.claude/commands/<role>.md` verbatim (worker=terra, all judgment
roles=sol, effort medium pinned via `--variant` + opencode.json
reasoningEffort).

## M3 COMPLETE (2026-07-19): fleet + spec-consistency, and four v7 engine fixes

**Fleet drill (recipe -0cf597 s2/s3, closed succeeded via mark_outcome_met):**
a sol PLANNER drove the entire plan lifecycle on opencode — grounding brief +
fingerprint + exact_content acceptance with authored verify cmd, dispatch,
park, watchdog resume, evidence verification, plan close. The SPEC drill then
proved the whole specialization framework: sol SME (train_specialist →
opencode) compiled `spec-python-stdlib-utility-module-engineer` at exemplar
grade (all seven sections, adherence tags, real Unicode craft); terra WORKER
loaded it via get_specialist_docs and built a compliant module; sol REVIEWER
assembled the layered ruleset, found a REAL violation (orphan combining
marks), fixed it inline (`fixed_inline=true`), and flowed a spec-learning
back (ratified `[required]`, spec v28); the FSM's verify-only leg re-ran
acceptance green. Consistency loop closed: spec → worker adherence →
reviewer enforcement → learning → spec.

**Four LATENT v7 ENGINE gaps this exposed (all pre-dated the port — the v7
live 2-planner run was deferred; all fixed + suites green 249 pool/1309
engine):**
1. **Planner watch handles** (`service._watch_handles` + per-handle
   `watermarks`): park watermarked only the SPAWN handle (`recipe:sN`) but a
   planner's worker flowback lands on its PLAN handle (`recipe-sN`) — parked
   planners stranded forever. Watchdog now watches every consumed handle.
2. **Park drain gate** (`PoolCloseSelf`): the watermark is RAW depth, so
   UNREAD mail at park time is inside the watermark and never wakes the
   shell. State-side (where read cursors live) the park is now REFUSED
   naming the unread handles; the shell drains and re-parks. Observed
   teaching a live sol planner mid-drill.
3. **Done flowback publish** (`RecordActionStatus._arm_close`): NOTHING ever
   published `CORE_KINDS["done"]` — worker.md ends "the planner's heartbeat
   will see your result on disk", which only an alive polling planner can.
   Every terminal record_action_status now publishes `done` to the plan
   handle (best-effort), waking parked planners in seconds.
4. **Verify-leg latch persistence** (`next_action` change-signature): P4.2's
   `verify_leg_emitted` latch was mutated but not in the persist signature →
   DISPATCH_VERIFY_LEG re-emitted every tick, wedging the planner after a
   fixed_inline verdict. Signature now carries the latch.

**Wrapper/HARNESS fixes:** all 7 generated agent wrappers had a literal
`$name` in their protocol path (shells were recovering by inference) — now
correct per-role paths. HARNESS.md gained deviation 8: monitor-mode
conversation (SME training) must ask via inbox/ask_above then PARK — a
headless shell's terminal text reaches nobody.

**Neuron seat (2026-07-19):** PORTED — no Claude dependency remains.
`.opencode/agents/edp-neuron.md` (sol) + `launch-opencode-neuron.bat`
(clone of the codex Gen-2 launcher): default = interactive opencode TUI in
the fleet workspace (drive sol exactly like the Claude neuron — type the
goal, the protocol does the rest); `--auto` = non-interactive kickoff →
session captured by title from the fleet store → `scripts/
neuron_heartbeat.py` resumes the SAME session on all four wake planes
(timer / broker SSE / flowback tail / pool-dead) via the REAL exe (python
parent cannot launch the npm shim) with `--session <id> --continue`.
Launcher sets EDP_ROLE=neuron + EDP_AGENT_HOME + stack URLs + fleet
XDG_DATA_HOME; CRLF/ASCII enforced.
  LIVE VALIDATION BLOCKED at time of writing by the PROVIDER, not the
harness: every request (sol AND terra) died with
`ProviderHeaderTimeoutError: response headers timed out after 10000ms` —
the ChatGPT-plan throttle after a full day of fleet drills (or an OpenAI
incident). opencode retries silently with backoff, which presents as a
silent stall: know this signature (`--print-logs` shows it). Retry
`launch-opencode-neuron.bat --auto` when the plan window resets. One real
lesson from the attempt: a turn KILLED mid-flight can leave the session
wedge-prone on `--continue` — recover with `--fork` (M2 hatch) or a fresh
kickoff, never by re-continuing blindly.

**Residual (minor):** terra workers skip `steer_ack` sometimes (protocol
adherence polish; the v7 unacked-steer advisory detects it — observed
firing).

## 2026-07-19 second wave (operator ruling: "1:1 means 1:1")

- **Obsidian VAULT = the memory-facing layer** (`store/vault_mirror.py`):
  every RecipeStore/PlanStore save re-renders a wikilinked Markdown note
  under `EDP_VAULT_DIR` (default `eda-base3/vault`) — recipes (goal,
  outcomes, step checklist with [[plan]] links, decisions, questions) and
  plans (action checklist, spec ids, verdicts, [[recipe]] backlink). Pure
  PROJECTION: the JSON stores stay the single source of truth; every
  engine formula (digests, tiering, injection, ack ledger, cursors) is
  untouched; a vault write failure never fails the save. Zero manual
  steps — created/updated/terminal-stamped exactly when recipe.json is.
- **MODEL_TIERS → gpt-5.6 translation** (`opencode_launcher.map_model`):
  the tier formula is unchanged; its output is translated at spawn —
  host-default→None (role wrapper's pinned model, the Claude host-default
  analog), sonnet-tier→terra, haiku-class→luna (reserved; no current
  MODEL_TIERS row uses it), explicit opus→sol; env re-points via
  EDP_OPENCODE_MODEL_{SONNET,HAIKU,OPUS}. Unknown tier → wrapper default,
  never a guess.
- **Phase-guide enforcement** in edp-neuron/edp-agentic-plan wrappers:
  guides are MANDATORY and never-from-memory (orchestrator-launch +
  neuron-phase-<x> / planner-phase-*), reload_role_guides honored; both
  wrappers name the ready-frontier drive (`all_ready=true`, steps/actions
  dispatch when THEY are ready).
- **OCAK/consult isolation** (HARNESS.md item 9, operator ruling): no
  verdict is produced in the shell whose work it judges —
  consult_curiosity/convene_consult spawn separate shells (structural in
  one-shot opencode); OCAK verdicts route run_ocak_audit's deterministic
  report through a convene_consult shell reading ocak.md.
- **start-stack.bat** now arms the FULL sol fleet by default
  (EDP_OPENCODE_ROLES=worker,planner,reviewer,specialist,consult,
  curiosity,goal_keeper,pattern_observer); the neuron seat is
  launch-opencode-neuron.bat.
- Suites: 1313 engine (incl. 4 vault-mirror) + 250 pool (incl. tier-map)
  green.

## 1:1 PARITY MATRIX (2026-07-19 — the checkable claim)

| edp mechanism (Claude shell) | sol harness mechanism (opencode shell) | status |
|---|---|---|
| Protocol files `.claude/commands/<role>.md` | THE SAME FILES, read verbatim via role wrappers | PROVEN (all drills) |
| MCP tool surface + role scoping (EDP_ROLE) | same server, same env contract | PROVEN (M0 probe 1 + every shell) |
| Grounding echo gate, ack_epoch, reground | identical (engine-side, backend-blind) | PROVEN (worker/planner/reviewer live) |
| rx event wakes: `observe()` + Monitor consume broker kinds in-shell | SAME broker kinds/planes; consumer = pool ResumeWatchdog per-consumed-handle + done-flowback publish | PROVEN (park→message→resume in seconds, many cycles) |
| Mid-turn wake injection (Monitor types into live pty) | IMPOSSIBLE in headless opencode (no stdin channel) — equivalence is brief in-turn poll (HARNESS item 4) then park/resume with FULL context retention | PLATFORM BOUNDARY, equivalence proven (M2 recall probe) |
| 30-min CronCreate heartbeat (reconcile tick) | POOL-SPAWNED shells: watchdog HEARTBEAT (parked row older than EDP_PARKED_HEARTBEAT_SECS resumed → one reconcile turn → re-park). SEAT shells: NATIVE `edp_cron_create` (edp-drivers plugin, engine in the seat's serve, EDP_DRIVER_HOST=1) | watchdog: BUILT + unit-proven. NATIVE: PROVEN 2026-07-24 (engine live-fire: 60s cron fired twice via prompt_async, TICK-ACK reply, lastFiredAt stamped, coalescing on session.idle) |
| Monitor tool (self-armed watch, agent-owned) | SEAT shells: NATIVE `edp_monitor_arm` (file-growth tail or broker-inbox SSE, once/persistent, coalesced) — pool-spawned shells stay watchdog-owned (agent gate REFUSES driver tools; ownership rule in HARNESS.md) | tools PROVEN 2026-07-24 (GPT worker armed cron+monitor argument-perfect; gate refusal proven); monitor-source live fire pending first recipe |
| PreToolUse guard hook (stack-nuke protection) | NATIVE edp-guard plugin: `tool.execute.before` refuses kill-verbs against :9300/:9301/:4747 + writes/deletes of pool-state.json / `.opencode/drivers/` | PROVEN 2026-07-24 (live GPT probe: taskkill against seat window refused with deny text, command never executed) |
| Crash sweep → broker `crashed` publish (watchdog) | pool-spawned: SAME watchdog. Seat sessions: edp-drivers forwards `session.error` → `/v1/publish` kind `crashed`, wire-identical body | BUILT (live fire pending first recipe) |
| Idle-at-prompt between turns | park (0 tokens) + resume `--session --continue` | PROVEN (M2/M3) |
| Fork-resume recovery (`--fork-session`) | `--fork` (fork-not-mutate, title-collision-safe) | PROVEN (M2 probe) |
| Specialist framework (train/compile/adhere/enforce/learn) | identical loop on sol SME / terra worker / sol reviewer | PROVEN (spec drill, learning ratified) |
| Neuron seat (user drives via terminal, /neuron) | interactive opencode TUI via launch-opencode-neuron.bat; cadence = NATIVE edp-drivers self-arm as of 2026-07-24 (neuron_heartbeat.py = documented fallback, nothing arms it) | PROVEN 2026-07-19: live sol turn (guides loaded, refused to guess between 2 live recipes) + heartbeat driver repeatedly WOKE THE DEAD one-shot session with context intact (`--session --continue`); driver refusal-not-guess on ambiguous recipe also observed; launcher takes optional recipe-id arg |
| AskUserQuestion (neuron↔user) | TUI conversation (interactive) / durable open_questions (--auto) | BUILT with the seat |
| steer_ack discipline | same protocol text; terra adherence imperfect | RESIDUAL (detector works) |
| Memory layer: JSON store + digests | SAME stores + digests, plus automatic Obsidian vault projection (recipes/plans as wikilinked notes) | BUILT + unit-proven |
| MODEL_TIERS (Opus default / Sonnet coding+verify) | same formula, translated: wrapper-default(sol·terra) / terra; luna reserved for a haiku-class tier | BUILT + unit-proven |
| Phased guides (get_guide per phase, reload_role_guides) | same guides, mandatory-never-from-memory stated in wrappers | PROVEN (drills showed get_guide calls) + reinforced |
| OCAK/consult unbiased verdicts (separate shell) | consult_curiosity / convene_consult separate shells; OCAK report routed through consult shell (HARNESS item 9) | BUILT (guide-level; live drill pending provider) |

## Build order

- **M0 — probes (cheap, ~1 session):** (1) EDP_ROLE process-env inheritance
  into opencode-spawned MCP stdio servers — #1 blast radius; (2) pinned
  `--session <uuid>` accepted?; (3) `--fork` = fork-not-mutate?; (4) output/
  session-storage shape (--format json) for evidence + flush; (5) config-dir
  pin; (6) AGENTS.md/.claude precedence in eda-base3/claude.
- **M1 — opencode WORKER under existing Claude planners:** no sessions, no
  park; validates env→MCP, argv activation, evidence capture, caps, the
  record_action_status round trip. First shippable.
- **M2 — planner park/resume loop on opencode** (ResumeWatchdog does the
  waking; it already exists).
- **M3 — full fleet** (reviewer/specialist/consult/curiosity/goal-keeper/
  pattern-observer + neuron via launch-opencode-neuron cloned from the codex
  launcher).

## Non-goals

- No re-implementation of any FSM/broker/tool behavior in opencode-land.
- The sol-lean-harness repo is FROZEN as an experiment record; transferable
  lessons (stdin $null, stall watchdog, ASCII-ps1, host-native evidence
  commands) inform the port; its conductor does NOT become the orchestrator.
