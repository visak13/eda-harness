import { describe, expect, it } from 'vitest';
import { confirmDetail, guardedArgs, parsePorcelainZ, terminalLaunch } from '../src/core/git';

describe('parsePorcelainZ', () => {
  it('modified, staged and untracked', () =>
    expect(parsePorcelainZ(' M src/a.ts\0M  b.py\0?? new.txt\0')).toEqual([' M src/a.ts', 'M  b.py', '?? new.txt']));
  it('a rename lists the new path and consumes the old one', () =>
    expect(parsePorcelainZ('R  new name.ts\0old name.ts\0 M z\0')).toEqual(['R  new name.ts', ' M z']));
  it('paths with spaces are kept whole (-z: no quoting)', () =>
    expect(parsePorcelainZ('?? dir with space/f i le.md\0')).toEqual(['?? dir with space/f i le.md']));
  it('clean tree -> nothing', () => expect(parsePorcelainZ('')).toEqual([]));
});

describe('guardedArgs', () => {
  it('checkout / merge / pull argv', () => {
    expect(guardedArgs('checkout', 'main')).toEqual(['checkout', 'main']);
    expect(guardedArgs('merge', 'feature/x')).toEqual(['merge', '--no-edit', 'feature/x']);
    expect(guardedArgs('pull')).toEqual(['pull']);
  });
  it('refuses a ref that looks like an option', () => expect(() => guardedArgs('checkout', '--orphan=x')).toThrow(/option/));
  it('needs a ref for checkout/merge', () => expect(() => guardedArgs('merge')).toThrow(/needs a ref/));
});

describe('confirmDetail', () => {
  it('lists live seats, dirty paths and the unguarded built-in SCM', () => {
    const d = confirmDetail([{ handle: 'engineer.s-1', ticket_id: 's-1' }], [' M a.ts']);
    expect(d).toContain('1 live seat on this board');
    expect(d).toContain('engineer.s-1 (s-1)');
    expect(d).toContain(' M a.ts');
    expect(d).toContain('built-in Source Control view is not guarded');
  });
  it('an unreachable board reads "unknown", not zero', () =>
    expect(confirmDetail(undefined, [], 'board unreachable')).toContain('Live seats: unknown (board unreachable)'));
  it('caps the listed paths at 30', () => {
    const d = confirmDetail([], Array.from({ length: 40 }, (_, i) => `?? f${i}`));
    expect(d).toContain('… 10 more');
  });
});

describe('terminalLaunch (cmd /c start gives the shell its own console)', () => {
  it('pwsh: start "" /D "<cwd>" "<exe>", every piece quoted', () =>
    expect(terminalLaunch('pwsh', 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe', 'C:\\Program Files\\my repo')).toEqual({
      file: 'C:\\Windows\\System32\\cmd.exe',
      commandLine: '/d /c start "" /D "C:\\Program Files\\my repo" "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"',
    }));
  it('git-bash also gets --cd', () =>
    expect(terminalLaunch('git-bash', 'C:\\Program Files\\Git\\git-bash.exe', 'C:\\v8').commandLine).toBe('/d /c start "" /D "C:\\v8" "C:\\Program Files\\Git\\git-bash.exe" "--cd=C:\\v8"'));
  it('a .cmd/.bat is refused', () => expect(() => terminalLaunch('cmd', 'C:\\x\\start.cmd', 'C:\\v8')).toThrow(/\.exe/));
  it.each(['C:\\a&calc', 'C:\\a"b', 'C:\\100%x', 'C:\\a|b', 'C:\\a^b', 'C:\\a>b'])('a folder with a cmd metacharacter is refused: %s', cwd =>
    expect(() => terminalLaunch('pwsh', 'C:\\p\\powershell.exe', cwd)).toThrow(/cmd\.exe would interpret/));
  it('an exe with a metacharacter is refused', () => expect(() => terminalLaunch('pwsh', 'C:\\a&b\\x.exe', 'C:\\v8')).toThrow(/exe path/));
  it('an unknown kind is refused', () => expect(() => terminalLaunch('zsh' as never, 'C:\\x.exe', 'C:\\v8')).toThrow(/kind/));
});
