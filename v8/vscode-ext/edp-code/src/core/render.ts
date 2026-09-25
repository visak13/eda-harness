// The tag message text (steer m-1607603a0c): the user's note plus ONE anchor line, the same compact
// form S4 renders for agents (`CodeAnchor.at()`). The snippet is NOT repeated in the text: the
// ticket page renders code_context as a code card and agents get it from S4's context rendering.
import type { Anchor } from './anchor';

/** `path:Lx-y @sha7[dirty]`, or `@no-git` outside a repo (or on an unborn branch). */
export function at(a: Pick<Anchor, 'path' | 'line_start' | 'line_end' | 'commit' | 'dirty'>): string {
  const sha = a.commit ? `@${a.commit.slice(0, 7)}${a.dirty ? '[dirty]' : ''}` : '@no-git';
  return `${a.path}:L${a.line_start}-${a.line_end} ${sha}`;
}

export function render(a: Anchor, note: string, truncated: boolean): string {
  // S4 refuses a backtick in `path`, so a single-backtick code span cannot be broken out of
  return `${note.trim()}\n\n\`${at(a)}\`${truncated ? ' (snippet truncated to 4096 B)' : ''}`;
}
