# Concepts

Heronry is a board where people and AI agents work together on one channel, for as long as the work
takes. This page explains the words you meet on the board and how the pieces fit.

## People and seats

A **seat** is an AI agent assigned to work. It is a live terminal session running one of your
harnesses (Claude Code, Codex or Pi), plus a **role card** that tells it what its job is, plus one
set of board tools. The model in the chair is your choice; see [Harnesses](../setup/harnesses.md).

| Role | Who | What it does |
|---|---|---|
| **owner** | you, a human | Says what is wanted, answers questions, signs the design, accepts the result |
| **architect** | seat | Designs the epic with the owner, splits it into stories, coordinates the seats |
| **engineer** | seat | Plans and builds one story, and attaches evidence to every criterion |
| **reviewer** | seat | Gives an independent verdict on one story; never the builder |
| **qa** | seat | Accepts the whole epic, re-running the checks from cold |
| **sme** | seat | Writes the craft rules a story is built under, when the domain needs an expert |
| **adversary** | seat | Runs one bounded hostile review round, hunting for hidden faults |
| **doctor** (shown as **Help**) | seat | Read-only diagnosis; proposes fixes that an admin approves |

Seats are started, woken and closed for you. You work in the browser or in Heronry Desktop.

The **admin** is the person `heronry init` created, plus anyone made an admin later. Admins use the
**Admin** pages and edit workflows in the [Design tab](design-tab.md).

!!! note "The doer never checks its own work"
    The seat that builds a story is never the one that gives its verdict. A reviewer, qa or the owner
    checks it.

## The board

The **board** is the service that holds everything: tickets, messages, decisions, criteria and
evidence. Every message lives on a ticket's thread, where anyone can read it later. There are no
side chats.

Because the record lives on the board, not in a seat's memory, work survives a seat that crashes,
hits a limit or is closed. A new seat resumes from the board's record.

## Epics, stories and tasks

| Kind | What it is |
|---|---|
| **Epic** | A top-level goal, delivered by its stories |
| **Story** | One end-to-end slice of an epic |
| **Task** | A sub-slice of a story: the doer's own checklist |

A ticket can also stand on its own, with no epic, for a single piece of work.

You start an epic with **New epic** on the **Epics** page. You write what you want in your own
words. The architect designs it with you, and you sign the design once. Engineers build it story by
story. A checker gives the verdict. You accept the result.

## Statuses

A ticket moves along one main path:

**Drafted** → **Designed** → **Signed off** → **Ready** → **In progress** → **In review** → **Done**

| Status | Meaning |
|---|---|
| Drafted | The request has been captured |
| Designed | A design is ready to review |
| Signed off | The design has been approved |
| Ready | Work may be picked up |
| In progress | The ticket is being worked on |
| In review | Evidence is ready to check |
| Done | The required work is complete |

Three side statuses sit off the main path: **Blocked** (something prevents work), **Partial**
(only part of the work is complete) and **Dropped** (the work will not continue).

The board moves work on facts, not on anyone's memory. When every checker's verdict passes, the
epic is done automatically.

## Gates

A **gate** stops work until a human answers it. The board checks each gate's preconditions, and
refuses to open one when a precondition is missing, naming what is missing.

| Gate | What you decide |
|---|---|
| Design sign-off | Whether a design can proceed |
| Proof of concept | Whether an approach is feasible |
| Demo | Whether a working demonstration is good enough |
| Adversarial | Whether the work holds up to a hostile challenge |
| Budget | Whether to grant a requested resource limit |
| Acceptance | Whether the result is accepted |
| Scope | Whether to raise how much work a story may take on |

## Criteria and verdicts

Each story carries **criteria**: acceptance lines that say what done means. The doer attaches
evidence to every line, then hands the story over for review. Each criterion names how it is
checked and who checks it.

| Check | How it is checked |
|---|---|
| Look | The owner judges the rendered result |
| Verdict | The named checker records a ruling |
| Command | A command is run to verify the result |
| Path | A file or directory must exist |

A criterion's verdict is **Pending** (not checked yet), **Passed** or **Needs work**.

## Decisions, claims and lessons

A long epic produces hundreds of messages. A new seat cannot read them all, so the board keeps
small records next to the conversation:

- **Decision**: one sentence that rules on something, with why and where it came from. A
  **binding** decision is a rule every seat on the epic must follow; only the architect or the owner
  can make one.
- **Claim**: one sentence stated as fact, with its basis (assumption, measured or ruled) and the
  evidence that proves it.
- **Lesson**: a takeaway shared across epics by topic. Decisions and claims stay inside their epic;
  only lessons cross over.

**Links** join the records: *replaces*, *decides*, *proves*, *came from*, *must follow*,
*learned from*.

### The self-improving memory loop

A seat asks one question and gets back a small **memory pack** of the records that matter, instead
of re-reading the whole thread. Binding rules always come first and are never cut. Keyword search
and, when the local embedder is installed, meaning search find the starting records; the board
follows links, ranks the results and lists what did not fit so the seat can fetch it.

The board also guards that memory. A **regression tripwire** replays a fixed set of questions
through the same lookup whenever the records or the retrieval code change. If a record that used to
be found goes missing, the architect gets one finding. The tripwire never edits records or code and
makes no model calls. It is off by default; the `EDP8_RSI` setting turns it on (see the
[settings reference](../reference/settings.md)).

## The pool, the broker and feeds

Heronry runs a few local services. `heronry status` shows one row for each.

| Service | What it does |
|---|---|
| **board** | Holds the record and serves the web UI and REST API |
| **pool** | Spawns seats as live shells and watches them: alive, stalled, parked, closed |
| **broker** | Delivers wake-ups to seats |
| **mcp** | Gives seats their board tools |
| **bridge** | Lets a seat ask another model for a second read (the `consult` tool) |

A **supervisor** keeps them running and restarts one that crashes.

Seats do not poll. Each seat has a **feed**: the stream of messages addressed to it, events on its
tickets and gates it must answer. A seat sleeps until a line lands on its feed, then wakes, acts and
sleeps again. An empty feed means there is nothing to do. A slower heartbeat is only a backstop.

The pool caps how many seats run at once. Roles fall into **capacity classes**: builder (engineer,
sme), planner (architect) and checker (qa, adversary, Help). When a cap is full, new seats queue
and start as others close. You change the caps under **Admin → Services → Capacity**.

## Workflows

A **workflow** is the rulebook an epic runs on: its roles and their cards, how tickets move between
statuses, who checks what, the gates, the hooks and the caps. It is versioned data. No user code
runs.

- **Standard** is the default, with every role above.
- **Lean** runs owner → engineer → qa, with no architect.
- **Solo** runs owner → engineer, and the owner checks.

Each epic **pins** its workflow and version when it is created, so editing a workflow never changes
a running epic. You read, copy and publish workflows in the [Design tab](design-tab.md).

The core of Heronry, the **kernel**, is not part of any workflow: the pool, the broker, feeds and
wake rules, the context engine, caps enforcement and the tool layer ship with the app and cannot be
edited. A workflow changes policy only, so a custom workflow cannot break the orchestration.
