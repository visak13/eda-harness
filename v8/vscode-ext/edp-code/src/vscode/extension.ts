// EDP extension entry (design-449b628cdd §4; strategyll-51e4dae0bc). Runs in code-server's Node
// extension host (extensionKind workspace). Activation never fails for a missing secret.
import * as vscode from 'vscode';
import { boardClient } from '../core/api';
import { creds, signIn, signOut } from './auth';
import { Badge, showSeats } from './badge';
import { guarded } from './guardedGit';
import { tagSelection } from './tag';
import { openExternalTerminal } from './terminal';

export function activate(ctx: vscode.ExtensionContext): void {
  if (typeof process === 'undefined' || !process.versions?.node) {
    throw new Error('EDP needs the Node extension host (extensionKind workspace); it cannot run in the web worker host.');
  }
  // `method path -> status (ms)` lines only: never headers, bodies or creds
  const out = vscode.window.createOutputChannel('EDP', { log: true });
  const boardUrl = () => vscode.workspace.getConfiguration('edp').get<string>('boardUrl') || 'http://127.0.0.1:9400';
  const board = () => boardClient(boardUrl(), () => creds(ctx), fetch, line => out.info(line));
  const badge = new Badge(ctx, board);
  const cmd = (id: string, fn: (...a: any[]) => unknown) => vscode.commands.registerCommand(id, fn);

  ctx.subscriptions.push(out, badge,
    cmd('edp.signIn', async () => { if (await signIn(ctx, board)) badge.refresh(0); }),
    cmd('edp.signOut', async () => { await signOut(ctx); badge.refresh(0); }),
    cmd('edp.tagSelection', () => tagSelection(ctx, board, boardUrl)),
    cmd('edp.showSeats', () => showSeats(badge, boardUrl)),
    cmd('edp.checkout', () => guarded('checkout', ctx, board)),
    cmd('edp.merge', () => guarded('merge', ctx, board)),
    cmd('edp.pull', () => guarded('pull', ctx, board)),
    cmd('edp.openExternalTerminal', (uri?: vscode.Uri) => openExternalTerminal(uri)),
  );
}

export function deactivate(): void {}
