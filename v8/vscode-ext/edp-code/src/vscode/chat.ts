// The chat controller (design-10b21760d9 §4.1): ticket/epic picker, epic-first thread with a Stories
// strip, live feed, send, code cards. All board access is here, in the Node host, through boardClient
// (X-Participant + X-Token); the webview only gets plain data. One FeedClient per window, filtered to
// the open epic + its stories; raw events never reach the webview. Threads are never merged
// (dec-8dfe3d97af): one ThreadStore per open ticket.
import * as vscode from 'vscode';
import type { Anchor } from '../core/anchor';
import { BoardError, type Board, type Ticket } from '../core/api';
import type { ChatState, FeedStatus, HostToView, StoryRow, TicketRef, ViewToHost } from '../core/chatProtocol';
import { chipForSend, chipView, newChip, type Chip } from '../core/chip';
import { codeTarget } from '../core/codeTarget';
import { FeedClient, type FeedEvent } from '../core/feed';
import { epicArchitect, personRows, type Reachable } from '../core/people';
import { render } from '../core/render';
import { fromMessageRow, fromThreadRow, ThreadStore } from '../core/thread';
import { creds, signIn } from './auth';
import { ChatViewProvider, CHAT_VIEW } from './chatView';
import { gitApi } from './repo';
import type { TagTarget } from './tag';

const LAST_PICK = 'edp.chat.lastTicket';
const LAST_SEEN = 'edp.chat.lastSeen'; // ticket id -> ISO time the thread was last open

type Item = vscode.QuickPickItem & { id?: string };
const ref = (t: Ticket): TicketRef => ({ id: t.id, kind: t.kind, title: t.title, status: t.status });

export class ChatController implements vscode.Disposable, TagTarget {
  readonly provider: ChatViewProvider;
  private feed?: FeedClient;
  private feedStatus: FeedStatus = 'connecting';
  private ready?: Promise<void>;
  private readyResolve?: () => void;
  private readyDone = false;
  /** feed events are handled one at a time, in seq order (a slow message fetch never reorders appends) */
  private chain: Promise<void> = Promise.resolve();
  /** per story: the ids of messages not yet seen (the strip count is the set size; a message counts once) */
  private unread = new Map<string, Set<string>>();
  private booted = false;
  private store?: ThreadStore;
  private ticket: TicketRef | null = null;
  private epic: TicketRef | null = null;
  private stories: StoryRow[] = [];
  private people: Reachable[] = [];
  private titles = new Map<string, string>();
  private me: { id: string; handle: string } | null = null;
  private notice: string | null = null;
  private opening = 0;
  /** per thread: the code chip a Tag selection put in its composer (C4); the anchor never leaves the host */
  private chips = new Map<string, Chip>();

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
      items: this.store?.items ?? [], hasOlder: this.store?.before != null, chip: this.chipOf(this.ticket?.id), feed: this.feedStatus, notice: this.notice,
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
      case 'send': return this.send(m.ticketId, m.text, m.kind, m.to ?? null, m.replyTo ?? null, m.chipId);
      case 'dropCode': {
        if (this.chips.get(m.ticketId)?.id === m.chipId) this.chips.delete(m.ticketId);
        return;
      }
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
    if (s === 'live') { this.readyDone = true; this.readyResolve?.(); }
    else if (this.readyDone) this.armReady(); // the next open waits for the next `: ready`
    if (s === 'signed-out') this.notice = 'Sign in to the board to read and send.';
    this.post({ type: 'feed', v: 1, status: s });
    if (s === 'signed-out') this.postState();
  }

  private armReady() {
    this.readyDone = false;
    this.ready = new Promise<void>(r => (this.readyResolve = r));
  }

  private async boot(): Promise<void> {
    this.booted = true;
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

  /** After a sign-in or sign-out: a fresh feed and a reload of the open thread, or, signed out, an
   *  empty view (nothing read under the old identity stays on screen). A no-op before the first resolve. */
  async restart(): Promise<void> {
    if (!this.booted) return;
    this.feed?.dispose();
    this.feed = undefined;
    this.notice = null;
    this.me = null;
    this.people = [];
    if (!(await creds(this.ctx))) {
      ++this.opening;
      this.store = undefined; this.ticket = null; this.epic = null; this.stories = []; this.unread.clear(); this.chips.clear();
      this.feedStatus = 'signed-out';
      this.notice = 'Sign in to the board to read and send.';
      this.postState();
      return;
    }
    this.startFeed();
    const id = this.ticket?.id ?? this.ctx.workspaceState.get<string>(LAST_PICK);
    if (id) await this.open(id); else this.postState();
  }

  private startFeed(): void {
    if (this.feed) return; // one stream per window; a re-resolve never opens a second one
    this.armReady();
    this.feedStatus = 'connecting';
    this.feed = new FeedClient({
      baseUrl: this.boardUrl(), creds: () => creds(this.ctx), fetch,
      onEvent: ev => this.enqueue(() => this.onEvent(ev), `event ${ev.kind}`),
      onStatus: s => this.setFeed(s),
      onResync: () => this.enqueue(() => this.reload(), 'resync'),
      log: line => this.log(line),
    });
    this.feed.start(-1);
  }

  private enqueue(job: () => Promise<void>, what: string): void {
    this.chain = this.chain.then(job).catch(e => this.log(`chat: ${what} failed (${(e as Error)?.name ?? 'error'})`));
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
      // subscribe before loading (strategyll-1a201146c8 §4): wait for `: ready`, at most 5 s
      if (this.feedStatus !== 'signed-out' && !this.readyDone) {
        let timer: ReturnType<typeof setTimeout> | undefined;
        await Promise.race([this.ready ?? Promise.resolve(), new Promise<void>(r => (timer = setTimeout(r, 5_000)))]);
        clearTimeout(timer);
      }
      const store = new ThreadStore(t.id);
      const [page] = await Promise.all([b.thread(t.id), this.loadPeople(b)]);
      if (n !== this.opening) return;
      store.loadPage(page);
      // only now does the host switch: until the page is in, sends and events still belong to the old thread
      this.markSeen(this.ticket?.id); // leaving a thread: everything on it was seen
      if (epic?.id !== this.epic?.id) this.unread.clear();
      this.ticket = ref(t);
      this.epic = epic ? ref(epic) : null;
      this.store = store;
      this.stories = storyTickets.map(s => ({ ...ref(s), unread: 0 }));
      this.markSeen(t.id);
      this.syncUnread();
      this.notice = null;
      void this.ctx.workspaceState.update(LAST_PICK, t.id);
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
        if (n !== this.opening || s.id === this.ticket?.id) return;
        const since = seen[s.id] ? Date.parse(seen[s.id]) : 0;
        const set = this.unreadSet(s.id); // a union: a live event that already counted a message is not counted twice
        for (const r of page.thread) if (Date.parse(r.at) > since && r.by !== this.me?.id) set.add(r.id);
      } catch { /* the strip keeps what it has */ }
    }));
    if (n === this.opening) { this.syncUnread(); this.post({ type: 'stories', v: 1, stories: this.stories }); }
  }

  private unreadSet(id: string): Set<string> {
    let set = this.unread.get(id);
    if (!set) this.unread.set(id, (set = new Set()));
    return set;
  }

  private syncUnread(): void {
    for (const s of this.stories) s.unread = this.unread.get(s.id)?.size ?? 0;
  }

  private markSeen(id: string | undefined): void {
    if (!id) return;
    const seen = { ...(this.ctx.workspaceState.get<Record<string, string>>(LAST_SEEN) ?? {}), [id]: new Date().toISOString() };
    this.unread.delete(id);
    const s = this.stories.find(x => x.id === id);
    if (s) s.unread = 0;
    void this.ctx.workspaceState.update(LAST_SEEN, seen);
  }

  /** A resync (the board dropped events for this stream): reload the open thread's newest page. */
  private async reload(): Promise<void> {
    const store = this.store;
    if (!store) return;
    try {
      const fresh = store.merge((await this.board().thread(store.ticketId)).thread.map(r => fromThreadRow(store.ticketId, r)))
        .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at) || a.seq - b.seq);
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
      if (!to) return;
      const s = this.stories.find(x => x.id === subject);
      if (s) s.status = to;
      if (this.ticket?.id === subject) this.ticket = { ...this.ticket, status: to };
      if (this.epic?.id === subject) this.epic = { ...this.epic, status: to };
      this.postState();
      return;
    }
    if (ev.kind !== 'message_sent') return;
    const mid = typeof ev.data?.message === 'string' ? ev.data.message : undefined;
    if (!mid) return;
    const store = this.store;
    if (store && subject === store.ticketId) {
      if (store.has(mid)) return;
      let m;
      try { m = await this.board().message(mid); } // the event carries a preview, never code_context
      catch (e) { this.log(`chat: message fetch failed (${(e as BoardError)?.code ?? 'error'}); reloading`); return this.reload(); }
      const fresh = store.merge([fromMessageRow(m, ev.seq)]);
      if (store === this.store && fresh.length) {
        this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
        this.provider.noteUnseen(fresh.length);
      }
      if (this.provider.isVisible) this.markSeen(store.ticketId);
      return;
    }
    const s = this.stories.find(x => x.id === subject);
    const from = typeof ev.data?.from === 'string' ? ev.data.from : ev.created_by; // events carry the sender in data.from
    if (s && from !== this.me?.id) {
      this.unreadSet(s.id).add(mid);
      this.syncUnread();
      this.post({ type: 'stories', v: 1, stories: this.stories });
    }
  }

  private async loadOlder(): Promise<void> {
    const store = this.store;
    if (!store) return;
    // always answered, so the view's "older" button never stays disabled
    const answer = (items: ReturnType<ThreadStore['loadOlder']>) =>
      this.post({ type: 'prepend', v: 1, ticketId: store.ticketId, items, hasOlder: store.before != null });
    if (store.before == null) { answer([]); return; }
    try {
      const fresh = store.loadOlder(await this.board().thread(store.ticketId, store.before));
      if (store === this.store) answer(fresh);
    } catch (e) { if (store === this.store) answer([]); this.fail(e, 'could not load older messages'); }
  }

  private async send(ticketId: string, text: string, kind: string, to: string | null, replyTo: string | null, chipId?: string): Promise<void> {
    const store = this.store;
    // the view names the thread it shows; a send for any other thread is refused, never re-targeted
    if (!store || store.ticketId !== ticketId) {
      this.post({ type: 'sendFailed', v: 1, ticketId, text: 'Not sent: that thread is no longer open.' });
      return;
    }
    // a chip send carries the host's own anchor, and the S5 rendered anchor line in its text for agents
    // that do not read code_context; a chip id the host does not hold is refused, never guessed
    const c = chipForSend(this.chips.get(ticketId), chipId);
    if ('error' in c) {
      this.post({ type: 'sendFailed', v: 1, ticketId, text: c.error });
      this.post({ type: 'insertCode', v: 1, ticketId, chip: this.chipOf(ticketId), focus: false });
      return;
    }
    const chip = c.chip;
    try {
      const m = await this.board().send({ ticket_id: store.ticketId, to, kind, reply_to: replyTo,
        ...(chip ? { text: render(chip.anchor, text, chip.truncated), code_context: chip.anchor } : { text }) });
      if (chip && this.chips.get(ticketId)?.id === chip.id) this.chips.delete(ticketId);
      const fresh = store.merge([fromMessageRow(m, 0)]);
      this.post({ type: 'sent', v: 1, ticketId, id: m.id });
      if (chip) this.post({ type: 'insertCode', v: 1, ticketId, chip: this.chipOf(ticketId), focus: false });
      if (store === this.store && fresh.length) this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
      const un = m.unresolved_mentions ?? [];
      if (un.length) void vscode.window.showWarningMessage(`EDP: sent, but nobody is registered as ${un.map(h => '@' + h).join(', ')}`);
    } catch (e) {
      // the draft stays in the composer
      this.post({ type: 'sendFailed', v: 1, ticketId, text: `Not sent: ${(e as Error).message}` });
    }
  }

  private async openCode(messageId: string): Promise<void> {
    const cc = this.store?.get(messageId)?.code_context;
    if (!cc) return;
    const api = await gitApi();
    const roots = api?.repositories.map(r => r.rootUri.fsPath) ?? []; // repo-relative paths resolve against git roots only
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

  // -- Tag selection (C4 s-a34658f02f) -------------------------------------------------------------
  /** the view was resolved in this window and not disposed (a hidden view still counts) */
  get chatResolved(): boolean { return this.provider.isOpen; }
  get threadOpen(): boolean { return !!this.store; }

  private chipOf(ticketId: string | undefined) {
    const c = ticketId ? this.chips.get(ticketId) : undefined;
    return c ? chipView(c) : null;
  }

  /** Reveal the view and put the chip in the open thread's composer (one chip per composer: a new tag
   *  replaces it). With no thread open the picker comes first; a cancelled pick inserts nothing. */
  async insertChip(anchor: Anchor, truncated: boolean, pickFirst: boolean): Promise<void> {
    const chip = newChip(anchor, truncated);
    await ChatViewProvider.reveal();
    if (pickFirst || !this.store) await this.pick();
    const ticketId = this.store?.ticketId;
    if (!ticketId) return;
    this.chips.set(ticketId, chip);
    this.post({ type: 'insertCode', v: 1, ticketId, chip: chipView(chip), focus: true });
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
