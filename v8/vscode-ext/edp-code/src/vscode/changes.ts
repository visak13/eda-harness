// Change cards, host side (design-10b21760d9 §4.1-4.2; strategyll-86c5b5068f §3): the commit index of
// the shared tree's repo, live on a HEAD move, the live uncommitted card, and the diff openers. git runs
// through execFile with the git extension's own git by absolute path and an argument array (no shell);
// every parse is in src/core. Paths from git are repo-relative and resolve against repo.rootUri only.
import { execFile } from 'node:child_process';
import * as vscode from 'vscode';
import type { UncommittedCard } from '../core/chatProtocol';
import { commitWindow, index, logArgs, mergeNewer, parseLog, type Indexed } from '../core/commits';
import { cardTitle, diffArgs, fileTitle, sides, workSides } from '../core/diffSides';
import { sameRows, uncommittedCard, workFiles, type RawChange, type WorkFile } from '../core/uncommitted';
import { sharedTreePaths } from './badge';
import type { API, Change, Repository } from './git.d';
import { inSharedTree } from '../core/seats';
import { gitApi } from './repo';

const DEBOUNCE_MS = 500;
const STATUS_GAP_MS = 1500;

function run(exe: string, cwd: string, args: string[], input?: string): Promise<string> {
  return new Promise((res, rej) => {
    const p = execFile(exe, args, { cwd, windowsHide: true, maxBuffer: 64 << 20, encoding: 'utf8' },
      (e, out, err) => (e ? rej(new Error((err || e.message).trim().slice(0, 300))) : res(out)));
    if (input !== undefined) p.stdin?.end(input); else p.stdin?.end();
  });
}

export type ChangesEvents = {
  /** commits that arrived on a HEAD move (newest first) */
  onCommits(added: Indexed[]): void;
  /** history was rewritten or the repo changed: re-read everything */
  onReset(): void;
  onUncommitted(card: UncommittedCard | null): void;
};

export class Changes implements vscode.Disposable {
  private repo?: Repository;
  private api?: API;
  private all: Indexed[] = [];
  private bySha = new Map<string, Indexed>();
  private head?: string;
  private empty?: string;
  private work: WorkFile[] = [];
  private card: UncommittedCard | null = null;
  private subs: vscode.Disposable[] = [];
  private repoSubs: vscode.Disposable[] = [];
  private headTimer?: ReturnType<typeof setTimeout>;
  private workTimer?: ReturnType<typeof setTimeout>;
  private reading: Promise<void> = Promise.resolve();
  private started?: Promise<void>;
  private disposed = false;

  constructor(private ctx: vscode.ExtensionContext, private ev: ChangesEvents, private log: (line: string) => void) {}

  get commits(): Indexed[] { return this.all; }
  get uncommitted(): UncommittedCard | null { return this.card; }
  get ready(): boolean { return !!this.repo; }

  /** Idempotent: find the repo, read the window, watch it. */
  start(): Promise<void> {
    return (this.started ??= (async () => {
      const api = await gitApi();
      if (this.disposed) return;
      // no git (disabled, failed to activate): let a later open() try again
      if (!api) { this.started = undefined; return; }
      this.api = api;
      this.subs.push(
        api.onDidOpenRepository(() => void this.pickRepo()),
        api.onDidCloseRepository(r => { if (r === this.repo) void this.pickRepo(); }),
        vscode.workspace.onDidChangeConfiguration(e => {
          if (e.affectsConfiguration('edp.chat.commitWindow')) this.queue(() => this.readAll(true));
          if (e.affectsConfiguration('edp.sharedTreePaths')) void this.pickRepo();
        }));
      await this.pickRepo();
    })());
  }

  /** The repo holding the shared tree (the badge's rule), else the first open one. */
  private async pickRepo(): Promise<void> {
    const api = this.api;
    if (!api || this.disposed) return;
    const paths = sharedTreePaths(this.ctx);
    const repo = api.repositories.find(r => inSharedTree(r.rootUri.fsPath, paths)) ?? api.repositories[0];
    if (repo === this.repo) return;
    this.repoSubs.forEach(d => d.dispose());
    this.repoSubs = [];
    clearTimeout(this.headTimer);
    this.repo = repo;
    this.empty = undefined;
    this.log(`changes: repo ${repo ? repo.rootUri.fsPath : 'none'}`);
    if (!repo) { this.all = []; this.bySha.clear(); this.head = undefined; this.setCard([]); this.ev.onReset(); return; }
    this.repoSubs.push(repo.state.onDidChange(() => {
      // a burst of git state events is one read
      clearTimeout(this.headTimer);
      this.headTimer = setTimeout(() => { if (repo.state.HEAD?.commit !== this.head) this.queue(() => this.readNewer()); }, DEBOUNCE_MS);
      this.scheduleWork();
    }));
    // the git extension's own refresh after an external save can take ~4 s; our watcher asks for a
    // status sooner (a burst of writes is one status call); .git internals are left to state.onDidChange
    const w = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(repo.rootUri, '**/*'));
    const poke = (u: vscode.Uri) => { if (!/\/\.git(\/|$)/.test(u.path)) this.scheduleStatus(); };
    this.repoSubs.push(w, w.onDidChange(poke), w.onDidCreate(poke), w.onDidDelete(poke));
    this.queue(() => this.readAll(true));
    this.scheduleWork(0);
  }

  private statusTimer?: ReturnType<typeof setTimeout>;
  private lastStatus = 0;
  /** Throttled: at most one status per STATUS_GAP_MS, however busy the shared tree is (seats write constantly). */
  private scheduleStatus() {
    if (this.statusTimer) return;
    const wait = Math.max(300, this.lastStatus + STATUS_GAP_MS - Date.now());
    this.statusTimer = setTimeout(() => {
      this.statusTimer = undefined;
      this.lastStatus = Date.now();
      const repo = this.repo;
      if (repo && !this.disposed) void repo.status().then(() => this.readWork(), () => {});
    }, wait);
  }

  private queue(job: () => Promise<void>): void {
    this.reading = this.reading.then(job).catch(e => this.log(`changes: git read failed (${(e as Error).message})`));
  }

  private get exe(): string { return this.api?.git.path || 'git'; }

  private async readAll(notify: boolean): Promise<void> {
    const repo = this.repo;
    if (!repo) return;
    const w = commitWindow(vscode.workspace.getConfiguration('edp.chat').get('commitWindow'));
    // the log and the recorded head come from one resolved sha (repo.state can lag the real HEAD)
    const root = repo.rootUri.fsPath;
    const head = (await run(this.exe, root, ['rev-parse', '--verify', '-q', 'HEAD']).catch(() => '')).trim();
    const out = /^[0-9a-f]{40}$/.test(head) ? await run(this.exe, root, logArgs(w, head)) : '';
    if (repo !== this.repo || this.disposed) return;
    this.set(index(parseLog(out)));
    this.head = head || undefined;
    this.log(`changes: ${this.all.length} commits in the window (${w.count} / ${w.days} days)`);
    if (notify) this.ev.onReset();
  }

  /** HEAD moved: read `<old>..HEAD` if the old head is an ancestor, else rebuild the window. */
  private async readNewer(): Promise<void> {
    const repo = this.repo;
    const head = repo?.state.HEAD?.commit;
    if (!repo || !head || head === this.head) return;
    const old = this.head;
    if (!old) return this.readAll(true);
    const root = repo.rootUri.fsPath;
    const ancestor = await run(this.exe, root, ['merge-base', '--is-ancestor', old, head]).then(() => true, () => false);
    if (this.disposed) return;
    if (!ancestor) { this.log('changes: history rewritten, rebuilding'); return this.readAll(true); }
    const w = commitWindow(vscode.workspace.getConfiguration('edp.chat').get('commitWindow'));
    const added = index(parseLog(await run(this.exe, root, logArgs(w, `${old}..HEAD`))));
    if (repo !== this.repo || this.disposed) return;
    const known = new Set(this.bySha.keys());
    this.set(mergeNewer(added, this.all, w.count));
    this.head = head;
    // only commits new to the index (an overlap re-read is not news), and still inside the window
    const fresh = added.filter(c => !known.has(c.sha) && this.bySha.has(c.sha));
    if (fresh.length) this.ev.onCommits(fresh);
  }

  private set(cs: Indexed[]) {
    this.all = cs;
    this.bySha = new Map(cs.map(c => [c.sha, c]));
  }

  // -- uncommitted ---------------------------------------------------------------------------------
  private scheduleWork(delay = DEBOUNCE_MS) {
    clearTimeout(this.workTimer);
    this.workTimer = setTimeout(() => void this.readWork(), delay);
  }

  private rel(uri: vscode.Uri): string | undefined {
    const root = this.repo?.rootUri;
    if (!root) return undefined;
    const r = root.path.endsWith('/') ? root.path : root.path + '/';
    const same = process.platform === 'win32' ? uri.path.toLowerCase().startsWith(r.toLowerCase()) : uri.path.startsWith(r);
    return same ? uri.path.slice(r.length) : undefined;
  }

  private raw(cs: readonly Change[]): RawChange[] {
    const out: RawChange[] = [];
    for (const c of cs) {
      const path = this.rel(c.uri);
      if (!path) continue;
      const old = c.originalUri && c.originalUri.path !== c.uri.path ? this.rel(c.originalUri) : undefined;
      out.push({ path, ...(old ? { oldPath: old } : {}), status: c.status });
    }
    return out;
  }

  private async readWork(): Promise<void> {
    const repo = this.repo;
    if (!repo || this.disposed) return;
    const s = repo.state;
    this.setCard(workFiles(this.raw(s.indexChanges), this.raw(s.workingTreeChanges), this.raw(s.untrackedChanges)));
  }

  private setCard(files: WorkFile[]) {
    this.work = files;
    const next = files.length ? uncommittedCard(files) : null;
    if (sameRows(next, this.card)) return;
    this.card = next;
    this.ev.onUncommitted(next);
  }

  // -- diffs ---------------------------------------------------------------------------------------
  private at = (p: string) => vscode.Uri.joinPath(this.repo!.rootUri, ...p.split('/'));
  private toGit = (u: vscode.Uri, ref: string) => this.api!.toGitUri(u, ref);

  private async emptyTree(): Promise<string> {
    // sha1 and sha256 repos differ: ask git once per repo
    return (this.empty ??= (await run(this.exe, this.repo!.rootUri.fsPath, ['hash-object', '-t', 'tree', '--stdin'], '')).trim());
  }

  /** A file row (path) opens vscode.diff; the card opens the multi-file diff. Only shas and paths in
   *  the host's own index are opened (the webview can name nothing else). */
  async openDiff(sha: string, path?: string): Promise<void> {
    await this.reading;
    const c = this.bySha.get(sha);
    if (!c || !this.repo || !this.api) { void vscode.window.showWarningMessage('EDP: that commit is not in this window\'s history (pull to see this change).'); return; }
    const present = await run(this.exe, this.repo.rootUri.fsPath, ['cat-file', '-e', `${sha}^{commit}`]).then(() => true, () => false);
    if (!present) { void vscode.window.showWarningMessage(`EDP: ${sha.slice(0, 7)} is not in this clone; pull to see this change.`); return; }
    const empty = await this.emptyTree();
    if (path !== undefined) {
      const f = c.files.find(x => x.path === path);
      if (!f) { this.log('changes: openDiff refused a path not in the commit'); return; }
      const [l, r] = diffArgs(sides(c, f, empty, this.at, this.toGit), empty, this.toGit);
      await vscode.commands.executeCommand('vscode.diff', l, r, fileTitle(c, f), { preview: true });
      return;
    }
    if (!c.files.length) { void vscode.window.showInformationMessage(`EDP: ${sha.slice(0, 7)} changes no files.`); return; }
    await vscode.commands.executeCommand('vscode.changes', cardTitle(c),
      c.files.map(f => { const s = sides(c, f, empty, this.at, this.toGit); return [s.label, s.l, s.r]; }));
  }

  async openUncommitted(path?: string): Promise<void> {
    if (!this.repo || !this.api) return;
    await this.repo.status().catch(() => {});
    await this.readWork();
    const files = path !== undefined ? this.work.filter(f => f.path === path) : this.work;
    if (path !== undefined && !files.length) { void vscode.window.showInformationMessage(`EDP: ${path} has no uncommitted change now.`); return; }
    if (!files.length) return;
    const empty = await this.emptyTree();
    if (path !== undefined) {
      const s = workSides(files[0], this.at, this.toGit);
      await vscode.commands.executeCommand('vscode.diff', s.l ?? this.toGit(s.label, empty), s.r ?? this.toGit(s.label, empty),
        `${path} (uncommitted)`, { preview: true });
      return;
    }
    await vscode.commands.executeCommand('vscode.changes', 'Uncommitted changes — all seats',
      files.map(f => { const s = workSides(f, this.at, this.toGit); return [s.label, s.l, s.r]; }));
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.headTimer);
    clearTimeout(this.workTimer);
    clearTimeout(this.statusTimer);
    this.repoSubs.forEach(d => d.dispose());
    this.subs.forEach(d => d.dispose());
  }
}
