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

/** The picker rows for `query`: case-insensitive; the basename's prefix ranks first, then a basename
 *  substring, a path substring, and a subsequence of the path; shorter paths first, then A-Z. An
 *  empty query lists the top-level folders, then the top-level files, each A-Z. At most `cap` rows. */
export function matchPaths(entries: readonly PathHit[], query: string, cap = PATH_HITS_MAX): PathHit[] {
  const q = query.toLowerCase().replace(/\\/g, '/').replace(/\/+$/, '');
  const byName = (a: PathHit, b: PathHit) => a.path.length - b.path.length || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
  if (!q) {
    const top = entries.filter(e => !e.path.includes('/'));
    const az = (a: PathHit, b: PathHit) => a.path.localeCompare(b.path, undefined, { sensitivity: 'base' });
    return [...top.filter(e => e.kind === 'folder').sort(az), ...top.filter(e => e.kind === 'file').sort(az)].slice(0, cap);
  }
  const scored: [number, PathHit][] = [];
  for (const e of entries) {
    const p = e.path.toLowerCase();
    const b = base(p);
    const s = b.startsWith(q) ? 0 : b.includes(q) ? 1 : p.includes(q) ? 2 : subsequence(p, q) ? 3 : -1;
    if (s >= 0) scored.push([s, e]);
  }
  return scored.sort((a, b) => a[0] - b[0] || byName(a[1], b[1])).slice(0, cap).map(x => x[1]);
}

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
