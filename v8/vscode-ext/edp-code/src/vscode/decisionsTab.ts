// The Decisions tab's host half (C17 s-5e83f9d0af; design-10b21760d9 §14.2, §14.4): reads the picked scope's
// decision records (`GET /v1/decisions?scope=`) with the viewer's token, and runs the two owner/architect writes
// (Withdraw with a reason, Binding on/off) through the existing routes. Every write and every open is resolved
// from this host's own last list by decision id; the view never names a scope, a source or a flag it did not get.
// A refusal is the board's own message, shown on the row. A 403 on the list (not a participant of this epic) is
// shown in the tab: it is a scope answer, not a sign-out.
import * as vscode from 'vscode';
import type { Board, BoardError } from '../core/api';
import type { HostToView } from '../core/chatProtocol';
import { decisionRows, reasonProblem, rowActions, REASON_MAX, type DecisionRow, type DecisionsState } from '../core/decisions';

/** a burst of events in scope settles before one read */
const DEBOUNCE_MS = 1500;

export type DecisionsScope = { id: string };
/** Opens a decision's source: a message in the Chat tab, a doc in the EDP reader (the controller's). */
export type SourceOpener = { message: (ticketId: string, messageId: string) => Promise<void>; doc: (id: string) => Promise<void> };

const isAuth = (e: unknown) => {
  const err = e as BoardError;
  return err?.status === 401 || err?.code === 'not_signed_in';
};

export class DecisionsHost implements vscode.Disposable {
  private state: DecisionsState | null = null;
  private gen = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  /** the reason prompt (tests stub it) */
  ask = (o: vscode.InputBoxOptions) => vscode.window.showInputBox(o);

  constructor(private board: () => Board, private scope: () => DecisionsScope | null, private post: (m: HostToView) => void,
    private open: SourceOpener, private onAuthFail: (e: unknown) => void, private log: (line: string) => void) {}

  snapshot(scopeId: string | undefined): DecisionsState | null {
    return this.state && this.state.scope === scopeId ? this.state : null;
  }

  /** a listed decision: an event on it (binding changed) re-reads the list */
  has(id: string): boolean { return !!this.state?.rows.some(r => r.id === id); }

  clear(): void { ++this.gen; this.state = null; clearTimeout(this.timer); }

  async openScope(): Promise<void> {
    const sc = this.scope();
    if (!sc) { this.clear(); return; }
    if (this.state?.scope !== sc.id) this.state = { scope: sc.id, rows: [], canManage: false, loading: true, error: null };
    await this.refresh();
  }

  schedule(): void {
    clearTimeout(this.timer);
    if (this.disposed) return;
    this.timer = setTimeout(() => void this.refresh(), DEBOUNCE_MS);
  }

  private emit(): void {
    if (this.state) this.post({ type: 'decisions', v: 1, ticketId: this.state.scope, decisions: this.state });
  }

  async refresh(): Promise<void> {
    clearTimeout(this.timer);
    const sc = this.scope();
    if (!sc || this.disposed) return;
    const n = ++this.gen;
    try {
      const list = await this.board().scopeDecisions(sc.id);
      if (n !== this.gen || this.scope()?.id !== sc.id) return; // a newer read or another scope won
      const keep = this.state?.scope === sc.id ? this.state : null;
      this.state = { scope: sc.id, rows: decisionRows(list), canManage: list.can_manage === true, loading: false, error: null,
        busy: keep?.busy ?? null, notice: keep?.notice ?? null };
    } catch (e) {
      if (n !== this.gen || this.scope()?.id !== sc.id) return;
      const err = e as BoardError;
      const keep = this.state?.scope === sc.id ? this.state : null;
      const why = err?.status === 403 ? `You cannot read this epic's decisions: ${err.message}`
        : err?.status === 404 || err?.code === 'not_found' ? `The board has no decision list for ${sc.id} (${err.message}). It may predate C17.`
        : `Could not list the decisions: ${err?.message ?? String(e)}`;
      // a refusal (403) means this viewer may not read the list: nothing read earlier stays on screen
      const refused = err?.status === 403;
      this.state = { scope: sc.id, rows: refused ? [] : keep?.rows ?? [], canManage: refused ? false : keep?.canManage ?? false, loading: false, error: why };
      if (isAuth(e)) { this.emit(); this.onAuthFail(e); return; }
    }
    this.emit();
  }

  private row(id: string): DecisionRow | undefined {
    return this.state?.scope === this.scope()?.id ? this.state?.rows.find(r => r.id === id) : undefined;
  }

  /** A row's source: a message opens in Chat (its thread, scrolled to it), a doc in the reader. */
  async openRow(id: string): Promise<void> {
    const r = this.row(id);
    if (!r?.source) return;
    try {
      if (r.source.kind === 'message') await this.open.message(r.source.ticketId, r.source.id);
      else await this.open.doc(r.source.id);
    } catch (e) {
      if (isAuth(e)) { this.onAuthFail(e); return; }
      void vscode.window.showErrorMessage(`EDP: could not open the source of ${id}: ${(e as Error)?.message ?? String(e)}`);
    }
  }

  withdraw(id: string): Promise<void> {
    return this.write(id, 'withdraw', async r => {
      const reason = await this.ask({ title: `EDP: Withdraw ${r.id}`, prompt: `“${clip(r.text)}”: why is it withdrawn? The reason stays on the record.`,
        placeHolder: 'Reason (required, one line)', ignoreFocusOut: true, validateInput: t => reasonProblem('withdraw', t) });
      if (reason === undefined) return null;
      await this.board().withdrawDecision(r.id, reason.trim());
      return `Withdrawn: ${r.id}.`;
    });
  }

  binding(id: string, on: boolean): Promise<void> {
    return this.write(id, 'binding', async r => {
      if (r.binding === on) return `${r.id} is already ${on ? 'binding' : 'not binding'}.`;
      const reason = await this.ask({ title: `EDP: ${on ? 'Make' : 'Stop making'} ${r.id} binding`,
        prompt: on ? 'Binding decisions are always handed to agents in scope. Why? (optional)' : 'Agents will no longer always get it. Why? (optional)',
        placeHolder: `Reason (optional, at most ${REASON_MAX} characters)`, ignoreFocusOut: true, validateInput: t => reasonProblem('binding', t) });
      if (reason === undefined) return null;
      await this.board().setBinding(r.id, on, reason.trim());
      return `${r.id} is ${on ? 'binding' : 'no longer binding'}.`;
    });
  }

  /** One write on a listed live row, for a viewer the board said may manage; `null` from `run` = cancelled. */
  private async write(id: string, what: 'withdraw' | 'binding', run: (r: DecisionRow) => Promise<string | null>): Promise<void> {
    const r = this.row(id);
    const st = this.state;
    if (!r || !st || !rowActions(r, st.canManage)[what]) {
      this.note(id, false, r ? 'You cannot change this decision here.' : 'This decision is no longer listed here.');
      void this.refresh();
      return;
    }
    if (st.busy) return; // one write at a time; the buttons are disabled meanwhile
    st.busy = id; st.notice = null; this.emit();
    let text: string | null;
    try {
      text = await run(r);
    } catch (e) {
      if (isAuth(e)) this.onAuthFail(e);
      this.log(`decisions: ${what} refused (${(e as BoardError)?.code ?? 'error'})`);
      this.settle(id, false, (e as Error)?.message ?? String(e));
      return;
    }
    if (text === null) { this.settle(id, null, ''); return; }
    this.settle(id, true, text);
    await this.refresh(); // a newer generation: a read in flight from before the write is dropped
  }

  private settle(id: string, ok: boolean | null, text: string): void {
    if (!this.state) return;
    this.state.busy = null;
    this.state.notice = ok === null ? null : { id, ok, text };
    this.emit();
  }

  private note(id: string, ok: boolean, text: string): void {
    if (!this.state) return;
    this.state.notice = { id, ok, text };
    this.emit();
  }

  dispose(): void { this.disposed = true; this.clear(); }
}

const clip = (t: string) => (t.length > 80 ? `${t.slice(0, 79)}…` : t);
