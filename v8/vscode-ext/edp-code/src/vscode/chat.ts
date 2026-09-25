// The chat controller (design-10b21760d9 §4.1): ticket/epic picker, epic-first thread with a Stories
// strip, live feed, send, code cards. All board access is here, in the Node host, through boardClient
// (X-Participant + X-Token); the webview only gets plain data. One FeedClient per window, filtered to
// the open epic + its stories; raw events never reach the webview. Threads are never merged
// (dec-8dfe3d97af): one ThreadStore per open ticket.
import * as vscode from 'vscode';
import { BoardError, type Board, type Ticket } from '../core/api';
import type { ChatState, FeedStatus, HostToView, StoryRow, TicketRef, ViewToHost } from '../core/chatProtocol';
import { codeTarget } from '../core/codeTarget';
import { FeedClient, type FeedEvent } from '../core/feed';
import { epicArchitect, personRows, type Reachable } from '../core/people';
import { fromMessageRow, fromThreadRow, ThreadStore } from '../core/thread';
import { creds, signIn } from './auth';
import { ChatViewProvider, CHAT_VIEW } from './chatView';
import { gitApi } from './repo';

const LAST_PICK = 'edp.chat.lastTicket';
const LAST_SEEN = 'edp.chat.lastSeen'; // ticket id -> ISO time the thread was last open

type Item = vscode.QuickPickItem & { id?: string };
const ref = (t: Ticket): TicketRef => ({ id: t.id, kind: t.kind, title: t.title, status: t.status });

export class ChatController implements vscode.Disposable {
  readonly provider: ChatViewProvider;
  private feed?: FeedClient;
  private feedStatus: FeedStatus = 'connecting';
  private ready?: Promise<void>;
  private readyResolve?: () => void;
  private store?: ThreadStore;
  private ticket: TicketRef | null = null;
  private epic: TicketRef | null = null;
  private stories: StoryRow[] = [];
  private people: Reachable[] = [];
  private titles = new Map<string, string>();
  private me: { id: string; handle: string } | null = null;
  private notice: string | null = null;
  private opening = 0;

  constructor(private ctx: vscode.ExtensionContext, private board: () => Board, private boardUrl: () => string,
    private log: (line: string) => void) {
    this.provider = new ChatViewProvider(ctx, this, log);
  }

  register(): vscode.Disposable[] {
    return [
      vscode.window.registerWebviewViewProvider(CHAT_VIEW, this.provider, { webviewOptions: { retainContextWhenHidden: false } }),
      this.provider, this,
    ];
  }

  // -- ChatHost ------------------------------------------------------------------------------------
  snapshot(): ChatState {
    return {
      type: 'state', v: 1, me: this.me, ticket: this.ticket, epic: this.epic, stories: this.stories,
      architect: epicArchitect(this.people, this.epic?.id ?? null), people: this.rows(),
      items: this.store?.items ?? [], hasOlder: this.store?.before != null, feed: this.feedStatus, notice: this.notice,
    };
  }

  handles(): ReadonlySet<string> {
    return new Set(this.people.flatMap(p => [p.id, p.handle]));
  }

  onFirstResolve(): void {
    void this.boot();
  }

  async onIntent(m: ViewToHost): Promise<void> {
    switch (m.type) {
      case 'pickTicket': return m.id ? this.open(m.id) : this.pick();
      case 'loadOlder': return this.loadOlder();
      case 'send': return this.send(m.text, m.kind, m.to ?? null, m.replyTo ?? null);
      case 'openCode': return this.openCode(m.messageId);
      case 'openBoard': {
        const base = this.boardUrl().replace(/\/+$/, '');
        void vscode.env.openExternal(vscode.Uri.parse(`${base}/ui/ticket/${encodeURIComponent(m.ticketId)}${m.messageId ? `#${encodeURIComponent(m.messageId)}` : ''}`));
        return;
      }
      case 'signIn': {
        if (await signIn(this.ctx, this.board)) await this.restart();
        return;
      }
    }
  }

  // -- lifecycle -----------------------------------------------------------------------------------
  private post(m: HostToView) { this.provider.post(m); }
  private postState() { this.post(this.snapshot()); }

  private setFeed(s: FeedStatus) {
    this.feedStatus = s;
    if (s === 'signed-out') this.notice = 'Sign in to the board to read and send.';
    this.post({ type: 'feed', v: 1, status: s });
    if (s === 'signed-out') this.postState();
  }

  private async boot(): Promise<void> {
    if (!(await creds(this.ctx))) {
      this.feedStatus = 'signed-out';
      this.notice = 'Sign in to the board to read and send.';
      this.postState();
      return;
    }
    this.startFeed();
    const last = this.ctx.workspaceState.get<string>(LAST_PICK);
    if (last) await this.open(last);
    else this.postState();
  }

  /** After a sign-in: a fresh feed and a reload of the open thread. */
  async restart(): Promise<void> {
    this.feed?.dispose();
    this.feed = undefined;
    this.notice = null;
    this.me = null;
    this.startFeed();
    const id = this.ticket?.id ?? this.ctx.workspaceState.get<string>(LAST_PICK);
    if (id) await this.open(id); else this.postState();
  }

  private startFeed(): void {
    if (this.feed) return; // one stream per window; a re-resolve never opens a second one
    this.ready = new Promise<void>(r => (this.readyResolve = r));
    this.feedStatus = 'connecting';
    this.feed = new FeedClient({
      baseUrl: this.boardUrl(), creds: () => creds(this.ctx), fetch,
      onEvent: ev => void this.onEvent(ev).catch(e => this.log(`chat: event ${ev.kind} failed (${(e as Error)?.name})`)),
      onStatus: s => this.setFeed(s),
      onReady: () => { this.readyResolve?.(); },
      onResync: () => void this.reload(),
      log: line => this.log(line),
    });
    this.feed.start(-1);
  }

  dispose(): void {
    this.feed?.dispose();
    this.feed = undefined;
  }

  // -- threads -------------------------------------------------------------------------------------
  /** The thread set: the open epic + its stories (or the lone ticket). */
  private threadSet(): Set<string> {
    const s = new Set<string>();
    if (this.epic) s.add(this.epic.id);
    if (this.ticket) s.add(this.ticket.id);
    for (const x of this.stories) s.add(x.id);
    return s;
  }

  private rows() {
    return personRows(this.people, this.titles, { ticket: this.ticket?.id ?? null, epic: this.epic?.id ?? null, stories: this.stories.map(s => s.id) });
  }

  private async open(id: string): Promise<void> {
    const n = ++this.opening;
    const b = this.board();
    try {
      const t = await b.ticket(id);
      let epic: Ticket | null = null;
      if (t.kind === 'epic') epic = t;
      else {
        const eid = t.epic_id ?? (t.parent_id?.startsWith('epic-') ? t.parent_id : null);
        if (eid) epic = await b.ticket(eid).catch(() => null);
      }
      const storyTickets = epic ? (await b.tickets({ parent_id: epic.id })).filter(x => x.kind === 'story') : [];
      if (n !== this.opening) return; // a newer pick won
      this.markSeen(this.ticket?.id); // leaving a thread: everything on it was seen
      this.ticket = ref(t);
      this.epic = epic ? ref(epic) : null;
      this.markSeen(t.id);
      await this.ctx.workspaceState.update(LAST_PICK, t.id);
      this.store = new ThreadStore(t.id);
      this.stories = storyTickets.map(s => ({ ...ref(s), unread: 0 }));
      this.notice = null;
      // subscribe before loading (strategyll-1a201146c8 §4): wait for `: ready`, at most 5 s
      await Promise.race([this.ready ?? Promise.resolve(), new Promise(r => setTimeout(r, 5_000))]);
      const [page] = await Promise.all([b.thread(t.id), this.loadPeople(b)]);
      if (n !== this.opening) return;
      this.store.loadPage(page);
      this.postState();
      void this.countUnread(n);
    } catch (e) {
      if (n !== this.opening) return;
      this.fail(e, `could not open ${id}`);
    }
  }

  private async loadPeople(b: Board): Promise<void> {
    try {
      if (!this.me) {
        const p = await b.me();
        this.me = p ? { id: p.id, handle: p.handle } : null;
      }
      this.people = await b.people();
      const missing = [...new Set(this.people.map(p => p.seat_ticket).filter((x): x is string => !!x && !this.titles.has(x)))];
      await Promise.all(missing.map(id => b.ticket(id).then(t => this.titles.set(id, t.title), () => {})));
    } catch (e) {
      this.log(`chat: people unavailable (${(e as BoardError)?.code ?? 'error'})`);
    }
  }

  /** Stories-strip counts: messages newer than the last time that story's thread was open. */
  private async countUnread(n: number): Promise<void> {
    const seen = this.ctx.workspaceState.get<Record<string, string>>(LAST_SEEN) ?? {};
    const b = this.board();
    await Promise.all(this.stories.map(async s => {
      if (s.id === this.ticket?.id) return;
      try {
        const page = await b.thread(s.id);
        const since = seen[s.id] ? Date.parse(seen[s.id]) : 0;
        s.unread = page.thread.filter(r => Date.parse(r.at) > since && r.by !== this.me?.id).length;
      } catch { /* the strip keeps 0 */ }
    }));
    if (n === this.opening) this.post({ type: 'stories', v: 1, stories: this.stories });
  }

  private markSeen(id: string | undefined): void {
    if (!id) return;
    const seen = { ...(this.ctx.workspaceState.get<Record<string, string>>(LAST_SEEN) ?? {}), [id]: new Date().toISOString() };
    const s = this.stories.find(x => x.id === id);
    if (s) s.unread = 0;
    void this.ctx.workspaceState.update(LAST_SEEN, seen);
  }

  /** A resync (the board dropped events for this stream): reload the open thread's newest page. */
  private async reload(): Promise<void> {
    const store = this.store;
    if (!store) return;
    try {
      const fresh = store.merge((await this.board().thread(store.ticketId)).thread.map(r => fromThreadRow(store.ticketId, r)));
      if (store === this.store && fresh.length) {
        this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
        this.provider.noteUnseen(fresh.length);
      }
    } catch (e) { this.log(`chat: resync reload failed (${(e as BoardError)?.code ?? 'error'})`); }
  }

  private async onEvent(ev: FeedEvent): Promise<void> {
    const subject = ev.subject_id;
    if (!subject || !this.threadSet().has(subject)) return;
    if (ev.kind === 'status_changed') {
      const to = typeof ev.data?.to === 'string' ? ev.data.to : undefined;
      const s = this.stories.find(x => x.id === subject);
      if (to && s) { s.status = to; this.post({ type: 'stories', v: 1, stories: this.stories }); }
      if (to && this.ticket?.id === subject) { this.ticket = { ...this.ticket, status: to }; }
      return;
    }
    if (ev.kind !== 'message_sent') return;
    const mid = typeof ev.data?.message === 'string' ? ev.data.message : undefined;
    if (!mid) return;
    const store = this.store;
    if (store && subject === store.ticketId) {
      if (store.has(mid)) return;
      const m = await this.board().message(mid); // the event carries a preview, never code_context
      const fresh = store.merge([fromMessageRow(m, ev.seq)]);
      if (store === this.store && fresh.length) {
        this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
        this.provider.noteUnseen(fresh.length);
      }
      if (this.provider.isVisible) this.markSeen(store.ticketId);
      return;
    }
    const s = this.stories.find(x => x.id === subject);
    if (s && ev.created_by !== this.me?.id) {
      s.unread += 1;
      this.post({ type: 'stories', v: 1, stories: this.stories });
    }
  }

  private async loadOlder(): Promise<void> {
    const store = this.store;
    if (!store || store.before == null) return;
    try {
      const fresh = store.loadOlder(await this.board().thread(store.ticketId, store.before));
      if (store === this.store) this.post({ type: 'prepend', v: 1, ticketId: store.ticketId, items: fresh, hasOlder: store.before != null });
    } catch (e) { this.fail(e, 'could not load older messages'); }
  }

  private async send(text: string, kind: string, to: string | null, replyTo: string | null): Promise<void> {
    const store = this.store;
    if (!store) { this.post({ type: 'sendFailed', v: 1, text: 'Pick a ticket first.' }); return; }
    try {
      const m = await this.board().send({ ticket_id: store.ticketId, to, kind, text, reply_to: replyTo });
      const fresh = store.merge([fromMessageRow(m, 0)]);
      this.post({ type: 'sent', v: 1, id: m.id });
      if (store === this.store && fresh.length) this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
      const un = m.unresolved_mentions ?? [];
      if (un.length) void vscode.window.showWarningMessage(`EDP: sent, but nobody is registered as ${un.map(h => '@' + h).join(', ')}`);
    } catch (e) {
      // the draft stays in the composer
      this.post({ type: 'sendFailed', v: 1, text: `Not sent: ${(e as Error).message}` });
    }
  }

  private async openCode(messageId: string): Promise<void> {
    const cc = this.store?.get(messageId)?.code_context;
    if (!cc) return;
    const api = await gitApi();
    const roots = [...(api?.repositories.map(r => r.rootUri.fsPath) ?? []), ...(vscode.workspace.workspaceFolders?.map(f => f.uri.fsPath) ?? [])];
    const exists = new Map<string, boolean>();
    await Promise.all(roots.map(async r => {
      const rel = cc.path;
      try { await vscode.workspace.fs.stat(vscode.Uri.joinPath(vscode.Uri.file(r), ...rel.split('/'))); exists.set(r, true); }
      catch { exists.set(r, false); }
    }));
    const t = codeTarget(cc, roots, r => exists.get(r) === true);
    if ('error' in t) { void vscode.window.showWarningMessage(`EDP: ${t.error}`); return; }
    const uri = vscode.Uri.joinPath(vscode.Uri.file(t.root), ...t.path.split('/'));
    const doc = await vscode.workspace.openTextDocument(uri);
    const last = Math.min(t.line_end, doc.lineCount) - 1;
    const first = Math.min(t.line_start, doc.lineCount) - 1;
    const range = new vscode.Range(first, 0, last, doc.lineAt(last).text.length);
    await vscode.window.showTextDocument(doc, { selection: range, preview: true, viewColumn: vscode.ViewColumn.Active });
    if (t.commit) {
      const head = api?.getRepository(uri)?.state.HEAD?.commit;
      if (head && head !== t.commit) void vscode.window.setStatusBarMessage(`EDP: anchored at ${t.commit.slice(0, 7)}; HEAD is ${head.slice(0, 7)}, lines may have moved`, 8_000);
    }
  }

  // -- picker --------------------------------------------------------------------------------------
  async pick(): Promise<void> {
    if (!(await creds(this.ctx))) { if (!(await signIn(this.ctx, this.board))) return; await this.restart(); }
    const qp = vscode.window.createQuickPick<Item>();
    Object.assign(qp, { title: 'EDP chat: open a thread', placeholder: 'An epic opens its own thread with a Stories strip', busy: true,
      matchOnDescription: true, matchOnDetail: true, ignoreFocusOut: true });
    const chosen = new Promise<string | undefined>(resolve => {
      let done = false;
      const finish = (v?: string) => { if (!done) { done = true; resolve(v); qp.dispose(); } };
      qp.onDidAccept(() => finish(qp.selectedItems[0]?.id));
      qp.onDidHide(() => finish(undefined));
    });
    qp.show();
    try {
      const all = await this.board().tickets();
      const live = (t: Ticket) => !['done', 'cancelled', 'closed'].includes(t.status);
      const item = (t: Ticket): Item => ({ label: t.title, description: t.id, detail: `${t.kind} · ${t.status}${t.assignee ? ` · ${t.assignee}` : ''}`, id: t.id });
      const epics = all.filter(t => t.kind === 'epic' && live(t));
      const stories = all.filter(t => (t.kind === 'story' || t.kind === 'task') && live(t));
      qp.items = [
        { label: 'Epics', kind: vscode.QuickPickItemKind.Separator }, ...epics.map(item),
        { label: 'Stories and tasks', kind: vscode.QuickPickItemKind.Separator }, ...stories.map(item),
      ];
      qp.busy = false;
    } catch (e) {
      qp.dispose();
      this.fail(e, 'could not list tickets');
      return;
    }
    const id = await chosen;
    if (id) await this.open(id);
  }

  private fail(e: unknown, what: string) {
    const err = e as BoardError;
    if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') {
      this.feedStatus = 'signed-out';
      this.notice = 'Sign in to the board to read and send.';
      this.postState();
      return;
    }
    this.post({ type: 'error', v: 1, text: `EDP: ${what}: ${err?.message ?? String(e)}` });
  }
}
