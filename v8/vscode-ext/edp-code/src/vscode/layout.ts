// t-93da8bf09d: the workbench layout commands and the Code tab's Reset layout. The board cannot reach the layout
// (code-server keeps it in the browser), so POST /v1/code/reset-layout stamps RESET_STAMP in this extension's global
// storage, on the code-server host; every open window's extension host polls it and resets its own window.
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { Layout, RESET_STAMP, freshStamp } from '../core/layout';

const POLL_MS = 1500;

export function registerLayout(ctx: vscode.ExtensionContext, layout: Layout, log: (line: string) => void): vscode.Disposable[] {
  const stamp = path.join(ctx.globalStorageUri.fsPath, RESET_STAMP);
  const since = Date.now();
  const onStamp = (cur: fs.Stats, prev: fs.Stats) => {
    if (!freshStamp(cur.mtimeMs, prev.mtimeMs, since)) return;
    log('layout: Reset layout stamp from the Code tab');
    void layout.reset();
  };
  fs.watchFile(stamp, { interval: POLL_MS, persistent: false }, onStamp);
  return [
    vscode.commands.registerCommand('edp.layout.reset', () => layout.reset()),
    vscode.commands.registerCommand('edp.doc.exitFullScreen', () => layout.exitFullScreen()),
    { dispose: () => fs.unwatchFile(stamp, onStamp) },
  ];
}
