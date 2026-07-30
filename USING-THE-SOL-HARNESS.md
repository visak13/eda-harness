# Using the sol harness (edp on opencode/gpt-5.6)

The edp engine is unchanged. Exactly two things differ from the Claude
harness: the TUI is **opencode** (models gpt-5.6, never a fast variant:
**sol** for neuron/reviewer/consult and all judgment seats, **terra** for
planners AND workers — luna retired 2026-07-21 on quality), and the
memory-facing layer is the **Obsidian vault** at `eda-base3\vault`
(auto-projected; the JSON stores stay authoritative). Everything else —
recipes, plans, FSMs, park/resume, specs, reviews — behaves identically.
Parity claims + proof status: `claude\docs\design\PORT-OPENCODE.md`
(the 1:1 PARITY MATRIX section).

## 1. Start the stack

    start-stack.bat

This brings up broker (:9300), pool (:9301) and the rest. The sol fleet is
armed by default (`EDP_OPENCODE_ROLES=` all eight spawned roles) with caps
**workers=3, planners=1**. To mix Claude shells back in, trim that roles
list in start-stack.bat.

## 2. Drive it — the neuron seat

    launch-opencode-neuron.bat

A dumb terminal, exactly like opening a Claude shell: it hosts the neuron's
session server and attaches your TUI. Nothing runs until you type. Select
the **Edp-Neuron** agent (Tab / agent switcher), then state your goal in
one message — `/neuron` semantics. The NEURON decides everything from
there: it resolves whether your goal matches an open recipe or starts a new
one (`resolve_recipe`), runs comprehension, asks for signoff, declares
steps, dispatches the fleet — free-flowing, no harness-side choices.

**Its cadence is self-armed with NATIVE driver tools** (edp-drivers
plugin, live-fired 2026-07-24): at recipe adoption the neuron calls
`edp_cron_create` (30-min heartbeat) + `edp_monitor_arm` (recipe inbox,
optionally flowback file) — the 1:1 analog of a Claude neuron self-arming
CronCreate + Monitor. The firing ENGINE runs inside the seat's own
`opencode serve` (`EDP_DRIVER_HOST=1`, set by the launcher): a trigger
fires ONE coalesced turn into the session via prompt_async; registrations
persist in `opencode-fleet\.opencode\drivers\registrations.json` across
server restarts. Seat closed ⇒ engine gone ⇒ driving holds (the seat
gate, structural). Driver-fired turns render live in your attached TUI.

**OWNERSHIP RULE** — one wake authority per session: the seat session is
plugin-owned; pool-spawned shells stay ResumeWatchdog-owned, and the
plugin's agent gate REFUSES driver tools to them. The old
`arm_external_driver` + `neuron_heartbeat.py` pair is the documented
fallback only — nothing arms it by default.

**ENFORCED GUARD (edp-guard plugin)** — the opencode analog of the
Claude-side PreToolUse guard: bash kills against the stack (:9300/:9301/
:4747, stack processes) and writes/deletes of harness state
(pool-state.json, `.opencode\drivers\`) are refused at the harness layer,
not merely discouraged by policy prose. Crash flowback: a `session.error`
on a registered session publishes CORE kind `crashed` to its broker
handle — wire-identical to the ResumeWatchdog's crash publish.

Unattended mode:

    launch-opencode-neuron.bat --auto

One neutral kickoff turn so the neuron grounds and self-arms without you;
supervise via the panel, attach a TUI anytime:
`opencode attach http://127.0.0.1:4747`.

## 2b. SEEING the fleet work

- **Visible consoles:** consult, curiosity and specialist shells open their
  own console window and stream the turn live (set
  `EDP_OPENCODE_MONITOR_ROLES=*` in start-stack.bat to watch EVERY role —
  workers, planners, reviewers too; `""` = all headless). The window stays
  open after the turn so you can read the transcript; the pool closes it
  when the shell is reaped.
- **The neuron is LIVE (rx-driven), and you watch it:** the launcher runs
  one `opencode serve` that owns the neuron session, an **rx driver**
  console that fires a turn into that session the instant broker traffic /
  flowback / a dead shell lands (plus the 30-min heartbeat band), and your
  TUI **attached** to the same server — driver-fired turns render in front
  of you in real time, and you can type into the very same session at any
  moment. This is the edp Monitor/observe plane, supplied server-side.
  `--auto` is identical minus the attached TUI (attach later anytime:
  `opencode attach http://127.0.0.1:4747`).

## 3. Watch and steer — the panel

    panel-window.bat        (or http://127.0.0.1:9301/panel)

- **Shells** — every live/parked shell, pause/resume per shell or recipe.
- **Spawn config → Spawn caps** — change max workers / planners / total at
  runtime. Saved caps persist across restarts and override the `EDP_MAX_*`
  env values; "Reset to env defaults" clears them.
- **Approvals / Gates / Plan review** — as in the Claude harness.

## 4. Read the state — Obsidian

Open `eda-base3\vault` as an Obsidian vault. `recipes/` and `plans/` notes
are re-rendered on every save: goals, outcome checkboxes, step checklists
wikilinked to their plan notes, decisions, review verdicts. This is a
read-only projection — edit nothing there; the engine's JSON is the truth.

## 5. What happens underneath (so the behavior reads as intended)

- Shells are ONE-SHOT processes: a shell runs a turn and exits. Waiting is
  **parking** (0 tokens); the pool's watchdog resumes it within seconds of
  relevant mail (worker `done` flowback is published automatically) and, as
  a backstop, after the 30-min heartbeat band even with no traffic — so a
  dead agent always wakes.
- Steps and actions dispatch **when they are ready** (`all_ready` waves),
  not serialized behind the recipe/plan.
- Specs rule the fleet: workers load compiled specialist docs, reviewers
  re-check against the assembled ruleset and fix inline, learnings flow
  back and are ratified into the spec. Consult/curiosity/OCAK verdicts run
  in SEPARATE shells — never the shell whose work is judged.
- Effort is pinned medium everywhere; model per seat comes from the same
  MODEL_TIERS formula as always, translated sol/terra(/luna).

## 6. When something looks stuck

1. `http://127.0.0.1:9301/panel` — is the shell parked (fine, it wakes on
   mail/heartbeat) or active-silent?
2. Silent stall on a fresh spawn = usually the PROVIDER throttling
   (opencode retries quietly). Diagnose with `--print-logs` on an
   `opencode run`; wait for the plan window to reset.
3. A turn killed mid-flight can wedge its session on `--continue` —
   recover with `--fork` (base stays pristine) or a fresh kickoff.
4. Never blanket-kill by process name; reap a specific shell via the panel
   or `pool_reap`.
