import { beforeEach, describe, expect, it, vi } from 'vitest';
import type * as vscode from 'vscode';
import type { Board } from '../src/core/api';
import { parseSigninLink, redeemInvite } from '../src/core/signinUri';

// S6 (s-e6b4fa59d5): vscode://edp.edp-code/signin?board=&handle=&code= — confirm, redeem at /v1/join,
// store through the verified sign-in path, open EDP Chat.
const ui = vi.hoisted(() => ({ url: 'https://board-a.invalid', warn: vi.fn(), error: vi.fn(), exec: vi.fn(), update: vi.fn() }));
vi.mock('vscode', () => ({
  workspace: { getConfiguration: () => ({ get: () => ui.url, update: async (k: string, v: string) => { ui.update(k, v); ui.url = v; } }) },
  window: { showInputBox: vi.fn(), showErrorMessage: ui.error, showInformationMessage: vi.fn(), showWarningMessage: ui.warn },
  commands: { executeCommand: ui.exec },
  ConfigurationTarget: { Global: 1 },
}));
import { creds, signInFromUri } from '../src/vscode/auth';

function storage() {
  const values = new Map<string, string>();
  const ctx = { secrets: {
    get: async (key: string) => values.get(key),
    store: async (key: string, value: string) => { values.set(key, value); },
    delete: async (key: string) => { values.delete(key); },
  } } as unknown as vscode.ExtensionContext;
  return { values, ctx };
}
const reply = (status: number, body: unknown) => async () => ({ ok: status < 300, status, json: async () => body });
const link = (q: Record<string, string>) => ({ path: '/signin', query: new URLSearchParams(q).toString() });
const whoamiBoard = (whoami = vi.fn(async () => ({ handle: 'carol', role: 'owner' }))) => ({ board: () => ({ whoami } as unknown as Board), whoami });

beforeEach(() => { ui.url = 'https://board-a.invalid'; for (const f of [ui.warn, ui.error, ui.exec, ui.update]) f.mockReset(); });

describe('parseSigninLink', () => {
  it('reads board origin, handle and code', () => {
    expect(parseSigninLink('/signin', 'board=https%3A%2F%2Fhost.tail.ts.net%2Fui%2F&handle=carol&code=abc'))
      .toEqual({ origin: 'https://host.tail.ts.net', handle: 'carol', code: 'abc' });
  });
  it('says what is wrong with a bad link', () => {
    expect(parseSigninLink('/other', 'code=x')).toMatch(/not a sign-in link/);
    expect(parseSigninLink('/signin', 'code=x')).toMatch(/names no board/);
    expect(parseSigninLink('/signin', 'board=file%3A%2F%2Fx&code=x')).toMatch(/not http/);
    expect(parseSigninLink('/signin', 'board=http%3A%2F%2Fb')).toMatch(/no sign-in code/);
  });
});

describe('redeemInvite', () => {
  const l = { origin: 'http://b', handle: 'carol', code: 'abc' };
  it('posts the code to /v1/join and returns the handle and token', async () => {
    const f = vi.fn(reply(200, { ok: true, value: { handle: 'carol', token: 'T' } }));
    expect(await redeemInvite(f, l)).toEqual({ participant: 'carol', token: 'T' });
    expect(f).toHaveBeenCalledWith('http://b/v1/join', expect.objectContaining({ method: 'POST', body: JSON.stringify({ code: 'abc' }) }));
  });
  it("throws the board's refusal in its own words", async () => {
    await expect(redeemInvite(reply(401, { ok: false, error: { code: 'http', message: 'this invite was already used or has expired' } }), l))
      .rejects.toThrow('this invite was already used or has expired');
  });
  it('refuses a code that belongs to someone else', async () => {
    await expect(redeemInvite(reply(200, { ok: true, value: { handle: 'dave', token: 'T' } }), l)).rejects.toThrow(/belongs to dave/);
  });
});

describe('signInFromUri', () => {
  it('confirms, redeems, verifies, stores origin-bound creds and opens EDP Chat', async () => {
    const { ctx } = storage();
    const { board, whoami } = whoamiBoard();
    ui.warn.mockResolvedValueOnce('Sign in');
    const f = vi.fn(reply(200, { ok: true, value: { handle: 'carol', token: 'T' } }));
    const c = await signInFromUri(ctx, board, link({ board: 'https://board-a.invalid', handle: 'carol', code: 'abc' }), f);
    const want = { participant: 'carol', token: 'T', origin: 'https://board-a.invalid' };
    expect(c).toEqual(want);
    expect(whoami).toHaveBeenCalledWith(want);
    expect(await creds(ctx)).toEqual(want);
    expect(ui.exec).toHaveBeenCalledWith('edp.chat.open');
    expect(ui.update).not.toHaveBeenCalled();
  });

  it('sends nothing when the person does not confirm', async () => {
    const { ctx, values } = storage();
    ui.warn.mockResolvedValueOnce(undefined);
    const f = vi.fn();
    expect(await signInFromUri(ctx, whoamiBoard().board, link({ board: 'https://evil.invalid', handle: 'carol', code: 'abc' }), f)).toBeUndefined();
    expect(f).not.toHaveBeenCalled();
    expect(values.size).toBe(0);
    expect(ui.update).not.toHaveBeenCalled();
  });

  it('switches edp.boardUrl to the link board only on confirmation, saying so', async () => {
    const { ctx } = storage();
    ui.warn.mockResolvedValueOnce('Sign in');
    const f = vi.fn(reply(200, { ok: true, value: { handle: 'carol', token: 'T' } }));
    const c = await signInFromUri(ctx, whoamiBoard().board, link({ board: 'https://board-b.invalid/ui/', handle: 'carol', code: 'abc' }), f);
    expect(ui.warn.mock.calls[0][0]).toMatch(/this switches it/);
    expect(ui.update).toHaveBeenCalledWith('boardUrl', 'https://board-b.invalid');
    expect(c?.origin).toBe('https://board-b.invalid');
  });

  it("shows the board's refusal and stores nothing on a spent code", async () => {
    const { ctx, values } = storage();
    ui.warn.mockResolvedValueOnce('Sign in');
    const f = vi.fn(reply(401, { ok: false, error: { code: 'http', message: 'this invite was already used or has expired; ask an admin for a new one' } }));
    expect(await signInFromUri(ctx, whoamiBoard().board, link({ board: 'https://board-a.invalid', handle: 'carol', code: 'abc' }), f)).toBeUndefined();
    expect(ui.error).toHaveBeenCalledWith(expect.stringContaining('this invite was already used or has expired'));
    expect(values.size).toBe(0);
    expect(ui.exec).not.toHaveBeenCalled();
  });

  it('a malformed link is an error, never a prompt', async () => {
    const { ctx } = storage();
    expect(await signInFromUri(ctx, whoamiBoard().board, { path: '/signin', query: 'handle=carol' }, vi.fn())).toBeUndefined();
    expect(ui.warn).not.toHaveBeenCalled();
    expect(ui.error).toHaveBeenCalledWith(expect.stringMatching(/names no board/));
  });
});
