// The EDP reader editor's protocol and rules (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.7): a board doc at one
// version in our own custom editor tab. The host reads the board with the viewer's token and posts plain data; the
// reader webview renders it (markdown-it html:false + DOMPurify) and posts intents, each checked by `parseReaderInbound`.
// Every write is built here from the HOST's panel state (doc id, the version shown, the gate event), never from a
// field the view sent. Pure: no vscode import.

export const READER_VIEW = 'edp.docReader';
export const FEEDBACK_MAX = 16_384;
/** a C20 quote is at most this much selected text; longer selections are cut (the line range stays exact) */
export const SELECTION_MAX = 4096;

export type ReaderComment = { id: string; by: string; at: string | null; kind: string; text: string; via: string; version: number | null };
export type ReaderDoc = {
  id: string; title: string; docType: string; status: string; version: number;
  /** every version the board holds, ascending; the newest is `current` */
  versions: number[]; current: number;
  body: string;
  proposes: string | null;
  resolution: string | null;
};
/** The design gate on this doc, from `GET /v1/docs/{id}/context` (null: not a design, or no source ticket) */
export type ReaderGate = { ticketId: string; ticketTitle: string; gateEventId: string | null; canApprove: boolean; canReview: boolean; currentVersion: number;
  /** C22: the design the ticket's sign-off is for (its design_ref); undefined when it could not be read */
  designRef?: string | null };
/** A proposed strategy doc against the active doc it revises (`GET /v1/docs/{id}/diff`) */
export type ReaderDiff = { baseId: string | null; baseVersion: number | null; text: string };

export type ReaderState = {
  type: 'doc'; v: 1;
  doc: ReaderDoc | null;
  gate: ReaderGate | null;
  /** C22: the review context of a design could not be read (the board's words); the header says so instead of guessing */
  gateError?: string | null;
  /** strategy_hl/ll proposed and the viewer is the owner: Approve / Reject */
  canResolve: boolean;
  diff: ReaderDiff | null;
  comments: { rows: ReaderComment[]; error: string | null } | null;
  loading: boolean;
  error: string | null;
};

export type HostToReader =
  | ReaderState
  /** a write settled: `text` is the outcome or the board's refusal, verbatim */
  | { type: 'done'; v: 1; what: ReaderWrite; ok: boolean; text: string };

export type ReaderWrite = 'approve' | 'requestChanges' | 'resolveApprove' | 'resolveReject';

export type ReaderToHost =
  | { v: 1; type: 'ready' }
  | { v: 1; type: 'pickVersion'; version: number }
  | { v: 1; type: 'compare' }
  | { v: 1; type: 'source' }
  | { v: 1; type: 'fullScreen' }
  | { v: 1; type: 'refresh' }
  | { v: 1; type: 'approve' }
  | { v: 1; type: 'requestChanges'; feedback: string }
  | { v: 1; type: 'resolve'; approve: boolean }
  | { v: 1; type: 'openProposalDiff' }
  /** http(s) links in the doc open outside the editor */
  | { v: 1; type: 'openLink'; href: string }
  /** C20's hook: the reader's selection as a 1-based inclusive source line range of the markdown (from = 0: none) */
  | { v: 1; type: 'selection'; from: number; to: number; text: string };

const LINE_MAX = 10_000_000;
const int = (x: unknown, min: number) => (typeof x === 'number' && Number.isSafeInteger(x) && x >= min && x <= LINE_MAX ? x : null);

/** The reader's inbound gate: known types and fields only; anything else is dropped. */
export function parseReaderInbound(raw: unknown): ReaderToHost | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Record<string, unknown>;
  if (r.v !== 1 || typeof r.type !== 'string') return null;
  switch (r.type) {
    case 'ready': case 'compare': case 'source': case 'fullScreen': case 'refresh': case 'approve': case 'openProposalDiff':
      return { v: 1, type: r.type };
    case 'pickVersion': {
      const version = int(r.version, 1);
      return version ? { v: 1, type: 'pickVersion', version } : null;
    }
    case 'requestChanges': {
      const f = r.feedback;
      return typeof f === 'string' && f.trim() && f.length <= FEEDBACK_MAX ? { v: 1, type: 'requestChanges', feedback: f } : null;
    }
    case 'resolve':
      return typeof r.approve === 'boolean' ? { v: 1, type: 'resolve', approve: r.approve } : null;
    case 'openLink': {
      const href = r.href;
      if (typeof href !== 'string' || href.length > 2048) return null;
      try { const u = new URL(href); return u.protocol === 'https:' || u.protocol === 'http:' ? { v: 1, type: 'openLink', href: u.href } : null; }
      catch { return null; }
    }
    case 'selection': {
      const from = int(r.from, 0), to = int(r.to, 0), text = r.text;
      if (from === null || to === null || typeof text !== 'string') return null;
      if (from === 0) return { v: 1, type: 'selection', from: 0, to: 0, text: '' };
      if (to < from) return null;
      return { v: 1, type: 'selection', from, to, text: text.slice(0, SELECTION_MAX) };
    }
  }
  return null;
}

/** `POST /v1/gates/decide`: the version shown is the version reviewed; the board refuses it if the doc moved,
 *  the gate closed or the viewer is not the epic's human owner. */
export function decideBody(doc: ReaderDoc, gate: ReaderGate, decision: 'approve' | 'request_changes', feedback: string, key: string) {
  return { ticket_id: gate.ticketId, gate_event_id: gate.gateEventId ?? '', decision, design_ref: doc.id,
    reviewed_version: doc.version, feedback: decision === 'approve' ? '' : feedback, idempotency_key: key };
}

/** Why a design decision cannot be sent from this panel, or null. */
export function decideProblem(doc: ReaderDoc | null, gate: ReaderGate | null, decision: 'approve' | 'request_changes', feedback: string): string | null {
  if (!doc || !gate) return 'This doc has no design review open here.';
  if (!gate.canApprove || !gate.gateEventId) {
    if (gate.canReview && doc.version !== gate.currentVersion) return `You are reading v${doc.version}; the design is now v${gate.currentVersion}. Open v${gate.currentVersion} to review it.`;
    return 'The design review is not open for you on this version.';
  }
  if (decision === 'request_changes' && !feedback.trim()) return 'Say what to change: Request changes needs feedback.';
  if (feedback.length > FEEDBACK_MAX) return `Too long: ${feedback.length} of ${FEEDBACK_MAX} characters.`;
  return null;
}

/** The header tooltip on a design: when the actions show, and that a design has no Reject (the board has none). */
export const SIGNOFF_TIP = 'Approve and Request changes show in the title bar while a design sign-off is open on this version for the epic\'s owner. '
  + 'A design has no Reject: Request changes sends it back to the architect with your feedback.';

/** Why a design shows no Approve (C22 s-3b86872bf0), in one header line; null when it is not a design or the actions
 *  show. `openVersion`: the version the open sign-off is on, when it is not the one shown ("open it"). */
export type ApproveReason = { text: string; openVersion: number | null; ticketId: string | null };

export function approveReason(doc: ReaderDoc | null, gate: ReaderGate | null, gateError: string | null = null): ApproveReason | null {
  if (!doc || doc.docType !== 'design') return null;
  if (gate?.canApprove && gate.gateEventId) return null;
  // a failed read is not "no sign-off": say it could not be told
  if (!gate && gateError) return { text: `Could not read the sign-off status of v${doc.version}`, openVersion: null, ticketId: null };
  const on = gate ? ` (${gate.ticketId})` : '';
  const ticketId = gate?.ticketId ?? null;
  if (!gate?.gateEventId) return { text: `No sign-off open on v${doc.version}${on}`, openVersion: null, ticketId };
  // the ticket's sign-off is for another design: never point at a version of this one
  if (gate.designRef && gate.designRef !== doc.id) return { text: `Sign-off open${on} is for ${gate.designRef}, not this design`, openVersion: null, ticketId };
  // a sign-off is open on the ticket: the board lets the owner approve only the current version
  // "open it" only when the sign-off is known to be on this design (design_ref read), never on a guess
  if (doc.version !== gate.currentVersion) return { text: `Sign-off is open on v${gate.currentVersion}${on}`, openVersion: gate.designRef === doc.id ? gate.currentVersion : null, ticketId };
  if (!gate.canReview) return { text: `Sign-off is open on v${doc.version}${on}; only the epic's owner approves it`, openVersion: null, ticketId };
  return { text: `Sign-off open${on} is not for this design`, openVersion: null, ticketId };
}

/** The other versions a Compare can pair with `shown`, newest first; the older of a pair goes on the left. */
export function compareChoices(versions: readonly number[], shown: number): number[] {
  return [...versions].filter(v => v !== shown).sort((a, b) => b - a);
}
export const diffPair = (a: number, b: number): [number, number] => (a < b ? [a, b] : [b, a]);

/** The board's comment rows (`GET /v1/docs/{id}/comments`), shaped; malformed rows are skipped. */
export function readerComments(rows: unknown): ReaderComment[] {
  if (!Array.isArray(rows)) return [];
  const out: ReaderComment[] = [];
  for (const r of rows as Record<string, unknown>[]) {
    if (!r || typeof r.id !== 'string') continue;
    const dc = r.document_context as { reviewed_version?: unknown } | null | undefined;
    const version = typeof dc?.reviewed_version === 'number' ? dc.reviewed_version : null;
    out.push({ id: r.id, by: String(r.created_by ?? ''), at: typeof r.created_at === 'string' ? r.created_at : null, kind: String(r.kind ?? 'note'),
      text: String(r.text ?? ''), via: r.via === 'quote' ? 'quote' : 'review', version });
  }
  return out;
}
