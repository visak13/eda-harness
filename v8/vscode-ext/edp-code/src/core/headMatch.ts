// Is a tag anchor's text the file at HEAD? (s-17c13096e5, qa finding m-7beeffa077.) The answer is
// about the lines CAPTURED for the anchor: reading the buffer again after the git awaits let an edit
// made in between decide, so a stale clean could be reported as clean.

/** The buffer as it was when the anchor's lines were taken. */
export interface Snapshot {
  lines: readonly string[];
  isDirty: boolean;
}

const lf = (text: string) => text.replace(/\r\n/g, '\n');

/** The committed blob equals the captured lines (line endings aside). */
export function sameAsHead(committed: string, lines: readonly string[]): boolean {
  return lf(committed) === lines.join('\n');
}

/** dirty = unsaved at capture, OR git lists the path as changed, OR the captured lines differ from the
 *  blob at the captured HEAD. A missing blob or a failed read is never clean. No HEAD: status decides. */
export async function dirtyAgainstHead(snap: Snapshot, statusChanged: boolean, commit: string | null,
  show: (commit: string) => Promise<string>): Promise<boolean> {
  if (snap.isDirty || statusChanged) return true;
  if (!commit) return false;
  try {
    return !sameAsHead(await show(commit), snap.lines);
  } catch {
    return true;
  }
}
