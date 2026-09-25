// #-tags for workspace files and folders (C11 s-35ccc6d35f; design-10b21760d9 §13). Pure: the host
// builds the index from `git ls-files` (architect ruling m-287aaaad59) and matches here; the view finds
// the `#` under the caret here. A tag is a backticked repo-relative path in the message text (no board
// change); a folder ends with `/`.
import { isTagPath, type PathHit } from './chatProtocol';
import { stripCode } from './mentions';

export type { PathHit, PathKind } from './chatProtocol';

export const PATH_HITS_MAX = 50;

/** The `#`-query the caret sits in: `#` at the start or after a non-word character, outside code
 *  (closed spans and fences, and an unclosed span or fence the caret is still typing in), and the
 *  path typed so far (possibly empty; no whitespace, backtick or `#`). Undefined = no picker. */
export function activeHashTag(text: string, caret: number): { start: number; query: string } | undefined {
  const raw = text.slice(0, caret);
  const before = stripCode(raw);
  const m = /(^|[^\w#])#([^\s`#]*)$/.exec(before);
  if (!m) return undefined;
  const start = caret - m[2].length - 1;
  // still inside code the user has opened but not closed: a fence left after the closed ones, or an
  // odd ` count on this line once the closed spans are blanked
  if (raw.replace(/```[\s\S]*?```/g, '').includes('```')) return undefined;
  const line = before.slice(before.lastIndexOf('\n') + 1, start);
  if ((line.match(/`/g)?.length ?? 0) % 2) return undefined;
  // the caret may sit inside a code span that closes after it: judge the `#` against the whole text
  if (stripCode(text)[start] !== '#') return undefined;
  return { start, query: m[2] };
}

/** The text a pick inserts: the backticked path (a folder ends with `/`) and a space. */
export const pathToken = (h: PathHit) => `\`${h.path}${h.kind === 'folder' ? '/' : ''}\` `;

/** A path we can put in a token and a link (the protocol's own rule). */
export const taggable = isTagPath;

/** `git ls-files -z` output: the paths, deduplicated (a conflicted path is listed per stage). */
export function parseLsFilesZ(out: string): string[] {
  return [...new Set(out.split('\0').filter(p => p.length > 0))];
}

/** Every ancestor folder of the files (no trailing `/`), sorted. */
export function foldersOf(files: readonly string[]): string[] {
  const out = new Set<string>();
  for (const f of files) {
    for (let i = f.indexOf('/'); i > 0; i = f.indexOf('/', i + 1)) out.add(f.slice(0, i));
  }
  return [...out].sort();
}

// -- files.exclude ---------------------------------------------------------------------------------
/** A VS Code glob (`**`, `*`, `?`, `{a,b}`, `[…]`) as an anchored RegExp over a `/`-separated path. */
export function globToRegExp(glob: string, ignoreCase = false): RegExp {
  let re = '';
  let depth = 0;
  const g = glob.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
  for (let i = 0; i < g.length; i++) {
    const c = g[i];
    if (c === '*') {
      if (g[i + 1] === '*') {
        // `**/` = zero or more folders; a trailing `**` = anything
        if (g[i + 2] === '/') { re += '(?:[^/]*/)*'; i += 2; } else { re += '.*'; i += 1; }
      } else re += '[^/]*';
    } else if (c === '?') re += '[^/]';
    else if (c === '{') { re += '(?:'; depth++; }
    else if (c === '}' && depth) { re += ')'; depth--; }
    else if (c === ',' && depth) re += '|';
    else if (c === '[') {
      const end = g.indexOf(']', i + 1);
      if (end < 0) { re += '\\['; continue; }
      const body = g.slice(i + 1, end).replace(/^!/, '^').replace(/\\/g, '\\\\');
      re += `[${body}]`;
      i = end;
    } else re += c.replace(/[.+^$()|\\]/g, '\\$&');
  }
  while (depth-- > 0) re += ')';
  return new RegExp(`^${re}$`, ignoreCase ? 'i' : '');
}

/** `files.exclude` as a predicate: a path is excluded when the path or any of its folders matches a
 *  pattern set to `true` (a `{when: …}` sibling clause is not evaluated and does not exclude). */
export function excluder(patterns: Record<string, unknown> | undefined, ignoreCase = false): (path: string) => boolean {
  const res = Object.entries(patterns ?? {}).filter(([, v]) => v === true).map(([k]) => globToRegExp(k, ignoreCase));
  if (!res.length) return () => false;
  return path => {
    for (let i = path.indexOf('/'); ; i = path.indexOf('/', i + 1)) {
      const part = i < 0 ? path : path.slice(0, i);
      if (res.some(r => r.test(part))) return true;
      if (i < 0) return false;
    }
  };
}

// -- matching --------------------------------------------------------------------------------------
const base = (p: string) => p.slice(p.lastIndexOf('/') + 1);

function subsequence(hay: string, q: string): boolean {
  let j = 0;
  for (let i = 0; i < hay.length && j < q.length; i++) if (hay[i] === q[j]) j++;
  return j === q.length;
}

/** Fuzzy rows for `q` (lower case): the basename's prefix ranks first, then a basename substring, a path
 *  substring, and a subsequence of the path; shorter paths first, then A-Z. */
function fuzzy(entries: readonly PathHit[], q: string, cap: number): PathHit[] {
  const scored: [number, PathHit][] = [];
  for (const e of entries) {
    const p = e.path.toLowerCase();
    const b = base(p);
    const s = b.startsWith(q) ? 0 : b.includes(q) ? 1 : p.includes(q) ? 2 : subsequence(p, q) ? 3 : -1;
    if (s >= 0) scored.push([s, e]);
  }
  return scored.sort((a, b) => a[0] - b[0] || byName(a[1], b[1])).slice(0, cap).map(x => x[1]);
}

const byName = (a: PathHit, b: PathHit) => a.path.length - b.path.length || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
const az = (a: PathHit, b: PathHit) => a.path.localeCompare(b.path, undefined, { sensitivity: 'base' });
const parentOf = (p: string) => { const i = p.lastIndexOf('/'); return i < 0 ? '' : p.slice(0, i); };

/** One level of the tree (C13, shell completion, owner m-28122bc446): the children of `dir` (lower case,
 *  '' = the git root), folders then files, A-Z. A level whose only entry is one folder opens that folder
 *  instead (architect m-f1b57a4176). `dir` in the answer is the real-cased level listed. */
export function levelOf(entries: readonly PathHit[], dir: string): { dir: string; rows: PathHit[] } {
  let at = dir.toLowerCase();
  let real = at ? entries.find(e => e.kind === 'folder' && e.path.toLowerCase() === at)?.path ?? dir : '';
  let rows = entries.filter(e => parentOf(e.path.toLowerCase()) === at);
  while (rows.length === 1 && rows[0].kind === 'folder') {
    real = rows[0].path;
    at = real.toLowerCase();
    rows = entries.filter(e => parentOf(e.path.toLowerCase()) === at);
  }
  return { dir: real, rows: [...rows.filter(e => e.kind === 'folder').sort(az), ...rows.filter(e => e.kind === 'file').sort(az)] };
}

/** The picker's answer: the rows, the level they list (null: a fuzzy answer, no level), and the query
 *  that goes one level up (null: at the top, or no level). */
export type Level = { rows: PathHit[]; level: string | null; up: string | null };

const depth = (d: string) => (d ? d.split('/').length : 0);

/** The query that lists folder `dir` (root-relative), written from `home` (the open workspace folder's
 *  path in the repo): home itself is the empty query, an ancestor of home is `../` per level, anything else
 *  its root-relative path with a `/`. A token is always root-relative; only the query says `..`. */
export function queryFor(dir: string, home: string): string {
  const d = dir.toLowerCase(), h = home.toLowerCase();
  if (d === h) return '';
  if (!d || h.startsWith(`${d}/`)) return '../'.repeat(depth(h) - depth(d));
  return `${dir}/`;
}

/** The picker rows for `query`, case-insensitive, at most `cap`, as seen from `home`.
 *  - '' lists home (the open workspace folder's level; the git root when the folder is the repo).
 *  - Leading `../` (or a bare `..`) climb from home, one level each, never above the git root.
 *  - The text up to the last `/` names the level (a root-relative folder, or one under home); the rest
 *    filters it: the level's own matches first (basename prefix, substring, subsequence), then fuzzy
 *    matches deeper under it, so a name typed at the top still finds a deep file.
 *  - A `/` path that is no folder (`code/webview`) is matched fuzzily across the whole tree. */
export function findLevel(entries: readonly PathHit[], query: string, home = '', cap = PATH_HITS_MAX): Level {
  let q = query.toLowerCase().replace(/\\/g, '/');
  let from = home.toLowerCase();
  let climbed = false;
  while (q === '..' || q.startsWith('../')) { climbed = true; from = parentOf(from); q = q === '..' ? '' : q.slice(3); }
  const cut = q.lastIndexOf('/');
  const sub = cut < 0 ? '' : q.slice(0, cut).replace(/\/+$/, '');
  const leaf = q.slice(cut + 1);
  const isFolder = (d: string) => !d || entries.some(e => e.kind === 'folder' && e.path.toLowerCase() === d);
  const under = (b: string, x: string) => (b ? (x ? `${b}/${x}` : b) : x);
  let dir: string | null;
  if (climbed) dir = under(from, sub);
  else if (!sub) dir = from;
  // a name under home wins over the same name at the root (`docs/` from v8 is v8/docs; ../docs/ is the root's)
  else dir = isFolder(under(from, sub)) ? under(from, sub) : isFolder(sub) ? sub : null;
  if (dir === null || !isFolder(dir)) return { rows: fuzzy(entries, q.replace(/\/+$/, ''), cap), level: null, up: null };
  const lv = levelOf(entries, dir);
  const up = upFrom(entries, lv.dir, home);
  if (!leaf) return { rows: lv.rows.slice(0, cap), level: lv.dir, up };
  const mine: [number, PathHit][] = [];
  for (const e of lv.rows) {
    const b = base(e.path.toLowerCase());
    const s = b.startsWith(leaf) ? 0 : b.includes(leaf) ? 1 : subsequence(b, leaf) ? 2 : -1;
    if (s >= 0) mine.push([s, e]);
  }
  const first = mine.sort((a, b) => a[0] - b[0] || byName(a[1], b[1])).map(x => x[1]);
  if (first.length >= cap) return { rows: first.slice(0, cap), level: lv.dir, up };
  const seen = new Set(first);
  const lvl = lv.dir.toLowerCase();
  const deeper = entries.filter(e => !seen.has(e) && (!lvl || e.path.toLowerCase().startsWith(`${lvl}/`)));
  return { rows: [...first, ...fuzzy(deeper, leaf, cap - first.length)], level: lv.dir, up };
}

/** The query one level up from `level`: its parent, skipping parents that would auto-descend straight
 *  back here (their only entry is the folder we came from); null at the git root. */
function upFrom(entries: readonly PathHit[], level: string, home: string): string | null {
  if (!level) return null;
  let p = parentOf(level);
  while (levelOf(entries, p).dir.toLowerCase() === level.toLowerCase()) {
    if (!p) return null;
    p = parentOf(p);
  }
  return queryFor(p, home);
}

/** The picker rows only (see findLevel). */
export const matchPaths = (entries: readonly PathHit[], query: string, cap = PATH_HITS_MAX, home = ''): PathHit[] =>
  findLevel(entries, query, home, cap).rows;

/** Shell completion keys (C13): the query that opens folder `h` (its children listed next). */
export const descendQuery = (h: PathHit) => `${h.path}/`;

/** The index rows: every file and every folder above one, in no particular order. */
export function indexRows(files: readonly string[]): PathHit[] {
  const ok = files.filter(taggable);
  return [...foldersOf(ok).map(path => ({ path, kind: 'folder' as const })), ...ok.map(path => ({ path, kind: 'file' as const }))];
}

// -- links in rendered messages --------------------------------------------------------------------
/** An inline code span's text that could be a tagged path: repo-relative, no whitespace, with a `/`
 *  or a `.` (a bare word is not looked up). Returns the path without a folder's trailing `/`. */
export function pathCandidate(text: string): { path: string; folder: boolean } | undefined {
  const t = text.trim();
  if (!t || t.length > 1024 || /\s/.test(t) || !/[./]/.test(t)) return undefined;
  const folder = t.endsWith('/');
  const path = t.replace(/\/+$/, '');
  return taggable(path) && path !== '.' ? { path, folder } : undefined;
}
