// Where a code card opens (design-10b21760d9 §4.2, R8): the anchor's repo-relative `path` resolved in
// a LOCAL repo, preferring the one whose root is the anchor's `repo_root`, else the first open repo
// that has the file. `repo_root` is the sender's absolute path and is never opened as such on
// another machine. A path that is absolute, backslashed or climbs out with `..` is refused. Pure.
import { samePath } from './anchor';

export type CodeRef = { repo_root: string; path: string; line_start: number; line_end: number; commit: string | null };
export type CodeTarget = { root: string; path: string; line_start: number; line_end: number; commit: string | null } | { error: string };

export function safeRelPath(p: unknown): string | undefined {
  if (typeof p !== 'string' || !p || p.length > 1024) return undefined;
  if (p.includes('\\') || p.includes('\0') || p.startsWith('/') || /^[A-Za-z]:/.test(p)) return undefined;
  const segs = p.split('/');
  if (segs.some(s => s === '..' || s === '' || s === '.')) return undefined;
  return p;
}

export function codeTarget(a: CodeRef, roots: string[], exists: (root: string, rel: string) => boolean): CodeTarget {
  const rel = safeRelPath(a.path);
  if (!rel) return { error: `refused code path ${JSON.stringify(String(a.path).slice(0, 80))}` };
  const start = Math.max(1, Math.floor(Number(a.line_start) || 1));
  const end = Math.max(start, Math.floor(Number(a.line_end) || start));
  const ordered = [...roots.filter(r => samePath(r, a.repo_root)), ...roots.filter(r => !samePath(r, a.repo_root))];
  const root = ordered.find(r => exists(r, rel));
  if (!root) return { error: `${rel} is not in any open repo${roots.length ? '' : ' (no git repo is open)'}` };
  return { root, path: rel, line_start: start, line_end: end, commit: a.commit ?? null };
}
