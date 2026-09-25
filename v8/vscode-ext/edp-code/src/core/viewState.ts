// The webview's own per-viewer state (C9 s-b084884e6b): drafts, the composer kind and what is folded.
// It lives in vscode.getState/setState only, never on the board, so it survives the view being hidden
// and re-resolved (retainContextWhenHidden is false). Pure: whatever getState returns is untrusted
// (an older build's shape, or nothing), so every field is checked and falls back to its default.
import { SEND_KINDS, TICKET_ID, type SendKind } from './chatProtocol';

export type Fold = {
  /** the Uncommitted chip is expanded */
  uncommitted: boolean;
  /** the Unlinked chip is expanded */
  unlinked: boolean;
  /** the expanded Uncommitted list shows every seat's files, not only this epic's */
  allSeats: boolean;
};

export type ViewLocal = { v: 1; drafts: Record<string, string>; kind: SendKind; fold: Fold };

/** Everything folded: the thread gets the room. */
export const FOLDED: Fold = { uncommitted: false, unlinked: false, allSeats: false };

export function restoreLocal(saved: unknown): ViewLocal {
  const s = (saved && typeof saved === 'object' ? saved : {}) as Record<string, unknown>;
  const ok = s.v === 1;
  const drafts: Record<string, string> = {};
  if (ok && s.drafts && typeof s.drafts === 'object') {
    for (const [k, v] of Object.entries(s.drafts as Record<string, unknown>)) if (TICKET_ID.test(k) && typeof v === 'string') drafts[k] = v;
  }
  const kind = typeof s.kind === 'string' && (SEND_KINDS as readonly string[]).includes(s.kind) ? (s.kind as SendKind) : 'note';
  const f = (ok && s.fold && typeof s.fold === 'object' ? s.fold : {}) as Record<string, unknown>;
  const flag = (k: keyof Fold) => (typeof f[k] === 'boolean' ? (f[k] as boolean) : FOLDED[k]);
  return { v: 1, drafts, kind, fold: { uncommitted: flag('uncommitted'), unlinked: flag('unlinked'), allSeats: flag('allSeats') } };
}
