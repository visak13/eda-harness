// The chat controller (design-10b21760d9 §4.1): ticket/epic picker, epic-first thread with a Stories
// strip, live feed, send, code cards. All board access is here, in the Node host, through boardClient
// (X-Participant + X-Token); the webview only gets plain data. One FeedClient per window, filtered to
// the open epic + its stories; raw events never reach the webview. Threads are never merged
// (dec-8dfe3d97af): one ThreadStore per open ticket.
import * as vscode from 'vscode';
import type { Anchor } from '../core/anchor';
import { BoardError, type Board, type Ticket } from '../core/api';
import { boardTicketUrl } from '../core/boardLinks';
import type { ChatState, FeedStatus, HostToView, StoryRow, TicketRef, ViewToHost } from '../core/chatProtocol';
import type { CodeContext, CommitCard, UncommittedCard } from '../core/chatProtocol';
import { chipForSend, chipView, newChip, type Chip } from '../core/chip';
import { COMMIT, codeTarget, pullText, safeRelPath } from '../core/codeTarget';
import { FeedClient, type FeedEvent } from '../core/feed';
import { epicArchitect, personRows, type Reachable } from '../core/people';
import { render } from '../core/render';
import { fromMessageRow, fromThreadRow, ThreadStore } from '../core/thread';
import { creds, signIn } from './auth';
import { ChatViewProvider, CHAT_VIEW } from './chatView';
import { cardOf, inScope as commitsInScope, storyCounts, unlinked as unlinkedOf, type Indexed } from '../core/commits';
import { anchorPath, inScope, openScope, sameRows, scopeTickets, uncommittedCard, type Scope } from '../core/uncommitted';
import { Changes } from './changes';
import { Attachments } from './attachments';
import { attachText, INLINE_IMAGES, pickStaged } from '../core/attachments';
import type { AttachmentRef } from '../core/chatProtocol';
import { PathIndex } from './pathIndex';
import { gitApi } from './repo';
import { InboxHost, type InboxScope } from './inbox';
import { DocProvider, setReader } from './docs';
import { DocsHost, type DocsScope } from './docsTab';
import { DocReader } from './reader';
import { DecisionsHost } from './decisionsTab';
import type { TagTarget } from './tag';
import { QuoteHost, type QuoteChat } from './quotes';
import { messageDraft } from '../core/quotes';
import type { PathHit, PersonRow, QuoteChip, QuoteView } from '../core/chatProtocol';

const LAST_PICK = 'edp.chat.lastTicket';
const LAST_SEEN = 'edp.chat.lastSeen'; // ticket id -> ISO time the thread was last open
const UNLINKED_MAX = 100; // the epic's collapsed "Unlinked commits" section, newest first
const SOURCE_PAGES_MAX = 20; // C17: older pages read to reach a decision's source message before giving up

type Item = vscode.QuickPickItem & { id?: string };
const ref = (t: Ticket): TicketRef => ({ id: t.id, kind: t.kind, title: t.title, status: t.status });

export class ChatController implements vscode.Disposable, TagTarget, QuoteChat {
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
  /** C5 change cards: the shared tree's commit index, the open epic's tickets (tasks, assignees), the cards */
  private changes: Changes;
  /** C11: the #-picker's workspace file/folder index, and the resolver behind path links */
  private paths: PathIndex;
  /** C12: uploads staged per thread, artifact sizes/thumbnails, full-size opens */
  private attach: Attachments;
  /** C15: the open scope's Inbox (questions, sign-offs, gates waiting on the viewer) */
  private inbox: InboxHost;
  /** C16: the open scope's linked docs, and the reader editor they open in */
  private docs: DocsHost;
  readonly reader: DocReader;
  /** C17: the open scope's decision records, with the owner/architect writes */
  private decisions: DecisionsHost;
  /** C20: the draft tray (quote + note from code, docs and messages) and its inline comment boxes */
  readonly quotes: QuoteHost;
  private tree: Ticket[] = [];
  private commits: CommitCard[] = [];
  private unlinked: CommitCard[] = [];
  /** C9 uncommitted scope: the anchors on the open epic's (or lone ticket's) messages, by message id, each
   *  with the thread it came from (C14), and the key (epic id, else ticket id) they belong to; the chip
   *  last posted, to post only changes */
  private anchors = new Map<string, Pick<CodeContext, 'repo_root' | 'path'> & { thread: string }>();
  private anchorsFor: string | null = null;
  private ucPosted: UncommittedCard | null = null;
  /** per thread: the code chip a Tag selection put in its composer (C4); the anchor never leaves the host */
  private chips = new Map<string, Chip>();
  /** a tag made while an open() was in flight: the thread that open lands on gets it (C4 review #2) */
  private pendingChip?: Chip;
  /** the last open() that settled (switched, or failed as the newest); `opening !== opened` = one in flight */
  private opened = 0;

  constructor(private ctx: vscode.ExtensionContext, private board: () => Board, private boardUrl: () => string,
    private log: (line: string) => void) {
    this.provider = new ChatViewProvider(ctx, this, log);
    this.attach = new Attachments(ctx, board, log);
    this.paths = new PathIndex(log);
    this.inbox = new InboxHost(board, boardUrl, () => this.inboxScope(), m => this.post(m), ref => this.attach.open(ref),
      e => this.fail(e, 'could not use the Inbox'), log);
    this.docs = new DocsHost(board, () => this.docsScope(), m => this.post(m), e => this.fail(e, 'could not list the docs'), log);
    this.reader = new DocReader(ctx, board, log, e => this.fail(e, 'could not use the reader'));
    this.decisions = new DecisionsHost(board, () => (this.ticket && this.store ? { id: this.ticket.id } : null), m => this.post(m),
      { message: (t, id) => this.openMessage(t, id), doc: async id => { const d = await this.board().latestDoc(id); await this.reader.open(id, d.version, null); } },
      e => this.fail(e, 'could not use the Decisions tab'), log);
    setReader(this.reader);
    this.quotes = new QuoteHost(ctx, this, log);
    this.reader.setQuotes(this.quotes);
    this.provider.onVisibility = () => this.quotes.refresh();
    this.changes = new Changes(ctx, {
      onCommits: added => this.onCommits(added),
      onReset: () => this.onCommitsReset(),
      onUncommitted: () => this.refreshUncommitted(),
    }, log);
  }

  register(): vscode.Disposable[] {
    return [
      vscode.window.registerWebviewViewProvider(CHAT_VIEW, this.provider, { webviewOptions: { retainContextWhenHidden: false } }),
      this.provider, this, new DocProvider(this.board).register(), ...this.reader.register(), ...this.quotes.register(),
    ];
  }

  // -- ChatHost ------------------------------------------------------------------------------------
  snapshot(): ChatState {
    this.ucPosted = this.ucCard();
    return {
      type: 'state', v: 1, me: this.me, ticket: this.ticket, epic: this.epic, stories: this.stories,
      commits: this.ticket ? this.commits : [], unlinked: this.ticket ? this.unlinked : [], uncommitted: this.ucPosted,
      architect: epicArchitect(this.people, this.epic?.id ?? null), people: this.rows(),
      items: this.store?.items ?? [], hasOlder: this.store?.before != null, chip: this.chipOf(this.ticket?.id), feed: this.feedStatus, notice: this.notice,
      pending: this.attach.pendingOf(this.ticket?.id),
      artifacts: this.attach.known((this.store?.items ?? []).flatMap(i => (i.attachments ?? []).map(a => a.id))),
      inbox: this.inbox.snapshot(this.ticket?.id),
      docs: this.docs.snapshot(this.ticket?.id),
      decisions: this.decisions.snapshot(this.ticket?.id),
      quotes: this.quotes.chips(this.ticket?.id),
    };
  }

  // -- QuoteChat (C20) -------------------------------------------------------------------------------
  target(): { id: string; title: string } | null {
    return this.ticket && this.store && this.opening === this.opened ? { id: this.ticket.id, title: this.ticket.title } : null;
  }
  get chatVisible(): boolean { return this.provider.isVisible; }
  onChips(ticketId: string, quotes: QuoteChip[], focus: boolean, text?: string): void {
    this.post({ type: 'quotes', v: 1, ticketId, quotes, focus, ...(text ? { text } : {}) });
  }
  onMarks(): void { this.reader.pushMarks(); }
  peopleRows(): PersonRow[] { return this.rows(); }
  findPaths(q: string): Promise<{ rows: PathHit[]; up: string | null }> {
    return this.paths.find(q).then(l => ({ rows: l.rows, up: l.up ?? null }), () => ({ rows: [], up: null }));
  }

  handles(): ReadonlySet<string> {
    // C22: a reply goes to its parent's author, who may not be in the people list (a closed seat): anyone who wrote
    // in the open thread is a valid `to` too
    return new Set([...this.people.flatMap(p => [p.id, p.handle]), ...(this.store?.items ?? []).map(i => i.created_by)]);
  }

  onFirstResolve(): void {
    void this.boot();
  }

  async onIntent(m: ViewToHost): Promise<void> {
    switch (m.type) {
      case 'pickTicket': if (m.id) return this.open(m.id); await this.pick(); return;
      case 'loadOlder': return this.loadOlder();
      case 'send': return this.send(m.ticketId, m.text, m.kind, m.to ?? null, m.replyTo ?? null, m.chipId, m.attachmentIds ?? [], m.quoteKeys ?? []);
      case 'quoteMessage': return this.quoteMessage(m.ticketId, m.messageId, m.text, m.before, m.note);
      case 'quoteNote': return this.quotes.note(m.ticketId, m.key, m.note);
      case 'quoteMove': return this.quotes.move(m.ticketId, m.key, m.by);
      case 'quoteDrop': return this.quotes.drop(m.ticketId, m.key);
      case 'openQuote': return this.openQuote(m.messageId, m.index);
      case 'attach': return this.upload(m.ticketId, m.name, m.bytes);
      case 'dropAttachment': {
        this.post({ type: 'pending', v: 1, ticketId: m.ticketId, pending: this.attach.drop(m.ticketId, m.id) });
        return;
      }
      case 'resolveArtifacts': return this.resolveArtifacts(m.ids);
      case 'openArtifact': {
        const ref = this.store?.get(m.messageId)?.attachments?.find(a => a.id === m.id);
        if (ref) await this.attach.open(ref); // only an attachment of a message in the open thread
        return;
      }
      case 'dropCode': {
        if (this.chips.get(m.ticketId)?.id === m.chipId) this.chips.delete(m.ticketId);
        return;
      }
      case 'openDiff': return this.changes.openDiff(m.sha, m.path);
      case 'openUncommitted': {
        const sc = m.scoped ? this.scope() : null;
        if (!sc) return this.changes.openUncommitted(m.path);
        return this.changes.openUncommitted(m.path, f => inScope(f, sc.paths), `Uncommitted changes — this ${sc.kind}`);
      }
      case 'openCode': return this.openCode(m.messageId);
      case 'showMessage': return this.openMessage(m.ticketId, m.messageId);
      case 'openBoard': {
        void vscode.env.openExternal(vscode.Uri.parse(boardTicketUrl(this.boardUrl(), m.ticketId, m.messageId)));
        return;
      }
      case 'findPaths': {
        // always answer: the picker holds its navigation keys until this seq's rows arrive
        const lv = await this.paths.find(m.q).catch(() => ({ rows: [], up: null }));
        this.post({ type: 'paths', v: 1, seq: m.seq, items: lv.rows, up: lv.up });
        return;
      }
      case 'checkPaths': {
        this.post({ type: 'pathKinds', v: 1, ...(await this.paths.kinds(m.paths)) });
        return;
      }
      case 'openPath': return this.paths.open(m.path);
      case 'inboxAnswer': return this.inbox.answer(m.key, m.text);
      case 'inboxVerdict': return this.inbox.verdict(m.key, m.verdict, m.note, m.version);
      case 'inboxGate': return this.inbox.gate(m.key, m.text);
      case 'inboxOpen': return this.inbox.openRow(m.key);
      case 'inboxRefresh': return this.inbox.refresh();
      case 'docsOpen': return this.docs.openRow(m.id);
      case 'docsCompare': return this.docs.compareRow(m.id);
      case 'docsRefresh': return this.docs.refresh();
      case 'decisionOpen': return this.decisions.openRow(m.id);
      case 'decisionWithdraw': return this.decisions.withdraw(m.id);
      case 'decisionBinding': return this.decisions.binding(m.id, m.binding);
      case 'decisionsRefresh': return this.decisions.refresh();
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
    void this.changes.start();
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
      this.store = undefined; this.ticket = null; this.epic = null; this.stories = []; this.unread.clear(); this.chips.clear(); this.attach.clear();
      this.anchors.clear(); this.anchorsFor = null; this.inbox.clear(); this.docs.clear(); this.decisions.clear();
      this.opened = this.opening; this.pendingChip = undefined;
      this.feedStatus = 'signed-out';
      this.notice = 'Sign in to the board to read and send.';
      this.postState();
      return;
    }
    this.reader.reset();
    this.decisions.clear(); // C17: another identity reads its own list; the last viewer's rows and actions go
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
    this.changes.dispose();
    this.attach.dispose();
    this.inbox.dispose();
    this.docs.dispose();
    this.decisions.dispose();
    this.paths.dispose();
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
    for (const x of this.tree) if (x.kind === 'task') s.add(x.id); // C14: a task's anchors scope its story
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
      const [page, , tree] = await Promise.all([b.thread(t.id), this.loadPeople(b),
        // the epic's tickets give story tasks and assignees for change cards; a lone story has only its tasks
        b.tickets(epic ? { epic_id: epic.id } : { parent_id: t.id }).catch(e => { this.log(`tickets for change cards: ${(e as Error).message}`); return [] as Ticket[]; })]);
      // change cards never hold a thread open: boot started the git read, and its onReset re-posts the view
      if (n !== this.opening) return;
      store.loadPage(page);
      // only now does the host switch: until the page is in, sends and events still belong to the old thread
      this.markSeen(this.ticket?.id); // leaving a thread: everything on it was seen
      if (epic?.id !== this.epic?.id) this.unread.clear();
      this.ticket = ref(t);
      this.epic = epic ? ref(epic) : null;
      this.store = store;
      this.stories = storyTickets.map(s => ({ ...ref(s), unread: 0 }));
      this.tree = [...tree.filter(x => x.id !== t.id && x.id !== epic?.id), t, ...(epic && epic.id !== t.id ? [epic] : [])];
      const key = epic?.id ?? t.id;
      if (key !== this.anchorsFor) { this.anchors.clear(); this.anchorsFor = key; }
      this.addAnchors(store.items, t.id);
      this.recomputeCommits();
      this.markSeen(t.id);
      this.syncUnread();
      this.notice = null;
      void this.ctx.workspaceState.update(LAST_PICK, t.id);
      const inbox = this.inbox.open(); // sets the new scope's (loading) list before the state goes out
      void this.docs.open();
      void this.decisions.openScope();
      this.postState();
      void inbox;
      this.settleOpen(n);
      void this.countUnread(n);
    } catch (e) {
      if (n !== this.opening) return;
      this.fail(e, `could not open ${id}`);
      this.settleOpen(n);
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
      this.reader.pushMarks(); // the readers' note boxes list the same people (C20)
    } catch (e) {
      this.log(`chat: people unavailable (${(e as BoardError)?.code ?? 'error'})`);
    }
  }

  /** Stories-strip counts: messages newer than the last time that story's thread was open. */
  private async countUnread(n: number): Promise<void> {
    const seen = this.ctx.workspaceState.get<Record<string, string>>(LAST_SEEN) ?? {};
    const b = this.board();
    const epic = this.epic && this.epic.id !== this.ticket?.id ? this.epic.id : null;
    let anchored = false;
    // C14: the picked scope's task threads too, only for their anchors (a story counts its tasks' anchored files)
    const own = this.ticket ? scopeTickets(this.ticket, this.tree) : new Set<string>();
    const tasks = this.tree.filter(x => x.kind === 'task' && own.has(x.id)).map(x => x.id);
    await Promise.all([...this.stories.map(s => s.id), ...(epic ? [epic] : []), ...tasks].map(async id => {
      if (id === this.ticket?.id) return;
      try {
        const page = await b.thread(id);
        if (n !== this.opening || id === this.ticket?.id) return;
        if (this.addAnchors(page.thread, id)) anchored = true; // C9: the epic's anchors scope the uncommitted chip
        const s = this.stories.find(x => x.id === id);
        if (!s) return;
        const since = seen[s.id] ? Date.parse(seen[s.id]) : 0;
        const set = this.unreadSet(s.id); // a union: a live event that already counted a message is not counted twice
        for (const r of page.thread) if (Date.parse(r.at) > since && r.by !== this.me?.id) set.add(r.id);
      } catch { /* the strip keeps what it has */ }
    }));
    if (n === this.opening) { this.syncUnread(); this.post({ type: 'stories', v: 1, stories: this.stories }); if (anchored) this.refreshUncommitted(); }
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
    if (subject && this.docs.has(subject)) this.docs.schedule(); // C16: a listed doc moved (a new version, approved)
    if (subject && this.decisions.has(subject)) this.decisions.schedule(); // C17: a listed decision's binding changed
    if (!subject || !this.threadSet().has(subject)) return;
    // C15: a question, a gate or a verdict in scope changes what waits on the viewer
    if (this.ticket && scopeTickets(this.ticket, this.tree).has(subject)) {
      this.inbox.schedule();
      // C16: a link, a criterion's evidence or a design_ref in scope changes the Docs list
      if (ev.kind !== 'message_sent') this.docs.schedule();
      // C17: decisions are recorded as the thread moves (an answer, a ruling); no event names a new one, so any
      // event in scope re-reads the list once the burst settles
      this.decisions.schedule();
    }
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
      const fresh = store.merge([fromMessageRow(m, ev.seq, await this.attach.refs(m.artifacts))]);
      if (this.addAnchors(fresh, store.ticketId)) this.refreshUncommitted();
      if (store === this.store && fresh.length) {
        this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
        this.provider.noteUnseen(fresh.length);
      }
      if (this.provider.isVisible) this.markSeen(store.ticketId);
      return;
    }
    // C14: a message on another thread of the picked scope (a task of the open story, or any thread of the
    // open epic) may carry an anchor; the event has only a preview, so read the message for it
    if (this.ticket && scopeTickets(this.ticket, this.tree).has(subject)) {
      try {
        const m = await this.board().message(mid);
        if (this.addAnchors([m], subject)) this.refreshUncommitted();
      } catch (e) { this.log(`chat: anchor fetch failed (${(e as BoardError)?.code ?? 'error'})`); }
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
      if (store === this.store && this.addAnchors(fresh, store.ticketId)) this.refreshUncommitted();
      if (store === this.store) answer(fresh);
    } catch (e) { if (store === this.store) answer([]); this.fail(e, 'could not load older messages'); }
  }

  private async send(ticketId: string, text: string, kind: string, to: string | null, replyTo: string | null, chipId?: string, attachmentIds: string[] = [], quoteKeys: string[] = []): Promise<void> {
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
    // C12: only uploads this host staged for this thread; an unknown id is refused, never guessed
    const staged = pickStaged(this.attach.pendingOf(ticketId), attachmentIds);
    if ('error' in staged) {
      this.post({ type: 'sendFailed', v: 1, ticketId, text: staged.error });
      this.post({ type: 'pending', v: 1, ticketId, pending: this.attach.pendingOf(ticketId) });
      return;
    }
    const files = staged.ok;
    // C20: only drafts this host built for this thread, in the order the composer shows them
    const q = this.quotes.forSend(ticketId, quoteKeys);
    if ('error' in q) {
      this.post({ type: 'sendFailed', v: 1, ticketId, text: q.error });
      this.onChips(ticketId, this.quotes.chips(ticketId), false);
      return;
    }
    const body = files.length ? attachText(text, files.map(f => f.name)) : text; // an attachments-only send names its files
    try {
      const m = await this.board().send({ ticket_id: store.ticketId, to, kind, reply_to: replyTo,
        ...(files.length ? { artifacts: files.map(f => f.id) } : {}), ...(q.quotes.length ? { quotes: q.quotes } : {}),
        ...(chip ? { text: render(chip.anchor, body, chip.truncated), code_context: chip.anchor } : { text: body }) });
      if (files.length) this.post({ type: 'pending', v: 1, ticketId, pending: this.attach.sent(ticketId, files.map(f => f.id)) });
      if (chip && this.chips.get(ticketId)?.id === chip.id) this.chips.delete(ticketId);
      if (q.keys.length) this.quotes.sent(ticketId, q.keys);
      const refs: AttachmentRef[] = files.map(f => ({ id: f.id, name: f.name, contentType: f.contentType, image: INLINE_IMAGES.has(f.contentType) }));
      const fresh = store.merge([fromMessageRow(m, 0, refs)]);
      if (this.addAnchors(fresh, store.ticketId)) this.refreshUncommitted();
      this.post({ type: 'sent', v: 1, ticketId, id: m.id });
      if (chip) this.post({ type: 'insertCode', v: 1, ticketId, chip: this.chipOf(ticketId), focus: false });
      if (store === this.store && fresh.length) this.post({ type: 'append', v: 1, ticketId: store.ticketId, items: fresh });
      const un = m.unresolved_mentions ?? [];
      if (un.length) void vscode.window.showWarningMessage(`EDP: sent, but nobody is registered as ${un.map(h => '@' + h).join(', ')}`);
    } catch (e) {
      // the draft stays in the composer; a refused quote is marked on its chip
      if (q.keys.length) this.quotes.refused(ticketId, q.keys, (e as Error).message);
      this.post({ type: 'sendFailed', v: 1, ticketId, text: `Not sent: ${(e as Error).message}` });
    }
  }

  // -- quotes (C20 s-29f052c40e) -------------------------------------------------------------------
  /** A selection of a message in the open thread: mapped to the message's own source, which the host holds. */
  private async quoteMessage(ticketId: string, messageId: string, text: string, before: string, note: string): Promise<void> {
    const m = this.store?.ticketId === ticketId ? this.store.get(messageId) : undefined;
    const say = (why: string) => this.onChips(ticketId, this.quotes.chips(ticketId), false, `Not quoted: ${why}`);
    if (!m) return say('that message is not in the open thread.');
    const d = messageDraft({ id: m.id, text: m.text, created_by: m.created_by }, text, before, note);
    if ('error' in d) return say(d.error);
    await this.quotes.add(d);
  }

  /** A quote card's source link: the doc at that version and lines in the reader, the code at the lines, or the
   *  quoted message in its thread. Only quotes of a message in the open thread are followed. */
  private async openQuote(messageId: string, index: number): Promise<void> {
    const q: QuoteView | undefined = this.store?.get(messageId)?.quotes?.[index];
    if (!q) return;
    if (q.source === 'doc' && q.id && q.version) {
      const lo = q.locator;
      await this.reader.open(q.id, q.version, null, lo?.line_start ? { from: lo.line_start, to: lo.line_end ?? lo.line_start } : undefined);
      return;
    }
    if (q.source === 'code' && q.code) return this.openCodeAt(q.code);
    if (q.source === 'message' && q.id) {
      if (this.store?.has(q.id) && this.ticket) { this.post({ type: 'focusMessage', v: 1, ticketId: this.ticket.id, id: q.id }); return; }
      try {
        const src = await this.board().message(q.id);
        await this.openMessage(src.ticket_id, q.id);
      } catch (e) { this.fail(e, `could not open ${q.id}`); }
    }
  }

  // -- attachments (C12 s-85dd35a166) -------------------------------------------------------------
  /** Upload one file for a thread's composer; a refusal is the board's own message and the draft stays. */
  private async upload(ticketId: string, name: string, bytes: Uint8Array): Promise<void> {
    if (!this.store || this.store.ticketId !== ticketId) {
      this.post({ type: 'attachFailed', v: 1, ticketId, name, text: `Not attached: that thread is no longer open.` });
      return;
    }
    try {
      this.post({ type: 'pending', v: 1, ticketId, pending: await this.attach.upload(ticketId, name, bytes) });
    } catch (e) {
      const err = e as BoardError;
      if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') this.fail(e, `could not attach ${name}`);
      this.post({ type: 'attachFailed', v: 1, ticketId, name, text: `Not attached: ${name}: ${err?.message ?? String(e)}` });
    }
  }

  /** The view asks for attachments now in view (lazy, architect m-1a33d88bc7): only ids on the open thread's
   *  messages are resolved; each answer is posted as it lands. */
  private async resolveArtifacts(ids: string[]): Promise<void> {
    const store = this.store;
    if (!store) return;
    const refs = new Map<string, AttachmentRef>();
    for (const i of store.items) for (const a of i.attachments ?? []) if (ids.includes(a.id)) refs.set(a.id, a);
    await Promise.all([...refs.values()].map(async r => {
      const info = await this.attach.resolve(r);
      if (store === this.store) this.post({ type: 'artifacts', v: 1, ticketId: store.ticketId, items: [info] });
    }));
  }

  private async openCode(messageId: string): Promise<void> {
    const cc = this.store?.get(messageId)?.code_context;
    if (cc) await this.openCodeAt(cc);
  }

  private async openCodeAt(cc: CodeContext): Promise<void> {
    const api = await gitApi();
    const roots = api?.repositories.map(r => r.rootUri.fsPath) ?? []; // repo-relative paths resolve against git roots only
    const exists = new Map<string, boolean>();
    const has = new Map<string, boolean>();
    const rel = safeRelPath(cc.path);
    const sha = cc.commit && COMMIT.test(cc.commit) ? cc.commit : undefined;
    await Promise.all(roots.map(async r => {
      if (sha) has.set(r, await this.changes.hasCommit(r, sha));
      if (!rel) return;
      try { await vscode.workspace.fs.stat(vscode.Uri.joinPath(vscode.Uri.file(r), ...rel.split('/'))); exists.set(r, true); }
      catch { exists.set(r, false); }
    }));
    const t = codeTarget(cc, roots, r => exists.get(r) === true, r => has.get(r) === true);
    if ('error' in t) { void vscode.window.showWarningMessage(`EDP: ${t.error}`); return; }
    // the anchored commit is in no local repo (a teammate's clone behind the host): not an error (C6)
    if ('pull' in t) { void vscode.window.showWarningMessage(`EDP: ${t.path} @ ${pullText(t.pull)}`); return; }
    if (t.missingCommit && t.commit) void vscode.window.showWarningMessage(`EDP: anchored at ${pullText(t.commit)} This is the clone's own copy; the lines may differ.`);
    const uri = vscode.Uri.joinPath(vscode.Uri.file(t.root), ...t.path.split('/'));
    const doc = await vscode.workspace.openTextDocument(uri);
    const last = Math.min(t.line_end, doc.lineCount) - 1;
    const first = Math.min(t.line_start, doc.lineCount) - 1;
    const range = new vscode.Range(first, 0, last, doc.lineAt(last).text.length);
    await vscode.window.showTextDocument(doc, { selection: range, preview: true, viewColumn: vscode.ViewColumn.Active });
    if (t.commit && !t.missingCommit) {
      const head = api?.getRepository(uri)?.state.HEAD?.commit;
      if (head && head !== t.commit) void vscode.window.setStatusBarMessage(`EDP: anchored at ${t.commit.slice(0, 7)}; HEAD is ${head.slice(0, 7)}, lines may have moved`, 8_000);
    }
  }

  // -- a decision's source (C17 s-5e83f9d0af) -------------------------------------------------------
  /** Show a message in the Chat tab: its thread opens (a story's message opens that story's thread), older pages
   *  load until the thread holds it, then the view scrolls to it and marks it. */
  async openMessage(ticketId: string, messageId: string): Promise<void> {
    const n = this.opening; // a pick made while this runs wins: the source never takes the user back
    await ChatViewProvider.reveal();
    if (n !== this.opening) return;
    if (this.store?.ticketId !== ticketId) {
      await this.open(ticketId);
      if (this.opening !== n + 1 || this.store?.ticketId !== ticketId) return; // the open failed (already said) or another pick won
    }
    const store = this.store;
    for (let i = 0; i < SOURCE_PAGES_MAX && !store.has(messageId) && store.before != null; i++) {
      const fresh = store.loadOlder(await this.board().thread(store.ticketId, store.before));
      if (store !== this.store) return;
      if (this.addAnchors(fresh, store.ticketId)) this.refreshUncommitted();
      this.post({ type: 'prepend', v: 1, ticketId: store.ticketId, items: fresh, hasOlder: store.before != null });
    }
    if (store !== this.store) return;
    if (!store.has(messageId)) {
      void vscode.window.showWarningMessage(`EDP: ${messageId} is not in the thread of ${ticketId} as far back as this panel reads.`);
      return;
    }
    this.post({ type: 'focusMessage', v: 1, ticketId, id: messageId });
  }

  // -- Tag selection (C4 s-a34658f02f) -------------------------------------------------------------
  /** the view was resolved in this window and not disposed (a hidden view still counts) */
  get chatResolved(): boolean { return this.provider.isOpen; }
  /** a thread is open and readable: after a 401/403 the store stays but a chip could not be sent */
  get threadOpen(): boolean { return !!this.store && this.feedStatus !== 'signed-out'; }

  private chipOf(ticketId: string | undefined) {
    const c = ticketId ? this.chips.get(ticketId) : undefined;
    return c ? chipView(c) : null;
  }

  /** Reveal the view and put the chip in the open thread's composer (one chip per composer: a new tag
   *  replaces it). With no thread open the picker comes first; a cancelled pick inserts nothing. */
  async insertChip(anchor: Anchor, truncated: boolean, pickFirst: boolean): Promise<void> {
    const chip = newChip(anchor, truncated);
    await ChatViewProvider.reveal();
    if (pickFirst || !this.store) {
      // only the thread the user picked AND that opened gets the chip: a cancelled pick, or an open that
      // another one superseded, inserts nothing (C4 review #1)
      const picked = await this.pick();
      if (picked) this.placeChip(picked, chip);
      else void vscode.window.setStatusBarMessage('EDP: no thread was opened, so the tagged lines were not added', 6_000);
      return;
    }
    // a thread switch is in flight: the chip follows the user to the thread that opens (C4 review #2)
    if (this.opening !== this.opened) { this.pendingChip = chip; return; }
    this.placeChip(this.store.ticketId, chip);
  }

  private placeChip(ticketId: string, chip: Chip): void {
    this.chips.set(ticketId, chip);
    this.post({ type: 'insertCode', v: 1, ticketId, chip: chipView(chip), focus: true });
  }

  /** The newest open() settled: a chip tagged meanwhile lands on the thread now open. */
  private settleOpen(n: number): void {
    this.opened = n;
    this.quotes.refresh(); // the status-bar draft count follows the open thread
    const chip = this.pendingChip;
    this.pendingChip = undefined;
    if (chip && this.store) this.placeChip(this.store.ticketId, chip);
  }

  // -- change cards (C5 s-ab8e69650e; C13 Commits tab) ---------------------------------------------
  /** The open thread's ticket set: a story and its tasks; an epic (or a task) itself. An epic's Chat tab
   *  never shows its stories' commits (architect ruling m-2e3b14065e): those are its Commits tab. */
  private threadIds(): Set<string> {
    const t = this.ticket;
    if (!t) return new Set();
    if (t.kind !== 'story') return new Set([t.id]);
    return new Set([t.id, ...this.tree.filter(x => x.parent_id === t.id).map(x => x.id)]);
  }

  /** The Commits tab's scope (design §13.1): a story with its tasks; an epic with every ticket of it. */
  private scopeIds(): Set<string> {
    if (this.ticket?.kind !== 'epic') return this.threadIds();
    return new Set([this.ticket.id, ...this.tree.map(x => x.id)]);
  }

  private scopeCards(cs: Indexed[]): CommitCard[] {
    const epicScope = this.ticket?.kind === 'epic';
    return commitsInScope(cs, this.threadIds(), this.scopeIds()).map(({ c, thread }) =>
      ({ ...this.card(c), thread, ...(epicScope ? { story: this.storyOf(c.tickets) } : {}) }));
  }

  /** The epic's story a commit belongs to: the first named ticket that is a story, or a task's parent story. */
  private storyOf(tickets: string[]): string | null {
    const stories = new Set(this.stories.map(s => s.id));
    for (const id of tickets) {
      if (stories.has(id)) return id;
      const p = this.tree.find(x => x.id === id)?.parent_id;
      if (p && stories.has(p)) return p;
    }
    return null;
  }

  /** A subject-attributed card names the ticket's assignee as its seat (labelled in the view). */
  private assigneeOf = (id: string) => this.tree.find(x => x.id === id)?.assignee ?? null;
  private card = (c: Indexed) => cardOf(c, this.assigneeOf);

  private recomputeCommits(): void {
    const all = this.changes.commits;
    this.commits = this.scopeCards(all);
    this.unlinked = this.ticket?.kind === 'epic' ? unlinkedOf(all).slice(0, UNLINKED_MAX).map(this.card) : [];
    const tasksOf = new Map<string, string[]>();
    for (const x of this.tree) if (x.kind === 'task' && x.parent_id) tasksOf.set(x.parent_id, [...(tasksOf.get(x.parent_id) ?? []), x.id]);
    const counts = storyCounts(all, this.stories.map(s => s.id), tasksOf);
    for (const s of this.stories) s.commits = counts.get(s.id) ?? 0;
  }

  /** HEAD moved: new cards for the open thread, fresh strip counts. */
  private onCommits(added: Indexed[]): void {
    const t = this.ticket;
    if (!t) return;
    const items = this.scopeCards(added);
    const un = t.kind === 'epic' ? unlinkedOf(added).map(this.card) : [];
    this.recomputeCommits();
    if (items.length || un.length) {
      this.post({ type: 'commits', v: 1, ticketId: t.id, items, unlinked: un });
      this.provider.noteUnseen(items.filter(c => c.thread).length);
    }
    if (this.stories.length) this.post({ type: 'stories', v: 1, stories: this.stories });
    this.refreshUncommitted();
  }

  /** The index was (re)read: the whole view follows. */
  private onCommitsReset(): void {
    if (!this.ticket) return;
    this.recomputeCommits();
    this.postState();
  }

  // -- the uncommitted chip, scoped to the open epic (C9, option (a)) ------------------------------
  /** What the open thread counts as its own: every ticket of the epic (or the lone ticket and its
   *  tasks), through the commits naming them and the anchors on their messages. */
  scope(): Scope | null {
    if (!this.ticket) return null;
    const root = this.changes.root;
    const anchors: { thread: string; path: string }[] = [];
    for (const a of this.anchors.values()) { const p = anchorPath(a, root); if (p) anchors.push({ thread: a.thread, path: p }); }
    // C14: the picked scope's own tickets and threads; `this.tree` (the whole epic) stays for the change cards
    return openScope(this.ticket, this.tree, this.changes.commits, anchors);
  }

  private ucCard(): UncommittedCard | null {
    const work = this.changes.uncommitted;
    return work.length ? uncommittedCard([...work], this.scope()) : null;
  }

  /** Post the chip only when its rows or counts changed. */
  private refreshUncommitted(): void {
    const card = this.ucCard();
    if (sameRows(card, this.ucPosted)) return;
    this.ucPosted = card;
    this.post({ type: 'uncommitted', v: 1, card });
  }

  /** Remember the anchors of messages on the epic's threads, each with the thread it was read from, so a
   *  story scope keeps only its own (C14); true when one was new. */
  private addAnchors(rows: readonly { id: string; code_context?: CodeContext | null }[], thread: string): boolean {
    let added = false;
    for (const r of rows) {
      const cc = r.code_context;
      if (!cc || typeof cc.path !== 'string' || typeof cc.repo_root !== 'string' || this.anchors.has(r.id)) continue;
      this.anchors.set(r.id, { repo_root: cc.repo_root, path: cc.path, thread });
      added = true;
    }
    return added;
  }

  /** The Inbox's scope (C15): the picked scope's own tickets (the C14 set), with every title the host knows. */
  private inboxScope(): InboxScope | null {
    const t = this.ticket;
    if (!t || !this.store) return null;
    const titles = new Map<string, string>();
    for (const x of [...this.tree, ...this.stories, ...(this.epic ? [this.epic] : []), t]) titles.set(x.id, x.title);
    return { id: t.id, ids: scopeTickets(t, this.tree), titles };
  }

  /** The Docs tab's scope (C16): the picked scope's own tickets (the C14 set), and its epic for the doc list. */
  private docsScope(): DocsScope | null {
    const t = this.ticket;
    if (!t || !this.store) return null;
    const ids = scopeTickets(t, this.tree);
    return { id: t.id, epicId: this.epic?.id ?? null, tickets: this.tree.filter(x => ids.has(x.id)) };
  }

  // -- picker --------------------------------------------------------------------------------------
  /** The thread picker; resolves to the id it opened, or undefined (cancelled, failed, or another open won). */
  async pick(): Promise<string | undefined> {
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
    if (!id) return undefined;
    await this.open(id);
    return this.store?.ticketId === id ? id : undefined;
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
