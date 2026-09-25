// Change cards in the chat timeline (C5 s-ab8e69650e; design §4.1-4.2). A commit card shows seat,
// subject, sha7 and its files with +/-; the card opens the multi-diff, a file row that file's diff. The
// pinned "Uncommitted changes — all seats" card names no seat (dec-8dfe3d97af). Everything is set with
// textContent; the view only names a sha/path, and the host opens only what its own index holds.
import type { CardFile, ChatState, CommitCard, UncommittedCard, ViewToHost } from '../src/core/chatProtocol';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
export type Post = (m: Intent) => void;

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const same = new Date().toDateString() === d.toDateString();
  return same ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const STATUS: Record<string, string> = { A: 'added', M: 'modified', D: 'deleted', R: 'renamed', C: 'copied', T: 'type changed', U: 'untracked' };

export function seatLabel(c: CommitCard): string {
  if (c.attribution === 'none') return 'unlinked';
  if (!c.seat) return 'no seat';
  return c.seatVia === 'assignee' ? `${c.seat} (assignee)` : c.seat;
}

function fileRow(f: CardFile, open: () => void, counts: boolean): HTMLElement {
  const li = el('li');
  const b = el('button', 'cf');
  b.type = 'button';
  b.dataset.path = f.path;
  const what = STATUS[f.status] ?? f.status;
  b.title = f.oldPath ? `${f.oldPath} → ${f.path} (${what}): open the diff` : `${f.path} (${what}): open the diff`;
  b.append(el('span', `cf-st st-${f.status}`, f.status), el('span', 'cf-path', f.oldPath ? `${f.oldPath} → ${f.path}` : f.path));
  if (counts) {
    if (f.add === null) b.append(el('span', 'cf-bin', 'binary'));
    else b.append(el('span', 'cf-add', `+${f.add}`), el('span', 'cf-del', `−${f.del}`));
  }
  b.addEventListener('click', e => { e.stopPropagation(); open(); });
  li.append(b);
  return li;
}

export function commitCardEl(c: CommitCard, post: Post): HTMLElement {
  const a = el('article', `commit att-${c.attribution}`);
  a.dataset.sha = c.sha;
  a.dataset.at = c.at;
  const sha7 = c.sha.slice(0, 7);
  a.setAttribute('aria-label', `Commit ${sha7} by ${seatLabel(c)}: ${c.subject}`);
  const head = el('button', 'cm-head');
  head.type = 'button';
  head.title = c.local ? `Open all ${c.files.length + c.more} changed files (multi-diff)` : 'Not in this clone: pull to see this change';
  const meta = el('span', 'cm-meta');
  const t = el('time', 'at', fmtTime(c.at));
  t.dateTime = c.at;
  meta.append(el('span', 'cm-icon', '⎇'), el('span', `cm-seat via-${c.seatVia ?? 'none'}`, seatLabel(c)), el('span', 'cm-sha', sha7), t);
  head.append(meta, el('span', 'cm-subject', c.subject));
  head.addEventListener('click', () => post({ type: 'openDiff', sha: c.sha }));
  a.append(head);
  if (c.files.length) {
    const ul = el('ul', 'cm-files');
    ul.setAttribute('aria-label', 'Changed files');
    for (const f of c.files) ul.append(fileRow(f, () => post({ type: 'openDiff', sha: c.sha, path: f.path }), true));
    a.append(ul);
  }
  if (c.more) a.append(el('div', 'cm-more', `+${c.more} more files (open the card for all)`));
  if (!c.local) a.append(el('div', 'cm-more', 'Not in this clone: pull to see this change.'));
  return a;
}

// -- time placement ----------------------------------------------------------------------------------
const timeOf = (n: Element): number => {
  const h = n as HTMLElement;
  const iso = h.dataset.at ?? h.querySelector(':scope > header time.at, :scope > .mh time.at')?.getAttribute('datetime') ?? '';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
};

/** Put a card before the first timeline item that is newer than it (messages and cards alike). */
export function insertByTime(list: HTMLElement, node: HTMLElement): void {
  const t = timeOf(node);
  for (const child of Array.from(list.children)) {
    if (child === node || child.classList.contains('empty')) continue;
    if (timeOf(child) > t) { list.insertBefore(node, child); return; }
  }
  list.append(node);
}

/** After older messages were prepended: every card goes back to its place in time. */
export function placeCards(list: HTMLElement): void {
  for (const c of Array.from(list.querySelectorAll<HTMLElement>(':scope > .commit'))) { c.remove(); insertByTime(list, c); }
}

export function renderCommits(s: ChatState, list: HTMLElement, post: Post): void {
  list.querySelectorAll(':scope > .commit').forEach(n => n.remove());
  // oldest first, so each insert lands after the cards it follows
  for (const c of [...(s.commits ?? [])].reverse()) insertByTime(list, commitCardEl(c, post));
}

export function appendCommits(s: ChatState, items: CommitCard[], list: HTMLElement, post: Post): CommitCard[] {
  const have = new Set((s.commits ?? []).map(c => c.sha));
  const fresh = items.filter(c => !have.has(c.sha));
  s.commits = [...fresh, ...(s.commits ?? [])];
  for (const c of [...fresh].reverse()) insertByTime(list, commitCardEl(c, post));
  return fresh;
}

// -- pinned area: uncommitted card + the epic's unlinked commits ---------------------------------------
export function renderUncommitted(box: HTMLElement, card: UncommittedCard | null, open: boolean, post: Post): void {
  box.replaceChildren();
  box.hidden = !open;
  if (!open) return;
  const head = el('button', 'uc-head');
  head.type = 'button';
  head.id = 'uncommitted-open';
  const n = card?.total ?? 0;
  head.title = n ? 'Open every uncommitted change against HEAD (multi-diff)' : 'The shared tree has no uncommitted change';
  head.append(el('span', 'uc-title', 'Uncommitted changes — all seats'), el('span', 'uc-count', n ? `${n} file${n === 1 ? '' : 's'}` : 'clean'));
  head.disabled = !n;
  head.addEventListener('click', () => post({ type: 'openUncommitted' }));
  box.append(head);
  if (!card || !n) return;
  const ul = el('ul', 'cm-files uc-files');
  ul.setAttribute('aria-label', 'Uncommitted files');
  for (const f of card.files) ul.append(fileRow(f, () => post({ type: 'openUncommitted', path: f.path }), false));
  box.append(ul);
  if (card.more) box.append(el('div', 'cm-more', `+${card.more} more (open the card for all)`));
}

export function renderUnlinked(box: HTMLElement, s: ChatState, post: Post): void {
  const wasOpen = (box.querySelector('details') as HTMLDetailsElement | null)?.open ?? false;
  box.replaceChildren();
  const show = s.ticket?.kind === 'epic';
  box.hidden = !show;
  if (!show) return;
  const d = el('details', 'unlinked');
  d.open = wasOpen;
  const n = s.unlinked?.length ?? 0;
  const sum = el('summary', '', `Unlinked commits (${n}${n >= 100 ? ', newest 100' : ''})`);
  sum.id = 'unlinked-summary';
  const listEl = el('div', 'ul-list');
  for (const c of s.unlinked ?? []) listEl.append(commitCardEl(c, post));
  if (!n) listEl.append(el('p', 'empty', 'Every commit in the window names a ticket.'));
  d.append(sum, listEl);
  box.append(d);
}

export function appendUnlinked(box: HTMLElement, s: ChatState, items: CommitCard[], post: Post): void {
  if (!items.length || s.ticket?.kind !== 'epic') return;
  const have = new Set((s.unlinked ?? []).map(c => c.sha));
  s.unlinked = [...items.filter(c => !have.has(c.sha)), ...(s.unlinked ?? [])].slice(0, 100);
  renderUnlinked(box, s, post);
}

/** The Stories strip row's commit count. */
export function commitCount(n: number): HTMLElement {
  const c = el('span', 'st-commits', `⎇ ${n}`);
  c.title = `${n} commit${n === 1 ? '' : 's'} name this story or its tasks`;
  c.setAttribute('aria-label', `${n} commit${n === 1 ? '' : 's'}`);
  return c;
}
