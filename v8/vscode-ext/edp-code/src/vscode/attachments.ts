// Chat attachments, the host half (C12 s-85dd35a166; design §13 row C12, steer m-223446009c, architect
// m-1a33d88bc7). The host uploads through the board's own upload route with the seat's creds, holds the
// staged ids per thread until a send carries them, and answers the view's lazy "what is this artifact"
// requests with a size and, for an image under the caps, a worker-made thumbnail as a `data:` URI. The
// webview never fetches. Full size opens from a copy under the extension's storage.
import * as vscode from 'vscode';
import { BoardError, type Board } from '../core/api';
import { attachmentRef, InfoCache, openMode, safeFileName } from '../core/attachments';
import { ATTACH_MAX, type ArtifactInfo, type AttachmentRef, type PendingAttachment } from '../core/chatProtocol';
import { ThumbWorker } from './thumbs';

export class Attachments implements vscode.Disposable {
  /** per thread: staged uploads waiting in its composer */
  private pending = new Map<string, PendingAttachment[]>();
  private infos = new InfoCache();
  private inflight = new Map<string, Promise<ArtifactInfo>>();
  private thumbs: ThumbWorker;

  constructor(private ctx: vscode.ExtensionContext, private board: () => Board, private log: (line: string) => void) {
    this.thumbs = new ThumbWorker(ctx.extensionPath, log);
  }

  pendingOf(ticketId: string | undefined): PendingAttachment[] {
    return ticketId ? [...(this.pending.get(ticketId) ?? [])] : [];
  }

  /** Infos already known for these artifacts (a re-resolved view gets them in its snapshot). */
  known(ids: Iterable<string>): ArtifactInfo[] {
    const out: ArtifactInfo[] = [];
    for (const id of ids) { const i = this.infos.get(id); if (i) out.push(i); }
    return out;
  }

  clear(): void { this.pending.clear(); }

  /** Upload one file for a thread's composer. Resolves to the new pending list, or throws the board's refusal. */
  async upload(ticketId: string, name: string, bytes: Uint8Array): Promise<PendingAttachment[]> {
    const held = this.pending.get(ticketId) ?? [];
    if (held.length >= ATTACH_MAX) throw new BoardError('too_many', `At most ${ATTACH_MAX} attachments per message.`, 0);
    const art = await this.board().upload(ticketId, name, bytes);
    const p: PendingAttachment = { id: art.id, name: art.filename || name, size: bytes.byteLength, contentType: art.content_type };
    const next = [...(this.pending.get(ticketId) ?? []), p];
    this.pending.set(ticketId, next);
    return [...next];
  }

  drop(ticketId: string, id: string): PendingAttachment[] {
    const next = (this.pending.get(ticketId) ?? []).filter(p => p.id !== id);
    if (next.length) this.pending.set(ticketId, next); else this.pending.delete(ticketId);
    return next;
  }

  /** A send carried these: they are the board's now (finalised with the message). */
  sent(ticketId: string, ids: readonly string[]): PendingAttachment[] {
    const next = (this.pending.get(ticketId) ?? []).filter(p => !ids.includes(p.id));
    if (next.length) this.pending.set(ticketId, next); else this.pending.delete(ticketId);
    return next;
  }

  /** A live message's artifact ids → refs (the live row carries ids only). An unreadable one keeps its id as its name. */
  async refs(ids: readonly string[] | undefined): Promise<AttachmentRef[]> {
    if (!ids?.length) return [];
    const b = this.board();
    return Promise.all(ids.slice(0, ATTACH_MAX).map(id => b.artifact(id).then(attachmentRef,
      () => ({ id, name: id, contentType: '', image: false }))));
  }

  /** Size and thumbnail for refs in view; cached per artifact id for the session, one fetch per id at a time. */
  resolve(ref: AttachmentRef): Promise<ArtifactInfo> {
    const hit = this.infos.get(ref.id);
    if (hit) return Promise.resolve(hit);
    let p = this.inflight.get(ref.id);
    if (!p) {
      p = this.fetchInfo(ref).then(i => { if (!i.retry) this.infos.set(i); return i; }).finally(() => this.inflight.delete(ref.id));
      this.inflight.set(ref.id, p);
    }
    return p;
  }

  private async fetchInfo(ref: AttachmentRef): Promise<ArtifactInfo> {
    const b = this.board();
    try {
      if (!ref.image) {
        const c = await b.content(ref.id, true);
        return { id: ref.id, size: c.size, thumb: null, state: 'file' };
      }
      const c = await b.content(ref.id);
      const t = await this.thumbs.thumb(c.bytes!, ref.contentType);
      return t.ok ? { id: ref.id, size: c.size, thumb: t.dataUri, state: 'thumb' }
        : { id: ref.id, size: c.size, thumb: null, state: 'file', note: t.reason, ...(t.transient ? { retry: true as const } : {}) };
    } catch (e) {
      const err = e as BoardError;
      // a recorded artifact (url, repo path) has no stored bytes: a file row, not an error
      if (err?.code === 'not_found') return { id: ref.id, size: null, thumb: null, state: 'file', note: 'no stored content' };
      this.log(`attachments: ${ref.id} unavailable (${err?.code ?? 'error'})`);
      return { id: ref.id, size: null, thumb: null, state: 'error', note: err?.message ?? 'unavailable', retry: true };
    }
  }

  /** Full size: an image in VS Code's image preview, text in an editor tab, anything else saved where the
   *  user picks. A recorded http(s) artifact opens in the browser. */
  async open(ref: AttachmentRef): Promise<void> {
    const b = this.board();
    let content;
    try { content = await b.content(ref.id); }
    catch (e) {
      if ((e as BoardError)?.code === 'not_found') {
        const art = await b.artifact(ref.id).catch(() => null);
        if (art && /^https?:\/\//i.test(art.uri)) { void vscode.env.openExternal(vscode.Uri.parse(art.uri)); return; }
        void vscode.window.showWarningMessage(`EDP: ${ref.name} has no stored content${art?.uri ? ` (${art.uri})` : ''}.`);
        return;
      }
      void vscode.window.showErrorMessage(`EDP: could not open ${ref.name}: ${(e as Error).message}`);
      return;
    }
    const type = content.type || ref.contentType;
    const name = safeFileName(ref.name, ref.id, type);
    const mode = openMode(type);
    if (mode === 'save') {
      const home = vscode.workspace.workspaceFolders?.[0]?.uri;
      const target = await vscode.window.showSaveDialog({ title: `Save ${ref.name}`, saveLabel: 'Save attachment',
        ...(home ? { defaultUri: vscode.Uri.joinPath(home, name) } : {}) });
      if (!target) return;
      await vscode.workspace.fs.writeFile(target, content.bytes!);
      void vscode.window.setStatusBarMessage(`EDP: saved ${name}`, 6_000);
      return;
    }
    // one folder per artifact: the original name shows in the tab, and two attachments never collide
    const dir = vscode.Uri.joinPath(this.ctx.globalStorageUri, 'attachments', ref.id);
    const file = vscode.Uri.joinPath(dir, name);
    await vscode.workspace.fs.createDirectory(dir);
    await vscode.workspace.fs.writeFile(file, content.bytes!);
    await vscode.commands.executeCommand('vscode.open', file, { preview: true, viewColumn: vscode.ViewColumn.Active });
  }

  dispose(): void { this.thumbs.dispose(); }
}
