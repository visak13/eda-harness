// Board-backed pickers open at once with `busy` while the fetch runs (strategyll-ab18531441 §3).
// Esc (hide) resolves undefined: cancelling is not an error.
import * as vscode from 'vscode';

export function pick<T extends vscode.QuickPickItem>(title: string, load: () => Promise<T[]>, placeholder?: string): Promise<T | undefined> {
  return new Promise(resolve => {
    const qp = vscode.window.createQuickPick<T>();
    Object.assign(qp, { title, placeholder, busy: true, ignoreFocusOut: true, matchOnDescription: true, matchOnDetail: true });
    let done = false;
    const finish = (v?: T) => { if (!done) { done = true; resolve(v); qp.dispose(); } };
    qp.onDidAccept(() => finish(qp.selectedItems[0]));
    qp.onDidHide(() => finish(undefined));
    qp.show();
    load().then(items => { qp.items = items; qp.busy = false; },
      e => { finish(undefined); void vscode.window.showErrorMessage(`EDP: ${(e as Error).message}`); });
  });
}

export const separator = (label: string) => ({ label, kind: vscode.QuickPickItemKind.Separator });
