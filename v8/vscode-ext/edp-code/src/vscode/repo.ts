// The built-in git extension's API (strategyll-ab18531441 §2). Types are vendored (git.d.ts, 1.138).
import * as vscode from 'vscode';
import type { API, GitExtension, Repository } from './git.d';
import { dirtyAgainstHead, type Snapshot } from '../core/headMatch';

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
 *  tree, index or untracked) OR the captured lines differ from the HEAD blob (core/headMatch).
 *  `snap` is the buffer as the anchor took it; the default takes it now. No repo (or an unborn
 *  branch) gives commit null. */
export async function headAndDirty(api: API | undefined, doc: vscode.TextDocument,
  snap: Snapshot = { lines: Array.from({ length: doc.lineCount }, (_, n) => doc.lineAt(n).text), isDirty: doc.isDirty }):
  Promise<{ repo: Repository | undefined; repoRoot: string | undefined; commit: string | null; dirty: boolean }> {
  const repo = api?.getRepository(doc.uri) ?? undefined;
  if (!repo) return { repo: undefined, repoRoot: undefined, commit: null, dirty: snap.isDirty };
  await repo.status(); // state can lag an external edit
  const s = repo.state;
  const changed = [...s.workingTreeChanges, ...s.indexChanges, ...s.untrackedChanges, ...s.mergeChanges].some(c => same(c.uri, doc.uri));
  const commit = s.HEAD?.commit ?? null;
  // Ignored files are absent from every status list, so a clean status still compares the captured
  // text to the blob (never a later getText(): an edit during the awaits must not decide)
  const dirty = await dirtyAgainstHead(snap, changed, commit, c => repo.show(c, doc.uri.fsPath));
  return { repo, repoRoot: repo.rootUri.fsPath, commit, dirty };
}

/** The repository for the active editor, else the only/first open one. */
export async function currentRepo(): Promise<Repository | undefined> {
  const api = await gitApi();
  if (!api) return undefined;
  const uri = vscode.window.activeTextEditor?.document.uri;
  const byEditor = uri ? api.getRepository(uri) : null;
  return byEditor ?? api.repositories[0];
}
