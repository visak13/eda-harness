// EDP: Checkout… / Merge… / Pull (guarded) (strategyll-ab18531441 §5). An opt-in path: the built-in
// Source Control view stays unguarded and cannot be vetoed (no pre-checkout hook exists).
import { execFile } from 'node:child_process';
import * as vscode from 'vscode';
import type { Board } from '../core/api';
import { confirmDetail, guardedArgs, parsePorcelainZ, type GuardedOp } from '../core/git';
import { liveSeats } from '../core/seats';
import { creds } from './auth';
import type { Repository } from './git.d';
import { currentRepo, gitApi } from './repo';

/** The git extension's resolved git by absolute path, no shell: a branch name cannot inject a command, and
 *  a `git.exe` planted in the repo is not run (Windows searches the cwd before PATH for a bare name).
 *  stderr is the actionable text. */
export const git = (exe: string, cwd: string, args: string[]) => new Promise<string>((res, rej) =>
  execFile(exe, args, { cwd, windowsHide: true, maxBuffer: 8 << 20 }, (e, out, err) => (e ? rej(new Error((err || e.message).trim())) : res(out))));

async function pickRef(repo: Repository, op: GuardedOp): Promise<string | undefined> {
  const refs = repo.state.refs.length ? repo.state.refs : await repo.getRefs({});
  // RefType is a const enum (types only): 0 head, 1 remote head, 2 tag; tags are offered to checkout only
  const items = refs.filter(r => r.name && (op === 'checkout' || r.type !== 2))
    .map(r => ({ label: r.name!, description: r.type === 1 ? 'remote' : r.type === 2 ? 'tag' : 'branch', detail: r.commit?.slice(0, 7) }));
  const qp = vscode.window.createQuickPick();
  Object.assign(qp, { title: `EDP: git ${op} (guarded)`, placeholder: 'Pick a ref, or type one', items, ignoreFocusOut: true });
  return new Promise(resolve => {
    let done = false;
    const finish = (v?: string) => { if (!done) { done = true; resolve(v); qp.dispose(); } };
    qp.onDidAccept(() => finish((qp.selectedItems[0]?.label ?? qp.value).trim() || undefined));
    qp.onDidHide(() => finish(undefined));
    qp.show();
  });
}

export async function guarded(op: GuardedOp, ctx: vscode.ExtensionContext, board: () => Board): Promise<void> {
  const repo = await currentRepo();
  const exe = (await gitApi())?.git.path;
  if (!repo || !exe) { void vscode.window.showWarningMessage('EDP: no git repository is open.'); return; }
  const root = repo.rootUri.fsPath;
  try {
    const target = op === 'pull' ? undefined : await pickRef(repo, op);
    if (op !== 'pull' && !target) return;
    const args = guardedArgs(op, target); // refuses `-…` refs before anything runs
    const seatsP = (async () => {
      if (!(await creds(ctx))) throw new Error('not signed in');
      const b = board();
      const [ss, ps] = await Promise.all([b.sessions(), b.participants()]);
      return liveSeats(ss, ps);
    })();
    const [porcelain, seats] = await Promise.all([
      git(exe, root, ['status', '--porcelain=v1', '-z']),
      seatsP.then(s => ({ s }), (e: Error) => ({ e: e.message })),
    ]);
    const detail = confirmDetail('s' in seats ? seats.s : undefined, parsePorcelainZ(porcelain), 'e' in seats ? seats.e : undefined);
    const go = await vscode.window.showWarningMessage(`git ${args.join(' ')} on ${root}?`, { modal: true, detail }, 'Proceed');
    if (go !== 'Proceed') return;
    await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: `git ${args.join(' ')}` }, () => git(exe, root, args));
    await repo.status();
    void vscode.window.showInformationMessage(`EDP: git ${args.join(' ')} done`);
  } catch (e) {
    void vscode.window.showErrorMessage(`EDP: ${(e as Error).message}`);
  }
}
