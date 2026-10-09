// qa report-689ceb50f0 fail 10: the extension declares limited support for untrusted workspaces (so the Chat view shows in
// Restricted Mode) and every path that runs git in the folder refuses until the person trusts it.
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';

const ws = vi.hoisted(() => ({ isTrusted: true }));
vi.mock('vscode', () => ({ workspace: ws }));

import { RESTRICTED, requireTrust, trusted } from '../src/vscode/trust';
import { git } from '../src/vscode/guardedGit';

describe('Restricted Mode', () => {
  it('package.json declares limited untrusted-workspace support with a plain description', () => {
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    expect(pkg.capabilities.untrustedWorkspaces.supported).toBe('limited');
    expect(pkg.capabilities.untrustedWorkspaces.description).toMatch(/git/);
  });
  // live finding (qa 0.10.7, reproduced in code-server 4.138.0): the workbench disables an extension that DEPENDS on one without
  // untrusted-workspace support, whatever the extension declares itself. vscode.git declares `supported: false`, so
  // `extensionDependencies: ["vscode.git"]` kept EDP Chat off in Restricted Mode even with `limited` (and with `true`).
  // The git API is optional here anyway: gitApi() asks for the extension at run time and copes with its absence.
  it('does not depend on the git extension, which is off in Restricted Mode and would take this one with it', () => {
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    expect(pkg.extensionDependencies ?? []).toEqual([]);
    expect(pkg.extensionPack ?? []).toEqual([]);
  });
  it('a trusted folder, or a host that does not say, runs git', () => {
    ws.isTrusted = true;
    expect(trusted()).toBe(true);
    expect(() => requireTrust()).not.toThrow();
  });
  it('an untrusted folder refuses before any process starts', async () => {
    ws.isTrusted = false;
    expect(trusted()).toBe(false);
    expect(() => requireTrust()).toThrow(RESTRICTED);
    await expect(git('git', '.', ['status'])).rejects.toThrow(RESTRICTED);
    ws.isTrusted = true;
  });
});
