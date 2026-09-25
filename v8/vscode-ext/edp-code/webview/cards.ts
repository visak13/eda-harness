// Change cards in the chat timeline (C5 s-ab8e69650e; design §4.1-4.2). A commit card shows seat,
// subject, sha7 and its files with +/-; the card opens the multi-diff, a file row that file's diff. The
// Uncommitted chip names no seat (dec-8dfe3d97af); C9 folds it and Unlinked into chips (design §13).
// Everything is set with textContent; the view only names a sha/path, and the host opens only what its
// own index holds.
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

// -- the folded bands (C9): the Uncommitted and Unlinked chips and what they expand to ------------------
/** The Uncommitted chip's text and its spoken name. With a scope it reads `n/N`: n files this epic
 *  touched, N in the whole shared tree. */
export function uncommittedLabel(card: UncommittedCard | null): { text: string; aria: string } {
  const n = card?.total ?? 0;
  if (!n) return { text: 'Uncommitted · clean', aria: 'Uncommitted changes: the shared tree is clean' };
  const files = (k: number) => `${k} file${k === 1 ? '' : 's'}`;
  if (card?.scoped == null) return { text: `Uncommitted · ${n}`, aria: `Uncommitted changes: ${files(n)}` };
  return { text: `Uncommitted · ${card.scoped}/${n}`, aria: `Uncommitted changes: ${files(card.scoped)} this ${card.scope ?? 'epic'} touched, ${files(n)} across all seats` };
}

export function unlinkedLabel(s: ChatState): { text: string; aria: string } {
  const n = s.unlinked?.length ?? 0;
  const cap = n >= 100 ? ', newest 100' : '';
  return { text: `Unlinked · ${n}${n >= 100 ? '+' : ''}`, aria: `Unlinked commits: ${n}${cap}` };
}

/** The expanded Uncommitted list. Scoped (option (a)): only the rows this epic touched, with a
 *  "show all seats (M more)" toggle for the rest; the button opens the multi-diff of what is listed. */
export function renderUncommitted(box: HTMLElement, card: UncommittedCard | null, allSeats: boolean, post: Post, onAllSeats: (all: boolean) => void): void {
  box.replaceChildren();
  const n = card?.total ?? 0;
  const scoped = card?.scoped ?? null;
  const all = scoped === null || allSeats;
  const shown = all ? n : scoped;
  const who = all ? 'all seats' : `this ${card?.scope ?? 'epic'}`;
  const head = el('button', 'uc-head');
  head.type = 'button';
  head.id = 'uncommitted-open';
  head.title = shown ? `Open ${who === 'all seats' ? 'every' : "this epic's"} uncommitted change against HEAD (multi-diff)` : 'Nothing to open';
  head.append(el('span', 'uc-title', `Uncommitted changes — ${who}`),
    el('span', 'uc-count', !n ? 'clean' : shown ? `${shown} file${shown === 1 ? '' : 's'}` : 'none'));
  head.disabled = !shown;
  head.addEventListener('click', () => post(all ? { type: 'openUncommitted' } : { type: 'openUncommitted', scoped: true }));
  box.append(head);
  if (card && n) {
    const rows = card.files.filter(f => all || f.touched);
    if (rows.length) {
      const ul = el('ul', 'cm-files uc-files');
      ul.setAttribute('aria-label', 'Uncommitted files');
      for (const f of rows) {
        const li = fileRow(f, () => post({ type: 'openUncommitted', path: f.path }), false);
        if (all && f.touched) li.classList.add('touched');
        ul.append(li);
      }
      box.append(ul);
    } else box.append(el('div', 'cm-more', `No uncommitted file is one this ${card.scope ?? 'epic'} touched.`));
    if (all && card.more) box.append(el('div', 'cm-more', `+${card.more} more (open the list for all)`));
  }
  if (scoped !== null && n > scoped) {
    const t = el('button', 'uc-all', allSeats ? `only this ${card?.scope ?? 'epic'} (${scoped})` : `show all seats (${n - scoped} more)`);
    t.type = 'button';
    t.id = 'uncommitted-all';
    t.setAttribute('aria-pressed', String(allSeats));
    t.addEventListener('click', () => onAllSeats(!allSeats));
    box.append(t);
  }
}

/** The expanded Unlinked list (epic threads only): commits naming no ticket, newest first. */
export function renderUnlinked(box: HTMLElement, s: ChatState, post: Post): void {
  box.replaceChildren();
  const listEl = el('div', 'ul-list');
  for (const c of s.unlinked ?? []) listEl.append(commitCardEl(c, post));
  if (!s.unlinked?.length) listEl.append(el('p', 'empty', 'Every commit in the window names a ticket.'));
  box.append(listEl);
}

/** New unlinked commits (a HEAD move); true when the list changed. */
export function appendUnlinked(s: ChatState, items: CommitCard[]): boolean {
  if (!items.length || s.ticket?.kind !== 'epic') return false;
  const have = new Set((s.unlinked ?? []).map(c => c.sha));
  const fresh = items.filter(c => !have.has(c.sha));
  if (!fresh.length) return false;
  s.unlinked = [...fresh, ...(s.unlinked ?? [])].slice(0, 100);
  return true;
}

/** A Stories row's commit count. */
export function commitCount(n: number): HTMLElement {
  const c = el('span', 'st-commits', `⎇ ${n}`);
  c.title = `${n} commit${n === 1 ? '' : 's'} name this story or its tasks`;
  c.setAttribute('aria-label', `${n} commit${n === 1 ? '' : 's'}`);
  return c;
}
