// The #-tag index, host side (C11 s-35ccc6d35f; design-10b21760d9 §13, architect ruling m-287aaaad59).
// Per workspace folder in a git repo: `git ls-files --cached --others --exclude-standard` (exact
// .gitignore) through execFile with the git extension's git and a timeout, minus `files.exclude`;
// outside git: workspace.findFiles under files.exclude. Paths are repo-relative (the folder's path in
// the repo prefixes them), folders derive from files. Built lazily on the first `#`, rebuilt after file
// creates/deletes (debounced), never per keystroke. Links resolve by stat against the same roots.
import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as vscode from 'vscode';
import type { PathHit, PathKind } from '../core/chatProtocol';
import { excluder, indexRows, matchPaths, parseLsFilesZ } from '../core/paths';
import { gitApi } from './repo';

const GIT_TIMEOUT_MS = 10_000;
const FIND_MAX = 20_000;
const REBUILD_MS = 2_000;

type Root = { uri: vscode.Uri; rows: PathHit[] };

function lsFiles(exe: string, cwd: string): Promise<string> {
  return new Promise((res, rej) => {
    const p = execFile(exe, ['-c', 'core.quotepath=false', 'ls-files', '-z', '--full-name', '--cached', '--others', '--exclude-standard'],
      { cwd, windowsHide: true, maxBuffer: 64 << 20, encoding: 'utf8', timeout: GIT_TIMEOUT_MS },
      (e, out, err) => (e ? rej(new Error((err || e.message).trim().slice(0, 300))) : res(out)));
    p.stdin?.end();
  });
}

const posix = (p: string) => p.split(path.sep).join('/');

export class PathIndex implements vscode.Disposable {
  private roots?: Promise<Root[]>;
  private timer?: ReturnType<typeof setTimeout>;
  private subs: vscode.Disposable[] = [];
  private disposed = false;

  constructor(private log: (line: string) => void) {
    const w = vscode.workspace.createFileSystemWatcher('**/*', false, true, false);
    const stale = () => this.stale();
    this.subs.push(w, w.onDidCreate(stale), w.onDidDelete(stale),
      vscode.workspace.onDidChangeWorkspaceFolders(stale),
      vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('files.exclude')) stale(); }));
  }

  /** A create/delete: rebuild once things settle, only if the index was ever built. */
  private stale(): void {
    if (!this.roots || this.disposed) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.roots = this.build(); }, REBUILD_MS);
  }

  private index(): Promise<Root[]> {
    return (this.roots ??= this.build());
  }

  private async build(): Promise<Root[]> {
    const t0 = Date.now();
    const api = await gitApi();
    const exe = api?.git.path || 'git';
    const byRoot = new Map<string, Root>();
    const win = process.platform === 'win32';
    for (const f of vscode.workspace.workspaceFolders ?? []) {
      const ex = excluder(vscode.workspace.getConfiguration('files', f.uri).get<Record<string, unknown>>('exclude'), win);
      const repo = api?.getRepository(f.uri) ?? null;
      try {
        if (repo) {
          // files.exclude is relative to the workspace folder; the paths are relative to the repo
          const prefix = posix(path.relative(repo.rootUri.fsPath, f.uri.fsPath));
          const pre = prefix && !prefix.startsWith('..') ? `${prefix}/` : '';
          const files = parseLsFilesZ(await lsFiles(exe, f.uri.fsPath)).filter(p => !ex(pre && p.startsWith(pre) ? p.slice(pre.length) : p));
          const key = repo.rootUri.fsPath;
          const had = byRoot.get(key);
          const rows = indexRows(files);
          byRoot.set(key, { uri: repo.rootUri, rows: had ? dedupe([...had.rows, ...rows]) : rows });
        } else {
          const uris = await vscode.workspace.findFiles(new vscode.RelativePattern(f, '**/*'), undefined, FIND_MAX);
          byRoot.set(f.uri.fsPath, { uri: f.uri, rows: indexRows(uris.map(u => posix(path.relative(f.uri.fsPath, u.fsPath)))) });
        }
      } catch (e) {
        this.log(`paths: index of ${f.name} failed (${(e as Error).message})`);
      }
    }
    const roots = [...byRoot.values()];
    this.log(`paths: indexed ${roots.reduce((n, r) => n + r.rows.length, 0)} rows in ${roots.length} root(s), ${Date.now() - t0} ms`);
    return roots;
  }

  /** The #-picker rows for a query (across roots, capped). */
  async find(q: string): Promise<PathHit[]> {
    const roots = await this.index();
    const all = roots.length === 1 ? roots[0].rows : dedupe(roots.flatMap(r => r.rows));
    return matchPaths(all, q);
  }

  /** What `rel` is under the first root that has it, by stat (a gitignored path that exists still links). */
  private async resolve(rel: string): Promise<{ uri: vscode.Uri; kind: PathKind } | null> {
    const roots = await this.index();
    const bases = roots.length ? roots.map(r => r.uri) : (vscode.workspace.workspaceFolders ?? []).map(f => f.uri);
    for (const b of bases) {
      const uri = vscode.Uri.joinPath(b, ...rel.split('/'));
      try {
        const st = await vscode.workspace.fs.stat(uri);
        if (st.type & vscode.FileType.Directory) return { uri, kind: 'folder' };
        if (st.type & vscode.FileType.File) return { uri, kind: 'file' };
      } catch { /* not under this root */ }
    }
    return null;
  }

  async kinds(paths: readonly string[]): Promise<{ kinds: Record<string, PathKind>; missing: string[] }> {
    const kinds: Record<string, PathKind> = {};
    const missing: string[] = [];
    await Promise.all(paths.map(async p => { const r = await this.resolve(p); if (r) kinds[p] = r.kind; else missing.push(p); }));
    return { kinds, missing };
  }

  /** A file opens in the editor; a folder reveals in the Explorer. A path that is gone says so. */
  async open(rel: string): Promise<void> {
    const r = await this.resolve(rel);
    if (!r) { void vscode.window.showWarningMessage(`EDP: ${rel} is not in this workspace`); return; }
    if (r.kind === 'file') await vscode.window.showTextDocument(r.uri, { preview: true, viewColumn: vscode.ViewColumn.Active });
    else await vscode.commands.executeCommand('revealInExplorer', r.uri);
  }

  dispose(): void {
    this.disposed = true;
    clearTimeout(this.timer);
    this.subs.forEach(d => d.dispose());
  }
}

function dedupe(rows: PathHit[]): PathHit[] {
  const seen = new Set<string>();
  return rows.filter(r => { const k = `${r.kind}:${r.path}`; if (seen.has(k)) return false; seen.add(k); return true; });
}
