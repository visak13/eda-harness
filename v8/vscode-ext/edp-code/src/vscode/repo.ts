// The built-in git extension's API (strategyll-ab18531441 §2). Types are vendored (git.d.ts, 1.138).
import * as vscode from 'vscode';
import type { API, GitExtension, Repository } from './git.d';

let cached: Promise<API | undefined> | undefined;

export function gitApi(): Promise<API | undefined> {
  return (cached ??= (async () => {
    const ext = vscode.extensions.getExtension<GitExtension>('vscode.git');
    if (!ext) return undefined;
    const exp = ext.isActive ? ext.exports : await ext.activate();
    if (!exp.enabled) return undefined; // git.enabled=false
    const api = exp.getAPI(1);
    if (api.state !== 'initialized') {
      await new Promise<void>(r => { const d = api.onDidChangeState(s => { if (s === 'initialized') { d.dispose(); r(); } }); });
    }
    return api;
  })().catch(() => { cached = undefined; return undefined; }));
}

const same = (a: vscode.Uri, b: vscode.Uri) => process.platform === 'win32'
  ? a.fsPath.toLowerCase() === b.fsPath.toLowerCase() : a.fsPath === b.fsPath;

/** HEAD and dirty for a document: dirty = unsaved buffer OR the file differs from HEAD (working
 *  tree, index or untracked). No repo (or an unborn branch) gives commit null. */
export async function headAndDirty(api: API | undefined, doc: vscode.TextDocument):
  Promise<{ repo: Repository | undefined; repoRoot: string | undefined; commit: string | null; dirty: boolean }> {
  const repo = api?.getRepository(doc.uri) ?? undefined;
  if (!repo) return { repo: undefined, repoRoot: undefined, commit: null, dirty: doc.isDirty };
  await repo.status(); // state can lag an external edit
  const s = repo.state;
  const changed = [...s.workingTreeChanges, ...s.indexChanges, ...s.untrackedChanges, ...s.mergeChanges].some(c => same(c.uri, doc.uri));
  const commit = s.HEAD?.commit ?? null;
  let dirty = doc.isDirty || changed;
  // Ignored files are absent from every status list. A clean anchor must have a blob at the
  // captured HEAD and match that revision, even if status suppresses the selected path.
  if (!dirty && commit) {
    try {
      const committed = await repo.show(commit, doc.uri.fsPath);
      // Compare text, not status/diff shortcuts (which can omit ignored or assume-unchanged paths).
      const lf = (text: string) => text.replace(/\r\n/g, '\n');
      dirty = lf(committed) !== lf(doc.getText());
    } catch { dirty = true; } // missing blob or unreadable comparison: never claim clean
  }
  return { repo, repoRoot: repo.rootUri.fsPath, commit, dirty: doc.isDirty || dirty };
}

/** The repository for the active editor, else the only/first open one. */
export async function currentRepo(): Promise<Repository | undefined> {
  const api = await gitApi();
  if (!api) return undefined;
  const uri = vscode.window.activeTextEditor?.document.uri;
  const byEditor = uri ? api.getRepository(uri) : null;
  return byEditor ?? api.repositories[0];
}
