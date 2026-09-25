// The webview's own per-viewer state (C9 s-b084884e6b, C13 s-f4e767cfd1): drafts, the composer kind, the
// active tab, what is folded and which commits were seen. It lives in vscode.getState/setState only, never
// on the board, so it survives the view being hidden and re-resolved (retainContextWhenHidden is false).
// Pure: whatever getState returns is untrusted (an older build's shape, or nothing), so every field is
// checked and falls back to its default.
import { SEND_KINDS, TICKET_ID, type SendKind } from './chatProtocol';
import { INBOX_KEY, INBOX_TEXT_MAX } from './inbox';

export type Fold = {
  /** Changes tab: the group of files the open scope touched is expanded */
  scoped: boolean;
  /** Changes tab: the "all seats (M more)" group is expanded */
  allSeats: boolean;
  /** Commits tab (epic scope): the Unlinked group is expanded */
  unlinked: boolean;
};

export type ViewLocal = {
  v: 1; drafts: Record<string, string>; kind: SendKind; fold: Fold;
  /** the active tab's registry id (checked against the registry by the view; an unknown id falls back to the first tab) */
  tab: string;
  /** per scope (ticket id): the time of the newest commit seen in its Commits tab; the badge counts newer ones */
  seen: Record<string, string>;
  /** C15: unsent Inbox answers, rulings and sign-off notes, by row key */
  inbox: Record<string, string>;
};

/** The scope's own files open; the other seats' files and the unlinked commits folded. */
export const FOLDED: Fold = { scoped: true, allSeats: false, unlinked: false };
export const TAB_ID = /^[a-z][a-z0-9-]{0,31}$/;
/** at most this many scopes remember their seen marker (oldest dropped) */
export const SEEN_MAX = 50;
/** at most this many unsent Inbox drafts are kept */
export const INBOX_DRAFTS_MAX = 50;

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
  const tab = ok && typeof s.tab === 'string' && TAB_ID.test(s.tab) ? s.tab : 'chat';
  const seen: Record<string, string> = {};
  if (ok && s.seen && typeof s.seen === 'object') {
    for (const [k, v] of Object.entries(s.seen as Record<string, unknown>)) {
      if (TICKET_ID.test(k) && typeof v === 'string' && !Number.isNaN(Date.parse(v))) seen[k] = v;
    }
  }
  const inbox: Record<string, string> = {};
  if (ok && s.inbox && typeof s.inbox === 'object') {
    for (const [k, v] of Object.entries(s.inbox as Record<string, unknown>)) {
      if (INBOX_KEY.test(k) && typeof v === 'string' && v && v.length <= INBOX_TEXT_MAX && Object.keys(inbox).length < INBOX_DRAFTS_MAX) inbox[k] = v;
    }
  }
  return { v: 1, drafts, kind, fold: { scoped: flag('scoped'), allSeats: flag('allSeats'), unlinked: flag('unlinked') }, tab, seen: bound(seen), inbox };
}

/** Keep the SEEN_MAX most recent markers. */
function bound(seen: Record<string, string>): Record<string, string> {
  const e = Object.entries(seen);
  if (e.length <= SEEN_MAX) return seen;
  return Object.fromEntries(e.sort((a, b) => Date.parse(b[1]) - Date.parse(a[1])).slice(0, SEEN_MAX));
}

/** Commits newer than the scope's seen marker (none seen yet: every commit is new). */
export function unseenCommits(commits: readonly { at: string }[], seenAt: string | undefined): number {
  const t = seenAt ? Date.parse(seenAt) : Number.NEGATIVE_INFINITY;
  return commits.filter(c => Date.parse(c.at) > t).length;
}

/** The Commits tab was looked at: its newest commit is now seen. */
export function markSeen(local: ViewLocal, scope: string, commits: readonly { at: string }[]): boolean {
  const newest = commits.reduce<string | undefined>((m, c) => (!m || Date.parse(c.at) > Date.parse(m) ? c.at : m), undefined);
  const had = local.seen[scope];
  if (!newest || (had && Date.parse(had) >= Date.parse(newest))) return false;
  local.seen[scope] = newest;
  local.seen = bound(local.seen);
  return true;
}
