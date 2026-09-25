// Change cards (C5 s-ab8e69650e; design §4.1-4.2), reshaped by C13 (§13.1): a commit is an expandable
// card in the Commits tab (the head expands its file list, a file opens its diff, "Open all" the
// multi-diff) and a one-line marker in the Chat timeline that opens it there. The uncommitted rows name no
// seat (dec-8dfe3d97af). Everything is set with textContent; the view only names a sha/path, and the host
// opens only what its own index holds.
import type { CardFile, CommitCard, ViewToHost } from '../src/core/chatProtocol';

type Intent = ViewToHost extends infer T ? (T extends unknown ? Omit<T, 'v'> : never) : never;
export type Post = (m: Intent) => void;

const el = <K extends keyof HTMLElementTagNameMap>(tag: K, cls?: string, text?: string) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
};

export function fmtTime(iso: string): string {
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

export function fileRow(f: CardFile, open: () => void, counts: boolean): HTMLElement {
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

/** A Commits-tab card. The head (a button, aria-expanded) folds the file list; "Open all" opens the
 *  multi-diff; a file row that file's diff. `label` names the story at epic scope. */
export function commitCardEl(c: CommitCard, post: Post, open: boolean, onToggle: (open: boolean) => void, label?: string): HTMLElement {
  const a = el('article', `commit att-${c.attribution}${open ? ' open' : ''}`);
  a.dataset.sha = c.sha;
  a.dataset.at = c.at;
  const sha7 = c.sha.slice(0, 7);
  const n = c.files.length + c.more;
  a.setAttribute('aria-label', `Commit ${sha7} by ${seatLabel(c)}: ${c.subject}`);
  const row = el('div', 'cm-row');
  const head = el('button', 'cm-head');
  head.type = 'button';
  head.setAttribute('aria-expanded', String(open));
  head.setAttribute('aria-controls', `files-${sha7}`);
  head.title = `${open ? 'Fold' : 'Show'} the ${n} changed file${n === 1 ? '' : 's'}`;
  const meta = el('span', 'cm-meta');
  const t = el('time', 'at', fmtTime(c.at));
  t.dateTime = c.at;
  meta.append(el('span', 'cm-caret', open ? '▾' : '▸'), el('span', `cm-seat via-${c.seatVia ?? 'none'}`, seatLabel(c)), el('span', 'cm-sha', sha7), t);
  if (label) meta.append(el('span', 'cm-story', label));
  head.append(meta, el('span', 'cm-subject', c.subject));
  head.addEventListener('click', () => onToggle(!open));
  const all = el('button', 'act cm-open', 'Open all');
  all.type = 'button';
  all.title = c.local ? `Open all ${n} changed files (multi-diff)` : 'Not in this clone: pull to see this change';
  all.setAttribute('aria-label', `Open all ${n} changed files of ${sha7}`);
  all.addEventListener('click', e => { e.stopPropagation(); post({ type: 'openDiff', sha: c.sha }); });
  row.append(head, all);
  a.append(row);
  if (open) {
    const ul = el('ul', 'cm-files');
    ul.id = `files-${sha7}`;
    ul.setAttribute('aria-label', 'Changed files');
    for (const f of c.files) ul.append(fileRow(f, () => post({ type: 'openDiff', sha: c.sha, path: f.path }), true));
    a.append(ul);
    if (c.more) a.append(el('div', 'cm-more', `+${c.more} more files (Open all shows every file)`));
  }
  if (!c.local) a.append(el('div', 'cm-more', 'Not in this clone: pull to see this change.'));
  return a;
}

// -- Chat markers: one line per commit, in time order among the messages ---------------------------
/** `⎇ abc1234 subject`: opens the commit in the Commits tab. */
export function markerEl(c: CommitCard, jump: (sha: string) => void): HTMLElement {
  const b = el('button', 'cmark');
  b.type = 'button';
  b.dataset.sha = c.sha;
  b.dataset.at = c.at;
  const sha7 = c.sha.slice(0, 7);
  b.title = `${seatLabel(c)} · ${fmtTime(c.at)}: open ${sha7} in the Commits tab`;
  b.setAttribute('aria-label', `Commit ${sha7}: ${c.subject}. Open in the Commits tab`);
  b.append(el('span', 'cm-icon', '⎇'), el('span', 'cm-sha', sha7), el('span', 'cmark-subject', c.subject));
  b.addEventListener('click', () => jump(c.sha));
  return b;
}

const timeOf = (n: Element): number => {
  const h = n as HTMLElement;
  const iso = h.dataset.at ?? h.querySelector(':scope > header time.at, :scope > .mh time.at')?.getAttribute('datetime') ?? '';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? 0 : t;
};

/** Put a marker before the first timeline item that is newer than it (messages and markers alike). */
export function insertByTime(list: HTMLElement, node: HTMLElement): void {
  const t = timeOf(node);
  for (const child of Array.from(list.children)) {
    if (child === node || child.classList.contains('empty')) continue;
    if (timeOf(child) > t) { list.insertBefore(node, child); return; }
  }
  list.append(node);
}

/** After older messages were prepended: every marker goes back to its place in time. */
export function placeMarkers(list: HTMLElement): void {
  for (const c of Array.from(list.querySelectorAll<HTMLElement>(':scope > .cmark'))) { c.remove(); insertByTime(list, c); }
}

/** The Chat timeline's markers: only commits naming the open thread itself (ruling m-2e3b14065e). */
export function renderMarkers(commits: readonly CommitCard[], list: HTMLElement, jump: (sha: string) => void): void {
  list.querySelectorAll(':scope > .cmark').forEach(n => n.remove());
  // oldest first, so each insert lands after the markers it follows
  for (const c of [...commits].reverse()) if (c.thread) insertByTime(list, markerEl(c, jump));
}

/** New commits (a HEAD move): merged into `commits` newest first; returns the fresh ones. */
export function mergeCommits(commits: CommitCard[], items: CommitCard[]): { all: CommitCard[]; fresh: CommitCard[] } {
  const have = new Set(commits.map(c => c.sha));
  const fresh = items.filter(c => !have.has(c.sha));
  return { all: [...fresh, ...commits], fresh };
}

/** New unlinked commits (a HEAD move) for an epic scope, newest 100. */
export function mergeUnlinked(unlinked: CommitCard[], items: CommitCard[]): CommitCard[] | null {
  const have = new Set(unlinked.map(c => c.sha));
  const fresh = items.filter(c => !have.has(c.sha));
  return fresh.length ? [...fresh, ...unlinked].slice(0, 100) : null;
}

/** A Stories row's commit count. */
export function commitCount(n: number): HTMLElement {
  const c = el('span', 'st-commits', `⎇ ${n}`);
  c.title = `${n} commit${n === 1 ? '' : 's'} name this story or its tasks`;
  c.setAttribute('aria-label', `${n} commit${n === 1 ? '' : 's'}`);
  return c;
}
