// The Decisions tab's data (C17 s-5e83f9d0af; design-10b21760d9 §14.2, §14.4): the picked scope's decision
// records from `GET /v1/decisions?scope=<ticket>` (the ticket and every ticket under it; live and withdrawn;
// live binding first, then newest). The owner/architect may Withdraw (reason) and turn Binding on/off through
// the existing routes; the board says who may (`can_manage`) and enforces it regardless. Pure: no vscode import.
import { MESSAGE_ID, TICKET_ID } from './chatProtocol';
import { DOC_ID } from './docUri';

export const DECISION_ID = /^dec-[0-9a-f]{10}$/;
/** The board keeps a withdraw/binding reason to one line of 240 characters. */
export const REASON_MAX = 240;

/** One row as the board lists it (only the fields read here). */
export type BoardDecision = {
  id: string; scope: string; text: string; detail?: string; source?: string | null;
  source_kind?: 'message' | 'doc' | 'other' | null; source_ticket?: string | null;
  decided_by?: string; decided_at?: string; created_at?: string; binding?: boolean; status: string;
  replaces?: string[]; withdrawn_reason?: string;
};
export type BoardDecisionList = {
  scope: string; epic: string; decisions: BoardDecision[]; counts?: { live: number; withdrawn: number }; can_manage?: boolean;
};

/** What the view renders. `source` is set only when it is something the panel can open. */
export type DecisionRow = {
  id: string; scope: string; text: string; detail: string; decidedBy: string; decidedAt: string;
  binding: boolean; status: 'live' | 'withdrawn'; replaces: string[]; withdrawnReason: string;
  source: { kind: 'message'; id: string; ticketId: string } | { kind: 'doc'; id: string } | null;
  /** the raw source id when it is not openable here (a commit, an attachment), shown as text */
  sourceText: string | null;
};
/** The Decisions tab for one scope. `error`: the list could not be read (the last good rows stay). `busy`:
 *  a write in flight on that row. `notice`: the last write's outcome, in the board's words. */
export type DecisionsState = {
  scope: string; rows: DecisionRow[]; canManage: boolean; loading: boolean; error: string | null;
  busy?: string | null; notice?: { id: string; ok: boolean; text: string } | null;
};

const str = (x: unknown, max = 100_000) => (typeof x === 'string' ? x.slice(0, max) : '');

/** Normalise the board's list: rows with a malformed id or an unknown status are dropped, never guessed; the
 *  board's order is kept (live binding first, then newest). */
export function decisionRows(list: BoardDecisionList): DecisionRow[] {
  const out: DecisionRow[] = [];
  for (const d of Array.isArray(list?.decisions) ? list.decisions : []) {
    if (!d || typeof d.id !== 'string' || !DECISION_ID.test(d.id)) continue;
    if (d.status !== 'live' && d.status !== 'withdrawn') continue;
    const src = typeof d.source === 'string' ? d.source : null;
    let source: DecisionRow['source'] = null;
    if (src && d.source_kind === 'message' && MESSAGE_ID.test(src) && typeof d.source_ticket === 'string' && TICKET_ID.test(d.source_ticket)) {
      source = { kind: 'message', id: src, ticketId: d.source_ticket };
    } else if (src && d.source_kind === 'doc' && DOC_ID.test(src)) source = { kind: 'doc', id: src };
    out.push({
      id: d.id, scope: str(d.scope, 64), text: str(d.text, 1000), detail: str(d.detail, 4000),
      decidedBy: str(d.decided_by, 128), decidedAt: str(d.decided_at ?? d.created_at, 64),
      binding: d.binding === true, status: d.status, withdrawnReason: str(d.withdrawn_reason, 1000),
      replaces: Array.isArray(d.replaces) ? d.replaces.filter(x => typeof x === 'string' && DECISION_ID.test(x)) : [],
      source, sourceText: src && !source ? src.slice(0, 128) : null,
    });
  }
  return out;
}

export const liveCount = (s: DecisionsState | null | undefined) => s?.rows.filter(r => r.status === 'live').length ?? 0;

/** Badge = live decisions in scope (the story's criterion). */
export function decisionsBadge(s: DecisionsState | null | undefined): { text: string; aria: string } | null {
  const n = liveCount(s);
  return n ? { text: n > 99 ? '99+' : String(n), aria: `${n} live decision${n === 1 ? '' : 's'}` } : null;
}

/** Why a reason cannot be sent, or null. Withdraw needs one (it is the only record of why); binding may omit it. */
export function reasonProblem(action: 'withdraw' | 'binding', reason: string): string | null {
  if (reason.length > REASON_MAX) return `Keep the reason to ${REASON_MAX} characters.`;
  if (/[\r\n]/.test(reason)) return 'The reason is one line.';
  if (action === 'withdraw' && !reason.trim()) return 'Withdraw needs a reason.';
  return null;
}

/** What a row's action may do on this row now: only live rows are managed, only by a manager. */
export function rowActions(r: DecisionRow, canManage: boolean): { withdraw: boolean; binding: boolean } {
  const live = canManage && r.status === 'live';
  return { withdraw: live, binding: live };
}
