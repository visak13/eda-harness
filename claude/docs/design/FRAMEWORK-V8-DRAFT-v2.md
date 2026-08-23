# Framework v8 — planning draft v2 (complete overhaul, 2026-08-23)

Status: DRAFT for review and freeze. No code. Supersedes `FRAMEWORK-V8-DRAFT.md` (v1) where
they differ. Findings that motivated this: `NEURON-COMMAND-REDESIGN.md`.

What v2 corrects from v1:
- IoC/DI means *the framework injects a role's working context at runtime*; it does not mean
  the board orders the agent around. `next_action`-as-command is gone.
- Objects are small POJOs with typed fields, each with IS-A / HAS-A / USES-A / PRODUCES-A,
  an owner, and CRUD. The ledger is not inside the ticket; it is separate objects the ticket
  HAS-A.
- Planner+worker merge into **engineer**, planner+reviewer into **reviewer**: one agent
  completes a story end-to-end with a high-level strategy and low-level strategies, fanning
  out or invoking other models when useful.
- SME redefined as the **craft author**: strategies + domain docs written as intent-with-why
  so a lower-tier executing model can still use its brain.
- Architect produces a thorough design doc: problem types, communication types, who does what
  (including the consultant for creative/UI), not an abstract outline.
- Ticketing on a standard self-hosted tool (Plane) with a portal; our services adapt to it.

---

## 1. Vocabulary (one rename pass, no aliases)

| concept | name | command |
|---|---|---|
| the project manager (human) | owner | `/owner` |
| keeps the board moving | coordinator | `/coordinator` |
| comprehension + design + stories | architect | `/architect` |
| craft author (strategies, domain docs) | sme | `/sme` |
| completes a story end-to-end | engineer | `/engineer` |
| independent verdict on a story/task | reviewer | `/reviewer` |
| acceptance against the owner's words | qa | `/qa` |
| external model (GPT Sol): adversary, creative/UI | consultant | tool `consult` |
| work item | ticket (epic / story / task) | — |
| written knowledge | doc (design, strategy, domain, report) | — |
| conversation on a ticket | thread / message | — |
| what a shell receives to wake | feed | — |
| machine-local shell lifecycle | pool | — |
| the services together | board | — |

---

## 2. The DI model — how a role gets its working context

A role is a class. Its command is the class declaration: what it IS, what it HAS (injected),
what it USES (injected), what it PRODUCES (its outputs), and its operating protocol. The
framework is the container: at spawn it resolves every HAS-A and USES-A and hands them to
the shell through one call, `context()`. The agent then works autonomously; the framework
offers signals (feed), readiness (board), validation (schemas, transitions), search, and
human gates. It never issues orders.

```
Role (card)                         Container (framework) resolves at runtime
  IS-A    <role>                      → identity: participant, session, allowed bundles
  HAS-A   ticket, thread, docs…       → context(): the ticket, its thread, linked docs, criteria
  USES-A  tool bundles, strategies    → role-scoped MCP bundles; strategy docs for the ticket's kind
  PRODUCES-A docs, messages, events,  → write verbs validated against the schemas
            artifacts, status
  PROTOCOL  engage owner / messaging  → feed + thread + gates
            / tickets / docs
```

**Exactly what the framework enforces (invariants) — and nothing else:**
1. Schema: every object write is typed; a bad write returns the legal shape.
2. Identity/scope: a participant writes only objects it owns or is assigned; reads are open
   within its epic (architect/sme/qa: all epics).
3. Legal transitions: a ticket cannot be `done` without evidence for every criterion and a
   verdict from someone other than the doer; an epic cannot be `done` without qa `pass`.
4. Gates that need a human: design sign-off, POC, demo, adversarial scope finding, budget,
   acceptance — the board marks the gate open and notifies; a human answers in their shell.
5. Capacity: spawns beyond pool capacity queue; nothing is silently dropped.
6. Continuity: sessions are preserved per ticket; `context()` is complete and untruncated.

**What the agent controls:** everything else — how to read, what to ask, which strategy to
apply, whether to fan out, when to demo, how to write evidence, when to call the consultant.
Signals are suggestions; the agent may disagree and say why (a message), never silently.

**Framework-neutral wording — precise definition.** A card, skill, tool description, or guide
is framework-neutral when it (a) is written in the present tense about the role/object/tool
itself, (b) states responsibilities, dependencies, outputs and protocol, (c) states a rule only
together with its purpose ("write evidence per criterion so the reviewer can re-run it"), and
(d) contains no incident history, no person, no "remember that…", and no rule whose only
justification is a past defect. A defect is fixed in the object/tool/doc that caused it.

---

## 3. Objects — POJOs (each ≤ 7 fields, typed, owned, with CRUD)

All objects: `id: str`, `created_at: datetime`, `created_by: participant_id`. Not repeated below.

### 3.1 Participant
```
type: human | agent
role: owner | coordinator | architect | sme | engineer | reviewer | qa | consultant
handle: str           # @name for tagging; also the inbox address
location: pool_id | none
model: str | none     # agents only
```
IS-A actor. HAS-A feed, inbox. USES-A pool. PRODUCES-A messages, objects it owns.
Owner: registry. CRUD: create (register), read, query, update(location/model).

### 3.2 Ticket
```
kind: epic | story | task
work_type: feature | bug | rnd | creative | review | knowledge | chore
title: str
parent_id: ticket_id | none
status: drafted | designed | signed_off | ready | in_progress | in_review | blocked | done | partial | dropped
assignee: participant_id | none
design_ref: doc_id | none     # the doc that says WHAT (architect's design for epic/story; engineer's plan for task)
```
IS-A work item. HAS-A criteria[], thread, docs (via Link), artifacts (via Link), events.
USES-A strategies (via design_ref → strategy refs). PRODUCES-A nothing itself.
Owner: architect creates epic/story; engineer creates task; status derived upward by the board.
CRUD: create, read, query, update(status/assignee/design_ref). The epic's `title` is the
owner's words verbatim; the epic's design doc repeats them in full.

### 3.3 Criterion
```
ticket_id: ticket_id
text: str
check: command | path | look | verdict     # how it is verified
checked_by: reviewer | qa | owner
evidence_ref: doc_id | none                # report doc that carries the result
verdict: pending | pass | fail
```
IS-A definition of done. Written by the ticket's parent owner before work starts; the doer
never edits it. CRUD: create (parent), read, update(evidence_ref/verdict by checker only).

### 3.4 Doc
```
doc_type: design | strategy_hl | strategy_ll | domain | report | note
title: str
body_md: str            # markdown; a design body follows the template for its work_type
version: int            # every update creates a new version; old versions readable
owner_role: architect | sme | engineer | reviewer | qa | owner
scope: epic_id | domain_name | global
```
IS-A knowledge unit. HAS-A versions. USES-A nothing. PRODUCES-A nothing.
Linked to tickets via Link. CRUD: create, read(version?), query(doc_type/scope/search),
update (new version; diff kept). Docs are the *only* place prose lives.

Design doc template (architect, per work_type): words (verbatim) · problem statement ·
problem types present (e.g. geometry + rendering + tooling) · solution outline (HLD/LLD or
impact+likely fixes or R&D paths or look spec) · work breakdown: stories with who-does-what
(engineer / reviewer / consultant for creative-UI / human teammate) and which strategies ·
communication plan: which decisions come to the owner, which to the architect, which the
engineer owns · knowledge domains needed (→ sme) · acceptance criteria for the epic · risks.

### 3.5 Link
```
from_id: ticket_id | doc_id
to_id: doc_id | artifact_id | ticket_id
relation: designed_by | uses_strategy | uses_domain | evidence_for | blocks | produced
```
IS-A typed edge. Lets a ticket HAS-A docs/artifacts without embedding them. CRUD: create,
query(from/to/relation), delete.

### 3.6 Message (in a Thread = all messages with the same ticket_id)
```
ticket_id: ticket_id
to: participant_id | role | "@handle" | none   # none = thread note for anyone on the ticket
kind: question | answer | steer | status | finding | deviation | note
text: str
reply_to: message_id | none
```
IS-A unit of communication. PRODUCES-A a feed item for `to`. CRUD: create, read, query.
The thread is the a2a channel for a ticket; nothing is communicated outside it.

### 3.7 Event (emitted by the board; read-only)
```
subject_id: ticket_id | doc_id | participant_id
kind: status_changed | gate_opened | gate_answered | assigned | doc_updated | shell_dead | shell_stalled
data: dict              # small: from/to, gate name, version
```
IS-A audit record + feed source. CRUD: query only.

### 3.8 Artifact
```
form: image | file | url | app | repo_ref
uri: str                # artifact store / git ref — never a machine path
note: str
```
IS-A produced thing. Linked to tickets/docs via Link. CRUD: create (upload), read, query.

### 3.9 Session
```
participant_id, ticket_id, pool_id
state: alive | stalled | dead | parked
resume_token: str       # preserved for fork/resume
last_output_at: datetime
```
IS-A running or parked shell. Owner: pool. CRUD: read, query; spawn/resume/park/reap verbs.

### 3.10 Feed (not stored: the subscription a shell runs)
A merged stream for one participant: messages `to` it, events on its tickets, gate openings it
must answer, shell deaths of its children. Delivered by `subscribe()` as a monitor command;
cron backstop reconciles only if the monitor is stale.

Ten objects. Nothing else. The v1 "ledger" is Message + Event + Doc(report) + Criterion;
the v1 "recipe/plan/action/outcome/worklog" is Ticket + Criterion + Doc + Message.

---

## 4. Ticketing tool: Plane (self-hosted) — decision and drawbacks

Use Plane Community Edition (docker compose, AGPL) as the ticket store and portal; run its
official MCP server self-hosted. Mapping: Plane *project* = one product/codebase; *issue* =
ticket (epic/story/task via parent links); *state* = our status set (custom states allowed);
*cycle* = sprint; *module* = epic grouping; *labels* = work_type/domain; *pages* = docs
(design/strategy/domain) if we want them in the portal; *comments* = thread; *webhooks* →
our broker (events). Official MCP exposes issues/cycles/modules/pages/worklogs (30+ tools) and
has an @mention agent framework.

Drawbacks to accept or design around:
- Custom fields are limited in CE → typed bodies live in our Doc store and are linked from
  the issue (description carries the summary + link), or in Plane Pages.
- Plane's MCP OAuth callback must be reachable over HTTPS → a reverse proxy with a cert even
  on LAN (or a tunnel); alternatively agents use our thin adapter over Plane's REST API with
  an API key (simpler, role-scoped, and our tool descriptions stay ours).
- State machine guards (e.g. "done needs evidence") are ours, not Plane's → the board adapter
  validates before it writes to Plane, and a webhook-driven reconciler flags any edit made in
  the portal that violates a guard (posts a message on the ticket rather than reverting).
- Vendor shape: Plane issues have their own field set; we keep our 10-object model as the
  agent-facing contract and map, so Plane can be swapped (Gitea/Forgejo issues if git hosting
  is wanted; OpenProject; Jira DC) without touching cards.

Recommendation: agents talk to **our** adapter tools (role-scoped, self-describing); humans
use the Plane portal and/or their `/owner` shell; webhooks keep the feed live.

---

## 5. Roles as objects (the cards — complete text)

Each card: IS-A / HAS-A / USES-A / PRODUCES-A / PROTOCOL (how to engage the owner, use
messaging, use tickets, use docs) / SKILLS. Boot is identical for every role and is the first
line: `whoami() → subscribe() → context()`; run the returned monitor once and cron once.

```
# /owner — project manager (human shell)
Boot: whoami() → subscribe(); run the returned feed monitor once.
IS-A   participant(type=human, role=owner)
HAS-A  feed (questions, gates, demos, findings addressed to you); the board view (board(epic))
USES-A messages (answer, steer, tag @teammate); docs (read designs/reports)
PRODUCES-A answers, steers, sign-offs — each written on the ticket that asked
PROTOCOL  answer in this shell; the asker wakes on it. Sign gates here. Tag a teammate to hand
          them a ticket or a question. You never relay; the board moves itself.
```
```
# /coordinator — board keeper
Boot: whoami() → subscribe() → context().
IS-A   participant(role=coordinator) for one epic
HAS-A  the epic ticket; its feed (status events, gate openings, shell deaths); pool view
USES-A board(epic) for readiness; spawn/resume/reap; messages
PRODUCES-A spawns and recoveries; one status message on the epic thread when the picture changes
PROTOCOL  open the epic with the owner's words verbatim (create ticket kind=epic) or resume it.
          When the feed shows a story ready, assign and spawn its engineer; a story in_review,
          spawn its reviewer; the epic all-done, spawn qa; a dead or stalled shell, resume it.
          Keep the board true; design, craft and scope are not yours — route a question to its
          owner's thread. Budget threshold → gate to the owner.
SKILLS /doubt · /pain
```
```
# /architect — comprehension and design
Boot: whoami() → subscribe() → context().
IS-A   participant(role=architect), session preserved on the epic (forked for re-comprehension)
HAS-A  the epic ticket (words verbatim), the codebase, prior design docs (find), domain docs
USES-A docs (create design), tickets (create stories + criteria), messages (ask the owner),
       /ocak, consult (second opinion)
PRODUCES-A the design doc (template §3.4), stories with criteria and who-does-what, knowledge
           tickets for needed domains, fidelity verdicts on re-comprehension
PROTOCOL  read the words and the code first. Classify the work_type. Draft the design; audit it
          with /ocak; ask the owner here, one question per message, until no gap remains; write
          answers on the epic thread. Size honestly (one story when it fits one sitting). The
          last story is the adversarial review. Name the knowledge domains. Present the design
          for sign-off when complete; iterate in this shell. When forked later, diff the record
          against your design and rule on the change.
SKILLS /ocak · /doubt · /pain · /learn
```
```
# /sme — craft author for one domain
Boot: whoami() → subscribe() → context().
IS-A   participant(role=sme, domain=<name>); human or agent
HAS-A  the knowledge ticket, the codebase, prior domain docs and learnings (find), the epic design
USES-A docs (create/update strategy_hl, strategy_ll, domain), messages (answer domain questions)
PRODUCES-A the domain doc and the strategies the engineer/reviewer/qa for this domain will use;
           ratified learnings folded into them at epic close
PROTOCOL  write craft as intent + why + example, never as bare rules, so the executing model can
          adapt (e.g. "structured output so the caller can parse it — pydantic where the model
          supports it, plain JSON where it does not"). Name the measurable bars the words carry.
          Keep docs short and current. Answer questions on tickets in your domain. A learning
          that changes a strategy is a new doc version.
SKILLS /doubt · /learn · /pain
```
```
# /engineer — completes one story end-to-end
Boot: whoami() → subscribe() → context().
IS-A   participant(role=engineer) assigned one story (or task)
HAS-A  the story, its design slice and criteria, the strategy_hl and strategy_ll docs for its
       work_type and domains, the domain docs, the thread
USES-A the codebase and tools; fan-out (subagents for parallel tasks); consult (the consultant
       for creative/UI/visual work or a hostile second read); messages; docs (plan, report)
PRODUCES-A tasks (when you split), a plan doc (which strategy, why, the steps), evidence per
           criterion in a report doc, artifacts, status on the story
PROTOCOL  choose the high-level strategy for the story (poc-then-iterate · diagnose-with-logs-
          and-traces-then-fix · research-then-build · walking-skeleton · refactor-in-steps …)
          and record the choice and why. Apply the low-level strategies as craft (design
          patterns, SOLID, DDD where it fits, logging, resource handling, documentation,
          tests). Split into tasks only for parallelism or a resume point; fan out to subagents
          for them. Show the owner an artifact as soon as there is one to look at (/demo). A
          design deviation → /deviation to the architect; a scope question → /doubt to the
          owner; blocked → say so on the thread. Write evidence per criterion so the reviewer
          can re-run it; hand over with in_review.
SKILLS /methodology · /demo · /verify · /deviation · /doubt · /learn · /pain
```
```
# /reviewer — independent verdict on one story or task
Boot: whoami() → subscribe() → context().
IS-A   participant(role=reviewer), never the doer of the same ticket
HAS-A  the ticket, its criteria, the engineer's plan and report docs, the strategies and domain
       docs used, the thread
USES-A the codebase; re-running checks; consult (adversarial read); fan-out for large sweeps
PRODUCES-A a verdict per criterion (pass/fail with evidence), a review report doc, fixes that
           are small and re-verified, findings for the rest
PROTOCOL  re-run every check yourself; the report is a claim until you have. Fix inline only
          what you can re-verify; otherwise a finding on the thread. The criteria are the law;
          if they miss the words, say so — a finding to the architect. Close with in_review →
          done or back to in_progress.
SKILLS /verify · /deviation · /doubt · /pain
```
```
# /qa — acceptance of the epic
Boot: whoami() → subscribe() → context().
IS-A   participant(role=qa), spawned when every story is done
HAS-A  the epic (words), its design doc, criteria, all reports and artifacts, the repository
USES-A a cold seat: run the thing, open the files, walk the user path; consult for look judgment
PRODUCES-A a verdict per epic criterion and one verdict for the whole against the words, in a
           report doc; trivial fixes re-verified; gaps most severe first
PROTOCOL  the criteria are a translation; judge the words too. Say plainly what passed and
          what did not. You owe nobody a pass.
SKILLS /verify · /pain
```
Consultant (GPT Sol) is not a shell we author; it is reached by `consult(purpose=adversary|
creative|visual|second_opinion, context, question)`, and its answers are written on the
thread by the caller.

---

## 6. Docs layer — how craft reaches a lower-tier model

- **strategy_hl** (one doc each, sme-authored, global or per domain): the shape of an
  approach — when it applies, the phases, the exit condition, the typical gates. Examples:
  poc-then-iterate, diagnose-with-logs-and-traces, research-then-build, walking-skeleton,
  refactor-in-steps, creative-reference-then-build.
- **strategy_ll** (sme-authored, per language/stack/domain): craft rules as intent + why +
  example: patterns, SOLID, DDD, error handling, logging, resource lifecycle, documentation,
  tests, output contracts (structured output — pydantic or JSON by model capability).
- **domain** (sme-authored, per knowledge domain): what is true here — module map,
  conventions, measurable bars from the words, known pitfalls, references.
- **design** (architect): §3.4 template.
- **report** (engineer/reviewer/qa): plan-and-evidence; per criterion what ran and the result.

Selection is by Link: the architect's design names the strategies/domains per story; the
engineer's `context()` carries them. The engineer may deviate for the model it runs on or the
facts it finds; a deviation that should become craft is a `/learn` → sme folds it.

Search: `find(query, scope)` — hybrid BM25 + dense vectors (sqlite-vec, RRF fusion; the
existing ollama `nomic-embed-text` client stays as the embedder) over docs, tickets, threads;
results are ids + snippets; scoped to the caller's epic/domains by default.

---

## 7. Flow — objects produced at each beat (a2a = state passed through objects)

| beat | actor | reads (HAS-A) | produces |
|---|---|---|---|
| open | owner → coordinator | words | Ticket(epic, title=words) |
| comprehend | architect | epic, code, prior designs | Doc(design) · Messages(questions/answers) · Tickets(stories, knowledge) · Criteria · Links |
| knowledge | sme (per domain) | knowledge ticket, code, epic design | Doc(domain), Doc(strategy_*) · Links to stories |
| sign-off | owner | design doc | Message(answer) · Event(gate_answered) → stories signed_off |
| sprint | coordinator | board(epic) | Session(engineer) per ready story |
| build | engineer | story, design slice, strategies, domain docs | Doc(plan) · Tasks · Artifacts · Doc(report) · Messages(status/demo/doubt) |
| review | reviewer | ticket, criteria, reports | Criterion.verdict · Doc(review report) · Messages(findings) |
| steer | owner (any shell) | — | Message(steer) on that ticket; widening → Message(question→architect) → fork |
| adversarial | engineer of review story | all reports, repo | consult(adversary) → Messages(findings) · fixes · gate for scope findings |
| accept | qa | epic, words, reports, repo | Doc(qa report) · Criterion.verdicts · epic done/partial |
| close | coordinator | — | Event(closed); subscriptions disarmed; docs remain |

Continuity: a shell has no memory. Everything it needs is in `context()`; everything it
learned is in docs/messages before it ends. `/handoff` writes a note when a shell will close
mid-work. Compaction = run boot again.

---

## 8. Tools — bundling and contract (adopting the ReactiveAgents shape)

ReactiveAgents' model fits: a tool is one `ToolDef(name, description, args_model, handler)`,
descriptions are short model-facing lines that state what the tool does and what it returns,
args schemas derive from pydantic models, results are typed dicts, and tools are grouped into
**bundles** composed per run. We adopt that, with two choices: bundles are **role-scoped and
static** (roles are fixed; no self-selection needed), and every output carries
`{ok, value|error, hint}` where `hint` is the one line a refusal needs (legal values).

Bundles (one file each):

| bundle | verbs | roles |
|---|---|---|
| identity | `whoami`, `subscribe`, `context` | all |
| ticket | `ticket.create/read/query/update`, `criterion.create/read/update` | architect, engineer (tasks), reviewer/qa (verdicts), coordinator (status) |
| doc | `doc.create/read/query/update`, `link.create/query` | architect, sme, engineer, reviewer, qa |
| thread | `message.send/read/query` | all |
| board | `board(epic)`, `events.query` | coordinator, owner, architect |
| pool | `spawn`, `resume`, `park`, `reap`, `session.query` | coordinator (all roles), engineer (fan-out subagents only) |
| search | `find` | all |
| consult | `consult` | architect, engineer, reviewer, qa |
| artifact | `artifact.create/read` | engineer, reviewer, qa, sme |
| close | `close(epic)` | coordinator |

Every tool description: one sentence *what it does*, one sentence *what it returns*, the
preconditions if any. Every tool output: typed fields, plus `hint` when something else is
expected next (e.g. `criterion.update` → "verdict recorded; 2 criteria still pending").
Guides (`get_guide(name)`) return one minimal on-demand page: the design template, a
strategy_hl, the feed format. ~25 verbs total; no role sees more than ~15.

Role scoping everywhere: `.claude/commands/<role>.md`, `skills/<role>/…`, `bundles` per role,
`guides/<role>/…` — a role's toolset and skill list are the only ones it can see.

---

## 9. Skills (bounded reactions; Trigger · Do · Writes)

| skill | trigger | do | writes |
|---|---|---|---|
| /doubt | you would otherwise assume, override, or widen on a decision you do not own | name the owner (owner/architect/sme), ask one question with the options you see, end turn | Message(question) |
| /deviation | the design or a strategy cannot be followed as written | state what and why, propose the alternative, send to the architect (design) or sme (craft); proceed only if reversible and noted | Message(deviation) |
| /demo | an artifact exists that the owner should see | show it (SendUserFile / link) in this shell, ask for reaction, record it | Artifact + Message |
| /verify | before handing over, or when checking | per criterion: run the check, record result | Doc(report) section + Criterion.evidence_ref |
| /methodology | starting a story | read the strategy_hl docs for the work_type; choose; record choice + why | Doc(plan) |
| /ocak | a design draft exists | the four audit questions; findings change the draft or become questions | design doc revision / Message |
| /learn | something reusable beyond this ticket | one note: what, where it applies, evidence; addressed to the domain sme | Message(note→sme) |
| /handoff | shell about to close/compact mid-work | status, done, next, open questions on the thread | Message(status) |
| /pain | a tool or guide is wrong vs reality | one structured line; continue | pain log entry |

---

## 10. Infrastructure (machine-independent)

```
central (docker compose):
  plane          tickets, portal, comments, pages, webhooks   (CE)
  board-adapter  our typed objects ↔ Plane; guards; events; board(epic); close
  broker         inboxes, feeds, tagging, delivery; webhook sink
  registry       participants, pools, models/seats, tokens
  docstore+search docs with versions; sqlite-vec + BM25 index; artifact store (or S3/minio)
per machine:
  pool-runner    registers; spawns/resumes/parks/reaps shells; liveness; capacity
  mcp            thin client exposing the role-scoped bundles over HTTP to central
```
Identity: participant token. Spawns placed by the registry on a pool with capacity. A human
teammate needs only a token: Plane portal + `/owner`-style shell, or just the portal.

---

## 11. Freeze checklist

- [ ] Vocabulary §1
- [ ] DI model and the six invariants §2; framework-neutral definition
- [ ] Ten objects §3 (fields, types, owners, CRUD)
- [ ] Plane as ticket store + adapter approach §4
- [ ] Eight cards §5 verbatim
- [ ] Docs layer and sme redefinition §6
- [ ] Flow table §7
- [ ] Bundles + tool contract + role-scoped layout §8
- [ ] Skills §9
- [ ] Infra §10
- [ ] Migration map from today's objects/verbs; live test plan (feature, bug, rnd, creative)

---

## 12. Corrections after review (2026-08-23)

- Planning Q&A and sign-off happen IN the architect shell. The owner shell/feed is only the
  asynchronous path (answer a question from any shell when you are not in the one that asked);
  both paths post on the same ticket thread.
- The architect runs in plan mode: read-only research + drafting; the design doc is the plan;
  ExitPlanMode approval = sign-off, recorded on the epic thread; then stories/criteria are created.
- SME brief = the criteria on the knowledge ticket (coverage, stories served, measurable bars
  from the words, executing model tier); architect fidelity-checks before dependent stories are ready.
- Base concerns: design template mandatory sections (scope/done, workspace, cost/time, tech
  preferences, actors/data/sensitivity, deliverable form, communication plan, domains,
  who-does-what, risks) + /ocak audit + owner sign-off. No checklist gates.
- Re-engaging the architect is structural: only the architect writes stories/criteria/design;
  /deviation, widening steers, reviewer "criteria miss the words", qa gaps are addressed to the
  architect participant; a message to a parked participant forks its session; @architect anytime.
- SMEs: domain SMEs (per product knowledge domain, reused across epics) + craft SMEs (per
  stack/practice) + global strategy_hl library; created only when missing/stale; docs are
  intent+why+example; delivered by Link via context() as summaries+ids (full on doc.read) under
  a size budget — never pasted into cards.

### 2.1 Rule: tools never execute on the agent's behalf (owner ruling 2026-08-24)
A tool validates, stores, routes and signals. When something must be run (a check, a build, a
command), the tool tells the agent what to run; the agent runs it in its own shell and records the
evidence. No tool takes code or a command and executes it internally, and no tool swallows a failure —
every error travels back in the envelope. The one subprocess in the system is the consultant bridge,
which surfaces the real exit code and error line. Enforced by `tests/test_no_code_execution_in_tools.py`.
