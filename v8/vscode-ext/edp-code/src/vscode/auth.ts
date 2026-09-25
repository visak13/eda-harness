// Sign-in: the participant id and token live ONLY in context.secrets (strategyll-51e4dae0bc §8).
// On code-server, secrets are per browser profile (PR #6450): a fresh browser prompts again.
import * as vscode from 'vscode';
import type { Board, Creds } from '../core/api';

const P = 'edp.participant', T = 'edp.token', C = 'edp.credentials.v1';
const boardOrigin = () => new URL(vscode.workspace.getConfiguration('edp').get<string>('boardUrl') || 'http://127.0.0.1:9400').origin;

export async function creds(ctx: vscode.ExtensionContext): Promise<Creds | undefined> {
  try {
    const origin = boardOrigin();
    const raw = await ctx.secrets.get(C);
    if (!raw) return undefined; // legacy unbound secrets require one fresh sign-in
    const c = JSON.parse(raw) as Creds;
    return c.origin === origin && boardOrigin() === origin && typeof c.participant === 'string' && c.participant
      && typeof c.token === 'string' && c.token ? c : undefined;
  } catch {
    return undefined; // an unreadable store reads as signed out: the next command prompts
  }
}

/** Prompt, check the creds against the board, and store them only when the board accepts them. */
export async function signIn(ctx: vscode.ExtensionContext, board: () => Board): Promise<Creds | undefined> {
  let origin: string;
  try { origin = boardOrigin(); } catch { void vscode.window.showErrorMessage('EDP: board address is invalid.'); return; }
  const client = board(); // keep this sign-in attached to the destination shown in its prompts
  const participant = (await vscode.window.showInputBox({
    title: 'EDP: board participant id', prompt: `Your participant id or handle on ${origin}`, ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!participant) return undefined;
  const token = (await vscode.window.showInputBox({
    title: `EDP: token for ${participant}`, prompt: `Sign in to ${origin}; stored in VS Code secret storage only`, password: true, ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!token) return undefined;
  const c = { participant, token, origin };
  try {
    if (boardOrigin() !== origin) throw new Error('Board address changed; sign in again.');
    const me = await client.whoami(c);
    if (boardOrigin() !== origin) throw new Error('Board address changed; sign in again.');
    await ctx.secrets.store(C, JSON.stringify(c)); // one atomic origin-bound record
    await Promise.all([ctx.secrets.delete(P), ctx.secrets.delete(T)]);
    void vscode.window.showInformationMessage(`EDP: signed in as ${me.handle} (${me.role})`);
    return c;
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: sign-in refused: ${(e as Error).message}`);
    return undefined;
  }
}

export async function signOut(ctx: vscode.ExtensionContext): Promise<void> {
  await Promise.all([ctx.secrets.delete(C), ctx.secrets.delete(P), ctx.secrets.delete(T)]);
  void vscode.window.showInformationMessage('EDP: signed out');
}

/** The creds, prompting for sign-in when there are none; undefined = the user cancelled. */
export async function credsOrSignIn(ctx: vscode.ExtensionContext, board: () => Board): Promise<Creds | undefined> {
  return (await creds(ctx)) ?? (await signIn(ctx, board));
}
