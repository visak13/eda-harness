# Framework v8 — planning draft (whiteboard, 2026-08-22)

Status: DRAFT for review. Nothing here is implemented. Freeze before any code.
Supersedes the role/tool/object layout in DESIGN-v7 where they conflict.
Companion: `NEURON-COMMAND-REDESIGN.md` (findings that motivated this).

---

## 0. Principles

1. **Engineering team, not an agent swarm.** User = project manager. Neuron = board keeper.
   Curiosity = architect. Planner = team lead. Worker/reviewer = engineers. Sol = external
   consultant (adversary + visual authority). Acceptor = QA against the original words.
2. **Inversion of control.** No role decides what happens next; the **board** does. A role
   reads its ticket, does its one job, writes status + evidence on its ticket, and ends its
   turn. The board routes the consequences and emits the next instruction.
3. **Minimum command.** A slash command only (a) identifies the role, (b) arms the wake plane,
   (c) states the one job and its boundary, (d) names the skills it uses. Everything else is
   delivered by the board when it is needed.
4. **Bounded authority.** A role never overrides, assumes, or widens. Doubt is not reasoned
   away — it is *reported* through a skill (`/doubt`, `/pain`, `/deviation`) to the owner of
   that decision. Skills are the safety valves of IoC.
5. **Checkpoints, not a non-stop run.** The board stops for the user at defined gates:
   design sign-off, POC gate (novel work), story demo, adversarial findings, acceptance.
   Between gates the user can enter any shell at will; what they say there is written on the
   ticket by that shell.
6. **Tools own invariants; seats own judgment.** Tools validate structure, sequence, and
   capacity and return instructions/deltas. They never decide scope, taste, methodology or
   correctness. A refusal names the legal values; that is the documentation.
7. **Truth is the record.** One object (ticket) with an append-only ledger, status derived
   upward, constraints inherited downward by reference. Documentation and grounding are
   renders of the record. Shells are disposable; tickets are not.
8. **Framework-neutral wording.** Cards and skills describe the job and the boundary, never a
   person's preference. Defects in wording are fixed via `/pain` evidence, not by adding
   "always remember that…" lines.

---

## 1. Layers and what each owns

| Layer | Owns | Interface | Never |
|---|---|---|---|
| **User** | goal words, scope, money, sign-off, pacing, destructive acts; can enter any shell | talks in any shell; answers on tickets | — |
| **Board** (record + state machine) | tickets, ledger, derived status, ready queue, gates, capacity-bounded sprint | `reconcile`, `next_action`, CRUD | judge content |
| **Pool** | shells: spawn / liveness / resume / reap; sessions preserved per ticket | `pool` object (read), spawn/resume/reap verbs | know what a shell does |
| **Broker** | delivery of ticket events + messages to the owning shell; wake planes | `arm_wiring`, inbox, `post` | route by judgment |
| **Tools** | validation, composition (briefs, wiring), sequencing, deltas | MCP verbs, per role | hold policy text |
| **Skills** | bounded reactions: report doubt, report pain, file learning, demo, verify-done, OCAK, adversary | `/skill` invoked by the role when its trigger fires | drive flow |
| **Commands** | identity + wake plane + one job + skill list | `/role` at spawn | protocol, objects, rituals |
| **Roles** | judgment inside their concern | read ticket → do → write ticket | other roles' concerns |

Dependency direction (dependency inversion): **Roles → Skills → Tools → Board schemas.**
The board knows no role's prompt; roles know no board internals — only the ticket schema
and the instruction they receive. A new role is a card + a skill list + a toolset entry;
the board is untouched. A new work kind is a ticket body schema + an architect rule; the
cards are untouched.

---

## 2. Object layer

### 2.1 Ticket — the one work object (recursive, typed)

```
ticket
  id, kind, title
  parent_id | null           # root = epic (the user's goal)
  serves: [parent line ids]  # which lines of the parent this ticket exists for (required for non-root)
  depends_on: [ticket ids]
  owner_role, owner_session_id | null      # preserved for resume/fork (architect, team lead)
  status: drafted | designed | signed_off | ready | in_progress | in_review | blocked | done | partial | dropped
           # derived upward: a parent is in_progress if any child is; done when all children done + its own criteria met
  words: "<verbatim>"        # root only: the user's goal, whole. Children reference via serves.
  body: <kind-specific, see 2.2>
  criteria: [ {id, text, check: command|path|look|verdict, checked_by: reviewer|parent|acceptor|user} ]
           # written by the PARENT before work starts; the doer never edits them
  ledger: [ entry ]          # append-only, see 2.3
  artifacts: [ {id, path|url, form: image|file|url|app, note} ]
  budget: {tokens?, usd?, hours?}  estimate: {...}  spent: {...}
  gates: [ design_signoff | poc | demo | adversarial | acceptance ]   # which checkpoints apply
```

Root ticket = epic = today's "recipe". Story = today's "step"/"plan". Task = today's "action".
Same object; no separate recipe/plan/action/outcome/worklog types. Outcomes become the epic's
`criteria`. Worklog becomes the ledger.

### 2.2 Ticket kinds and bodies (architect-extensible registry)

| kind | body | typical gates |
|---|---|---|
| feature / enhancement | HLD, LLD, impact areas, interfaces touched, test strategy | design_signoff, demo, adversarial, acceptance |
| bug | symptom, reproduction, impact areas, likely fixes, regression risk | design_signoff (short), adversarial, acceptance |
| rnd | question, paths to try, libraries/candidates, success metric, stop condition | design_signoff, poc, acceptance |
| creative / asset | references, look spec (Sol-authored), measurable bars, review-by-eye plan | design_signoff, demo, acceptance |
| review (adversarial) | scope to attack, inputs, what counts as a finding | — (it is a gate) |
| chore | what, where, done-check | acceptance |

The architect chooses the kind for the epic and for each story; a team lead chooses kinds
for tasks within the story's kind. New kinds = new body schema + one architect rule.

### 2.3 Ledger entry types (append-only, every entry has ts, by_role, by_session)

`decision` (text, supersedes?) · `steer` (user words verbatim, scope: this ticket) ·
`question` (to: user|architect|parent, text, answered_by_entry?) · `answer` ·
`status_change` (from, to, reason) · `evidence` (criterion_id, what ran, result, artifact?) ·
`finding` (by adversary/reviewer, severity, obvious|scope) · `learning` (reusable, ratified?) ·
`deviation` (from design, why, approved_by?) · `pain` (framework defect) · `note`.

Rules: decisions propagate **as deltas** to affected children (by `serves`); steers never widen
scope (a widening becomes a `question` to the architect via the board); status is derived.

### 2.4 Other objects (read via the same CRUD)

- **pool** (read-only): `{capacity, shells:[{session_id, role, ticket_id, state: alive|stalled|dead, last_output_ts}]}`
- **message**: `{id, kind, from, to, ticket_id, body, ts, replied_by?}` — inbox = `query(message, to=me)`
- **instruction** (returned by `next_action`, not stored): `{kind, ticket_id, verb, args, why, guide?}`
- **brief** (generated at spawn, not stored): root words → decisions in force (chain) → this ticket
  (body + criteria) → specialist doc pointer. Delivered whole; never truncated (size is bounded
  by construction: decisions are deltas, not essays).

CRUD: `describe(type)`, `read(type,id,detail)`, `query(type,filter)`, `create(type,body)`,
`update(type,id,patch)`, `append(ticket,entry)`. Every write validated against the schema; a
refusal returns the legal shape. Snapshots/versions invisible to roles.

---

## 3. The board (state machine over tickets)

```
drafted ──architect writes body+criteria──▶ designed ──user sign-off──▶ signed_off
signed_off ──deps met + capacity──▶ ready ──spawn owner──▶ in_progress
in_progress ──doer records evidence for all criteria──▶ in_review ──checker pass──▶ done
in_review ──checker gaps──▶ in_progress            any ──▶ blocked (question open) ──answer──▶ back
any ──architect/user──▶ dropped                    epic: all stories done + acceptance pass ──▶ done | partial
```

Gates (the board stops and emits a user-facing instruction; the owning shell asks the user
directly, records the answer):

| gate | when | who asks | recorded as |
|---|---|---|---|
| design_signoff | epic/story `designed` | architect (its shell) | `steer`/`answer` + status→signed_off |
| poc | rnd/novel story, after POC task done | team lead (its shell) | `answer`: continue / pivot / stop |
| demo | story reaches in_review with a showable artifact | team lead | `answer` |
| adversarial | review story findings of type `scope` | team lead (review story) | `answer` per finding |
| budget | spend crosses threshold | neuron | `answer`: extend / descope |
| acceptance | epic all-done | acceptor | verdict entry |

`next_action` = the ready queue + the open gates for the calling role's tickets, one
instruction at a time, with the verb and args filled in. `reconcile` = sync record ↔ pool ↔
broker and return the **delta** (what changed since this caller's last reconcile), nothing more.

---

## 4. Data flow, beat by beat

**Boot (any role):** `whoami()` → identity (role, session, ticket_id). `arm_wiring()` → returns
`monitor_cmd` + `cron` → run once each. Read your ticket (`read(ticket, me)`) — that is your
world. End of boot.

**Epic open:** user types the goal to the neuron. Neuron: `create(ticket, kind=epic,
words=verbatim)` → board: `drafted` → `next_action` → `SPAWN(architect, epic)`.

**Comprehension (architect shell):** reads words + codebase → classifies kind → drafts body →
`/ocak` on the draft → open questions → asks the user *in its own shell* (gate design_signoff
not yet; these are clarifications) → writes answers as `answer` entries → right-sizes →
creates child stories with bodies + criteria (+ last story kind=review) → sets epic criteria →
status→designed → board emits gate `design_signoff` → architect shows the design verbatim to
the user in its shell → user signs → `steer` entry + status→signed_off → architect's session id
stays on the epic; shell closes.

**Sprint:** board: stories with deps met → `ready` (capacity-bounded) → neuron wake:
`reconcile` delta = ["story s1 ready", "s2 ready"] → `next_action` → `SPAWN(team_lead, s1)` …

**Story (team lead shell):** reads story + chain brief → picks methodology (`/methodology`) →
writes tasks with criteria (poc first if novel) → `SPAWN(engineer, t1)` … → monitors its
tasks' events → demo gate when showable → status flows up.

**Task (engineer shell):** reads task → does it → `evidence` per criterion (command run, path,
artifact) → status→in_review → reviewer checks against criteria → pass → done. Learned
something → `/learn` entry.

**Steer mid-flight (user enters any shell or tells the neuron):** the shell writes `steer` on
its ticket. Board classifies by the ticket's scope: within → owner continues; widening →
`question(to: architect)` → board `SPAWN(architect, fork=epic.owner_session_id)` →
re-comprehension of the affected slice → re-sign-off gate → children updated via deltas.

**Reach-back (any role in doubt):** `/doubt` → `question` entry addressed to the owner of that
decision (user / architect / parent) → ticket `blocked` → owner's monitor wakes with it → answer
entry → unblocked. The neuron is not in the path unless the question is about the board itself.

**Dead/stalled shell:** pool event → neuron wake → `next_action` → `RESUME(session)` or
`RESPAWN(ticket)`; ticket keeps its ledger, nothing lost.

**Adversarial story (last):** team lead of the review story calls Sol (`/adversary`) on the
whole delivery → `finding` entries: obvious → fixed inline by engineers of that story; scope →
gate adversarial, user answers in that shell → one confirmation round → done.

**Acceptance:** epic all stories done → `next_action` → `SPAWN(acceptor, epic)` → acceptor walks
the delivery against `words`, checks the commit, records verdict → pass → epic done; gaps →
new/updated stories (via architect fork) or epic partial.

**Close:** neuron `next_action` → `CLOSE` with the disarm list → executes → epic read-only;
design doc + ledger render as the product record.

**Compaction/restart (any role):** boot again; `whoami` + ticket = full re-ground. No digest
prose; no "rewire block" — `arm_wiring` is idempotent.

---

## 5. Commands (the full text of each — minimum to get the ball rolling)

Every command has the same skeleton: **Boot · Job · Boundary · Skills**. Boot is identical
(whoami, arm_wiring, read ticket); it is repeated in each card because each card is read
alone.

```
# /neuron — board keeper
Boot: whoami() → arm_wiring() → run the returned monitor once and cron once.
Job: open the epic with the user's words verbatim (create ticket kind=epic) or resume it.
     On every wake: reconcile() → if changed, next_action() → do the one thing it names.
Boundary: you design, decide, build and review nothing. Dead or stalled shell → recover it.
          Questions go to their owners, not to you; the board is your only concern.
Skills: /pain (framework fights you) · /doubt (instruction contradicts the record).
```
```
# /architect — comprehension (curiosity seat)
Boot: whoami() → arm_wiring() → read your ticket (the epic, or the slice you were forked for).
Job: read the words and the codebase. Classify the kind. Draft the design body. Audit it
     (/ocak). Ask the user in this shell until no gap remains; write every answer on the ticket.
     Right-size. Write child stories with bodies and checkable criteria; the last story is the
     adversarial review. Present the design for sign-off when the board asks.
Boundary: you do not build. You do not narrow or drop a named requirement silently — that is a
          question. Fidelity: when re-opened, diff the record against your design.
Skills: /ocak · /doubt · /pain · /learn.
```
```
# /team-lead — one story (planner seat)
Boot: whoami() → arm_wiring() → read your story and its brief.
Job: choose the methodology (/methodology). Write tasks with checkable criteria; a POC task
     first when the work is novel. Spawn engineers and reviewers; steer them through their
     tickets. Show the user the result in this shell at the demo gate. Keep story status true.
Boundary: craft is yours; design changes go to the architect (/deviation); scope goes to the
          user (/doubt). Other stories are not yours.
Skills: /methodology · /demo · /deviation · /doubt · /pain · /learn · /adversary (review story only).
```
```
# /engineer — one task (worker seat)
Boot: whoami() → arm_wiring() → read your task and its brief.
Job: meet each criterion; record evidence per criterion (what ran, result, artifact). Done is
     decided by the checker, not by you.
Boundary: no scope, no design; blocked → /doubt. Reusable lesson → /learn.
Skills: /verify (self-check before handing over) · /doubt · /learn · /pain.
```
```
# /reviewer — one verdict
Boot: whoami() → arm_wiring() → read the task, its criteria, its evidence.
Job: check each criterion yourself. Fix inline only what you can re-verify. Record pass or
     gaps with evidence.
Boundary: the criteria are the law; scope is not yours.
Skills: /verify · /doubt · /pain.
```
```
# /acceptor — the epic verdict
Boot: whoami() → arm_wiring() → read the epic: words, criteria, stories, artifacts.
Job: walk the delivery yourself from a cold seat; check the commit; judge the whole against
     the words. Record pass, or gaps most severe first. Fix only trivial, re-verifiable defects.
Boundary: you owe nobody a pass; a translation (criteria) can be met while the words are not.
Skills: /verify · /pain.
```
```
# /specialist — product knowledge
Boot: whoami() → arm_wiring() → read the learning queue for your domain.
Job: compile ratified learnings into the domain doc; keep it short and current.
Boundary: you never touch tickets.
Skills: /pain.
```

No card mentions: other roles' protocols, object schemas, wiring internals, phases, output
style, the user's preferences. The board delivers those when relevant.

---

## 6. Skills (when to trigger · what to do · what it writes)

Skills are the bounded reactions that keep IoC honest. Each skill file has exactly three
sections: **Trigger**, **Do**, **Writes**.

| skill | Trigger | Do | Writes |
|---|---|---|---|
| `/doubt` | you would have to assume, override, narrow, or guess on a decision you do not own | name the decision owner (user / architect / parent); post the question in one line with the options you see; end the turn; your monitor wakes you with the answer | `question` entry; ticket → blocked |
| `/pain` | a tool refuses against the record, a verb is missing, a wake never comes, an instruction contradicts reality | one structured line (symptom, expected, evidence, workaround); continue | `pain` entry + pain log |
| `/deviation` | the design cannot be followed as written (wrong assumption, better path) | describe the deviation and why; route to the architect; do not proceed on the deviated path until answered unless reversible and noted | `deviation` entry |
| `/learn` | you found something reusable beyond this ticket | one entry: what, where it applies, evidence | `learning` (unratified) |
| `/verify` | before handing a task to review, or when a checker judges | for each criterion: run its check, record the result; prose is not evidence | `evidence` entries |
| `/demo` | a story has a showable artifact (image, UI, app, doc) | show it to the user in this shell; record the reaction verbatim | `artifact` + `answer` |
| `/ocak` | architect has a draft design | the 4 audit questions on the draft; findings change the draft or become questions | `note`/`question` |
| `/methodology` | team lead starts a story | pick from the strategy library (poc-then-build, research-then-build, diagnose-fix-verify, walking-skeleton, …) by the story kind and novelty; record the choice | `decision` |
| `/adversary` | review story starts, or a story owner wants a hostile read | call Sol with the delivery scope; classify each finding obvious vs scope; obvious → fix tasks; scope → gate | `finding` entries |
| `/handoff` | a shell is about to close or compact with work in flight | write status, what is done, what is next, open questions — on the ticket | `note` |

Skills never decide flow; they write entries the board reacts to.

---

## 7. Tools (per role, minimal; outputs are instructions or deltas)

| verb | roles | in → out |
|---|---|---|
| `whoami` | all | → role, session, ticket_id, inbox |
| `arm_wiring` | all | → monitor_cmd, cron (role-specific streams composed server-side) |
| `reconcile` | neuron, team-lead | → `{changed, delta:[...]}` since this caller's last call |
| `next_action` | neuron, team-lead | → one instruction `{kind, ticket_id, verb, args, why, guide?}` |
| `describe/read/query/create/update/append` | all (scoped by role to its tickets) | CRUD; refusals return the legal shape |
| `spawn` | neuron (architect, team-lead, acceptor), team-lead (engineer, reviewer) | ticket_id → session; brief generated from the chain |
| `resume` / `reap` | neuron, team-lead | session → ok |
| `post` | all | message to a ticket owner (question/answer/steer) |
| `consult_sol` | team-lead, architect | question + context → Sol reply (adversary / visual) |
| `close` | neuron | epic → disarm list |

Dropped from the neuron: everything else in today's 61 (record_*, fold/supersede, budget_status,
guides, specialist verbs, broker_send, status_ping …). Budget and guides ride on instructions.

---

## 8. Monitor / cron contract (what each role's wake plane carries)

| role | monitor carries | cron |
|---|---|---|
| neuron | ticket status changes in the epic, pool deaths/stalls, open gates for neuron, questions addressed to the board | backstop, 60 min: reconcile; silent if no delta |
| architect | answers to its questions, fork requests | 30 min backstop |
| team-lead | its tasks' status changes, questions from its engineers, answers from user/architect, demo/poc gate opens | 30 min |
| engineer / reviewer | answers to its questions, steers on its ticket | 30 min |
| acceptor | answers to its questions | 30 min |

Cron never duplicates a monitor wake: the cron prompt is "reconcile; if no delta, end".

---

## 9. Why planning will now reflect in the work

- Criteria are written by the parent **before** work, in checkable form, and the doer cannot
  edit them: what was planned is what is checked.
- The architect's design is the body of the ticket the team lead reads; the team lead's tasks
  `serve` lines of it; the brief at spawn is generated from that chain — nothing is re-typed.
- Deviations and widenings are ticket entries routed to the design owner, not silent choices.
- Gates (sign-off, POC, demo, adversarial, acceptance) put the user in front of the work at
  the points where drift is cheapest to catch; every shell is open to the user between them.
- The architect session is preserved and forked for every re-comprehension: the same mind
  that planned judges the change.

---

## 10. Freeze checklist (review before any code)

- [ ] Ticket schema + kind bodies + ledger types accepted
- [ ] Board states, transitions, gates accepted
- [ ] Seven cards accepted verbatim
- [ ] Skill table accepted (names, triggers)
- [ ] Tool table accepted (verbs per role, outputs)
- [ ] Monitor/cron contract accepted
- [ ] Migration: map today's recipe/step/plan/action/outcome/worklog → ticket; today's 61→10 verbs
- [ ] Live test plan: one small epic end-to-end (feature kind), one bug kind, one rnd kind

---

## 11. Addendum (round 2): names, humans in the loop, SMEs, visibility, distribution

### 11.1 Naming (replaces the old vocabulary everywhere — commands, tools, objects, docs)

| old | new | why |
|---|---|---|
| neuron | **coordinator** (`/coordinator`) | keeps the board moving; nothing else |
| curiosity | **architect** (`/architect`) | comprehension, design, OCAK, stories, fidelity |
| agentic-plan / planner | **lead** (`/lead`) | owns one story |
| worker | **engineer** (`/engineer`) | owns one task |
| reviewer | **reviewer** (`/reviewer`) | unchanged |
| specialist | **sme** (`/sme`) | subject-matter expert, bound to tickets by domain |
| acceptor | **qa** (`/qa`) | acceptance against the words |
| Sol / bridge | **consultant** (`consult`) | external adversary + visual authority |
| user (foreground shell) | **owner** (`/owner`) | the PM's own shell: a participant with an inbox |
| recipe / step / plan / action / outcome / worklog | **ticket** — epic / story / task; criteria; ledger | one object |
| pain | `/pain` | unchanged |
| arm_wiring / monitor | **subscribe** → the shell's **feed** | the feed is the messaging surface |

### 11.2 Participants — humans and agents are the same thing to the broker

```
participant
  id (e.g. owner, alice, architect@epic-12, lead@s3)
  type: human | agent
  roles_allowed: [...]            # humans: owner | sme | reviewer | qa (any they register for)
  inbox, feed subscription
  location: pool_id | remote      # where its shell runs (or none for a pure human on the web board)
```

- Every shell — including the owner's — runs `subscribe()` → a feed. The feed carries the
  ticket events and messages addressed to that participant. The owner's feed is where
  questions from the architect, SMEs, leads and QA arrive; the owner answers **in the owner
  shell**; the answer is posted on the asking ticket and wakes the asker.
- Tagging: `@alice` in any shell's `post` (or in a ledger entry) routes a message to alice's
  inbox; her feed wakes her shell wherever it runs. Humans can be assigned tickets (e.g. a
  human SME, a human reviewer) exactly like agents.
- The owner shell's card (`/owner`) is therefore: subscribe → read the feed → answer
  questions / sign gates / steer / tag teammates. The coordinator still keeps the board; the
  owner is never required to relay.

### 11.3 SMEs — consistency before work starts

- The architect, while designing the epic, names the **knowledge domains** the work touches
  (e.g. "procedural conifer geometry", "FastAPI service conventions", "Unreal import").
- For each domain the board opens a `knowledge` ticket (kind=knowledge, body: scope, sources,
  measurable bars) assigned to an SME participant (agent, or a tagged human teammate).
- The SME compiles the **domain doc** from the codebase, prior ratified learnings, and the
  references named in the epic's words — including any process rule the words carry for that
  domain. The doc is the ticket's artifact; the ticket is done when the architect's fidelity
  check passes (named requirements of the words are present).
- **Gate `knowledge_ready`**: a story whose domains have no done knowledge ticket cannot become
  `ready`. Every engineer/reviewer brief for that story carries the domain doc by reference.
- During execution SMEs are reachable via `/doubt` (domain questions); at epic close SMEs
  ratify `learning` entries from their domain into the doc. Domain docs persist across epics —
  they are the product documentation tier.

### 11.4 Visibility — one call shows a shell everything relevant

- `context()` (any role): returns the caller's ticket, the chain brief (root words → decisions
  in force → this ticket body + criteria), attached domain docs (by reference + summary line),
  open questions on this ticket, and the last N ledger entries. This is THE grounding call;
  boot is `whoami → subscribe → context`.
- `board(epic_id)` (any participant): rendered tree of tickets with status, owner, open gates —
  the human-readable standup. The owner shell uses it; a web board renders the same call.
- `find(query)`: search across tickets, ledger entries, domain docs, artifacts — scoped to the
  caller's epic by default, all epics for architects/SMEs (OCAK Observation needs it).
- No raw file paths anywhere in objects; artifacts are references into an artifact store/git.

### 11.5 Distribution — machine-independent, dockerized

```
central (docker compose, one stack per organisation):
  board     — tickets + ledger + state machine + CRUD/instruction API (reconcile/next_action)
  broker    — inboxes, feeds (subscriptions), tagging, delivery receipts
  registry  — participants, pools, seats/models, auth tokens
  artifacts — object store for renders/files (or git refs)
  web-board — read-only board + feed view for humans without a shell (later)

per machine (any teammate, anywhere):
  pool-runner — registers with the registry, spawns/resumes/reaps shells locally, reports
                liveness; can be capacity-limited per machine
  mcp         — thin client: every tool call is an HTTP call to board/broker/registry
  shells      — Claude/Codex shells with EDP_PARTICIPANT token; no local state except the
                transcript
```

- Identity = participant token; scope = the tickets that participant owns; the pool-runner
  is the only machine-specific component. A human teammate with no pool still has an inbox and
  feed (web board or a bare `/owner`-style shell).
- Spawns are placed by the registry: the coordinator asks `spawn(lead, s3)`; the registry picks
  a pool with capacity (local by default, remote if configured).

### 11.6 Updated cards affected by this addendum

```
# /owner — the project manager's shell
Boot: whoami() → subscribe() → run the returned feed once.
Job: read the feed. Answer questions here; sign gates here; steer here; tag teammates (@name).
     Everything you say is written on the ticket that asked.
Boundary: the board moves itself; you never need to relay.
```
```
# /sme — one knowledge domain
Boot: whoami() → subscribe() → context().
Job: compile the domain doc from the codebase, prior ratified learnings and the sources the
     epic names; keep every named bar measurable. Answer domain questions on tickets. At epic
     close, ratify learnings into the doc.
Boundary: you never touch work tickets; the doc is your only artifact.
Skills: /doubt · /learn · /pain.
```
Coordinator, architect, lead, engineer, reviewer, qa: as §5 with `arm_wiring`→`subscribe`,
`read ticket`→`context()`, and the architect's Job gaining "name the knowledge domains".

### 11.7 Additions to the freeze checklist
- [ ] Names (§11.1) accepted — then renamed everywhere in one pass, no aliases
- [ ] Participant model + owner shell + tagging accepted
- [ ] SME flow + `knowledge_ready` gate accepted
- [ ] `context` / `board` / `find` accepted as the visibility contract
- [ ] Central-vs-per-machine split accepted; docker compose for board/broker/registry/artifacts
