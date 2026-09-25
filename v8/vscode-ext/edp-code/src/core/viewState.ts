// The webview's own per-viewer state (C9 s-b084884e6b, C13 s-f4e767cfd1): drafts, the composer kind, the
// active tab, what is folded and which commits were seen. It lives in vscode.getState/setState only, never
// on the board, so it survives the view being hidden and re-resolved (retainContextWhenHidden is false).
// Pure: whatever getState returns is untrusted (an older build's shape, or nothing), so every field is
// checked and falls back to its default.
import { SEND_KINDS, TICKET_ID, type SendKind } from './chatProtocol';
import { INBOX_KEY, INBOX_TEXT_MAX } from './inbox';
import { restoreReplies, type ReplyRef } from './reply';

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
  /** C22: the message each thread's composer replies to (unsent), by ticket id */
  replies: Record<string, ReplyRef>;
  /** C26 rule 3: the board viewer (origin + participant, the host's `viewer`) that drafts, inbox and replies above
   *  belong to; null before the host has read the stored creds, or signed out */
  who: string | null;
  /** C26: other viewers' unsent drafts, by viewer key, restored when that viewer is back; never shown to another */
  others: Record<string, ViewerDrafts>;
};

/** What one viewer has typed and not sent: the composer drafts, the Inbox drafts, the reply targets. */
export type ViewerDrafts = Pick<ViewLocal, 'drafts' | 'inbox' | 'replies'>;

/** The scope's own files open; the other seats' files and the unlinked commits folded. */
export const FOLDED: Fold = { scoped: true, allSeats: false, unlinked: false };
export const TAB_ID = /^[a-z][a-z0-9-]{0,31}$/;
/** at most this many scopes remember their seen marker (oldest dropped) */
export const SEEN_MAX = 50;
/** at most this many unsent Inbox drafts are kept (the most recently typed) */
export const INBOX_DRAFTS_MAX = 50;

/** at most this many other viewers keep their unsent drafts (the most recently left kept) */
export const VIEWERS_MAX = 8;

/** A viewer key as the host builds it: JSON of [board origin, participant]. */
export function viewerKey(k: unknown): k is string {
  if (typeof k !== 'string' || k.length > 512) return false;
  try {
    const a = JSON.parse(k) as unknown;
    return Array.isArray(a) && a.length === 2 && a.every(x => typeof x === 'string' && x.length > 0);
  } catch { return false; }
}

function restoreDrafts(s: Record<string, unknown>): ViewerDrafts {
  const drafts: Record<string, string> = {};
  if (s.drafts && typeof s.drafts === 'object') {
    for (const [k, v] of Object.entries(s.drafts as Record<string, unknown>)) if (TICKET_ID.test(k) && typeof v === 'string') drafts[k] = v;
  }
  const inbox: Record<string, string> = {};
  if (s.inbox && typeof s.inbox === 'object') {
    // insertion order is last-typed last (the view re-inserts on each edit): keep the newest drafts
    const kept = Object.entries(s.inbox as Record<string, unknown>)
      .filter(([k, v]) => INBOX_KEY.test(k) && typeof v === 'string' && v && v.length <= INBOX_TEXT_MAX);
    for (const [k, v] of kept.slice(-INBOX_DRAFTS_MAX)) inbox[k] = v as string;
  }
  return { drafts, inbox, replies: restoreReplies(s.replies) };
}

const empty = (d: ViewerDrafts) => !Object.keys(d.drafts).length && !Object.keys(d.inbox).length && !Object.keys(d.replies).length;

/** C26 rule 3: a state post names its viewer. Another viewer (or none yet) never sees these drafts and never wipes
 *  them: they are put aside under their own viewer and come back when that viewer does. True when it switched. */
export function switchViewer(local: ViewLocal, who: string | null): boolean {
  if (who === local.who) return false;
  const mine: ViewerDrafts = { drafts: local.drafts, inbox: local.inbox, replies: local.replies };
  // drafts with no known viewer (a pre-0.13.3 state) cannot safely be given to anyone: dropped
  if (local.who !== null && !empty(mine)) { delete local.others[local.who]; local.others[local.who] = mine; }
  const back = who !== null ? local.others[who] : undefined;
  if (who !== null) delete local.others[who];
  local.drafts = back?.drafts ?? {}; local.inbox = back?.inbox ?? {}; local.replies = back?.replies ?? {};
  local.who = who;
  const keys = Object.keys(local.others);
  for (const k of keys.slice(0, Math.max(0, keys.length - VIEWERS_MAX))) delete local.others[k];
  return true;
}

export function restoreLocal(saved: unknown): ViewLocal {
  const s = (saved && typeof saved === 'object' ? saved : {}) as Record<string, unknown>;
  const ok = s.v === 1;
  const own = restoreDrafts(ok ? s : {});
  const who = ok && viewerKey(s.who) ? s.who : null;
  const others: Record<string, ViewerDrafts> = {};
  if (ok && s.others && typeof s.others === 'object') {
    for (const [k, v] of Object.entries(s.others as Record<string, unknown>).slice(-VIEWERS_MAX)) {
      if (viewerKey(k) && k !== who && v && typeof v === 'object') { const d = restoreDrafts(v as Record<string, unknown>); if (!empty(d)) others[k] = d; }
    }
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
  return { v: 1, drafts: own.drafts, kind, fold: { scoped: flag('scoped'), allSeats: flag('allSeats'), unlinked: flag('unlinked') }, tab, seen: bound(seen),
    inbox: own.inbox, replies: own.replies, who, others };
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
