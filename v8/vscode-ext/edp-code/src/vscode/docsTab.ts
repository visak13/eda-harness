// The Docs tab's host half (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.4): reads what the picked scope's tickets
// link (design_ref, doc links, criteria evidence) with the viewer's token, describes each doc (the epic's doc list in
// one read, any other doc singly) and shapes the rows (core/docs.ts). A row opens in the EDP reader or compares two
// versions; both resolve the doc from this host's own list by id, never from a field the view sent.
import * as vscode from 'vscode';
import type { Board, BoardError, Ticket } from '../core/api';
import type { HostToView } from '../core/chatProtocol';
import { scopeDocIds, scopeDocs, type DocMeta, type DocsState, type TicketDocs } from '../core/docs';
import { openDoc } from './docs';
import { openVersionDiff } from './reader';

/** The picked scope: its id, the epic whose doc list describes most docs, and its tickets (the C14 set). */
export type DocsScope = { id: string; epicId: string | null; tickets: readonly Ticket[] };

/** a burst of events in scope settles before one read */
const DEBOUNCE_MS = 1500;
/** board reads in flight at once while listing (two per ticket) */
const PARALLEL = 6;

async function pool<T, R>(items: readonly T[], n: number, fn: (x: T) => Promise<R>): Promise<R[]> {
  const out: R[] = new Array(items.length);
  let i = 0;
  await Promise.all(Array.from({ length: Math.min(n, items.length) }, async () => {
    while (i < items.length) { const k = i++; out[k] = await fn(items[k]); }
  }));
  return out;
}

export class DocsHost implements vscode.Disposable {
  private state: DocsState | null = null;
  private gen = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  /** the reader opener (tests stub it) */
  openDoc = openDoc;
  openDiff = openVersionDiff;

  constructor(private board: () => Board, private scope: () => DocsScope | null, private post: (m: HostToView) => void,
    private onAuthFail: (e: unknown) => void, private log: (line: string) => void) {}

  snapshot(scopeId: string | undefined): DocsState | null {
    return this.state && this.state.scope === scopeId ? this.state : null;
  }

  /** a doc in the list: an event on it re-reads the list */
  has(docId: string): boolean { return !!this.state?.docs.some(d => d.id === docId); }

  clear(): void { ++this.gen; this.state = null; clearTimeout(this.timer); }

  async open(): Promise<void> {
    const sc = this.scope();
    if (!sc) { this.clear(); return; }
    if (this.state?.scope !== sc.id) this.state = { scope: sc.id, docs: [], loading: true, error: null };
    await this.refresh();
  }

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
    const b = this.board();
    try {
      // design_ref is read fresh (the scope's tree is only as new as the last open): the epic and its tickets in
      // two calls, or the lone ticket of an epic-less scope
      const [refs, tickets] = await Promise.all([
        this.designRefs(b, sc),
        pool(sc.tickets, PARALLEL, async t => {
          const [links, criteria] = await Promise.all([b.links(t.id), b.criteria(t.id)]);
          return { id: t.id, title: t.title, design_ref: t.design_ref ?? null, links, criteria } as TicketDocs;
        }),
      ]);
      for (const t of tickets) if (refs.has(t.id)) t.design_ref = refs.get(t.id) ?? null;
      const meta = new Map<string, DocMeta>();
      if (sc.epicId) for (const d of await b.docsOf(sc.epicId).catch(() => [] as DocMeta[])) meta.set(d.id, d);
      const missing = [...scopeDocIds(tickets).keys()].filter(id => !meta.has(id));
      await pool(missing, PARALLEL, async id => {
        try { const d = await b.latestDoc(id); meta.set(id, d); } catch (e) { this.log(`docs: ${id} unreadable (${(e as BoardError)?.code ?? 'error'})`); }
      });
      if (n !== this.gen || this.scope()?.id !== sc.id) return;
      this.state = { scope: sc.id, docs: scopeDocs(tickets, meta), loading: false, error: null };
    } catch (e) {
      if (n !== this.gen || this.scope()?.id !== sc.id) return;
      const err = e as BoardError;
      this.state = { scope: sc.id, docs: this.state?.scope === sc.id ? this.state.docs : [], loading: false, error: `Could not list the docs: ${err?.message ?? String(e)}` };
      if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') {
        this.post({ type: 'docs', v: 1, ticketId: sc.id, docs: this.state });
        this.onAuthFail(e);
        return;
      }
    }
    this.post({ type: 'docs', v: 1, ticketId: sc.id, docs: this.state });
  }

  /** Each scope ticket's current design_ref; a failed read leaves the tree's value in place. */
  private async designRefs(b: Board, sc: DocsScope): Promise<Map<string, string | null>> {
    const out = new Map<string, string | null>();
    const rows = await (sc.epicId
      ? Promise.all([b.ticket(sc.epicId), b.tickets({ epic_id: sc.epicId })]).then(([e, ts]) => [e, ...ts])
      : b.ticket(sc.id).then(t => [t])).catch((e: BoardError) => { this.log(`docs: design_ref read failed (${e?.code ?? 'error'})`); return []; });
    for (const t of rows) out.set(t.id, t.design_ref ?? null);
    return out;
  }

  private row(id: string) {
    return this.state?.scope === this.scope()?.id ? this.state?.docs.find(d => d.id === id) : undefined;
  }

  /** Open a listed doc in the reader at its current version; a design is reviewed from the ticket it designs. */
  async openRow(id: string): Promise<void> {
    const d = this.row(id);
    if (!d) return;
    try { await this.openDoc(d.id, d.version, d.designOf ?? this.scope()?.id ?? null); }
    catch (e) { this.fail(e, d.id); }
  }

  /** Compare two versions of a listed doc: pick both (the current one first in the list). */
  async compareRow(id: string): Promise<void> {
    const d = this.row(id);
    if (!d) return;
    if (d.version < 2) { void vscode.window.showInformationMessage(`EDP: ${d.id} has only v1.`); return; }
    const all = Array.from({ length: d.version }, (_, i) => d.version - i);
    const item = (v: number) => ({ label: `v${v}`, description: v === d.version ? 'current' : undefined, v });
    const a = await vscode.window.showQuickPick(all.map(item), { title: `EDP: compare ${d.title}: first version`, placeHolder: 'Pick one version' });
    if (!a) return;
    const b = await vscode.window.showQuickPick(all.filter(v => v !== a.v).map(item), { title: `EDP: compare ${d.title} v${a.v} with…`, placeHolder: 'The older version goes on the left' });
    if (!b) return;
    try { await this.openDiff(d.id, a.v, b.v); } catch (e) { this.fail(e, d.id); }
  }

  private fail(e: unknown, id: string): void {
    const err = e as BoardError;
    if (err?.status === 401 || err?.status === 403) { this.onAuthFail(e); return; }
    void vscode.window.showErrorMessage(`EDP: could not open ${id}: ${err?.message ?? String(e)}`);
  }

  dispose(): void { this.disposed = true; this.clear(); }
}
