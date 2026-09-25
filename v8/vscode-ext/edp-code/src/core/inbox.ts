// The Inbox tab's data (C15 s-e14d316891; design-10b21760d9 §14.2, §14.4). The board already derives what
// waits on the viewer in `GET /v1/me/decisions` (sign-offs they must rule, questions in their inbox, open
// gates they can answer); this module keeps only the picked scope's rows (owner m-db09472a68: every tab is
// scoped, no all-epics view) and shapes them for the view. The board lists only rows the viewer may act on,
// so a listed row is a row with write controls; the server enforces every write regardless.
// Pure: no vscode import. The host resolves every write from its own last list, by row key, never from a
// field the view sent.

export const INBOX_KEY = /^(q:m-[0-9a-f]{10}|c:c-[0-9a-f]{10}|g:(epic|s|t)-[0-9a-f]{10}:[a-z_]{1,32})$/;
/** a ruling, an answer or a sign-off note */
export const INBOX_TEXT_MAX = 16_384;
export const VERDICTS = ['pass', 'fail'] as const;
export type InboxVerdict = (typeof VERDICTS)[number];

// -- the board's rows (views.decisions_for), only the fields read here -----------------------------------
export type BoardSignoff = {
  criterion: { id: string; text: string; check?: string; checked_by?: string | null; verdict?: string; evidence_ref: string | null; evidence_version?: number | null };
  ticket: { id: string; title: string; epic_id?: string; epic_title?: string; assignee: string | null; quick?: boolean };
  doc: { id: string; title: string; doc_type: string; version: number } | null;
  excerpt?: string;
};
export type BoardQuestion = {
  id: string; ticket_id: string; created_by: string; created_at?: string; to?: string | null; kind: string; text: string;
  why?: string; asker?: { type?: string; role?: string; seat_state?: string | null; note?: string };
};
export type BoardGate = { event_id?: string; ticket_id: string; gate: string; by?: string | null; note?: string | null; opened_at?: string; epic?: string };
export type DecisionsHome = { signoffs?: BoardSignoff[]; questions?: BoardQuestion[]; gates?: BoardGate[] };

// -- what the view gets ------------------------------------------------------------------------------------
export type InboxQuestion = {
  type: 'question'; key: string; id: string; ticketId: string; ticketTitle: string | null;
  by: string; byHuman: boolean; byRole: string; kind: string; text: string; at: string | null;
  /** the board's routing reason, verbatim ("addressed to you (@owner)") */
  why: string | null;
  /** the board's note on the asker ("Its shell is alive; your answer wakes it.") */
  note: string | null;
};
export type InboxSignoff = {
  type: 'signoff'; key: string; criterionId: string; ticketId: string; ticketTitle: string; text: string; quick: boolean;
  /** the evidence: a doc with the version the row shows (the version a verdict is sent with), or another ref */
  evidence: { ref: string; doc: boolean; title: string | null; docType: string | null };
  version: number;
  excerpt: string;
  assignee: string | null;
};
export type InboxGate = {
  type: 'gate'; key: string; ticketId: string; ticketTitle: string | null; gate: string; by: string | null; note: string | null; at: string | null;
  /** design_signoff: reviewed in the board UI for now (C16 brings the editor reader); no ruling box here */
  design: boolean;
};
export type InboxItem = InboxQuestion | InboxSignoff | InboxGate;
/** The Inbox for one scope. `error`: the list could not be read (the last good rows stay). */
export type InboxState = { scope: string; items: InboxItem[]; loading: boolean; error: string | null };

/** An asker whose shell has closed cannot receive the answer: not an item that waits on a human act (the
 *  board UI's Needs you rule, design §18.2); it stays readable on the thread. */
const GONE = new Set(['dead', 'reaped', 'closed', 'done']);

export const questionKey = (id: string) => `q:${id}`;
export const signoffKey = (criterionId: string) => `c:${criterionId}`;
export const gateKey = (ticketId: string, gate: string) => `g:${ticketId}:${gate}`;

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** The scope's rows, in three runs: sign-offs, gates, questions (each in the board's order). `scope` is the
 *  picked scope's ticket ids (an epic with every ticket of it, a story with its tasks, a lone ticket);
 *  `titles` names tickets the board row does not. Malformed rows are skipped, never guessed. */
export function scopeInbox(home: DecisionsHome | null | undefined, scope: ReadonlySet<string>, titles: ReadonlyMap<string, string> = new Map()): InboxItem[] {
  const out: InboxItem[] = [];
  const seen = new Set<string>();
  const add = (i: InboxItem) => { if (INBOX_KEY.test(i.key) && !seen.has(i.key)) { seen.add(i.key); out.push(i); } };
  for (const s of home?.signoffs ?? []) {
    const c = s?.criterion, t = s?.ticket;
    if (!c || !t || typeof c.id !== 'string' || typeof t.id !== 'string' || !scope.has(t.id) || !c.evidence_ref) continue;
    const doc = s.doc && s.doc.id === c.evidence_ref && Number.isSafeInteger(s.doc.version) ? s.doc : null;
    // the version shown is the version ruled: the doc's version as listed; evidence that is not a doc has no
    // version (the board checks none), so it carries the criterion's own, else 1
    const version = doc ? doc.version : Number.isSafeInteger(c.evidence_version) && (c.evidence_version as number) > 0 ? (c.evidence_version as number) : 1;
    add({ type: 'signoff', key: signoffKey(c.id), criterionId: c.id, ticketId: t.id, ticketTitle: str(t.title) ?? titles.get(t.id) ?? t.id,
      text: String(c.text ?? ''), quick: !!t.quick,
      evidence: { ref: c.evidence_ref, doc: !!doc, title: doc ? doc.title : null, docType: doc ? doc.doc_type : null },
      version, excerpt: typeof s.excerpt === 'string' ? s.excerpt : '', assignee: str(t.assignee) });
  }
  for (const g of home?.gates ?? []) {
    if (!g || typeof g.ticket_id !== 'string' || typeof g.gate !== 'string' || !scope.has(g.ticket_id)) continue;
    add({ type: 'gate', key: gateKey(g.ticket_id, g.gate), ticketId: g.ticket_id, ticketTitle: titles.get(g.ticket_id) ?? null, gate: g.gate,
      by: str(g.by), note: str(g.note), at: str(g.opened_at), design: g.gate === 'design_signoff' });
  }
  for (const q of home?.questions ?? []) {
    if (!q || typeof q.id !== 'string' || typeof q.ticket_id !== 'string' || !scope.has(q.ticket_id)) continue;
    if (GONE.has(q.asker?.seat_state ?? '')) continue;
    add({ type: 'question', key: questionKey(q.id), id: q.id, ticketId: q.ticket_id, ticketTitle: titles.get(q.ticket_id) ?? null,
      by: String(q.created_by), byHuman: q.asker?.type === 'human', byRole: str(q.asker?.role) ?? 'unknown', kind: String(q.kind ?? 'question'),
      text: String(q.text ?? ''), at: str(q.created_at), why: str(q.why), note: str(q.asker?.note) });
  }
  return out;
}

/** The badge: every row waits on the viewer. */
export function inboxBadge(inbox: InboxState | null | undefined): { text: string; aria: string } | null {
  const n = inbox?.items.length ?? 0;
  if (!n) return null;
  return { text: n > 99 ? '99+' : String(n), aria: `${n} item${n === 1 ? '' : 's'} waiting on you` };
}

// -- the three writes, built from the host's own row --------------------------------------------------------
/** A question's reply: an answer to the asker, threaded under the question (the board's Needs you reply). */
export const answerBody = (q: InboxQuestion, text: string) =>
  ({ ticket_id: q.ticketId, to: q.by, kind: 'answer', text, reply_to: q.id });

/** A sign-off: the verdict for the version the row showed; the board refuses an older one than the doc's
 *  current (its message is shown verbatim). A note also goes to the assignee as `[sign-off …] note`. */
export const verdictBody = (s: InboxSignoff, verdict: InboxVerdict, note: string) =>
  ({ criterion_id: s.criterionId, verdict, note, ticket_id: s.ticketId, evidence_version: s.version });

export const gatePath = (g: InboxGate) => `/v1/gates/${encodeURIComponent(g.ticketId)}/${encodeURIComponent(g.gate)}/answer`;

/** Why a write cannot be sent, checked in the view and again in the host (a Fail needs a note, as on the board UI). */
export function writeProblem(kind: 'answer' | 'gate' | 'verdict', text: string, verdict?: InboxVerdict): string | null {
  if (text.length > INBOX_TEXT_MAX) return `Too long: ${text.length} of ${INBOX_TEXT_MAX} characters.`;
  if (kind === 'answer' && !text.trim()) return 'Write an answer first.';
  if (kind === 'gate' && !text.trim()) return 'Write a ruling first.';
  if (kind === 'verdict' && verdict === 'fail' && !text.trim()) return 'Say what needs work: a Fail needs a note.';
  return null;
}
