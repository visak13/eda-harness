# COPY.md — the board's user-facing words (design §15, story s-7a3fd347d2)

Every user-facing string in the Folio board SPA, by page, with the plain-language intent behind it.
The bar (c-2535561ce2): a first-time human can read any page and say what it shows and what it wants
from them, without asking; nothing on screen is agent jargon they cannot hover to understand.

## The single source for enum words

Every **status word, kind, gate, role, check and verdict** renders through one table —
`web/src/copy/glossary.ts` — which gives each value a plain **label** and a one-line **meaning**.
Components never hardcode these words; they call `label(category, value)` and expose `meaning(...)`
as a tooltip (hover + keyboard focus, `aria-describedby`) via `<Term>` / `StatusChip`. The
`glossary.test.ts` table test fails, naming the missing key, if any enum value in `api/types.ts`
lacks a label + meaning. So the authoritative copy for those words lives in the glossary, not here;
this file covers the surrounding prose, labels and framings.

Glossary categories and where their words surface:

| Category | Values (label ← raw) | Seen on |
|---|---|---|
| ticket_status | Drafted, Designed, Signed off, Ready, In progress, In review, Done, Blocked, Partial, Dropped | status chips, process strip, status control, filters |
| ticket_kind | Epic, Story, Task | ticket/epic headers, filters |
| work_type | Feature, Bug, R&D, Creative | ticket details, filters |
| gate | Design sign-off, Proof of concept, Demo, Adversarial, Budget, Acceptance, Scope | gate forms, open-a-gate control |
| message_kind | Question, Answer, Steer, Finding, Deviation, Status, Note | thread rows, composer |
| role | Owner, Coordinator, Architect, Engineer, Reviewer, QA, SME | seats, assignee, ask-a-role |
| check | Command, Path, Look, Verdict | criterion cards, add-criterion |
| verdict | Passed, Needs work, Pending | criterion cards |

## Page framings (the one-sentence landmark each route opens with)

Rendered in a landmark on every route (`AppShell` → `defaultFraming(pathname)`, overridable per page
via `usePageFrame`). "What this is, what you can do here":

| Route | Framing sentence |
|---|---|
| /epics | Every project on the board and how far each has got. |
| /epic/:id | One epic: its goal, its work, and what needs a decision. |
| /ticket/:id | One story: review its criteria, read its evidence, and move it forward. |
| /doc/:id | Read a document and record your sign-off on its criteria. |
| /seats | See who is available, read their latest status, and message or resume a seat. |
| /library | Browse the board's tickets, documents, artifacts, links and history. |
| /me (Decisions) | The one place to see what needs you: sign-offs, questions, gates, and your conversations. |

## Decisions (`/me`)

| String | Plain intent |
|---|---|
| "Decisions" (h1) | Your desk: what is waiting on you. |
| Tabs: Sign-offs / Questions / Gates / Resolved | The four kinds of thing that need a decision, plus what you've already decided. |
| "Nothing is waiting for your sign-off. A clear desk." | Empty state — reassurance, not an error. |
| "Review evidence" | Open the document behind this sign-off so you can rule on it. |
| "N more documents awaiting your sign-off" | There are more; these are summarised below the featured one. |
| "Seats, now" · "Shell alive ≠ work progressing" | Who is running right now — and a caution that a live shell is not the same as progress. |
| "Last work update unavailable" | This seat has reported no status; we will not invent a number. |
| "People" | The humans on the board (no shell state — people aren't seats). |
| "Epic pulse" | A one-line health read per project. |

## Seats (`/seats`)

| String | Plain intent |
|---|---|
| "The people behind the work." (h1) | Who is on the board, agents and humans. |
| Tabs: All seats / Alive / Parked / Closed | Filter seats by whether their shell is running. |
| State words: Working / Presence not refreshed / Parked / Closed / Availability unknown | The 60s presence rule in plain words — never "dead from silence". |
| "Last work update unavailable" | No status reported (never a fake progress %). |
| "Message" | Open a composer addressed to this seat; the preview says whether it wakes now. |
| "Resume" | Continue this seat's saved session (parked always; closed only when the pool can). |
| "Closed; the owner shell can spawn a fresh seat." | Why Resume is absent on a closed seat with no resume-from-closed. |
| "Sending will wake {seat} now." / "…waits on its ticket for the next shell; nobody is woken now." | Honest delivery preview for the composer. |

## Ticket (`/ticket/:id`)

| String | Plain intent |
|---|---|
| "← Epic {id}" | Breadcrumb up to the parent project. |
| Process strip: "Next: …" | Where the story is in its life and the one next action, linked to its control. |
| "Change status" + "Move to {status}" + consequence line | Change the story's stage; each move says what it does; illegal moves are shown disabled with the board's reason. |
| "Seat" — "Assigned to {who}" / "Assign an existing seat or person" / "Spawn a fresh engineer seat for this ticket" | Put someone on the work, or start a fresh shell (spawn shown only when the pool can). |
| "Raise a decision" — "Open the {gate} gate" | Ask the owner to rule on something. |
| "Link & ask" — "Link a document" / "Ask a role" | Attach a doc with a named relation, or ask a role a question on the thread. |
| "Add an acceptance criterion" | Add a new check the work must pass. |
| Criterion card: "YOUR CRITERION" / "Approve criterion" / "Needs work" / "Reword" | Rule on a criterion (approve/needs-work), or reword it while it's still pending. |
| "Open evidence ↗" | Open the document that proves this criterion. |

## Epic (`/epic/:id`)

| String | Plain intent |
|---|---|
| "Owner's words · original request" | The owner's request, verbatim, never paraphrased by an agent. |
| Tabs: Overview / Work / Documents / Thread | The epic's summary, its tickets, its docs, its conversation. |
| "Steer this epic" | Post a steer — a direction the seats must follow. |
| Process strip / "Change status" / "Raise a decision" | Same controls as a ticket (an epic is a ticket): stage + status + gates. |
| Kanban columns: Backlog / Ready / In progress / In review / Done | The work grouped by stage. |

## Doc (`/doc/:id`)

| String | Plain intent |
|---|---|
| meta: "{type} · owner {role} · scope {id} · version {n}" | What this document is, whose it is, and which version you're reading. |
| Sign-off pane (per criterion) | Rule on a criterion this document is the evidence for, naming the version you read. |
| "Comment on this document" | Leave a note on the doc's thread. |
| "Request a review" / "Ask for a review" | Ask a role to look at this document. |
| "Publish a new version" | Replace the body; the board keeps every version. |

## Library (`/library`)

| String | Plain intent |
|---|---|
| Sub-tabs: Documents / Tickets / Artifacts / Links / History | Everything on the board, by kind, for browsing. |

## Agent-authored text (framing rule, §15)

Wherever an agent's words appear (thread messages, status lines, notes), they are shown **verbatim**
but framed: the author's handle + role word, the object they're about, and — where the viewer is the
addressee — a reader-relative tag ("Waiting on you" for a question to you; "For your information"
otherwise). **Names come first; ids follow in the mono face** — no route shows a bare id as the
primary label. (Status/kind words in that text still resolve through the glossary tooltip.)

## Conventions

- **Name first, id after** (`{title}` then `{id}` in Consolas/mono), everywhere.
- **Never infer death from silence** — presence copy uses "Presence not refreshed", never "dead".
- **Never claim progress no seat reported** — "Last work update unavailable", never a made-up number.
- **Consequences, not just labels** — every control names what it will do; confirmation only for
  close/drop.
- **The board's words on refusal** — a blocked control shows the board's own plain-sentence hint,
  never a client-invented reason.
