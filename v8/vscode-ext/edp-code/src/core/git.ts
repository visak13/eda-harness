// Guarded git and the external terminal: the parts that need no `vscode` (strategyll-ab18531441 §5-6).
import * as path from 'node:path';

/** Paths from `git status --porcelain=v1 -z`. A rename/copy entry is `XY new\0old\0`: the new path
 *  is reported, and the old path (the extra NUL field) is consumed, not listed. */
export function parsePorcelainZ(out: string): string[] {
  const parts = out.split('\0');
  const paths: string[] = [];
  for (let i = 0; i < parts.length; i++) {
    const e = parts[i];
    if (e.length < 4) continue;          // the trailing empty field
    const xy = e.slice(0, 2);
    paths.push(`${xy} ${e.slice(3)}`);
    if (xy[0] === 'R' || xy[0] === 'C') i++;
  }
  return paths;
}

export type GuardedOp = 'checkout' | 'merge' | 'pull';

/** The git argv for a guarded op; a ref that looks like an option is refused (execFile, no shell). */
export function guardedArgs(op: GuardedOp, target?: string): string[] {
  if (op === 'pull') return ['pull'];
  if (!target) throw new Error(`git ${op} needs a ref`);
  if (target.startsWith('-')) throw new Error('refusing a ref that looks like an option');
  return op === 'checkout' ? ['checkout', target] : ['merge', '--no-edit', target];
}

/** The confirm's detail: live seats (or "unknown"), dirty paths, and the honest limit. */
export function confirmDetail(seats: Array<{ handle: string; ticket_id: string | null }> | undefined, dirty: string[], reason?: string): string {
  const s = seats
    ? (seats.length ? `${seats.length} live seat${seats.length === 1 ? '' : 's'} on this board:\n${seats.map(x => `  ${x.handle} (${x.ticket_id ?? 'no ticket'})`).join('\n')}`
      : 'No live seats on this board.')
    : `Live seats: unknown (${reason ?? 'board unreachable'})`;
  const d = dirty.length
    ? `git status --porcelain (${dirty.length}):\n${dirty.slice(0, 30).map(p => `  ${p}`).join('\n')}${dirty.length > 30 ? `\n  … ${dirty.length - 30} more` : ''}`
    : 'Working tree clean.';
  return [s, d, 'This guard is opt-in: the built-in Source Control view is not guarded and cannot be vetoed.'].join('\n\n');
}

export type TerminalKind = 'pwsh' | 'cmd' | 'git-bash';

/** argv for the external terminal. The exe must be a real .exe: a .cmd/.bat needs a shell to spawn. */
export function terminalLaunch(kind: TerminalKind, exe: string, cwd: string): { exe: string; args: string[] } {
  if (!exe) throw new Error('edp.externalTerminal.exe is empty');
  if (path.win32.extname(exe).toLowerCase() !== '.exe') throw new Error(`edp.externalTerminal.exe must be a .exe (got ${exe})`);
  if (!['pwsh', 'cmd', 'git-bash'].includes(kind)) throw new Error(`edp.externalTerminal.kind must be pwsh, cmd or git-bash (got ${kind})`);
  return { exe, args: kind === 'git-bash' ? [`--cd=${cwd}`] : [] };
}
