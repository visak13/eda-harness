// Where a code card opens (design-10b21760d9 §4.2, R8): the anchor's repo-relative `path` resolved in
// a LOCAL repo, never the sender's absolute `repo_root` (on a teammate's machine it names the host's
// clone). Order: a root that has the file AND the anchored commit, preferring the one whose root is
// `repo_root`; then any root that has the file. A commit that no local repo has is not an error: the
// card says "pull to see this change" (C6), and still opens the file when this clone has it. A path
// that is absolute, backslashed or climbs out with `..` is refused. Pure.
import { samePath } from './anchor';

export type CodeRef = { repo_root: string; path: string; line_start: number; line_end: number; commit: string | null };
export type CodeTarget =
  | { root: string; path: string; line_start: number; line_end: number; commit: string | null;
      /** the anchored commit is in no local repo: the lines may be from a newer tree */ missingCommit?: true }
  | { pull: string; path: string }
  | { error: string };

/** a full sha1/sha256 object name, the only thing ever passed to git from a card */
export const COMMIT = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/;

export function pullText(sha: string): string {
  return `${sha.slice(0, 7)} is not in this clone; pull to see this change.`;
}

export function safeRelPath(p: unknown): string | undefined {
  if (typeof p !== 'string' || !p || p.length > 1024) return undefined;
  if (p.includes('\\') || p.includes('\0') || p.startsWith('/') || /^[A-Za-z]:/.test(p)) return undefined;
  const segs = p.split('/');
  if (segs.some(s => s === '..' || s === '' || s === '.')) return undefined;
  return p;
}

/** `hasCommit` answers for roots and a COMMIT-shaped sha only; omitted, commits are not checked. */
export function codeTarget(a: CodeRef, roots: string[], exists: (root: string, rel: string) => boolean,
  hasCommit?: (root: string, sha: string) => boolean): CodeTarget {
  const rel = safeRelPath(a.path);
  if (!rel) return { error: `refused code path ${JSON.stringify(String(a.path).slice(0, 80))}` };
  const start = Math.max(1, Math.floor(Number(a.line_start) || 1));
  const end = Math.max(start, Math.floor(Number(a.line_end) || start));
  const commit = typeof a.commit === 'string' && a.commit ? a.commit : null;
  const ordered = [...roots.filter(r => samePath(r, a.repo_root)), ...roots.filter(r => !samePath(r, a.repo_root))];
  const withFile = ordered.filter(r => exists(r, rel));
  const at = (root: string, missingCommit?: true) =>
    ({ root, path: rel, line_start: start, line_end: end, commit, ...(missingCommit ? { missingCommit } : {}) });
  if (commit && hasCommit && COMMIT.test(commit)) {
    const both = withFile.find(r => hasCommit(r, commit));
    if (both) return at(both);
    if (!ordered.some(r => hasCommit(r, commit))) return withFile.length ? at(withFile[0], true) : { pull: commit, path: rel };
  }
  if (!withFile.length) return { error: `${rel} is not in any open repo${roots.length ? '' : ' (no git repo is open)'}` };
  return at(withFile[0]);
}
