// C20 s-29f052c40e (design-10b21760d9 v12 §14.7): the draft tray and the inline comment boxes. Every Add to chat,
// from a code editor, a doc's markdown source or version diff (VS Code's own Comments API box), the EDP reader or a
// chat message, lands as a draft in the tray of the thread open in the chat panel. The tray lives here in the host
// (workspaceState), so it survives the chat being hidden, its webview reloading and the window reloading; the
// chat composer shows it as chips and nothing is sent until Ctrl+Enter there. While the chat is hidden a status-bar
// item "EDP draft: N → <thread>" reveals it. A draft made in an editor keeps an inline marker (a collapsed comment
// thread) until it is sent or removed.
import * as vscode from 'vscode';
import { codeDraft, chipOf, docSourceDraft, quotesForSend, refusedKey, restoreTray, Tray, type Draft, type DraftWhere, type QuoteIn } from '../core/quotes';
import type { PathHit, PersonRow, QuoteChip } from '../core/chatProtocol';
import { DOC_SCHEME, parseDocPath } from '../core/docUri';
import { lineSpan } from '../core/anchor';
import { anchorFor } from './tag';
import { mentionRows, noteToken, pathRows, refRows, type NoteCompletionRow } from '../core/noteCompletion';
import { activeRef, type RefRow } from '../core/boardRefs';

/** No token in this key. Legacy unowned trays cannot safely be assigned to a viewer. */
export const trayKey = (origin: string, participant: string): string =>
  'edp.quotes.tray.v2.' + JSON.stringify([new URL(origin).origin, participant]);
export const QUOTE_CONTROLLER = 'edp.quotes';
const DRAFT_CTX = 'edpDraft';

/** What the tray needs from the chat. */
export interface QuoteChat {
  /** the thread open in the chat panel (null: none) */
  target(): { id: string; title: string } | null;
  /** open the thread picker (no thread open yet); the id it opened, or undefined */
  pick(): Promise<string | undefined>;
  readonly chatVisible: boolean;
  /** a thread's chips changed; `focus`: one was just added */
  onChips(ticketId: string, chips: QuoteChip[], focus: boolean, text?: string): void;
  /** the reader panels' draft markers changed */
  onMarks(): void;
  /** C20 (owner m-5a9111ce12): the @ list's labelled people and the # picker's rows, for note boxes outside the chat */
  peopleRows(): PersonRow[];
  findPaths(q: string): Promise<{ rows: PathHit[]; up: string | null }>;
  /** C24: the $ picker's rows (the open epic's tree first, then the board's open items) */
  findRefs(q: string): Promise<RefRow[]>;
  /** C24: open a `$<id>` chip's target */
  openRef(id: string): Promise<void>;
}

export class QuoteHost implements vscode.Disposable {
  private tray: Tray;
  private identity: string | null = null;
  /** per thread: the draft the board refused on the last send */
  private invalid = new Map<string, string>();
  private ctl: vscode.CommentController;
  private markers = new Map<string, { thread: vscode.CommentThread; note: string }>();
  private status: vscode.StatusBarItem;

  constructor(private ctx: vscode.ExtensionContext, private chat: QuoteChat, private log: (line: string) => void) {
    this.tray = new Tray();
    this.ctl = this.controller();
    this.status = vscode.window.createStatusBarItem('edp.quotes.draft', vscode.StatusBarAlignment.Left, 99);
    this.status.name = 'EDP draft';
    this.status.command = 'edp.chat.open';
    this.syncMarkers();
  }

  private controller(): vscode.CommentController {
    const ctl = vscode.comments.createCommentController(QUOTE_CONTROLLER, 'EDP chat');
    // the gutter + on every file and board doc: select lines, + (or Ctrl+Alt+Q, or the context menu), type a note
    ctl.commentingRangeProvider = {
      provideCommentingRanges: doc => (doc.uri.scheme === 'file' || doc.uri.scheme === DOC_SCHEME) && doc.lineCount > 0
        ? [new vscode.Range(0, 0, doc.lineCount - 1, 0)] : [],
    };
    ctl.options = { prompt: 'Comment for chat…', placeHolder: 'A note on these lines (optional), then Add to chat' };
    return ctl;
  }

  setIdentity(viewer: { origin: string; participant: string } | null): void {
    const key = viewer ? trayKey(viewer.origin, viewer.participant) : null;
    if (key === this.identity) return;
    this.identity = key;
    this.tray = new Tray(key ? restoreTray(this.ctx.workspaceState.get(key)) : undefined);
    this.invalid.clear();
    this.ctl.dispose(); this.markers.clear(); this.ctl = this.controller();
    this.syncMarkers(); this.chat.onMarks(); this.updateStatus();
  }

  register(): vscode.Disposable[] {
    return [
      vscode.commands.registerCommand('edp.quote.comment', () => this.comment()),
      vscode.commands.registerCommand('edp.quote.addToChat', (r: vscode.CommentReply) => this.addFromReply(r)),
      vscode.commands.registerCommand('edp.quote.cancel', (r: vscode.CommentReply | vscode.CommentThread) => ('thread' in r ? r.thread : r).dispose()),
      vscode.commands.registerCommand('edp.quote.remove', (t: vscode.CommentThread | vscode.Comment) => this.removeMarker(t)),
      // C20 (owner m-5a9111ce12): @ people and # paths in the comment boxes, as in the composer
      // C24: $ board objects too
      vscode.languages.registerCompletionItemProvider({ scheme: 'comment' }, { provideCompletionItems: (doc, pos) => this.complete(doc, pos) }, '@', '#', '/', '$'),
      this,
    ];
  }

  /** The completion list for the @ or # token at the caret of a comment box (null: not in one). */
  private async complete(doc: vscode.TextDocument, pos: vscode.Position): Promise<vscode.CompletionList | null> {
    const line = doc.lineAt(pos.line).text.slice(0, pos.character);
    const t = noteToken(line, pos.character);
    if (!t) return null;
    // C24: `$` needs the whole box (the ':' right of `$env|`, an earlier fence line, a closing backtick)
    if (t.kind === '$' && !activeRef(doc.getText(), doc.offsetAt(pos))) return null;
    const rows = t.kind === '@' ? mentionRows(this.chat.peopleRows(), t.query)
      : t.kind === '$' ? refRows(await this.chat.findRefs(t.query)) : pathRows((await this.chat.findPaths(t.query)).rows);
    const range = new vscode.Range(pos.line, t.start, pos.line, pos.character);
    const typed = line.slice(t.start);
    const kinds: Record<NoteCompletionRow['kind'], vscode.CompletionItemKind> = {
      person: vscode.CompletionItemKind.User, file: vscode.CompletionItemKind.File,
      folder: vscode.CompletionItemKind.Folder, descend: vscode.CompletionItemKind.Folder, ref: vscode.CompletionItemKind.Reference,
    };
    const items = rows.map((r, i) => {
      const it = new vscode.CompletionItem(r.label, kinds[r.kind]);
      it.insertText = r.insert;
      it.detail = r.detail;
      it.range = range;
      it.filterText = typed; // the rows are already filtered and ranked (a role match is not a prefix of the label)
      it.sortText = String(i).padStart(4, '0');
      if (r.kind === 'descend') it.command = { command: 'editor.action.triggerSuggest', title: 'List inside' };
      return it;
    });
    return new vscode.CompletionList(items, true); // incomplete: asked again as the query grows
  }

  // -- the tray -------------------------------------------------------------------------------------------
  chips(ticketId: string | null | undefined): QuoteChip[] {
    const bad = ticketId ? this.invalid.get(ticketId) ?? null : null;
    return this.tray.list(ticketId).map(d => chipOf(d, bad));
  }

  /** The drafts of `id` at `version` quoted from the reader or its source, for the reader's inline markers. */
  /** the chat's @ people rows and # path rows, for the reader's note box (C20, owner m-5a9111ce12) */
  people(): PersonRow[] { return this.chat.peopleRows(); }
  findPaths(q: string): Promise<{ rows: PathHit[]; up: string | null }> { return this.chat.findPaths(q); }
  findRefs(q: string): Promise<RefRow[]> { return this.chat.findRefs(q); }
  openRef(id: string): Promise<void> { return this.chat.openRef(id); }

  docMarks(id: string, version: number): { key: string; from: number; to: number; note: string; label: string }[] {
    return this.tray.all().filter(d => d.quote.source === 'doc' && d.quote.id === id && d.quote.version === version)
      .map(d => ({ key: d.key, from: d.quote.locator!.line_start!, to: d.quote.locator!.line_end!, note: d.quote.note ?? '', label: d.label }));
  }

  /** Add a draft to the open thread (the picker first when none is open). The thread it went to, or undefined.
   *  C26 Q5: the draft is the user's own selection, so a first chat boot during the pick (no identity, then one)
   *  keeps it; only a switch from one identity to another drops it. */
  async add(d: Draft): Promise<string | undefined> {
    const who = this.identity;
    let t = this.chat.target();
    if (!t) {
      await vscode.commands.executeCommand('edp.chat.open');
      const id = await this.chat.pick();
      t = id ? this.chat.target() : null;
      if (!t || t.id !== id) { void vscode.window.setStatusBarMessage('EDP: no thread was opened, so the quote was not added', 6_000); return; }
    }
    if (!this.identity || (who !== null && who !== this.identity)) {
      void vscode.window.setStatusBarMessage('EDP: the board sign-in changed, so the quote was not added', 6_000);
      return;
    }
    if (!this.tray.add(t.id, d)) {
      void vscode.window.showWarningMessage(`EDP: ${t.title} already holds 20 quotes, the most one message can carry. Send or remove some first.`);
      return;
    }
    this.changed(t.id, true, `Added ${d.label} to the draft for ${t.title}`);
    return t.id;
  }

  note(ticketId: string, key: string, note: string): void {
    if (this.tray.note(ticketId, key, note)) this.changed(ticketId, false, undefined, false);
  }
  move(ticketId: string, key: string, by: -1 | 1): void { if (this.tray.move(ticketId, key, by)) this.changed(ticketId, false); }
  drop(ticketId: string, key: string): void { if (this.tray.drop(ticketId, key)) this.changed(ticketId, false); }

  dropKey(key: string): void {
    const f = this.tray.find(key);
    if (f) this.drop(f.ticketId, key);
  }

  /** The quotes a send names, from this host's own drafts. */
  forSend(ticketId: string, keys: readonly string[]): { quotes: QuoteIn[]; keys: string[] } | { error: string } {
    return quotesForSend(this.tray.list(ticketId), keys);
  }

  sent(ticketId: string, keys: readonly string[]): void {
    this.invalid.delete(ticketId);
    this.tray.sent(ticketId, keys);
    this.changed(ticketId, false);
  }

  /** The board refused a send; mark the quote it named (if it named one). */
  refused(ticketId: string, keys: readonly string[], message: string | undefined): void {
    const k = refusedKey(message, keys);
    if (k) this.invalid.set(ticketId, k); else this.invalid.delete(ticketId);
    this.post(ticketId, false);
  }

  /** Re-post after the chat opened another thread, or became visible / hidden. */
  refresh(): void { this.updateStatus(); }

  private changed(ticketId: string, focus: boolean, text?: string, markers = true): void {
    if (this.identity) void this.ctx.workspaceState.update(this.identity, this.tray.data());
    if (this.invalid.has(ticketId) && !this.tray.list(ticketId).some(d => d.key === this.invalid.get(ticketId))) this.invalid.delete(ticketId);
    this.post(ticketId, focus, text);
    if (markers) this.syncMarkers(); else this.syncNotes();
    this.chat.onMarks();
    this.updateStatus();
  }

  private post(ticketId: string, focus: boolean, text?: string): void { this.chat.onChips(ticketId, this.chips(ticketId), focus, text); }

  /** "EDP draft: N → <thread>" while the chat is hidden and the open thread holds drafts. */
  private updateStatus(): void {
    const t = this.chat.target();
    const n = this.tray.list(t?.id).length;
    if (!t || !n || this.chat.chatVisible) { this.status.hide(); return; }
    const title = t.title.length > 40 ? `${t.title.slice(0, 39)}…` : t.title;
    this.status.text = `$(comment-discussion) EDP draft: ${n} → ${title}`;
    this.status.tooltip = `${n} quote${n === 1 ? '' : 's'} waiting in the composer of ${t.title} (${t.id}). Click to show the chat; Ctrl+Enter there sends.`;
    this.status.show();
  }

  // -- the Comments API box (code editors, a doc's markdown source, a version diff) --------------------------
  /** Ctrl+Alt+Q / context menu: open the inline comment box on the selection. */
  private async comment(): Promise<void> {
    const e = vscode.window.activeTextEditor;
    if (!e || !(e.document.uri.scheme === 'file' || e.document.uri.scheme === DOC_SCHEME)) {
      void vscode.window.showInformationMessage('EDP: select lines in a file or a board doc to comment for chat.');
      return;
    }
    await vscode.commands.executeCommand('workbench.action.addComment');
  }

  private async addFromReply(r: vscode.CommentReply): Promise<void> {
    const who = this.identity;
    const th = r?.thread;
    if (!th?.range) return;
    const note = r.text ?? '';
    try {
      const doc = await vscode.workspace.openTextDocument(th.uri);
      const d = await this.draftOf(doc, th.range, note);
      if (who !== null && who !== this.identity) return; // another identity: the box stays for them to re-add
      if ('error' in d) { void vscode.window.showWarningMessage(`EDP: ${d.error}`); return; }
      const went = await this.add(d);
      if (went) th.dispose(); // the tray's own marker replaces the box
    } catch (e) {
      void vscode.window.showWarningMessage(`EDP: could not add the quote: ${(e as Error).message}`);
    }
  }

  private async draftOf(doc: vscode.TextDocument, range: vscode.Range, note: string): Promise<Draft | { error: string }> {
    const [a, b] = lineSpan({ startLine: range.start.line, startChar: range.start.character, endLine: range.end.line, endChar: range.end.character, isEmpty: range.isEmpty });
    const where: DraftWhere = { uri: doc.uri.toString(), line_start: a, line_end: b };
    if (doc.uri.scheme === DOC_SCHEME) {
      const at = parseDocPath(doc.uri.path);
      if (!at) return { error: 'not a board doc version' };
      // a whole-line box (the gutter +) quotes the lines; a selection quotes exactly what was selected
      const partial = !range.isEmpty && (range.start.character > 0 || (range.end.character > 0 && range.end.character < doc.lineAt(range.end.line).text.length));
      return docSourceDraft({ id: at.id, version: at.version, body: doc.getText(), line_start: a, line_end: b, selected: partial ? doc.getText(range) : '', note, where });
    }
    const an = await anchorFor(doc, range); // the anchor always takes whole lines (lineSpan)
    if ('error' in an) return an;
    return codeDraft(an.anchor, note, where);
  }

  private removeMarker(t: vscode.CommentThread | vscode.Comment | undefined): void {
    for (const [key, m] of this.markers) {
      if (m.thread === t || m.thread.comments.includes(t as vscode.Comment)) { this.dropKey(key); return; }
    }
  }

  /** One collapsed comment thread per editor draft; gone once the draft is sent or removed. */
  private syncMarkers(): void {
    const drafts = new Map(this.tray.all().filter(d => d.where).map(d => [d.key, d]));
    for (const [key, m] of this.markers) if (!drafts.has(key)) { m.thread.dispose(); this.markers.delete(key); }
    for (const [key, d] of drafts) {
      if (this.markers.has(key)) continue;
      const w = d.where!;
      let uri: vscode.Uri;
      try { uri = vscode.Uri.parse(w.uri, true); } catch { continue; }
      const th = this.ctl.createCommentThread(uri, new vscode.Range(w.line_start - 1, 0, w.line_end - 1, 0), [this.comment_(d)]);
      th.canReply = false;
      th.contextValue = DRAFT_CTX;
      th.label = `Draft for chat: ${d.label}`;
      th.collapsibleState = vscode.CommentThreadCollapsibleState.Collapsed;
      this.markers.set(key, { thread: th, note: d.quote.note ?? '' });
    }
  }

  private syncNotes(): void {
    for (const d of this.tray.all()) {
      const m = this.markers.get(d.key);
      if (m && m.note !== (d.quote.note ?? '')) { m.thread.comments = [this.comment_(d)]; m.note = d.quote.note ?? ''; }
    }
  }

  private comment_(d: Draft): vscode.Comment {
    const f = this.tray.find(d.key);
    return { body: d.quote.note?.trim() ? d.quote.note : '(no note)', mode: vscode.CommentMode.Preview, contextValue: DRAFT_CTX,
      author: { name: 'EDP draft' }, label: f ? `in the chat composer of ${f.ticketId}; Ctrl+Enter there sends` : 'draft' };
  }

  dispose(): void {
    for (const m of this.markers.values()) m.thread.dispose();
    this.markers.clear();
    this.status.dispose();
    this.ctl.dispose();
  }
}
