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
  // checkout `<ref> --`: a typed path (`.`) is then an unknown ref, never a restore of working-tree files
  return op === 'checkout' ? ['checkout', target, '--'] : ['merge', '--no-edit', target];
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

/** cmd.exe metacharacters (and `"`): a path carrying one could break out of `start`'s quoted arguments. */
const CMD_META = /["%^&|<>!\r\n]/;

/** The external terminal launch. A shell spawned directly with `stdio: 'ignore'` reads NUL as stdin and
 *  exits at once (measured 2026-09-25: direct and conhost-hosted launches both died), so the shell is
 *  started through `cmd.exe /d /c start "" /D <cwd> <exe>`: `start` gives it a fresh console of its own.
 *  The command line is built here and passed verbatim; every piece is quoted, and a cwd or exe holding a
 *  cmd metacharacter is refused rather than escaped. The exe must be a real .exe. */
export function terminalLaunch(kind: TerminalKind, exe: string, cwd: string, comspec = 'C:\\Windows\\System32\\cmd.exe'):
  { file: string; commandLine: string } {
  if (!exe) throw new Error('edp.externalTerminal.exe is empty');
  if (path.win32.extname(exe).toLowerCase() !== '.exe') throw new Error(`edp.externalTerminal.exe must be a .exe (got ${exe})`);
  if (!['pwsh', 'cmd', 'git-bash'].includes(kind)) throw new Error(`edp.externalTerminal.kind must be pwsh, cmd or git-bash (got ${kind})`);
  for (const [what, v] of [['exe', exe], ['folder', cwd]] as const) {
    if (CMD_META.test(v)) throw new Error(`the ${what} path contains a character cmd.exe would interpret (" % ^ & | < > !): ${v}`);
  }
  const q = (s: string) => `"${s}"`;
  const args = kind === 'git-bash' ? [q(`--cd=${cwd}`)] : [];
  return { file: comspec, commandLine: ['/d', '/c', 'start', '""', '/D', q(cwd), q(exe), ...args].join(' ') };
}
