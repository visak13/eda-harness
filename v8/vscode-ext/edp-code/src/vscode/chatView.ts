// The chat WebviewView (strategyll-1a201146c8 §1, -5e3ecdb625 §1): secondary side bar, a webview that
// can die at any time without losing anything. retainContextWhenHidden stays false; the host re-sends
// the full state on every `ready`, and posts made before `ready` are queued, not lost. The bundle is
// read once and inlined with a fresh nonce per resolve; nothing is fetched after the HTML.
import * as vscode from 'vscode';
import { chatHtml } from '../core/chatHtml';
import { inboundType, parseInbound, type HostToView, type ViewToHost } from '../core/chatProtocol';

export const CHAT_VIEW = 'edp.chat';

export interface ChatHost {
  /** the full state for a (re)started view */
  snapshot(): HostToView;
  /** handles/ids a `to` may name (the last people list) */
  handles(): ReadonlySet<string>;
  onIntent(m: ViewToHost): void | Promise<void>;
  /** the first resolve of the window starts the feed; later ones must not open a second stream */
  onFirstResolve(): void;
}

export class ChatViewProvider implements vscode.WebviewViewProvider, vscode.Disposable {
  private view?: vscode.WebviewView;
  private ready = false;
  private queue: HostToView[] = [];
  private bundle?: Promise<{ js: string; css: string }>;
  private resolved = false;
  private unseen = 0;

  constructor(private ctx: vscode.ExtensionContext, private host: ChatHost, private log: (line: string) => void) {}

  get isOpen(): boolean { return this.view !== undefined; }
  get isVisible(): boolean { return !!this.view?.visible; }

  private loadBundle() {
    return (this.bundle ??= (async () => {
      const read = async (f: string) => new TextDecoder().decode(await vscode.workspace.fs.readFile(vscode.Uri.joinPath(this.ctx.extensionUri, 'dist', f)));
      const [js, css] = await Promise.all([read('webview.js'), read('webview-css.css')]);
      return { js, css };
    })().catch(e => { this.bundle = undefined; throw e; }));
  }

  async resolveWebviewView(view: vscode.WebviewView): Promise<void> {
    this.view = view;
    this.ready = false;
    const d: vscode.Disposable[] = [];
    view.webview.options = { enableScripts: true, localResourceRoots: [] }; // enableCommandUris stays off
    d.push(view.webview.onDidReceiveMessage(raw => this.onMessage(raw)));
    d.push(view.onDidChangeVisibility(() => { if (view.visible) { this.unseen = 0; view.badge = undefined; } }));
    view.onDidDispose(() => {
      d.forEach(x => x.dispose());
      if (this.view === view) { this.view = undefined; this.ready = false; }
    });
    try {
      const { js, css } = await this.loadBundle();
      view.webview.html = chatHtml(js, css);
    } catch (e) {
      this.log(`chat: bundle unreadable (${(e as Error)?.name ?? 'error'})`);
      view.webview.html = '<!DOCTYPE html><html><body><p>EDP chat: the webview bundle is missing; rebuild the extension.</p></body></html>';
    }
    if (!this.resolved) { this.resolved = true; this.host.onFirstResolve(); }
  }

  /** Post to the live view, or queue until it says `ready`. A full `state` supersedes the queue. */
  post(m: HostToView): void {
    if (m.type === 'state') this.queue = [];
    if (this.view && this.ready) void this.view.webview.postMessage(m);
    else if (this.view) this.queue.push(m);
    // no view: nothing to queue, the next resolve gets a fresh snapshot on `ready`
  }

  /** New messages arrived while the view is hidden: badge the container. */
  noteUnseen(n: number): void {
    if (!this.view || this.view.visible || n <= 0) return;
    this.unseen += n;
    this.view.badge = { value: this.unseen, tooltip: `${this.unseen} new` };
  }

  private onMessage(raw: unknown): void {
    const m = parseInbound(raw, this.host.handles());
    if (!m) { this.log(`chat: dropped inbound ${inboundType(raw)}`); return; }
    if (m.type === 'ready') {
      this.ready = true;
      const q = this.queue.splice(0);
      void this.view?.webview.postMessage(this.host.snapshot());
      q.forEach(x => void this.view?.webview.postMessage(x));
      return;
    }
    Promise.resolve(this.host.onIntent(m)).catch(e => this.log(`chat: ${m.type} failed (${(e as Error)?.name ?? 'error'})`));
  }

  /** Reveal the view (the workbench's generated `<viewId>.focus`). */
  static async reveal(): Promise<void> {
    await vscode.commands.executeCommand(`${CHAT_VIEW}.focus`);
  }

  dispose(): void { this.queue = []; }
}
