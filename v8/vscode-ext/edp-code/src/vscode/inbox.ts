// The Inbox tab's host half (C15 s-e14d316891; design-10b21760d9 §14.2): reads `GET /v1/me/decisions` with the
// viewer's token, keeps the picked scope's rows (core/inbox.ts), and answers them: a question with an answer to
// its asker, a sign-off with Pass/Fail for the version the row showed, a gate with a ruling. Every write is
// resolved from this host's own last list by row key; the view never names a ticket, a recipient or a
// criterion. A refusal is the board's own message, shown on the row (a stale version included).
import * as vscode from 'vscode';
import { BoardError, type Board } from '../core/api';
import { boardTicketUrl } from '../core/boardLinks';
import type { AttachmentRef, HostToView } from '../core/chatProtocol';
import { ARTIFACT_ID } from '../core/chatProtocol';
import { answerBody, scopeInbox, verdictBody, writeProblem, type InboxItem, type InboxState, type InboxVerdict } from '../core/inbox';
import { DOC_ID } from '../core/docUri';
import { openDoc } from './docs';

/** The picked scope: its id, its ticket ids (the C14 set) and the titles known for them. */
export type InboxScope = { id: string; ids: ReadonlySet<string>; titles: ReadonlyMap<string, string> };

/** feed events in scope arrive in bursts (a message + its delivery + a status); one read per quiet spell */
const DEBOUNCE_MS = 600;

export class InboxHost implements vscode.Disposable {
  private state: InboxState | null = null;
  private gen = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  /** the evidence version this viewer last opened, by sign-off row: a verdict rules on what was read, so a
   *  doc edited since then (the row relabelled vN+1 in place) is refused by the board as stale */
  private opened = new Map<string, number>();
  /** the evidence opener; C16 swaps it for its reader */
  openDoc = openDoc;

  constructor(private board: () => Board, private boardUrl: () => string, private scope: () => InboxScope | null,
    private post: (m: HostToView) => void, private openArtifact: (ref: AttachmentRef) => Promise<void>,
    private onAuthFail: (e: unknown) => void, private log: (line: string) => void) {}

  /** What the next `state` carries: the list for the open scope, or null. */
  snapshot(scopeId: string | undefined): InboxState | null {
    return this.state && this.state.scope === scopeId ? this.state : null;
  }

  /** Forget everything (signed out). */
  clear(): void { ++this.gen; this.state = null; this.opened.clear(); clearTimeout(this.timer); }

  /** A new scope is open: an empty, loading list now, then the board's. */
  async open(): Promise<void> {
    const sc = this.scope();
    if (!sc) { this.clear(); return; }
    if (this.state?.scope !== sc.id) this.state = { scope: sc.id, items: [], loading: true, error: null };
    await this.refresh();
  }

  /** Something in scope changed on the board: read again once the burst settles. */
  schedule(): void {
    clearTimeout(this.timer);
    if (this.disposed) return;
    this.timer = setTimeout(() => void this.refresh(), DEBOUNCE_MS);
  }

  async refresh(): Promise<void> {
    clearTimeout(this.timer);
    const sc = this.scope();
    if (!sc || this.disposed) return;
    const n = ++this.gen;
    try {
      const home = await this.board().decisions();
      const cur = this.scope();
      if (n !== this.gen || cur?.id !== sc.id) return; // a newer read or another scope won
      this.state = { scope: sc.id, items: scopeInbox(home, cur.ids, cur.titles), loading: false, error: null };
    } catch (e) {
      if (n !== this.gen || this.scope()?.id !== sc.id) return;
      const err = e as BoardError;
      const keep = this.state?.scope === sc.id ? this.state.items : [];
      this.state = { scope: sc.id, items: keep, loading: false, error: `Could not read what waits on you: ${err?.message ?? String(e)}` };
      if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') {
        // settle the tab first (never left "reading…"), then the sign-in path
        this.post({ type: 'inbox', v: 1, ticketId: sc.id, inbox: this.state });
        this.onAuthFail(e);
        return;
      }
    }
    this.post({ type: 'inbox', v: 1, ticketId: sc.id, inbox: this.state });
  }

  private row(key: string): InboxItem | undefined {
    return this.state?.scope === this.scope()?.id ? this.state?.items.find(i => i.key === key) : undefined;
  }

  private done(key: string, ok: boolean, text: string): void {
    this.post({ type: 'inboxDone', v: 1, key, ok, text });
  }

  /** Run one write for a listed row; the row leaves the list on success, the refusal shows on it otherwise. */
  private async write(key: string, run: (i: InboxItem) => Promise<string>, want: InboxItem['type']): Promise<void> {
    const i = this.row(key);
    if (!i || i.type !== want) {
      this.done(key, false, 'This item is no longer waiting on you here.');
      void this.refresh();
      return;
    }
    try {
      const text = await run(i);
      // a read already in flight began before this write landed and would list the row again: drop it
      ++this.gen;
      this.opened.delete(key);
      if (this.state) this.state = { ...this.state, items: this.state.items.filter(x => x.key !== key) };
      this.done(key, true, text);
    } catch (e) {
      const err = e as BoardError;
      if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') this.onAuthFail(e);
      this.done(key, false, err?.message ?? String(e));
    }
    this.schedule();
  }

  answer(key: string, text: string): Promise<void> {
    return this.write(key, async i => {
      if (i.type !== 'question') throw new Error('not a question');
      const bad = writeProblem('answer', text);
      if (bad) throw new Error(bad);
      await this.board().send(answerBody(i, text));
      return `Answered @${i.by}.`;
    }, 'question');
  }

  verdict(key: string, verdict: InboxVerdict, note: string, version: number): Promise<void> {
    return this.write(key, async i => {
      if (i.type !== 'signoff') throw new Error('not a sign-off');
      const bad = writeProblem('verdict', note, verdict);
      if (bad) throw new Error(bad);
      // the version the view showed must be the version this host listed: a row that moved under the
      // viewer is not ruled on a version they never saw
      if (version !== i.version) throw new Error(`This row now shows v${i.version}; you ruled on v${version}. Look again, then rule.`);
      // opened an older version than the row lists now: send the one read, and the board's stale refusal says so
      const read = Math.min(this.opened.get(key) ?? i.version, i.version);
      await this.board().verdict(verdictBody({ ...i, version: read }, verdict, note));
      return `${verdict === 'pass' ? 'Passed' : 'Failed'} v${i.version}.`;
    }, 'signoff');
  }

  gate(key: string, text: string): Promise<void> {
    return this.write(key, async i => {
      if (i.type !== 'gate' || i.design) throw new Error('the design review is answered on the board');
      const bad = writeProblem('gate', text);
      if (bad) throw new Error(bad);
      await this.board().gateAnswer(i, text.trim());
      return `Answered the ${i.gate} gate.`;
    }, 'gate');
  }

  /** A sign-off's evidence in an editor tab (a doc at the row's version, or the artifact); a design gate's
   *  review on the board UI until C16. */
  async openRow(key: string): Promise<void> {
    const i = this.row(key);
    if (!i) return;
    try {
      if (i.type === 'gate' && i.design) {
        await vscode.env.openExternal(vscode.Uri.parse(boardTicketUrl(this.boardUrl(), i.ticketId)));
        return;
      }
      if (i.type !== 'signoff') return;
      const ref = i.evidence.ref;
      if (i.evidence.doc && DOC_ID.test(ref)) { await this.openDoc(ref, i.version); this.opened.set(key, i.version); return; }
      if (ARTIFACT_ID.test(ref)) {
        const a = await this.board().artifact(ref);
        await this.openArtifact({ id: a.id, name: a.filename || ref, contentType: a.content_type ?? '', image: false });
        return;
      }
      void vscode.window.showWarningMessage(`EDP: the evidence ${ref} is not a doc or an artifact this panel can open.`);
    } catch (e) {
      const err = e as BoardError;
      if (err?.status === 401 || err?.status === 403) { this.onAuthFail(e); return; }
      this.log(`inbox: open failed (${err?.code ?? 'error'})`);
      void vscode.window.showErrorMessage(`EDP: could not open ${i.type === 'signoff' ? i.evidence.ref : i.ticketId}: ${err?.message ?? String(e)}`);
    }
  }

  dispose(): void { this.disposed = true; this.clear(); }
}
