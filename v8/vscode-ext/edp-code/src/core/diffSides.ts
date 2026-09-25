// Diff sides for a change card (strategyll-86c5b5068f §3). Pure over an injected `at` (repo-relative
// path -> file uri) and `toGitUri` (the git API's; never built by hand), so vitest covers every case.
// The git FS provider returns an empty file only for the EMPTY TREE ref; any other missing path throws
// FileNotFound, so an added file's left side (and a deleted file's right side) is the empty tree for
// vscode.diff and `undefined` for vscode.changes. Root commits diff against the empty tree, merges
// against their first parent, renames take the old path on the left.
import type { FileChange } from './commits';

export type Sides<U> = { label: U; l: U | undefined; r: U | undefined };

export function sides<U>(c: { sha: string; parents: string[] }, f: FileChange, empty: string,
  at: (p: string) => U, toGitUri: (u: U, ref: string) => U): Sides<U> {
  const left = c.parents[0] ?? empty;
  const label = at(f.path);
  switch (f.status) {
    case 'A': return { label, l: undefined, r: toGitUri(label, c.sha) };
    case 'D': return { label, l: toGitUri(label, left), r: undefined };
    case 'R': case 'C': return { label, l: toGitUri(at(f.oldPath ?? f.path), left), r: toGitUri(label, c.sha) };
    default: return { label, l: toGitUri(label, left), r: toGitUri(label, c.sha) };
  }
}

/** vscode.diff needs both sides: a missing side is the empty tree. */
export function diffArgs<U>(s: Sides<U>, empty: string, toGitUri: (u: U, ref: string) => U): [U, U] {
  return [s.l ?? toGitUri(s.label, empty), s.r ?? toGitUri(s.label, empty)];
}

/** The title of a card's multi-diff editor (and of a file diff tab). */
export const cardTitle = (c: { sha: string; subject: string }) => `${c.sha.slice(0, 7)} ${c.subject}`;
export const fileTitle = (c: { sha: string }, f: FileChange) => `${f.path} (${c.sha.slice(0, 7)})`;

/** The uncommitted card's file: HEAD on the left, the working file on the right; untracked/added have
 *  an empty-tree left, deleted an empty-tree right (vscode.changes takes `undefined` for those). */
export type WorkStatus = 'M' | 'A' | 'D' | 'U' | 'R';
export function workSides<U>(f: { path: string; oldPath?: string; status: WorkStatus }, at: (p: string) => U,
  toGitUri: (u: U, ref: string) => U): Sides<U> {
  const label = at(f.path);
  switch (f.status) {
    case 'A': case 'U': return { label, l: undefined, r: label };
    case 'D': return { label, l: toGitUri(label, 'HEAD'), r: undefined };
    case 'R': return { label, l: toGitUri(at(f.oldPath ?? f.path), 'HEAD'), r: label };
    default: return { label, l: toGitUri(label, 'HEAD'), r: label };
  }
}
