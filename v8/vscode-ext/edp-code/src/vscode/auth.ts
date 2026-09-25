// Sign-in: the participant id and token live ONLY in context.secrets (strategyll-51e4dae0bc §8).
// On code-server, secrets are per browser profile (PR #6450): a fresh browser prompts again.
import * as vscode from 'vscode';
import type { Board, Creds } from '../core/api';

const P = 'edp.participant', T = 'edp.token';

export async function creds(ctx: vscode.ExtensionContext): Promise<Creds | undefined> {
  try {
    const [participant, token] = await Promise.all([ctx.secrets.get(P), ctx.secrets.get(T)]);
    return participant && token ? { participant, token } : undefined;
  } catch {
    return undefined; // an unreadable store reads as signed out: the next command prompts
  }
}

/** Prompt, check the creds against the board, and store them only when the board accepts them. */
export async function signIn(ctx: vscode.ExtensionContext, board: () => Board): Promise<Creds | undefined> {
  const participant = (await vscode.window.showInputBox({
    title: 'EDP: board participant id', prompt: 'Your participant id or handle on the board', ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!participant) return undefined;
  const token = (await vscode.window.showInputBox({
    title: `EDP: token for ${participant}`, prompt: 'Stored in VS Code secret storage only', password: true, ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!token) return undefined;
  const c = { participant, token };
  try {
    const me = await board().whoami(c);
    await ctx.secrets.store(P, participant);
    await ctx.secrets.store(T, token);
    void vscode.window.showInformationMessage(`EDP: signed in as ${me.handle} (${me.role})`);
    return c;
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: sign-in refused: ${(e as Error).message}`);
    return undefined;
  }
}

export async function signOut(ctx: vscode.ExtensionContext): Promise<void> {
  await Promise.all([ctx.secrets.delete(P), ctx.secrets.delete(T)]);
  void vscode.window.showInformationMessage('EDP: signed out');
}

/** The creds, prompting for sign-in when there are none; undefined = the user cancelled. */
export async function credsOrSignIn(ctx: vscode.ExtensionContext, board: () => Board): Promise<Creds | undefined> {
  return (await creds(ctx)) ?? (await signIn(ctx, board));
}
