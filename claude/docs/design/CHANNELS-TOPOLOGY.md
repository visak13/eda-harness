# CHANNELS — the Discord-shaped topology over the unchanged edp mechanism

Operator's thesis (2026-07-21): keep the underlying mechanism (broker,
pool, FSMs, specs, vault), change the TOPOLOGY to channels + mentions.
Roles rebrand: neuron → **Product Manager**, planner → **Team Lead**,
worker → **Coder**, reviewer → **QA**. Spawning = mentioning a handle in
a channel. The user sits IN the channels.

## 0. One honest invariant before anything else

"Messages just pop up, no heartbeat/monitor needed" is true for the
INTERFACE, not the process. A one-shot shell that isn't running cannot
see a message pop up — something must still deliver the wake. So: the
pool watchdog / driver STAY as the delivery layer (that IS the retained
mechanism); what the topology removes is the *agent-facing* wake
vocabulary — no shell ever arms observe()/cron again; membership in a
channel IS its subscription. Cron survives only as the invisible 30-min
net. This keeps the user's core insight: agents think in channels and
mentions, never in wake machinery.

## 1. Topology → existing primitives (nothing new invented)

| Discord concept | edp primitive underneath |
|---|---|
| Channel | broker inbox with an ALIAS LIST of members (broker aliases exist; add multi-member) |
| DM | today's direct handle inbox, unchanged |
| Mention `@handle` | dispatch: pool spawn/resume of that handle (mention-scan in watchdog) |
| Thread | one action's worklog (plan worklog.jsonl, exists) |
| Channel history | vault projection (exists) + per-member read cursor |
| "Seen by" | per-(channel, member) cursor files (extend today's per-recipient cursors) |

Channels: `#product` (user + PM), `#leads` (PM + all team leads),
`#team-<step>` (lead + coders + QA of that step). Created/destroyed by
the FSM exactly when recipes/steps open/close — no manual channel admin.

## 2. Message routing without context pollution

- Every channel message carries `for:` (handle or `@all`). A member's
  delivery (check_inbox) filters to `for: me | @all` — others' traffic
  never enters its context. This is today's kind/recipient filter, one
  field wider.
- Per-member cursors mean a resumed shell reads only what it hasn't
  seen, never the channel's history (replay stays the explicit opt-in).
- The injection seam (briefing delta / grounding brief) stays the ONLY
  bulk-context carrier; channels carry COORDINATION, not payloads.
  Rule of thumb in every guide: "if it's longer than a paragraph, it's
  an artifact + a link, not a message."

## 3. Spawn-by-mention

A mention of a non-live handle in a channel = the dispatch signal. The
watchdog's mention-scan resolves it: `@coder(rec-s3:a4)` → the existing
pool_spawn_worker path (deterministic, code-side — the LLM writes a
mention, never invents spawn plumbing). Mention of a live/parked handle
= wake (today's inbox-growth resume). The tools remain for the FSM's own
dispatch; mentions are the human-legible surface over them.

## 4. The user in the loop

The user is a member (`@operator`) of `#product` and any channel they
join. Role→user questions post in-channel tagging `@operator` (today's
ask_above, re-skinned); the user replies by tagging the role — broker
`answer`, delivered on the role's next wake (seconds, via watchdog).
Surface options, in order of build cost: (a) vault channel notes
(read-only, exists day one), (b) panel "Channels" view with a reply box
(the panel already has approvals plumbing), (c) the neuron-TUI stays the
PM DM. Start with (a)+(b).

## 5. Bisected skill guides (the anti-overshoot craft)

Two DISJOINT guide sets per role, enforced not requested:
- **Drive guides** (PM, Team Lead): plan, quantify, delegate, verify by
  reading — role scoping (EDP_ROLE_SCOPE=enforce) already strips edit
  verbs; the guide says it, the registry enforces it. A PM cannot edit
  code even if it wants to.
- **Craft guides** (Coder, QA): execute exactly the mentioned task in
  the mentioned thread; QA fixes inline per protocol; neither ever
  mentions/spawns (spawn verbs absent from their surface — exists).
Guides are rewritten in channel vocabulary from the canonical
commands/*.md — substitution layer like HARNESS.md, not new protocol.

## STATUS (2026-07-21 EOD): COMPLETE — P5 drill PASSED live

Full chain proven on the real stack (drill recipe-channels-drill-p5):
spawn → auto-membership → operator steer-mention from the panel →
scope-gated dispatch (seconds) → worker steer_ack'd immediately →
grounding → done-flowback in the channel (root cause found live:
BrokerMessage requires msg_id+ts; the publish omitted them and the
ValidationError was swallowed — now stamped + failure-logged). Every
message in the feed carries `for:` addressing. Backend = opencode
(codex evaluated: no messaging infra, no headless steering — possible
future spawner, not the runtime). Mention-dispatch honors
EDP_SPAWN_MODE. Suites: broker 25 / pool 263 / engine 1318.
Residual polish: FSM-side channel archive on step close; live soak of
lost-park fix under real load.

## STATUS (2026-07-21): P1 + P2 core BUILT, suites green

- Broker `ChannelStore` + `/v1/channels` CRUD (registry over ordinary
  inboxes; topic field = pinned brief). Broker suite 25 ✓.
- Engine `channels.py` (derivation + `addressed_to` for-filter) and
  `check_inbox(channel=...)` member reads with per-(channel,member)
  cursors — owner semantics unchanged by construction. Engine 1317 ✓.
- Pool: spawn-time membership registration (`_register_channel_
  membership`), watchdog `channels_tick` — member-addressed wakes
  (live steer → parked member resumes ≤5s) + mention-dispatch with
  visible over-cap `blocker` refusal. Pool 263 ✓ (wake + dispatch +
  refusal test-pinned). Empty registry = zero behavior change.
- Guides hardened: `docs/guides/channel-coordination.md` (the bisected
  four-laws guide, DRIVE vs CRAFT) + HARNESS.md channels section with
  the PM/Lead/Coder/QA/SME vocabulary.
- REMAINING: P3 user surface (panel Channels view; vault notes cover
  read-only today), FSM channel creation at step boundaries with
  pinned-brief topic updates, #product/#experts seeding, P5 live drill
  — still gated on verifying the a4 done-flowback defect post-restart.

## 6. Build phases (each independently shippable)

1. **P1 Channel model**: multi-member aliases + per-(channel,member)
   cursors + `for:` filter. Broker + cursor layer only. Tests: fan-out,
   no cross-member re-delivery.
2. **P2 Mention dispatch**: watchdog mention-scan → spawn/wake; FSM
   creates/archives channels at step boundaries.
3. **P3 User surface**: vault channel notes + panel Channels view
   (post/reply as @operator).
4. **P4 Role guides**: the bisected rewrite (PM/Lead/Coder/QA), pilot
   with one scripted drill per role.
5. **P5 Live drill**: one small recipe end-to-end in channels; measure
   context per shell vs today (the efficiency claim must be measured,
   not assumed).

## 7. Operator additions (2026-07-21) + Codex-CLI ground truth

Verified against the Codex CLI reference (learn.chatgpt.com developer
commands, fetched 2026-07-21):
- **There is NO inter-instance messaging infra in Codex CLI** (reference
  documents none). Channels stay OUR broker; codex/opencode are clients.
- **Headless mid-turn injection does NOT exist** (`codex exec` has no
  stdin/IPC steer; Tab/Enter steering is TUI-only). So LIVE steering =
  `kind=steer, for:@handle` lands in the working channel instantly and
  the craft protocol's existing tool-boundary inbox poll picks it up
  MID-ACTION (this is already worker.md behavior); visible shells can
  additionally be steered by typing in their TUI window. Never promise
  token-level interruption — boundary-level is the honest contract.
- **Session-bound headless confirmed**: `codex exec resume <SESSION_ID>`
  / opencode `--session <id> --continue`. Every agent = ONE session id
  for life (the pool already enforces this).
- **Missed upgrades worth noting**: `codex mcp-server` (Codex itself as
  an MCP tool a driving agent can consume), `/subagents` threads, and
  `codex cloud exec` (hosted tasks) — candidates, not commitments.

Additions to the model:
- **Specialist/Consult = dedicated role + channel**: `#experts` (PM,
  leads, and all SMEs). SMEs are addressable as `@sme-<domain>`; consult
  verdicts post there with `for:` the asker. Training stays the SME
  protocol; presence is the channel.
- **Planner differentiation**: leads are named by their step —
  `@lead-<step_id>` — and every `#team-<step>` channel's PINNED FIRST
  MESSAGE is that plan's grounding brief (posted by the FSM at channel
  creation, updated on revalidation). Brief visibility = channel topic,
  not a buried artifact.
- **Tool results ARE channel traffic**: every engine-published kind
  (done, grounding, steer, steer_ack, flowback/learning, blocker,
  crashed, plan_closed) renders in the owning channel as a message with
  `for:` the consumer (P2's kind→mention map). Nothing flows outside
  the channels; the channel IS the audit trail.
- **Hard caps**: EDP_MAX_TOTAL_SHELLS=10 absolute parallel ceiling
  (pool-enforced, panel-adjustable); mention-dispatch REFUSES past cap
  with a visible channel message, never queues silently. No fan-out
  primitive exists that can launch unbounded agents.

Non-goals: no new broker, no Discord itself, no change to FSMs/specs/
vault/caps. The messaging substrate stays OURS (codex/opencode CLIs are
clients of it, not the infra).

Open defects that gate P2 (from 2026-07-20): lost-park (fixed, verify
live), a4 done-flowback gap (unfixed — mention-wake depends on exactly
this delivery path; root-cause FIRST).
