// The live "Uncommitted changes — all seats" card (design §4.1, dec-8dfe3d97af). Pure: the host turns
// the git API's index / working-tree / untracked changes into repo-relative rows; this file merges
// them into one row per path, diffed against HEAD. A shared tree cannot say which seat made an edit,
// so the card carries no seat.
import type { CardFile, UncommittedCard } from './chatProtocol';
import type { WorkStatus } from './diffSides';

/** The git extension's `Status` (a const enum in git.d.ts, so its numbers are spelled here). */
export const S = {
  INDEX_MODIFIED: 0, INDEX_ADDED: 1, INDEX_DELETED: 2, INDEX_RENAMED: 3, INDEX_COPIED: 4,
  MODIFIED: 5, DELETED: 6, UNTRACKED: 7, IGNORED: 8, INTENT_TO_ADD: 9, INTENT_TO_RENAME: 10, TYPE_CHANGED: 11,
} as const;

export type RawChange = { path: string; oldPath?: string; status: number };
export type WorkFile = { path: string; oldPath?: string; status: WorkStatus };

/** One row per path vs HEAD. The working tree wins over the index for the right side (a file staged as
 *  added then deleted in the tree is gone); an index add/rename keeps its A/R against HEAD. */
export function workFiles(index: RawChange[], work: RawChange[], untracked: RawChange[]): WorkFile[] {
  const out = new Map<string, WorkFile>();
  for (const c of index) {
    const st: WorkStatus | null = c.status === S.INDEX_ADDED || c.status === S.INDEX_COPIED ? 'A'
      : c.status === S.INDEX_DELETED ? 'D' : c.status === S.INDEX_RENAMED ? 'R' : c.status === S.IGNORED ? null : 'M';
    if (st) out.set(c.path, { path: c.path, ...(st === 'R' && c.oldPath ? { oldPath: c.oldPath } : {}), status: st });
  }
  for (const c of work) {
    if (c.status === S.IGNORED) continue;
    const had = out.get(c.path);
    if (c.status === S.DELETED) {
      // added in the index then deleted in the tree: nothing vs HEAD
      if (had?.status === 'A') out.delete(c.path);
      // renamed in the index then deleted in the tree: vs HEAD the old path is simply deleted
      else if (had?.status === 'R' && had.oldPath) { out.delete(c.path); out.set(had.oldPath, { path: had.oldPath, status: 'D' }); }
      else out.set(c.path, { path: c.path, status: 'D' });
      continue;
    }
    if (c.status === S.INTENT_TO_ADD) { out.set(c.path, { path: c.path, status: 'A' }); continue; }
    // git.untrackedChanges=mixed (the default) lists untracked files among the working-tree changes
    if (c.status === S.UNTRACKED) { untrackedRow(out, c.path); continue; }
    if (!had) out.set(c.path, { path: c.path, ...(c.status === S.INTENT_TO_RENAME && c.oldPath ? { oldPath: c.oldPath, status: 'R' as const } : { status: 'M' as const }) });
  }
  for (const c of untracked) untrackedRow(out, c.path);
  return [...out.values()].sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

/** An untracked file: new vs HEAD, unless the index deletes it (`git rm --cached`): it is still on disk,
 *  so vs HEAD it is the tracked file, perhaps edited. */
function untrackedRow(out: Map<string, WorkFile>, path: string) {
  const had = out.get(path);
  if (!had) out.set(path, { path, status: 'U' });
  else if (had.status === 'D') out.set(path, { path, status: 'M' });
}

export const CARD_ROWS = 200;

/** What the open thread counts as "its own" (C9, option (a)): the paths its tickets touched, and
 *  whether that is an epic or a lone ticket. */
export type Scope = { paths: ReadonlySet<string>; kind: 'epic' | 'ticket' };

/** A row belongs to the scope when its path, or a rename's old path, was touched. */
export const inScope = (f: { path: string; oldPath?: string }, paths: ReadonlySet<string>) =>
  paths.has(f.path) || (!!f.oldPath && paths.has(f.oldPath));

/** The chip's rows: with a scope, the rows it touched come first (flagged) and `scoped` counts them
 *  all, so the cap never hides one of them behind other seats' files. */
export function uncommittedCard(files: WorkFile[], scope: Scope | null = null, now = new Date()): UncommittedCard {
  const row = (f: WorkFile, touched: boolean): CardFile =>
    ({ path: f.path, ...(f.oldPath ? { oldPath: f.oldPath } : {}), status: f.status, add: null, del: null, ...(touched ? { touched: true } : {}) });
  const mine = scope ? files.filter(f => inScope(f, scope.paths)) : [];
  const rest = scope ? files.filter(f => !inScope(f, scope.paths)) : files;
  const rows = [...mine.map(f => row(f, true)), ...rest.map(f => row(f, false))].slice(0, CARD_ROWS);
  return { files: rows, more: Math.max(0, files.length - CARD_ROWS), total: files.length, at: now.toISOString(),
    scoped: scope ? mine.length : null, scope: scope?.kind ?? null };
}

/** Same rows as last time (a debounced refresh that changed nothing posts nothing). */
export const sameRows = (a: UncommittedCard | null, b: UncommittedCard | null) =>
  JSON.stringify(a && { f: a.files, t: a.total, s: a.scoped, k: a.scope }) === JSON.stringify(b && { f: b.files, t: b.total, s: b.scoped, k: b.scope });
export const sameWork = (a: WorkFile[], b: WorkFile[]) => JSON.stringify(a) === JSON.stringify(b);

/** A message anchor's path relative to the shared repo's root (C9). The anchor's `repo_root` is the
 *  git root it was taken in; when that is the same repo (compared case-insensitively, `\` = `/`) the
 *  path is used as is, a nested root prefixes its sub-path, and a parent root strips it (null when the
 *  file is outside the repo). Another machine's root (a teammate's clone) keeps the repo-relative path. */
export function anchorPath(cc: { repo_root: string; path: string }, repoRoot: string | null): string | null {
  const path = cc.path.replace(/\\/g, '/');
  if (!path || path.startsWith('/') || path.split('/').includes('..')) return null;
  if (!repoRoot) return path;
  const trim = (p: string) => p.replace(/\\/g, '/').replace(/\/+$/, '');
  const a = trim(cc.repo_root), r = trim(repoRoot);
  const al = a.toLowerCase(), rl = r.toLowerCase();
  if (al === rl) return path;
  if (al.startsWith(rl + '/')) return `${a.slice(r.length + 1)}/${path}`;
  if (rl.startsWith(al + '/')) {
    const pre = rl.slice(al.length + 1) + '/';
    return path.toLowerCase().startsWith(pre) ? path.slice(pre.length) : null;
  }
  return path;
}

/** The paths a set of tickets touched: every file (and rename source) of the commits naming one of
 *  them, plus the anchors on their messages. */
export function touchedPaths(commits: readonly { tickets: string[]; files: { path: string; oldPath?: string }[] }[],
  ids: ReadonlySet<string>, anchors: Iterable<string>): Set<string> {
  const out = new Set<string>(anchors);
  for (const c of commits) {
    if (!c.tickets.some(t => ids.has(t))) continue;
    for (const f of c.files) { out.add(f.path); if (f.oldPath) out.add(f.oldPath); }
  }
  return out;
}
