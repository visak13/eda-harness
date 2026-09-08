// The single table of human labels + one-line meanings for every agent-vocabulary term the SPA
// shows (design §15, criterion c-581d50496d). Components render `label` and expose `meaning` as a
// tooltip (hover + keyboard focus, aria-describedby); the header "What am I looking at?" panel
// (Ctrl-/) lists the terms visible on the current page.
//
// ONE source of truth: the value keys come from the enum arrays in `../api/types` (which mirror
// board schemas.py). `glossary.test.ts` iterates those arrays and fails NAMING the missing key if
// any value here is dropped — so a new board enum value cannot ship without a plain-language entry.
//
// Copy authority: folio-glossary.png (board-concepts-r3) for the terms it shows; the remaining
// enum values (kinds, work types, the retired/rare roles, the scope gate) are written in the same
// voice. Meanings are one plain sentence, no agent jargon, understandable by a first-time reader.

import {
  TICKET_STATUSES,
  TICKET_KINDS,
  WORK_TYPES,
  GATE_KINDS,
  MESSAGE_KINDS,
  ROLES,
  CHECKS,
  VERDICTS,
  SESSION_STATES,
} from "../api/types";

export interface Term {
  /** The human label shown in the UI (Title case, never the raw snake_case enum). */
  label: string;
  /** One plain sentence a first-time reader understands, shown as the tooltip / panel meaning. */
  meaning: string;
}

/** The glossary categories, one per board enum the UI renders + a `concept` group for the words
 *  (seat, wake, presence) the plate footer explains. */
export type GlossaryCategory =
  | "ticket_status"
  | "ticket_kind"
  | "work_type"
  | "gate"
  | "message_kind"
  | "role"
  | "check"
  | "verdict"
  | "session_state"
  | "concept";

type Table = Record<string, Term>;

const ticket_status: Table = {
  drafted: { label: "Drafted", meaning: "The request has been captured." },
  designed: { label: "Designed", meaning: "A design is ready to review." },
  signed_off: { label: "Signed off", meaning: "The design has been approved." },
  ready: { label: "Ready", meaning: "Work may be picked up." },
  in_progress: { label: "In progress", meaning: "The ticket is being worked on." },
  in_review: { label: "In review", meaning: "Evidence is ready to check." },
  blocked: { label: "Blocked", meaning: "Something prevents work." },
  done: { label: "Done", meaning: "The required work is complete." },
  partial: { label: "Partial", meaning: "Only part of the work is complete." },
  dropped: { label: "Dropped", meaning: "The work will not continue." },
};

const ticket_kind: Table = {
  epic: { label: "Epic", meaning: "A top-level goal, delivered by its stories." },
  story: { label: "Story", meaning: "One end-to-end slice of an epic." },
  task: { label: "Task", meaning: "A sub-slice of a story — the doer's own checklist." },
};

const work_type: Table = {
  feature: { label: "Feature", meaning: "New capability being added." },
  bug: { label: "Bug", meaning: "A defect to fix." },
  rnd: { label: "R&D", meaning: "Research to reduce an unknown before building." },
  creative: { label: "Creative", meaning: "Design or authored craft work." },
  review: { label: "Review", meaning: "Independent checking of someone else's work." },
  knowledge: { label: "Knowledge", meaning: "Craft or strategy written down for reuse." },
  chore: { label: "Chore", meaning: "Maintenance with no user-facing change." },
};

const gate: Table = {
  design_signoff: { label: "Design sign-off", meaning: "Decide whether a design can proceed." },
  poc: { label: "Proof of concept", meaning: "Check that an approach is feasible." },
  demo: { label: "Demo", meaning: "Judge a working demonstration." },
  adversarial: { label: "Adversarial", meaning: "Challenge the work for hidden faults." },
  budget: { label: "Budget", meaning: "Decide on a requested resource limit." },
  acceptance: { label: "Acceptance", meaning: "Decide whether the result is accepted." },
  scope: { label: "Scope", meaning: "Raise the limit on how much work a story may take on." },
};

const message_kind: Table = {
  question: { label: "Question", meaning: "A request for an answer." },
  answer: { label: "Answer", meaning: "A reply to a specific question." },
  steer: { label: "Steer", meaning: "An instruction about direction." },
  status: { label: "Status", meaning: "A seat's report of its work." },
  finding: { label: "Finding", meaning: "An observation from investigation." },
  deviation: { label: "Deviation", meaning: "A proposed departure from the plan." },
  note: { label: "Note", meaning: "Context for the ticket thread." },
};

const role: Table = {
  owner: { label: "Owner", meaning: "The human who steers and approves." },
  architect: { label: "Architect", meaning: "Design questions and rulings." },
  engineer: { label: "Engineer", meaning: "Builds the assigned work." },
  reviewer: { label: "Reviewer", meaning: "Checks the implementation." },
  qa: { label: "QA", meaning: "Verifies the required behavior." },
  sme: { label: "SME", meaning: "Advises on a specialist domain." },
  adversary: { label: "Adversary", meaning: "Hostile review that hunts for hidden faults." },
  consultant: { label: "Consultant", meaning: "An outside craft advisor brought in for a task." },
  coordinator: { label: "Coordinator", meaning: "A retired role; the owner shell now orchestrates." },
};

const check: Table = {
  look: { label: "Look", meaning: "The owner judges the rendered result." },
  verdict: { label: "Verdict", meaning: "The named checker records a ruling." },
  command: { label: "Command", meaning: "Run a command to verify the result." },
  path: { label: "Path", meaning: "Check a file or directory exists." },
};

const verdict: Table = {
  pending: { label: "Pending", meaning: "Not checked yet." },
  pass: { label: "Passed", meaning: "The checker recorded a pass." },
  fail: { label: "Needs work", meaning: "The checker recorded a fail." },
};

// The pool shell lifecycle (schemas.py SessionState) shown on Seats. "dead" reads "Closed" — a
// recorded end, not a guess from silence; the presence rule (presence.ts) handles staleness apart.
const session_state: Table = {
  alive: { label: "Alive", meaning: "The shell is running right now." },
  stalled: { label: "Stalled", meaning: "The shell is up but has gone quiet." },
  dead: { label: "Closed", meaning: "The shell has ended and recorded why." },
  parked: { label: "Parked", meaning: "The shell is paused and can be resumed." },
};

// Concept words the plate footer explains — not a board enum, so not gated by the table test, but
// listed in the help panel so a reader meets "seat", "wake", "presence" in plain words.
const concept: Table = {
  seat: { label: "Seat", meaning: "An agent assigned to work." },
  wake: { label: "Wake", meaning: "Notify a seat's shell so it acts." },
  alive: { label: "Alive", meaning: "The shell is running — this describes the shell, not progress." },
  presence: { label: "Presence", meaning: "What we last heard about a seat's shell; silence is not death." },
};

export const GLOSSARY: Record<GlossaryCategory, Table> = {
  ticket_status,
  ticket_kind,
  work_type,
  gate,
  message_kind,
  role,
  check,
  verdict,
  session_state,
  concept,
};

// The enum arrays the table MUST cover, paired with their category. `glossary.test.ts` reads this
// to prove every board enum value has an entry (and fails naming the missing key).
export const REQUIRED_COVERAGE: ReadonlyArray<readonly [GlossaryCategory, readonly string[]]> = [
  ["ticket_status", TICKET_STATUSES],
  ["ticket_kind", TICKET_KINDS],
  ["work_type", WORK_TYPES],
  ["gate", GATE_KINDS],
  ["message_kind", MESSAGE_KINDS],
  ["role", ROLES],
  ["check", CHECKS],
  ["verdict", VERDICTS],
  ["session_state", SESSION_STATES],
];

/** The label + meaning for one value, or `undefined` if the term is unknown (callers fall back to
 *  the raw value so an unglossed string is still shown, never blanked). */
export function term(category: GlossaryCategory, value: string): Term | undefined {
  return GLOSSARY[category]?.[value];
}

/** The human label for a value, falling back to a de-underscored raw value. */
export function label(category: GlossaryCategory, value: string): string {
  return term(category, value)?.label ?? value.replace(/_/g, " ");
}

/** The one-line meaning for a value, or `undefined` when the value is not glossed. */
export function meaning(category: GlossaryCategory, value: string): string | undefined {
  return term(category, value)?.meaning;
}
