// Status bar badge `⎇ <branch> · N seats live` on the shared tree (strategyll-ab18531441 §4).
import * as vscode from 'vscode';
import type { Board } from '../core/api';
import { boardTicketUrl } from '../core/boardLinks';
import { badgeView, branchLabel, defaultSharedTree, inSharedTree, liveSeats, type Seat } from '../core/seats';
import { creds } from './auth';
import type { Repository } from './git.d';
import { gitApi } from './repo';

export function sharedTreePaths(ctx: vscode.ExtensionContext): string[] {
  const set = vscode.workspace.getConfiguration('edp').get<string[]>('sharedTreePaths') ?? [];
  if (set.length) return set;
  const d = defaultSharedTree(ctx.globalStorageUri.fsPath);
  return d ? [d] : [];
}

export class Badge implements vscode.Disposable {
  readonly item = vscode.window.createStatusBarItem('edp.seats', vscode.StatusBarAlignment.Left, 100);
  seats: Seat[] | undefined;
  error: string | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private subs: vscode.Disposable[] = [];
  private watched = new Set<Repository>();
  private seq = 0;
  private lastKey = '';

  constructor(private ctx: vscode.ExtensionContext, private board: () => Board, private log: (line: string) => void = () => {}) {
    this.item.name = 'EDP live seats';
    this.item.command = 'edp.showSeats';
    const every = setInterval(() => this.refresh(), 30_000);
    this.subs.push({ dispose: () => clearInterval(every) },
      vscode.workspace.onDidChangeWorkspaceFolders(() => this.refresh()),
      vscode.workspace.onDidChangeConfiguration(e => { if (e.affectsConfiguration('edp')) this.refresh(); }),
      vscode.window.onDidChangeActiveTextEditor(() => this.refresh()));
    void gitApi().then(api => {
      if (!api) return;
      const watch = (r: Repository) => {
        if (this.watched.has(r)) return;
        this.watched.add(r);
        this.subs.push(r.state.onDidChange(() => this.refresh()));
      };
      api.repositories.forEach(watch);
      this.subs.push(api.onDidOpenRepository(r => { watch(r); this.refresh(); }),
        api.onDidCloseRepository(r => { this.watched.delete(r); this.refresh(); }));
      this.refresh();
    });
    this.refresh();
  }

  /** Debounced: a burst of git state events is one board call. */
  refresh(delay = 500): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.update(), delay);
  }

  async sharedRepo(): Promise<Repository | undefined> {
    const api = await gitApi();
    if (!api) return undefined;
    const paths = sharedTreePaths(this.ctx);
    const repo = api.repositories.find(r => inSharedTree(r.rootUri.fsPath, paths));
    const roots = api.repositories.map(r => r.rootUri.fsPath).join(', ');
    const key = `${roots} / ${paths.join(', ')}`;
    if (key !== this.lastKey) { // paths only (never creds): why the badge is shown or hidden
      this.lastKey = key;
      this.log(`badge: repos [${roots}] shared tree [${paths.join(', ')}] -> ${repo ? 'shown' : 'hidden'}`);
    }
    return repo;
  }

  async update(): Promise<void> {
    const my = ++this.seq;
    const repo = await this.sharedRepo();
    if (my !== this.seq) return;
    if (!repo) { this.item.hide(); return; }
    const branch = branchLabel(repo.state.HEAD);
    let r: { seats: Seat[] } | { error: string };
    try {
      if (!(await creds(this.ctx))) throw new Error('not signed in: run "EDP: Sign in to board"');
      const b = this.board();
      const [ss, ps] = await Promise.all([b.sessions(), b.participants()]);
      r = { seats: liveSeats(ss, ps) };
    } catch (e) {
      r = { error: (e as Error).message };
    }
    if (my !== this.seq) return;
    this.seats = 'seats' in r ? r.seats : undefined;
    this.error = 'error' in r ? r.error : undefined;
    const v = badgeView(branch, r);
    this.item.text = v.text;
    this.item.tooltip = v.tooltip;
    this.item.backgroundColor = v.warn ? new vscode.ThemeColor('statusBarItem.warningBackground') : undefined;
    this.item.show();
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.subs.forEach(d => d.dispose());
    this.item.dispose();
  }
}

/** Badge click: the live seats and their tickets; picking one opens its ticket page. */
export async function showSeats(badge: Badge, boardUrl: () => string): Promise<void> {
  await badge.update(); // this click's poll, not the previous one
  const seats = badge.seats;
  if (!seats) { void vscode.window.showWarningMessage(`EDP: live seats unknown (${badge.error ?? 'not loaded yet'})`); return; }
  if (!seats.length) { void vscode.window.showInformationMessage('EDP: no live agent seats on this board.'); return; }
  const chosen = await vscode.window.showQuickPick(
    seats.map(s => ({ label: `$(hubot) ${s.handle}`, description: s.role, detail: `${s.ticket_id ?? 'no ticket'}${s.stale ? ' · presence not refreshed' : ''}`, ticket: s.ticket_id })),
    { title: `EDP: ${seats.length} live seats on this board` });
  if (chosen?.ticket) void vscode.env.openExternal(vscode.Uri.parse(boardTicketUrl(boardUrl(), chosen.ticket)));
}
