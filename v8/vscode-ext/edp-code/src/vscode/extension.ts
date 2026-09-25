// EDP extension entry (design-449b628cdd §4; strategyll-51e4dae0bc). Runs in code-server's Node
// extension host (extensionKind workspace). Activation never fails for a missing secret.
import * as vscode from 'vscode';
import { ViewerRequests } from '../core/viewer';
import { creds, signIn, signOut } from './auth';
import { Badge, showSeats } from './badge';
import { ChatController } from './chat';
import { ChatViewProvider } from './chatView';
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
  const requests = new ViewerRequests(() => chat.clearViewer());
  const board = () => requests.board(boardUrl(), () => creds(ctx), line => out.info(line));
  const badge = new Badge(ctx, board, line => out.info(line));
  const chat = new ChatController(ctx, board, boardUrl, line => out.info(line), () => { requests.invalidate(); badge.clear(); }, () => requests.resume());
  const cmd = (id: string, fn: (...a: any[]) => unknown) => vscode.commands.registerCommand(id, fn);

  ctx.subscriptions.push(out, badge, ...chat.register(),
    ctx.secrets.onDidChange(e => { if (e.key === 'edp.credentials.v1') { badge.refresh(0); void chat.restart(); } }),
    vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('edp.boardUrl')) { badge.refresh(0); void chat.restart(); } }),
    cmd('edp.signIn', async () => { if (await signIn(ctx, board)) { badge.refresh(0); void chat.restart(); } }),
    cmd('edp.signOut', async () => { await signOut(ctx); badge.refresh(0); void chat.restart(); }),
    cmd('edp.chat.open', () => ChatViewProvider.reveal()),
    cmd('edp.chat.pick', async () => { await ChatViewProvider.reveal(); await chat.pick(); }),
    cmd('edp.tagSelection', () => tagSelection(ctx, board, boardUrl, chat)),
    cmd('edp.showSeats', () => showSeats(badge, boardUrl)),
    cmd('edp.checkout', () => guarded('checkout', ctx, board)),
    cmd('edp.merge', () => guarded('merge', ctx, board)),
    cmd('edp.pull', () => guarded('pull', ctx, board)),
    cmd('edp.openExternalTerminal', (uri?: vscode.Uri) => openExternalTerminal(uri)),
  );
}

export function deactivate(): void {}
