// EDP: Open external terminal here (strategyll-ab18531441 §6). Opens on the SERVER's desktop, which is
// the same machine in this epic (design §4).
import { spawn } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { terminalLaunch, type TerminalKind } from '../core/git';

// absolute: pwsh 7 is not installed on this host, and a bare name depends on the service's PATH
const DEFAULT_EXE = 'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe';

export async function openExternalTerminal(uri?: vscode.Uri): Promise<void> {
  const cfg = vscode.workspace.getConfiguration('edp').get<{ kind?: TerminalKind; exe?: string }>('externalTerminal') ?? {};
  const target = uri ?? vscode.window.activeTextEditor?.document.uri;
  const folder = target?.scheme === 'file'
    ? (vscode.workspace.getWorkspaceFolder(target)?.uri.fsPath ?? path.dirname(target.fsPath))
    : vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  if (!folder) { void vscode.window.showWarningMessage('EDP: open a folder first.'); return; }
  try {
    const exe = cfg.exe ?? DEFAULT_EXE;
    if (path.win32.isAbsolute(exe) && !fs.existsSync(exe)) throw new Error(`edp.externalTerminal.exe not found: ${exe}`);
    const comspec = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'cmd.exe');
    const { file, commandLine } = terminalLaunch(cfg.kind ?? 'pwsh', exe, folder, comspec);
    // windowsVerbatimArguments: terminalLaunch quoted every piece; node must not re-quote them for cmd
    const child = spawn(file, [commandLine], { cwd: folder, detached: true, stdio: 'ignore', windowsHide: true, windowsVerbatimArguments: true });
    child.on('error', e => void vscode.window.showErrorMessage(`EDP: could not start ${exe}: ${e.message}`));
    child.on('exit', code => { if (code) void vscode.window.showErrorMessage(`EDP: could not start ${exe} (start exited ${code})`); });
    child.unref();
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: ${(e as Error).message}`);
  }
}
