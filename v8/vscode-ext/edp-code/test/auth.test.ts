import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as vscode from 'vscode';
import type { Board } from '../src/core/api';
const ui = vi.hoisted(() => ({ url: 'https://board-a.invalid', input: vi.fn(), error: vi.fn() }));
vi.mock('vscode', () => ({
  workspace: { getConfiguration: () => ({ get: () => ui.url }) },
  window: { showInputBox: ui.input, showErrorMessage: ui.error, showInformationMessage: vi.fn() },
}));
import { creds, signIn, signOut } from '../src/vscode/auth';

function storage(seed: Record<string, string> = {}) {
  const values = new Map(Object.entries(seed));
  const ctx = { secrets: {
    get: async (key: string) => values.get(key),
    store: async (key: string, value: string) => { values.set(key, value); },
    delete: async (key: string) => { values.delete(key); },
  } } as unknown as vscode.ExtensionContext;
  return { values, ctx };
}
const bound = { origin: 'https://board-a.invalid', participant: 'owner', token: 'DUMMY' };
beforeEach(() => { ui.url = 'https://board-a.invalid'; ui.input.mockReset(); ui.error.mockReset(); });

describe('origin-bound SecretStorage', () => {
  it('normalizes the origin, then refuses a changed destination and legacy secrets', async () => {
    const { ctx } = storage({ 'edp.credentials.v1': JSON.stringify(bound) });
    ui.url = 'https://BOARD-A.invalid:443/';
    expect(await creds(ctx)).toEqual(bound);
    ui.url = 'https://board-b.invalid';
    expect(await creds(ctx)).toBeUndefined();
    expect(await creds(storage({ 'edp.participant': 'owner', 'edp.token': 'DUMMY' }).ctx)).toBeUndefined();
  });
  it('stores one destination-bound record after verification and removes old credentials', async () => {
    const { ctx, values } = storage({ 'edp.participant': 'old', 'edp.token': 'old' });
    ui.input.mockResolvedValueOnce('owner').mockResolvedValueOnce('DUMMY');
    const whoami = vi.fn(async () => ({ handle: 'owner', role: 'owner' }));
    await signIn(ctx, () => ({ whoami } as unknown as Board));
    expect(whoami).toHaveBeenCalledWith(bound);
    expect(await creds(ctx)).toEqual(bound);
    expect(values.has('edp.token')).toBe(false);
    await signOut(ctx);
    expect(values.size).toBe(0);
  });
  it('never sends the entered token if the destination changes during the prompts', async () => {
    const { ctx, values } = storage();
    ui.input.mockResolvedValueOnce('owner').mockImplementationOnce(async () => { ui.url = 'https://board-b.invalid'; return 'DUMMY'; });
    const whoami = vi.fn();
    expect(await signIn(ctx, () => ({ whoami } as unknown as Board))).toBeUndefined();
    expect(whoami).not.toHaveBeenCalled();
    expect(values.size).toBe(0);
  });
});
