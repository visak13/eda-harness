// EDP: Open external terminal here (strategyll-ab18531441 §6). Opens on the SERVER's desktop, which is
// the same machine in this epic (design §4).
import { spawn } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { terminalLaunch, type TerminalKind } from '../core/git';

export async function openExternalTerminal(uri?: vscode.Uri): Promise<void> {
  const cfg = vscode.workspace.getConfiguration('edp').get<{ kind?: TerminalKind; exe?: string }>('externalTerminal') ?? {};
  const target = uri ?? vscode.window.activeTextEditor?.document.uri;
  const folder = target?.scheme === 'file'
    ? (vscode.workspace.getWorkspaceFolder(target)?.uri.fsPath ?? path.dirname(target.fsPath))
    : vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!folder) { void vscode.window.showWarningMessage('EDP: open a folder first.'); return; }
  try {
    const { exe, args } = terminalLaunch(cfg.kind ?? 'pwsh', cfg.exe ?? 'pwsh.exe', folder);
    const child = spawn(exe, args, { cwd: folder, detached: true, stdio: 'ignore', windowsHide: false });
    child.on('error', e => void vscode.window.showErrorMessage(`EDP: could not start ${exe}: ${e.message}`));
    child.unref();
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: ${(e as Error).message}`);
  }
}
