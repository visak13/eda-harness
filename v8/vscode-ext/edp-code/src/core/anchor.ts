// The code anchor a tag carries (strategyll-ab18531441 §1; the field rules are S4's CodeContext).
// Pure: no `vscode` import. The VS Code shell turns editor objects into these plain inputs.
import { createHash } from 'node:crypto';
import * as path from 'node:path';

export const SNIPPET_MAX = 4096;

/** A selection in VS Code's 0-based coordinates, start <= end (editor.selection is always ordered). */
export type Sel = { startLine: number; startChar: number; endLine: number; endChar: number; isEmpty: boolean };

export type Anchor = {
  repo_root: string; path: string; line_start: number; line_end: number;
  commit: string | null; dirty: boolean; snippet: string; snippet_sha: string;
};

/** 1-based inclusive lines. An empty selection is the cursor line; a drag ending at column 0 of the
 *  next line does not include that line. */
export function lineSpan(s: Sel): [number, number] {
  let end = s.endLine;
  if (!s.isEmpty && end > s.startLine && s.endChar === 0) end -= 1;
  return [s.startLine + 1, end + 1];
}

/** `c:\x` -> `C:\x`: VS Code's fsPath lower-cases the drive letter. */
export const normDrive = (p: string) => p.replace(/^([a-z]):/, (_, d: string) => d.toUpperCase() + ':');

/** Windows paths compare case-insensitively; POSIX paths exactly. */
export function samePath(a: string, b: string, win = isWinPath(a) || isWinPath(b)): boolean {
  const n = (p: string) => stripSep(win ? path.win32.normalize(p) : path.posix.normalize(p));
  return win ? n(a).toLowerCase() === n(b).toLowerCase() : n(a) === n(b);
}
const isWinPath = (p: string) => /^[a-zA-Z]:[\\/]/.test(p) || p.startsWith('\\\\');
const stripSep = (p: string) => (p.length > 3 ? p.replace(/[\\/]+$/, '') : p);
const pathApi = (p: string) => (isWinPath(p) ? path.win32 : path.posix);

/** `fsPath` relative to `repoRoot`, `/`-separated. A file outside the root, or the root itself, throws. */
export function relPath(repoRoot: string, fsPath: string): string {
  const api = pathApi(repoRoot);
  const rel = api.relative(repoRoot, fsPath);
  if (!rel || rel === '..' || rel.startsWith('..' + api.sep) || api.isAbsolute(rel)) {
    throw new Error('file is outside the repo/folder');
  }
  return rel.split(api.sep).join('/');
}

/** Cut to at most `max` UTF-8 bytes on a code-point boundary. */
export function truncateUtf8(s: string, max = SNIPPET_MAX): { text: string; truncated: boolean } {
  const b = Buffer.from(s, 'utf8');
  if (b.length <= max) return { text: s, truncated: false };
  let cut = max;
  while (cut > 0 && (b[cut] & 0xc0) === 0x80) cut--; // b[cut] is the first byte NOT kept
  return { text: b.subarray(0, cut).toString('utf8'), truncated: true };
}

export const sha256 = (s: string) => createHash('sha256').update(s, 'utf8').digest('hex');

/** `lines` are the document's lines without EOL (TextDocument.lineAt(n).text), so the snippet is
 *  LF-joined whatever the file's EOL is. */
export function buildAnchor(i: { repoRoot: string; fsPath: string; lines: string[]; sel: Sel; commit: string | null; dirty: boolean }):
  { anchor: Anchor; truncated: boolean } {
  const [line_start, line_end] = lineSpan(i.sel);
  const repoRoot = normDrive(i.repoRoot);
  const { text: snippet, truncated } = truncateUtf8(i.lines.slice(line_start - 1, line_end).join('\n'));
  return {
    anchor: {
      repo_root: repoRoot, path: relPath(repoRoot, normDrive(i.fsPath)), line_start, line_end,
      commit: i.commit, dirty: i.dirty, snippet, snippet_sha: sha256(snippet),
    },
    truncated,
  };
}
