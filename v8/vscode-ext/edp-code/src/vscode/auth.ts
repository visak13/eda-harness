// Sign-in: the participant id and token live ONLY in context.secrets (strategyll-51e4dae0bc §8).
// On code-server, secrets are per browser profile (PR #6450): a fresh browser prompts again.
import * as vscode from 'vscode';
import type { Board, Creds } from '../core/api';
import { parseSigninLink, redeemInvite } from '../core/signinUri';

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
  try { origin = boardOrigin(); } catch { void vscode.window.showErrorMessage('Heronry: board address is invalid.'); return; }
  const client = board(); // keep this sign-in attached to the destination shown in its prompts
  const participant = (await vscode.window.showInputBox({
    title: 'Heronry: board participant id', prompt: `Your participant id or handle on ${origin}`, ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!participant) return undefined;
  const token = (await vscode.window.showInputBox({
    title: `Heronry: token for ${participant}`, prompt: `Sign in to ${origin}; stored in VS Code secret storage only`, password: true, ignoreFocusOut: true,
    validateInput: v => (v.trim() ? undefined : 'Required'),
  }))?.trim();
  if (!token) return undefined;
  return verifyAndStore(ctx, client, { participant, token, origin });
}

/** Check the creds against the board, and store them only when the board accepts them. */
async function verifyAndStore(ctx: vscode.ExtensionContext, client: Board, c: Creds): Promise<Creds | undefined> {
  try {
    if (boardOrigin() !== c.origin) throw new Error('Board address changed; sign in again.');
    const me = await client.whoami(c);
    if (boardOrigin() !== c.origin) throw new Error('Board address changed; sign in again.');
    await ctx.secrets.store(C, JSON.stringify(c)); // one atomic origin-bound record
    await Promise.all([ctx.secrets.delete(P), ctx.secrets.delete(T)]);
    void vscode.window.showInformationMessage(`Heronry: signed in as ${me.handle} (${me.role})`);
    return c;
  } catch (e) {
    void vscode.window.showErrorMessage(`Heronry: sign-in refused: ${(e as Error).message}`);
    return undefined;
  }
}

/**
 * S6: vscode://edp.edp-code/signin?board=&handle=&code= (the admin's invite). Any web page can open a
 * vscode:// link, so nothing is sent until the person confirms the destination; a board other than the
 * configured one becomes edp.boardUrl only on that confirmation. The one-time code is redeemed at
 * POST /v1/join, then stored through the same verify-then-store path as the prompted sign-in, and EDP Chat opens.
 */
export async function signInFromUri(ctx: vscode.ExtensionContext, board: () => Board, uri: { path: string; query: string },
  fetchFn: Parameters<typeof redeemInvite>[0] = fetch): Promise<Creds | undefined> {
  const link = parseSigninLink(uri.path, uri.query);
  if (typeof link === 'string') { void vscode.window.showErrorMessage(`Heronry: ${link}`); return undefined; }
  let current: string | undefined;
  try { current = boardOrigin(); } catch { current = undefined; }
  const who = link.handle ? ` as ${link.handle}` : '';
  const switching = current !== link.origin;
  const go = await vscode.window.showWarningMessage(
    switching ? `Heronry: sign in to ${link.origin}${who}? VS Code now points at ${current ?? 'no valid board'}; this switches it.`
      : `Heronry: sign in to ${link.origin}${who}?`,
    { modal: true, detail: 'Only continue if an admin of that board sent you this link. The link works once.' }, 'Sign in');
  if (go !== 'Sign in') return undefined;
  if (switching) await vscode.workspace.getConfiguration('edp').update('boardUrl', link.origin, vscode.ConfigurationTarget.Global);
  let redeemed: { participant: string; token: string };
  try { redeemed = await redeemInvite(fetchFn, link); } catch (e) {
    void vscode.window.showErrorMessage(`Heronry: sign-in refused: ${(e as Error).message}`);
    return undefined;
  }
  const c = await verifyAndStore(ctx, board(), { ...redeemed, origin: link.origin });
  if (c) await vscode.commands.executeCommand('edp.chat.open');
  return c;
}

export async function signOut(ctx: vscode.ExtensionContext): Promise<void> {
  await Promise.all([ctx.secrets.delete(C), ctx.secrets.delete(P), ctx.secrets.delete(T)]);
  void vscode.window.showInformationMessage('Heronry: signed out');
}

/** The creds, prompting for sign-in when there are none; undefined = the user cancelled. */
export async function credsOrSignIn(ctx: vscode.ExtensionContext, board: () => Board): Promise<Creds | undefined> {
  return (await creds(ctx)) ?? (await signIn(ctx, board));
}
