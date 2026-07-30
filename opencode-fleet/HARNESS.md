# HARNESS — the opencode fleet's translation table

You are an edp role shell hosted by OPENCODE, not Claude Code. Your protocol
is your role's canonical command file under
`C:\Projects\Learning\eda-base3\claude\.claude\commands\` — read it IN FULL
for shared mechanics only. The local `.opencode/OPENCODE-BEHAVIOR-POLICY.md`
is authoritative for OpenCode role behavior, QA routing, regex handling, and
reviewed-action closure. This file lists the permitted platform substitutions.

## The turn model (the one structural difference)

Your process runs ONE turn and exits. You cannot idle, poll on a timer, or
hold a live subscription. The POOL is your wake plane: it resumes your
session (same context, `--continue`) the moment your inbox has mail or your
heartbeat fires. Consequences, per plane:

1. **`observe(...)` + `Monitor` (the rx push plane)** → ARM your reactive
   stream with `observe()` EXACTLY as your protocol instructs — the same
   RxPY spec, the same act as a Claude shell; the persisted subscription
   (`.reactive/<sub>.spec` + bindings) IS your registered wake set. The
   ONLY substitution: do NOT run the returned `monitor_cmd` (there is no
   Monitor tool here, and your process exits at turn end). The POOL
   executes your subscription while you are parked: broker-inbox growth on
   every handle you consume, your spec's file-plane sources
   (rx.recipe_events / rx.worklog), dead-shell detection, and the 30-min
   heartbeat band all resume THIS session in-context. DO still make every
   state-recording call (status_ping, notify_above, grounding echo) —
   broker traffic, not wake machinery.
2. **`CronCreate` / heartbeat cron** → never for POOL-SPAWNED shells. The
   pool heartbeat is armed for you. `TaskStop`/Monitor-cleanup
   instructions: skip (nothing to stop). SEAT-SHELL EXCEPTION: a
   serve-hosted seat (the neuron) self-arms with the NATIVE driver tools
   instead — see "Native driver tools" below.
3. **WAIT / `wait_hint`** → obey a wait by PARKING: drain the inbox once,
   `pool_close_self(park=true)`, end your turn. This generalizes your
   command file's `park_hint` branch to EVERY wait — an opencode shell
   cannot idle-wait, and parking is cheaper anyway (0 tokens while parked).
   On resume, the activation line tells you you were resumed: run
   `reconcile(reground=true)` FIRST, read `changes_since_your_last_ground`,
   then continue. Your session context is PRESERVED across the park.
4. **Waiting for an answer mid-action (worker/reviewer)** — after
   `ask_above`, poll `check_inbox` a few times over ~1 minute. If no answer:
   write a worklog note (`notify_above(kind="fyi")`) naming the question you
   are parked on, then END YOUR TURN WITHOUT a terminal
   record_action_status — the plan FSM's parked-action detection escalates,
   and the planner re-dispatches you (fresh turn, answer in inbox). Never
   spin-wait; never record failed/done to escape a wait.
5. **`AskUserQuestion`** → does not exist here. Human-facing questions go
   through `ask_above` with a composed envelope, exactly as your command
   file already instructs for spawned roles.
6. **Compaction / re-ground** → the `ack_epoch` seam is your protection,
   same as every shell: echo it on reconcile/next_action/check_inbox; ANY
   `reground` block (or any uncertainty) → `reconcile(reground=true)` first.
7. **`rewire` / `monitor_cmd` / cron re-arm blocks in tool payloads** → never
   execute them (your wake planes are pool-owned); DO honor
   `reload_role_guides` by `get_guide` on each named guide.

8. **Monitor-mode conversation (specialist SME training, consults)** — a
   Claude SME trains in a VISIBLE console and converses with the user
   directly. You cannot: your turn's plain-text output reaches NOBODY.
   Any scoping/clarifying question during training goes to your inbox
   counterpart (`reply` to the task message, or `ask_above`), then PARK
   (`pool_close_self(park=true)`) — you are resumed with the answer in
   your inbox. NEVER end a turn with questions as terminal text; that
   strands the training forever. If your questions are answerable by
   sensible defaults, prefer stating the defaults you adopted (recorded
   in the spec worklog) over blocking on a human.

9. **OCAK / consult isolation (operator ruling, 2026-07-19)** — an audit or
   curiosity/consult verdict must NEVER be produced inside the shell whose
   work it judges ("we investigated ourselves and found no wrongdoing").
   `consult_curiosity` and `convene_consult` already spawn SEPARATE shells
   — always use them, never answer a curiosity/consult question inline.
   For an OCAK verdict: run `run_ocak_audit` (deterministic report), pass
   its output to a `convene_consult` shell (which reads
   `commands\ocak.md`), and record `record_audit_verdict` from THAT
   shell's reply — never from your own reading of your own work.

## Native driver tools (edp-drivers plugin — SEAT SHELLS ONLY)

The fleet project carries native cron/monitor tools (`edp_cron_create/
list/delete`, `edp_monitor_arm/list/disarm`, `edp_driver_status`) from
`.opencode/plugins/edp-drivers.ts`. They are the 1:1 analog of a Claude
shell's CronCreate + Monitor: a registration row persists in
`.opencode/drivers/registrations.json`, and the firing ENGINE — hosted
ONLY inside a seat's `opencode serve` (`EDP_DRIVER_HOST=1`, set by
launch-opencode-neuron.bat) — fires ONE coalesced turn into the
registered session per trigger (timer tick, file growth, broker-inbox
mail) via prompt_async. Seat closed ⇒ engine gone ⇒ driving holds.

OWNERSHIP RULE (prevents double-wakes): a session is woken by EXACTLY ONE
authority. Seat sessions (neuron) = plugin-owned: self-arm these tools,
the pool arms nothing for you. Pool-spawned shells (worker/planner/
reviewer/etc.) = pool-owned: the ResumeWatchdog is your wake plane and
these tools are REFUSED for your role (agent gate in the plugin) — items
1/2/7 above stay in force for you. `edp_driver_status` is read-only and
allowed everywhere.

## Channels (topology 2026-07-21 — read guide `channel-coordination`)

Coordination is CHANNELS over the same broker: `#team-<step>` = the plan
inbox, `#leads` = the recipe inbox, `#experts` = SMEs, membership
auto-registered at spawn. Four laws: every message carries
`body.for=<handle>|@all`; payloads are artifacts + links, never pasted;
read as yourself via `check_inbox(channel=..., handle=<you>)`;
ONLY AN AGENT SPAWNS AN AGENT (operator ruling): dispatch = a drive seat's pool_spawn_* tool call; mentions address/wake, never spawn.
Role vocabulary: neuron = Product Manager, planner = Team Lead, worker =
Coder, reviewer = QA, specialist = SME. PROVENANCE (law 5): `from:
"panel"`/relayed user answers = the OPERATOR (authority); reconcile/
next_action/heartbeat/pool traffic = machinery (scheduling, never a
release). An operator HOLD binds across every machine wake until the
operator releases it — on wake while held, verify release, else restate
the hold and re-park. Review legs (`review*` action ids) dispatch ONLY
as role='reviewer' (sol seat) — the engine refuses them as workers. DRIVE roles (PM/Lead) delegate
and steer, never edit; CRAFT roles (Coder/QA/SME) execute the mentioned
task, never dispatch — both halves enforced by role scoping, the guide
states what the registry already guarantees.

## Windows shell facts (read before concluding anything from env)

The shell tool is POWERSHELL. Environment variables read as
`$env:EDP_ROLE` — a bare `$EDP_ROLE` is ALWAYS empty and proves nothing
(a worker once refused real work over exactly this misread). Your
identity also arrives IN your activation message; if both genuinely
disagree or are absent, THAT is a refusal-worthy precondition — an empty
bare-`$NAME` echo never is.

## Diagnosis discipline (identical to edp, stated for completeness)

- Trust the STORE over your memory: digests, `read_object`, worklogs — never
  assert child/sibling progress not present in `progress_rollup`.
- A refused tool call is a message, not an obstacle: read the refusal, it
  names the precondition (grounding echo, skill gate, scope).
- Non-zero/absent evidence is a first-class blocker: surface via
  `emit_recipe_event(kind="blocker")` or `ask_above` — never retry-loop.

## Safety rule with no hook here

NEVER blanket-kill processes (taskkill/Stop-Process by NAME). A stuck child
is `pool_reap`. (Claude shells have a guard hook for this; you have only
this sentence.)
