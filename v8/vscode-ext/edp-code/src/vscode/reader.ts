// The EDP reader editor (C16 s-579fa02cca; design-10b21760d9 §14.2, §14.7): a custom readonly editor over the C15
// `edp-doc:/<id>/v<N>.md` URIs, so the version in the tab is the version shown and the version every write carries.
// The webview is our own (markdown-it + DOMPurify inlined with a fresh nonce, CSP default-src 'none', no resource
// roots): the native Markdown preview cannot host C20's inline note box. All board access is here, with the viewer's
// token; the webview gets plain data and posts intents that pass `parseReaderInbound`.
import { randomUUID } from 'node:crypto';
import * as vscode from 'vscode';
import { BoardError, type Board, type BoardDoc } from '../core/api';
import { chatHtml } from '../core/chatHtml';
import { canResolve } from '../core/docs';
import { DOC_ID, parseDocPath } from '../core/docUri';
import { compareChoices, decideBody, decideProblem, diffPair, parseReaderInbound, readerComments, READER_VIEW,
  type HostToReader, type ReaderDoc, type ReaderGate, type ReaderState, type ReaderToHost, type ReaderWrite } from '../core/reader';
import { docUri } from './docs';

const CTX_APPROVE = 'edp.doc.canApprove';
const CTX_RESOLVE = 'edp.doc.canResolve';
const CTX_VERSIONS = 'edp.doc.hasVersions';

/** One open reader tab. */
class ReaderPanel {
  state: ReaderState = { type: 'doc', v: 1, doc: null, gate: null, canResolve: false, diff: null, comments: null, loading: true, error: null };
  ready = false;
  /** C20: the reader's last selection as source lines of this version (from 0: none) */
  selection: { from: number; to: number; text: string } = { from: 0, to: 0, text: '' };
  private gen = 0;
  constructor(readonly id: string, readonly version: number, readonly panel: vscode.WebviewPanel, public source: string | null) {}
  next(): number { return ++this.gen; }
  current(n: number): boolean { return n === this.gen; }
  post(m: HostToReader): void { if (this.ready) void this.panel.webview.postMessage(m); }
}

export class DocReader implements vscode.CustomReadonlyEditorProvider, vscode.Disposable {
  private panels = new Set<ReaderPanel>();
  private active: ReaderPanel | null = null;
  private bundle?: Promise<{ js: string; css: string }>;
  /** the ticket a doc was opened from (the design review's source), by doc id; set by the opener */
  private sources = new Map<string, string>();
  private role: Promise<string | null> | null = null;

  constructor(private ctx: vscode.ExtensionContext, private board: () => Board, private log: (line: string) => void,
    private onAuthFail: (e: unknown) => void = () => {}) {}

  register(): vscode.Disposable[] {
    // an editor/title action passes its editor's resource: act on that reader, not whichever one is active
    const cmd = (id: string, fn: (p: ReaderPanel) => unknown) =>
      vscode.commands.registerCommand(id, (uri?: unknown) => { const p = this.panelFor(uri); if (p) return fn(p); });
    return [
      vscode.window.registerCustomEditorProvider(READER_VIEW, this, { webviewOptions: { retainContextWhenHidden: false }, supportsMultipleEditorsPerDocument: true }),
      cmd('edp.doc.approve', p => this.approve(p)),
      cmd('edp.doc.requestChanges', p => this.requestChangesPrompt(p)),
      cmd('edp.doc.resolveApprove', p => this.resolve(p, true)),
      cmd('edp.doc.resolveReject', p => this.resolve(p, false)),
      cmd('edp.doc.compare', p => this.compare(p)),
      cmd('edp.doc.source', p => this.source(p)),
      cmd('edp.doc.fullScreen', () => this.fullScreen()),
      cmd('edp.doc.refresh', p => this.load(p)),
      this,
    ];
  }

  /** Open a doc version in the reader; `source` is the ticket it was opened from (a design review's source). */
  async open(id: string, version: number, source?: string | null): Promise<void> {
    if (source) {
      this.sources.set(id, source);
      // an open reader on this doc was opened from another ticket: review from the new one (its gate, its actions)
      for (const p of this.panels) if (p.id === id && p.source !== source) { p.source = source; void this.load(p); }
    }
    await vscode.commands.executeCommand('vscode.openWith', docUri(id, version), READER_VIEW, { preview: false });
  }

  /** The reader a command acts on: the one showing `uri` (the active one of those first), else the active reader. */
  private panelFor(uri: unknown): ReaderPanel | null {
    const at = uri instanceof vscode.Uri && uri.scheme === 'edp-doc' ? parseDocPath(uri.path) : null;
    if (!at) return this.active;
    const on = [...this.panels].filter(p => p.id === at.id && p.version === at.version);
    return on.find(p => p === this.active) ?? on.find(p => p.panel.active) ?? on.find(p => p.panel.visible) ?? on[0] ?? null;
  }

  /** The panel on this doc version, if one is open (tests and C20). */
  panelOf(id: string, version: number): { state: ReaderState; selection: ReaderPanel['selection'] } | undefined {
    return [...this.panels].find(p => p.id === id && p.version === version);
  }

  /** The viewer signed in as someone else: forget the role. */
  reset(): void { this.role = null; for (const p of this.panels) void this.load(p); }

  openCustomDocument(uri: vscode.Uri): vscode.CustomDocument {
    return { uri, dispose: () => {} };
  }

  private loadBundle() {
    return (this.bundle ??= (async () => {
      const read = async (f: string) => new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(this.ctx.extensionUri, 'dist', f)));
      const [js, css] = await Promise.all([read('reader.js'), read('reader-css.css')]);
      return { js, css };
    })().catch(e => { this.bundle = undefined; throw e; }));
  }

  async resolveCustomEditor(document: vscode.CustomDocument, panel: vscode.WebviewPanel): Promise<void> {
    const at = parseDocPath(document.uri.path);
    panel.webview.options = { enableScripts: true, localResourceRoots: [] }; // enableCommandUris stays off
    if (document.uri.scheme !== 'edp-doc' || !at) {
      panel.webview.html = '<!DOCTYPE html><html><body><p>EDP reader: not a board doc.</p></body></html>';
      return;
    }
    const p = new ReaderPanel(at.id, at.version, panel, this.sources.get(at.id) ?? null);
    this.panels.add(p);
    panel.title = `${at.id} v${at.version}`;
    const d: vscode.Disposable[] = [];
    d.push(panel.webview.onDidReceiveMessage(raw => this.onMessage(p, raw)));
    d.push(panel.onDidChangeViewState(() => {
      if (panel.active) this.activate(p);
      else if (this.active === p) this.activate(null);
      if (!panel.visible) p.ready = false; // the document is gone (retainContextWhenHidden false): wait for `ready`
    }));
    panel.onDidDispose(() => {
      d.forEach(x => x.dispose());
      this.panels.delete(p);
      if (this.active === p) this.activate(null);
    });
    if (panel.active) this.activate(p);
    try {
      const { js, css } = await this.loadBundle();
      panel.webview.html = chatHtml(js, css, undefined, `EDP ${at.id} v${at.version}`, false);
    } catch (e) {
      this.log(`reader: bundle unreadable (${(e as Error)?.name ?? 'error'})`);
      panel.webview.html = '<!DOCTYPE html><html><body><p>EDP reader: the webview bundle is missing; rebuild the extension.</p></body></html>';
    }
    void this.load(p);
  }

  private activate(p: ReaderPanel | null): void {
    this.active = p;
    const s = p?.state;
    void vscode.commands.executeCommand('setContext', CTX_APPROVE, !!s?.gate?.canApprove);
    void vscode.commands.executeCommand('setContext', CTX_RESOLVE, !!s?.canResolve);
    void vscode.commands.executeCommand('setContext', CTX_VERSIONS, (s?.doc?.versions.length ?? 0) > 1);
  }

  private set(p: ReaderPanel, s: Partial<ReaderState>): void {
    p.state = { ...p.state, ...s };
    p.post(p.state);
    if (this.active === p) this.activate(p);
  }

  private onMessage(p: ReaderPanel, raw: unknown): void {
    const m = parseReaderInbound(raw);
    if (!m) { this.log(`reader: dropped inbound ${typeof (raw as { type?: unknown })?.type === 'string' ? (raw as { type: string }).type.slice(0, 32) : 'unknown'}`); return; }
    Promise.resolve(this.intent(p, m)).catch(e => this.log(`reader: ${m.type} failed (${(e as Error)?.name ?? 'error'})`));
  }

  private async intent(p: ReaderPanel, m: ReaderToHost): Promise<void> {
    switch (m.type) {
      case 'ready': p.ready = true; p.post(p.state); return;
      case 'refresh': return this.load(p);
      case 'pickVersion': if (m.version !== p.version && p.state.doc?.versions.includes(m.version)) await this.open(p.id, m.version, p.source); return;
      case 'compare': return this.compare(p);
      case 'source': return this.source(p);
      case 'fullScreen': return this.fullScreen();
      case 'approve': return this.approve(p);
      case 'requestChanges': return this.requestChanges(p, m.feedback);
      case 'resolve': return this.resolve(p, m.approve);
      case 'openProposalDiff': return this.openProposalDiff(p);
      case 'openLink': await vscode.env.openExternal(vscode.Uri.parse(m.href)); return;
      case 'selection': p.selection = { from: m.from, to: m.to, text: m.text }; return;
    }
  }

  private viewerRole(): Promise<string | null> {
    return (this.role ??= this.board().me().then(me => me?.role ?? null, () => { this.role = null; return null; }));
  }

  /** Read the doc at the panel's version, its review context, the proposal diff and the version's comments. */
  async load(p: ReaderPanel): Promise<void> {
    const n = p.next();
    const b = this.board();
    this.set(p, { loading: true });
    let at: BoardDoc, latest: BoardDoc;
    try {
      [at, latest] = await Promise.all([b.doc(p.id, p.version), b.latestDoc(p.id)]);
    } catch (e) {
      if (!p.current(n)) return;
      if (this.authFailed(e)) return this.set(p, { loading: false, error: 'Sign in to the board to read this doc.' });
      return this.set(p, { loading: false, error: `Could not read ${p.id} v${p.version}: ${(e as Error)?.message ?? String(e)}` });
    }
    if (!p.current(n)) return;
    const versions = (latest.versions ?? at.versions ?? [latest.version]).filter(v => Number.isSafeInteger(v) && v > 0).sort((x, y) => x - y);
    const doc: ReaderDoc = { id: p.id, title: latest.title || at.title || p.id, docType: String(latest.doc_type ?? ''), status: String(latest.status ?? ''),
      version: p.version, versions, current: latest.version, body: at.body_md ?? '', proposes: latest.proposes ?? null, resolution: latest.resolution ?? null };
    p.panel.title = `${doc.title} · v${p.version}`;
    const [gate, role, diff, comments] = await Promise.all([
      this.gateOf(p, doc), this.viewerRole(),
      doc.status === 'proposed' ? b.docDiff(p.id).then(d => ({ baseId: d.base_id, baseVersion: d.base_version, text: d.diff }), () => null) : Promise.resolve(null),
      b.docComments(p.id, p.version).then(r => ({ rows: readerComments(r), error: null }),
        (e: BoardError) => ({ rows: [], error: e?.status === 404 || e?.status === 405 ? 'Comments are not available on this board yet.' : `Could not read the comments: ${e?.message ?? String(e)}` })),
    ]);
    if (!p.current(n)) return;
    this.set(p, { doc, gate, diff, comments, canResolve: canResolve(doc, role) && p.version === doc.current, loading: false, error: null });
  }

  /** The design review this viewer may do on this version, from the ticket the doc was opened from. */
  private async gateOf(p: ReaderPanel, doc: ReaderDoc): Promise<ReaderGate | null> {
    if (doc.docType !== 'design' || !p.source) return null;
    try {
      const c = await this.board().docContext(p.id, p.source, p.version);
      return { ticketId: c.ticket_id, ticketTitle: c.source_title, gateEventId: c.gate_event_id, canApprove: !!c.can_approve, canReview: !!c.can_review, currentVersion: c.current_version };
    } catch (e) {
      this.log(`reader: no review context (${(e as BoardError)?.code ?? 'error'})`);
      return null;
    }
  }

  private authFailed(e: unknown): boolean {
    const err = e as BoardError;
    if (err?.status === 401 || err?.status === 403 || err?.code === 'not_signed_in') { this.onAuthFail(e); return true; }
    return false;
  }

  private done(p: ReaderPanel, what: ReaderWrite, ok: boolean, text: string): void {
    p.post({ type: 'done', v: 1, what, ok, text });
    if (!ok) void vscode.window.showWarningMessage(`EDP: ${text}`);
  }

  /** Run one write, then read the panel again (the gate closes, the proposal retires). */
  private async write(p: ReaderPanel, what: ReaderWrite, run: () => Promise<string>): Promise<void> {
    try { this.done(p, what, true, await run()); }
    catch (e) {
      const err = e as BoardError;
      if (err?.status === 401 || err?.status === 403) this.onAuthFail(e);
      this.done(p, what, false, err?.message ?? String(e));
    }
    await this.load(p);
  }

  async approve(p: ReaderPanel): Promise<void> {
    return this.write(p, 'approve', async () => {
      const { doc, gate } = p.state;
      const bad = decideProblem(doc, gate, 'approve', '');
      if (bad) throw new Error(bad);
      await this.board().decide(decideBody(doc!, gate!, 'approve', '', randomUUID()));
      return `Approved ${doc!.id} v${doc!.version}.`;
    });
  }

  async requestChanges(p: ReaderPanel, feedback: string): Promise<void> {
    return this.write(p, 'requestChanges', async () => {
      const { doc, gate } = p.state;
      const bad = decideProblem(doc, gate, 'request_changes', feedback);
      if (bad) throw new Error(bad);
      await this.board().decide(decideBody(doc!, gate!, 'request_changes', feedback, randomUUID()));
      return `Requested changes on ${doc!.id} v${doc!.version}; the architect has your feedback.`;
    });
  }

  /** The title-bar Request changes: the feedback in an input box. */
  private async requestChangesPrompt(p: ReaderPanel): Promise<void> {
    const v = p.state.doc?.version ?? p.version;
    const feedback = await vscode.window.showInputBox({ title: `EDP: Request changes on ${p.id} v${v}`, prompt: 'Your feedback goes to the architect with this version',
      placeHolder: 'What to change…', ignoreFocusOut: true, validateInput: t => (t.trim() ? null : 'Request changes needs feedback.') });
    if (feedback === undefined) return;
    await this.requestChanges(p, feedback);
  }

  async resolve(p: ReaderPanel, approve: boolean): Promise<void> {
    return this.write(p, approve ? 'resolveApprove' : 'resolveReject', async () => {
      if (!p.state.canResolve || !p.state.doc) throw new Error('This doc is not a proposal you can rule on here.');
      // the board's approve/reject takes no version: re-read the proposal so a version its author published after
      // this one was read is never ruled on unseen (the load after the refusal shows the newer version's note)
      const now = await this.board().latestDoc(p.id);
      if (now.version !== p.version) throw new Error(`${p.id} is now v${now.version}; you are reading v${p.version}. Read v${now.version} before you rule.`);
      if (now.status !== 'proposed') throw new Error(`${p.id} is ${now.status}, no longer proposed.`);
      const r = await this.board().docResolve(p.id, approve);
      return !approve ? `Rejected ${p.id}; it is retired.` : r.target ? `Approved: ${r.target.id} is now v${r.target.version}.` : `Approved: ${p.id} is active.`;
    });
  }

  /** Compare the shown version with another: the older on the left, the markdown source in the diff editor. */
  async compare(p: ReaderPanel, other?: number): Promise<void> {
    const versions = p.state.doc?.versions ?? [];
    let v = other;
    if (v === undefined) {
      const choices = compareChoices(versions, p.version);
      if (!choices.length) { void vscode.window.showInformationMessage(`EDP: ${p.id} has only v${p.version}.`); return; }
      const pick = await vscode.window.showQuickPick(choices.map(c => ({ label: `v${c}`, description: c === p.state.doc?.current ? 'current' : undefined, v: c })),
        { title: `EDP: compare ${p.id} v${p.version} with…`, placeHolder: 'The older version goes on the left' });
      if (!pick) return;
      v = pick.v;
    }
    await openVersionDiff(p.id, p.version, v);
  }

  private async source(p: ReaderPanel): Promise<void> {
    const doc = await vscode.workspace.openTextDocument(docUri(p.id, p.version));
    await vscode.window.showTextDocument(doc, { preview: false });
  }

  /** Full screen: Zen mode, the workbench's own toggle, hides every side bar (the chat included), the panel, the
   *  activity and status bars, and restores exactly what was showing when pressed again. (maximizeEditorHideSidebar
   *  has no inverse on a lone editor group: measured in the C16 smoke.) */
  private async fullScreen(): Promise<void> {
    await vscode.commands.executeCommand('workbench.action.toggleZenMode');
  }

  /** A proposal against the active doc it revises, in the native diff editor. */
  private async openProposalDiff(p: ReaderPanel): Promise<void> {
    const d = p.state.diff;
    if (!d?.baseId || !d.baseVersion || !DOC_ID.test(d.baseId)) return;
    await vscode.commands.executeCommand('vscode.diff', docUri(d.baseId, d.baseVersion), docUri(p.id, p.version),
      `${d.baseId} v${d.baseVersion} (active) ↔ ${p.id} v${p.version} (proposed)`);
  }

  dispose(): void { this.panels.clear(); this.active = null; }
}

/** Two versions of a doc in the diff editor, the older on the left (the Docs tab's Compare too). */
export async function openVersionDiff(id: string, a: number, b: number): Promise<void> {
  const [l, r] = diffPair(a, b);
  await vscode.commands.executeCommand('vscode.diff', docUri(id, l), docUri(id, r), `${id} v${l} ↔ v${r}`);
}
